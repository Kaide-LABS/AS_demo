"""Per-engagement Nia indexing for the extraction layer.

Separate from semantic_validator.py because the concerns are different:

- semantic_validator.py owns the static canonical vocabulary (5 long-lived
  Nia sources, indexed once via seed_nia.py).
- This module owns ephemeral per-engagement corpora (one Nia source per
  /v1/calibrate request, indexed at the start, torn down at the end).

Usage from the pipeline:

    source_id = await index_engagement_corpus(project_id, artifacts)
    if source_id:
        chunks = await query_engagement_corpus(source_id, "audience segments")
    ...
    await teardown_engagement_corpus(source_id)

Best-effort semantics: every function catches its own errors and returns
None / [] on failure. Pipeline never crashes due to Nia issues — it just
falls back to the existing raw_text[:50000] path.

Feature flag: RCS_NIA_EXTRACTION_ENABLED=true|false (default false).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

NIA_API_KEY = os.getenv("NIA_API_KEY")
NIA_API_URL = os.getenv("NIA_API_URL", "https://apigcp.trynia.ai") + "/v2"
NIA_INDEX_TIMEOUT = float(os.getenv("NIA_INDEX_TIMEOUT", "60"))
NIA_QUERY_TIMEOUT = float(os.getenv("NIA_QUERY_TIMEOUT", "10"))

EXTRACTION_ENABLED = (
    os.getenv("RCS_NIA_EXTRACTION_ENABLED", "false").lower() == "true"
)

_client: Optional[httpx.AsyncClient] = None
_client_lock = asyncio.Lock()


async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        async with _client_lock:
            if _client is None:
                _client = httpx.AsyncClient(timeout=httpx.Timeout(NIA_QUERY_TIMEOUT))
    return _client


async def aclose() -> None:
    global _client
    if _client is not None:
        try:
            await _client.aclose()
        finally:
            _client = None


def _safe_filename(artifact_id: str) -> str:
    """Sanitize artifact id for use as a Nia file_name. Keep round-trippable."""
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", artifact_id)
    return f"{safe}.txt"


def _filename_to_artifact_id(file_name: str) -> str:
    """Inverse of _safe_filename. Strips .txt extension only — the underscores
    cannot be reliably reversed, but artifact ids are UUIDs (no special chars
    that get sanitized) so this is identity in practice."""
    return file_name[:-4] if file_name.endswith(".txt") else file_name


async def index_engagement_corpus(
    project_id: str, artifacts
) -> Optional[str]:
    """Index this engagement's artifacts into a temporary Nia local_folder.

    artifacts: iterable of objects with .artifact_id and .raw_text (typically
    SourceArtifact instances).

    Returns the source_id once Nia reports indexing complete. Returns None on
    any failure (caller falls back to the truncation path).
    """
    if not EXTRACTION_ENABLED:
        return None
    if not NIA_API_KEY:
        logger.info("nia_corpus_skipped", extra={"reason": "api_key_missing"})
        return None

    try:
        client = await _get_client()
        files = []
        for art in artifacts:
            content = (getattr(art, "raw_text", None) or "").strip()
            if not content:
                continue
            files.append({
                "path": _safe_filename(art.artifact_id),
                "content": content,
            })
        if not files:
            return None

        display_name = f"rcs_engagement_{project_id}_{int(time.time())}"
        body = {
            "type": "local_folder",
            "folder_name": display_name,
            "folder_path": f"/virtual/{display_name}",
            "files": files,
            "display_name": display_name,
        }
        headers = {
            "Authorization": f"Bearer {NIA_API_KEY}",
            "Content-Type": "application/json",
        }
        resp = await client.post(
            f"{NIA_API_URL}/sources", json=body, headers=headers, timeout=30
        )
        resp.raise_for_status()
        source_id = resp.json().get("id")
        if not source_id:
            logger.warning("nia_corpus_no_id_returned")
            return None

        # Poll until Nia reports indexing complete or we hit the budget.
        deadline = time.monotonic() + NIA_INDEX_TIMEOUT
        poll_interval = 2.0
        while time.monotonic() < deadline:
            try:
                stat = await client.get(
                    f"{NIA_API_URL}/sources/{source_id}", headers=headers, timeout=10
                )
                stat.raise_for_status()
                status = stat.json().get("status")
                if status in ("indexed", "completed"):
                    elapsed = NIA_INDEX_TIMEOUT - (deadline - time.monotonic())
                    logger.info(
                        "nia_corpus_indexed",
                        extra={
                            "project_id": project_id,
                            "source_id": source_id,
                            "files": len(files),
                            "elapsed_s": round(elapsed, 1),
                        },
                    )
                    return source_id
                if status == "failed":
                    logger.warning(
                        "nia_corpus_index_failed",
                        extra={"source_id": source_id},
                    )
                    return None
            except Exception as e:
                logger.debug(f"nia_poll_error: {e}")
            await asyncio.sleep(poll_interval)

        logger.warning(
            "nia_corpus_index_timeout",
            extra={
                "project_id": project_id,
                "source_id": source_id,
                "timeout_s": NIA_INDEX_TIMEOUT,
            },
        )
        # We tried; pipeline falls back. Source may still index in the
        # background — teardown will handle it later.
        return None
    except Exception as e:
        logger.warning(
            "nia_corpus_index_error",
            extra={"project_id": project_id, "error": f"{type(e).__name__}: {e}"},
        )
        return None


async def query_engagement_corpus(
    source_id: str, query: str, top_k: int = 20
) -> list[dict]:
    """Query the engagement's indexed corpus. Returns chunks with artifact_id,
    content, score, locator. Returns [] on any failure."""
    if not source_id:
        return []
    try:
        client = await _get_client()
        body = {
            "mode": "query",
            "messages": [{"role": "user", "content": query}],
            "local_folders": [source_id],
            "include_sources": True,
            "stream": False,
            "skip_llm": True,
        }
        headers = {
            "Authorization": f"Bearer {NIA_API_KEY}",
            "Content-Type": "application/json",
        }
        resp = await asyncio.wait_for(
            client.post(f"{NIA_API_URL}/search", json=body, headers=headers),
            timeout=NIA_QUERY_TIMEOUT,
        )
        resp.raise_for_status()
        sources = resp.json().get("sources", []) or []
        out = []
        for s in sources[:top_k]:
            if not isinstance(s, dict):
                continue
            meta = s.get("metadata") or {}
            fname = meta.get("file_name") or ""
            if not fname:
                continue
            out.append({
                "artifact_id": _filename_to_artifact_id(fname),
                "content": s.get("content") or meta.get("summary") or "",
                "score": float(meta.get("score") or 0.0),
                "locator": f"chunk_{meta.get('chunk_index')}",
            })
        return out
    except Exception as e:
        logger.warning(
            "nia_corpus_query_error",
            extra={"source_id": source_id, "error": f"{type(e).__name__}: {e}"},
        )
        return []


async def teardown_engagement_corpus(source_id: Optional[str]) -> None:
    """Delete the engagement's temporary Nia source. Best-effort; never raises."""
    if not source_id or not NIA_API_KEY:
        return
    try:
        client = await _get_client()
        headers = {"Authorization": f"Bearer {NIA_API_KEY}"}
        resp = await client.delete(
            f"{NIA_API_URL}/sources/{source_id}", headers=headers, timeout=10
        )
        if resp.status_code >= 300:
            logger.warning(
                "nia_corpus_teardown_non_2xx",
                extra={"source_id": source_id, "status": resp.status_code},
            )
    except Exception as e:
        logger.warning(
            "nia_corpus_teardown_error",
            extra={"source_id": source_id, "error": f"{type(e).__name__}: {e}"},
        )

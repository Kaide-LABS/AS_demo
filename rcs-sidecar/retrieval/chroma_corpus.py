"""Per-engagement ChromaDB indexing for the extraction layer.

Replaces validators/nia_corpus.py. Same async signatures so callers in
pipeline.py and the segment/verbatim/demographic extractors are drop-in
compatible.

Why ChromaDB instead of Nia for retrieval:
The Nia retrieval layer hit a server-side ingestion ceiling at ~14M characters
during the F100 / Unilever 20-F stress test. The chunked-upload fix attempt
(commit 2123a3e) was reverted because Nia's downstream indexing pipeline did
not flip the source to `indexed` within 15 minutes for that volume. ChromaDB
runs locally with PersistentClient, embeddings come from Gemini
text-embedding-001, and there is no remote indexing throughput ceiling.

The validator layer (semantic_validator.py + seed_nia.py) still uses Nia
against the canonical_vocabulary.json. That integration is unchanged.

Feature flag: RCS_NIA_EXTRACTION_ENABLED=true|false (default false).
The flag name is preserved for env/test continuity even though the backing
store is now ChromaDB. RCS_RETRIEVAL_ENABLED is accepted as a synonym.

Best-effort semantics: every function catches its own errors and returns
None / [] on failure. Pipeline never crashes due to retrieval issues — it
falls back to the existing raw_text[:50000] truncation path.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

GEMINI_EMBEDDING_MODEL = os.getenv("RCS_EMBEDDING_MODEL", "gemini-embedding-001")
CHROMA_PATH = Path(os.getenv("RCS_CHROMA_PATH", "data/chromadb"))
CHUNK_SIZE = int(os.getenv("RCS_CHUNK_SIZE", "3000"))
CHUNK_OVERLAP = int(os.getenv("RCS_CHUNK_OVERLAP", "300"))
EMBED_BATCH = int(os.getenv("RCS_EMBED_BATCH", "100"))

EXTRACTION_ENABLED = (
    os.getenv("RCS_NIA_EXTRACTION_ENABLED", os.getenv("RCS_RETRIEVAL_ENABLED", "false")).lower() == "true"
)

_chroma_client = None
_chroma_lock = asyncio.Lock()


def _safe_collection_name(project_id: str) -> str:
    """Chroma collection names: 3-63 chars, [a-zA-Z0-9._-], start/end alnum."""
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", project_id)[:40]
    safe = safe.strip("._-") or "engagement"
    return f"eng_{safe}_{int(time.time())}"


async def _get_client():
    global _chroma_client
    if _chroma_client is None:
        async with _chroma_lock:
            if _chroma_client is None:
                import chromadb
                CHROMA_PATH.mkdir(parents=True, exist_ok=True)
                _chroma_client = await asyncio.to_thread(
                    chromadb.PersistentClient, path=str(CHROMA_PATH)
                )
    return _chroma_client


async def aclose() -> None:
    """No-op for symmetry with the previous httpx-backed module."""
    return None


def _chunk_text(text: str) -> list[str]:
    if not text:
        return []
    if len(text) <= CHUNK_SIZE:
        return [text]
    out = []
    step = max(1, CHUNK_SIZE - CHUNK_OVERLAP)
    for start in range(0, len(text), step):
        chunk = text[start : start + CHUNK_SIZE]
        if not chunk:
            break
        out.append(chunk)
        if start + CHUNK_SIZE >= len(text):
            break
    return out


def _embed_batch_sync(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts via Gemini text-embedding-001. Sync; called via to_thread."""
    from google import genai
    client = genai.Client()
    result = client.models.embed_content(
        model=GEMINI_EMBEDDING_MODEL,
        contents=texts,
    )
    embeddings = getattr(result, "embeddings", None) or []
    out: list[list[float]] = []
    for e in embeddings:
        vals = getattr(e, "values", None)
        if vals is None and isinstance(e, dict):
            vals = e.get("values")
        if vals is None:
            raise RuntimeError("gemini_embed_missing_values")
        out.append(list(vals))
    if len(out) != len(texts):
        raise RuntimeError(f"gemini_embed_count_mismatch: {len(out)} vs {len(texts)}")
    return out


async def _embed_many(texts: list[str]) -> list[list[float]]:
    out: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH):
        batch = texts[i : i + EMBED_BATCH]
        vecs = await asyncio.to_thread(_embed_batch_sync, batch)
        out.extend(vecs)
    return out


async def index_engagement_corpus(project_id: str, artifacts) -> Optional[str]:
    """Chunk artifacts, embed via Gemini, store in a per-engagement Chroma
    collection. Returns the collection name as the source_id handle, or None
    on failure (caller falls back to truncation path)."""
    if not EXTRACTION_ENABLED:
        return None

    try:
        client = await _get_client()
        collection_name = _safe_collection_name(project_id)

        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict] = []

        for art in artifacts:
            artifact_id = getattr(art, "artifact_id", None)
            content = (getattr(art, "raw_text", None) or "").strip()
            if not artifact_id or not content:
                continue
            chunks = _chunk_text(content)
            total = len(chunks)
            for idx, chunk in enumerate(chunks):
                ids.append(f"{artifact_id}__{idx}")
                documents.append(chunk)
                metadatas.append({
                    "artifact_id": artifact_id,
                    "chunk_index": idx,
                    "total_chunks": total,
                })

        if not documents:
            return None

        t0 = time.monotonic()
        embeddings = await _embed_many(documents)
        embed_elapsed = time.monotonic() - t0

        collection = await asyncio.to_thread(
            client.create_collection,
            name=collection_name,
            metadata={"project_id": str(project_id), "created_at": int(time.time())},
        )

        # Chroma's add() can choke on very large single calls; batch the writes too.
        ADD_BATCH = 500
        for i in range(0, len(documents), ADD_BATCH):
            sl = slice(i, i + ADD_BATCH)
            await asyncio.to_thread(
                collection.add,
                ids=ids[sl],
                embeddings=embeddings[sl],
                documents=documents[sl],
                metadatas=metadatas[sl],
            )

        logger.info(
            "chroma_corpus_indexed",
            extra={
                "project_id": project_id,
                "collection": collection_name,
                "chunks": len(documents),
                "embed_elapsed_s": round(embed_elapsed, 1),
            },
        )
        return collection_name
    except Exception as e:
        logger.warning(
            "chroma_corpus_index_error",
            extra={"project_id": project_id, "error": f"{type(e).__name__}: {e}"},
        )
        return None


async def query_engagement_corpus(
    source_id: str, query: str, top_k: int = 20
) -> list[dict]:
    """Query the engagement's Chroma collection. Returns chunks with
    artifact_id, content, score, locator. Returns [] on any failure.
    Same return shape as the previous Nia-backed implementation."""
    if not source_id:
        return []
    try:
        client = await _get_client()
        collection = await asyncio.to_thread(client.get_collection, name=source_id)
        q_emb = (await _embed_many([query]))[0]
        res = await asyncio.to_thread(
            collection.query,
            query_embeddings=[q_emb],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
        documents = (res.get("documents") or [[]])[0]
        metadatas = (res.get("metadatas") or [[]])[0]
        distances = (res.get("distances") or [[]])[0]
        out: list[dict] = []
        for doc, meta, dist in zip(documents, metadatas, distances):
            meta = meta or {}
            artifact_id = meta.get("artifact_id") or ""
            if not artifact_id:
                continue
            # Cosine distance -> similarity ~ 1 - distance.
            try:
                score = float(1.0 - float(dist))
            except (TypeError, ValueError):
                score = 0.0
            out.append({
                "artifact_id": artifact_id,
                "content": doc or "",
                "score": score,
                "locator": f"chunk_{meta.get('chunk_index')}",
            })
        return out
    except Exception as e:
        logger.warning(
            "chroma_corpus_query_error",
            extra={"source_id": source_id, "error": f"{type(e).__name__}: {e}"},
        )
        return []


async def teardown_engagement_corpus(source_id: Optional[str]) -> None:
    """Delete the engagement's Chroma collection. Best-effort; never raises."""
    if not source_id:
        return
    try:
        client = await _get_client()
        await asyncio.to_thread(client.delete_collection, name=source_id)
    except Exception as e:
        logger.warning(
            "chroma_corpus_teardown_error",
            extra={"source_id": source_id, "error": f"{type(e).__name__}: {e}"},
        )

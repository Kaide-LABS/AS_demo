"""One-shot script: index canonical_vocabulary.json into Nia.

Creates one Nia local_folder source per family (5 sources total). Each source
contains one virtual file per canonical key, with the canonical name + aliases
+ description as the file body — that becomes the embedding surface Nia ranks
against at validation time.

Usage:
    NIA_API_KEY=<key> python validators/seed_nia.py

After it runs, the source IDs are written to validators/nia_sources.json
(gitignored). The validator reads that file at runtime; no env vars required.

Re-running is safe: if a previously seeded source ID is still indexed in Nia
the script reuses it, otherwise it re-creates.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
VOCAB_PATH = HERE / "canonical_vocabulary.json"
SOURCES_PATH = HERE / "nia_sources.json"
NIA_API_KEY = os.getenv("NIA_API_KEY")
NIA_API_URL = os.getenv("NIA_API_URL", "https://apigcp.trynia.ai") + "/v2"
SOURCE_NAME_PREFIX = "rcs_canonical"


def _build_files(family_name: str, family_data: dict) -> list[dict]:
    """One virtual file per canonical key. Body packs canonical + aliases + desc.
    Filename uses the canonical key so Nia retrieves a clean handle back."""
    files = []
    for entry in family_data["keys"]:
        canonical = entry["canonical"]
        aliases = entry.get("aliases", [])
        description = entry.get("description", "")
        body_lines = [
            f"canonical: {canonical}",
            f"family: {family_name}",
            f"aliases: {', '.join(aliases)}",
            f"description: {description}",
            "",
            # Repeat the canonical + aliases as plain prose so retrieval surfaces it.
            canonical.replace("_", " "),
            *aliases,
            description,
        ]
        files.append({
            "path": f"{canonical}.txt",
            "content": "\n".join(body_lines),
        })
    return files


def _existing_source(client: httpx.Client, headers: dict, display_name: str) -> str | None:
    """Look up a previously seeded source by display_name."""
    try:
        resp = client.get(
            f"{NIA_API_URL}/sources",
            headers=headers,
            params={"type": "local_folder", "limit": 200},
            timeout=15,
        )
        resp.raise_for_status()
        body = resp.json()
        items = body if isinstance(body, list) else body.get("items") or body.get("sources") or []
        for item in items:
            if item.get("display_name") == display_name and item.get("status") in ("indexed", "completed", None):
                return item.get("id")
    except Exception as e:
        print(f"  warning: list lookup failed: {e}", file=sys.stderr)
    return None


def _create_source(
    client: httpx.Client, headers: dict, family: str, files: list[dict]
) -> str:
    display_name = f"{SOURCE_NAME_PREFIX}_{family}"
    body = {
        "type": "local_folder",
        "folder_name": display_name,
        "folder_path": f"/virtual/{display_name}",
        "files": files,
        "display_name": display_name,
    }
    resp = client.post(f"{NIA_API_URL}/sources", headers=headers, json=body, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    sid = data.get("id")
    if not sid:
        raise RuntimeError(f"Nia did not return a source id: {data}")
    return sid


def main() -> int:
    if not NIA_API_KEY:
        print("error: NIA_API_KEY not set", file=sys.stderr)
        return 2

    vocab = json.loads(VOCAB_PATH.read_text(encoding="utf-8"))
    families = vocab["families"]
    headers = {
        "Authorization": f"Bearer {NIA_API_KEY}",
        "Content-Type": "application/json",
    }

    out: dict[str, str] = {}
    if SOURCES_PATH.exists():
        try:
            out = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
        except Exception:
            out = {}

    with httpx.Client() as client:
        for family, data in families.items():
            display_name = f"{SOURCE_NAME_PREFIX}_{family}"
            existing = _existing_source(client, headers, display_name)
            if existing and out.get(family) == existing:
                print(f"  {family}: reusing existing source {existing}")
                continue
            if existing:
                out[family] = existing
                print(f"  {family}: discovered existing source {existing}")
                continue

            files = _build_files(family, data)
            print(f"  {family}: indexing {len(files)} files...")
            sid = _create_source(client, headers, family, files)
            out[family] = sid
            print(f"  {family}: created source {sid}")

    SOURCES_PATH.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {SOURCES_PATH}")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

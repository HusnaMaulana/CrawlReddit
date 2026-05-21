"""
json_utils.py — backward-compatibility shim.

New code should import from Utils.storage directly.
This module re-exports the helpers that the old codebase used so
existing scripts don't break.
"""

import json
import os
from typing import Any

from .storage import load_jsonl, load_existing_jsonl_ids


# ── legacy helpers ────────────────────────────────────────────


def load_json(path: str) -> list[Any]:
    """Load a JSON array from *path*."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def append_json(path: str, items: list[Any]) -> None:
    """
    Append *items* to a JSON array file.

    Reads the existing array (if any), extends it, writes back.
    For new code, prefer JsonlWriter which avoids the O(n²) rewrite.
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    existing: list[Any] = []
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, ValueError):
            existing = []

    existing.extend(items)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)


def load_existing_ids(path: str, id_field: str = "id") -> set[str]:
    """
    Return a set of existing IDs from a JSON array or JSONL file.

    Tries JSONL first (fast streaming); falls back to JSON array.
    """
    if not os.path.exists(path):
        return set()

    # try JSONL streaming
    try:
        ids = load_existing_jsonl_ids(path, id_field)
        if ids:
            return ids
    except Exception:
        pass

    # fall back to JSON array
    try:
        data = load_json(path)
        return {str(item[id_field]) for item in data if id_field in item}
    except Exception:
        return set()

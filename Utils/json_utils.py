import json
import os
from typing import Any

from .storage import load_jsonl, load_existing_jsonl_ids

def load_json(path: str) -> list[Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def append_json(path: str, items: list[Any]) -> None:
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
   
    if not os.path.exists(path):
        return set()

    try:
        ids = load_existing_jsonl_ids(path, id_field)
        if ids:
            return ids
    except Exception:
        pass

    try:
        data = load_json(path)
        return {str(item[id_field]) for item in data if id_field in item}
    except Exception:
        return set()

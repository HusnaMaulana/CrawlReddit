import json
import os

def append_jsonl(file_path: str, items: list[dict]) -> None:

    if not items:
        return

    os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)

    with open(file_path, "a", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

def load_existing_ids(
    file_path: str,
    id_field: str = "id"
) -> set[str]:

    if not os.path.exists(file_path):
        return set()

    ids = set()

    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                obj = json.loads(line)
                if id_field in obj:
                    ids.add(obj[id_field])
            except Exception:
                continue

    return ids

def load_jsonl(file_path: str) -> list[dict]:

    if not os.path.exists(file_path):
        return []

    results = []

    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                results.append(json.loads(line))
            except Exception:
                continue

    return results
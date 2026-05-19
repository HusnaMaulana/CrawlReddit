import json
import os

def append_json(file_path: str, items: list[dict]) -> None:
    """
    Append items to a JSON array file.
    Reads existing JSON, appends new items, and writes back.
    """
    if not items:
        return
        
    os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
    
    existing_data = []
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            try:
                existing_data = json.load(f)
            except Exception:
                pass
                
    existing_data.extend(items)
    
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(existing_data, f, ensure_ascii=False, indent=2)

def load_existing_ids(file_path: str, id_field: str = "id") -> set[str]:
    """
    Load existing IDs from a JSON array file.
    """
    if not os.path.exists(file_path):
        return set()
        
    ids = set()
    with open(file_path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
            if isinstance(data, list):
                for obj in data:
                    if isinstance(obj, dict) and id_field in obj:
                        ids.add(obj[id_field])
        except Exception:
            pass
            
    return ids

def load_json(file_path: str) -> list[dict]:
    """
    Load entire JSON array file.
    """
    if not os.path.exists(file_path):
        return []
        
    with open(file_path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            return []

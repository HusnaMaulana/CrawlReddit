import json
import os
import sqlite3
import threading
import time
from typing import Generator

class CrawlDatabase:

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._local: threading.local = threading.local()
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        if not getattr(self._local, "conn", None):
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return self._local.conn

    def _init_schema(self) -> None:
        self._conn().executescript(
            """
            CREATE TABLE IF NOT EXISTS crawled_posts (
                post_id    TEXT PRIMARY KEY,
                subreddit  TEXT DEFAULT '',
                status     TEXT DEFAULT 'pending',
                created_at REAL DEFAULT 0,
                crawled_at REAL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_status
                ON crawled_posts (status);

            CREATE TABLE IF NOT EXISTS crawl_state (
                key   TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )
        self._conn().commit()

    def is_known(self, post_id: str) -> bool:
        row = (
            self._conn()
            .execute("SELECT 1 FROM crawled_posts WHERE post_id = ?", (post_id,))
            .fetchone()
        )
        return row is not None

    def mark_pending(
        self,
        post_id: str,
        subreddit: str = "",
        created_at: float = 0.0,
    ) -> None:
        self._conn().execute(
            """
            INSERT OR IGNORE INTO crawled_posts
                (post_id, subreddit, status, created_at)
            VALUES (?, ?, 'pending', ?)
            """,
            (post_id, subreddit, created_at),
        )
        self._conn().commit()

    def mark_done(self, post_id: str) -> None:
        self._conn().execute(
            "UPDATE crawled_posts SET status='done', crawled_at=? WHERE post_id=?",
            (time.time(), post_id),
        )
        self._conn().commit()

    def mark_error(self, post_id: str) -> None:
        self._conn().execute(
            "UPDATE crawled_posts SET status='error', crawled_at=? WHERE post_id=?",
            (time.time(), post_id),
        )
        self._conn().commit()

    def get_pending_posts(self) -> list[dict]:
        rows = (
            self._conn()
            .execute(
                "SELECT post_id, subreddit FROM crawled_posts WHERE status IN ('pending', 'error')"
            )
            .fetchall()
        )
        return [{"id": r["post_id"], "subreddit": r["subreddit"]} for r in rows]

    def save_cursor(self, key: str, value: str) -> None:
        self._conn().execute(
            "INSERT OR REPLACE INTO crawl_state (key, value) VALUES (?, ?)",
            (key, value),
        )
        self._conn().commit()

    def load_cursor(self, key: str) -> str | None:
        row = (
            self._conn()
            .execute("SELECT value FROM crawl_state WHERE key=?", (key,))
            .fetchone()
        )
        return row["value"] if row else None

    def count_by_status(self) -> dict[str, int]:
        rows = (
            self._conn()
            .execute("SELECT status, COUNT(*) AS n FROM crawled_posts GROUP BY status")
            .fetchall()
        )
        return {r["status"]: r["n"] for r in rows}

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn:
            conn.close()
            self._local.conn = None

class JsonlWriter:

    def __init__(self, base_path: str, max_size_mb: int = 50) -> None:
        self.base_path = base_path
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self._lock = threading.Lock()
        self._chunk_index = 0
        os.makedirs(os.path.dirname(base_path) or ".", exist_ok=True)
        self._current_path = base_path

    def _chunk_path(self, index: int) -> str:
        if index == 0:
            return self.base_path
        stem, ext = os.path.splitext(self.base_path)
        return f"{stem}_{index:03d}{ext}"

    def _size_of_current(self) -> int:
        try:
            return os.path.getsize(self._current_path)
        except FileNotFoundError:
            return 0

    def _rotate_if_needed(self) -> None:
        if self._size_of_current() >= self.max_size_bytes:
            self._chunk_index += 1
            self._current_path = self._chunk_path(self._chunk_index)

    def append(self, items: list[dict]) -> None:
        if not items:
            return
        with self._lock:
            self._rotate_if_needed()
            with open(self._current_path, "a", encoding="utf-8") as f:
                for item in items:
                    f.write(json.dumps(item, ensure_ascii=False) + "\n")
                f.flush()

    def append_one(self, item: dict) -> None:
        self.append([item])

    def read_all(self) -> Generator[dict, None, None]:
        for path in self._all_chunk_paths():
            if not os.path.exists(path):
                continue
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            yield json.loads(line)
                        except json.JSONDecodeError:
                            continue

    def _all_chunk_paths(self) -> list[str]:
        paths = [self.base_path]
        i = 1
        while True:
            p = self._chunk_path(i)
            if os.path.exists(p):
                paths.append(p)
                i += 1
            else:
                break
        return paths

def load_jsonl(path: str) -> list[dict]:
    records: list[dict] = []
    if not os.path.exists(path):
        return records
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return records

def load_existing_jsonl_ids(path: str, field: str = "id") -> set[str]:
    ids: set[str] = set()
    if not os.path.exists(path):
        return ids
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                val = json.loads(line).get(field)
                if val is not None:
                    ids.add(str(val))
            except json.JSONDecodeError:
                continue
    return ids

def load_input(file_path: str) -> list[dict]:

    if file_path.endswith(".jsonl"):
        return load_jsonl(file_path)

    import json as _json

    with open(file_path, "r", encoding="utf-8") as f:
        return _json.load(f)

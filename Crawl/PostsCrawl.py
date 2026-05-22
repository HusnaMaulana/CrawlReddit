"""
PostsCrawl.py — Multi-listing Reddit post crawler (producer side).

Key improvements over v1
────────────────────────
• Crawls hot, new, top, rising (4× coverage)
• SQLite-backed dedup — O(1) lookups that survive restarts
• Pagination cursor persisted to SQLite — resume after crash
• Exponential back-off retry (2→4→8→16→32 s)
• 429 / 5xx handling with Retry-After respect
• Optional multiprocessing.Queue for real-time producer-consumer
• Continuous mode (loop forever with configurable delay)
• JSONL output (append-only, no O(n²) rewrite)
"""

import multiprocessing
import os
import time

import requests
import urllib3

from Utils.logging_config import get_logger, setup_logging
from Utils.storage import CrawlDatabase, JsonlWriter

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── constants ─────────────────────────────────────────────────

MULTIREDDIT_BASE = "https://www.reddit.com/user/chivalricsystems/m/indonesiasemua"

PROXIES = {
    "http": os.environ.get("HTTP_PROXY"),
    "https": os.environ.get("HTTPS_PROXY"),
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

MIN_DELAY_BETWEEN_REQUESTS = 15.0  # seconds
SENTINEL = None  # poison pill for queue consumers


# ── HTTP layer ────────────────────────────────────────────────


def _request_with_retry(
    url: str,
    params: dict | None = None,
    max_retries: int = 10,
) -> requests.Response:
    log = get_logger("posts")
    backoff = 5

    for attempt in range(max_retries):
        try:
            resp = requests.get(
                url,
                headers=HEADERS,
                params=params,
                proxies=PROXIES,
                verify=False,
                timeout=15,
            )

            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", backoff * (attempt + 1)))
                log.warning(
                    f"Rate-limited (429). Waiting {wait}s "
                    f"(attempt {attempt + 1}/{max_retries})"
                )
                time.sleep(wait)
                continue

            if resp.status_code in (500, 502, 503, 504):
                log.warning(
                    f"Server error {resp.status_code}. " f"Retrying in {backoff}s..."
                )
                time.sleep(backoff)
                backoff = min(backoff * 2, 32)
                continue

            resp.raise_for_status()
            return resp

        except requests.exceptions.RequestException as exc:
            if attempt == max_retries - 1:
                raise
            log.warning(f"Request error: {exc}. Retrying in {backoff}s...")
            time.sleep(backoff)
            backoff = min(backoff * 2, 32)

    raise RuntimeError(f"Failed after {max_retries} retries: {url}")


def _fetch_page(
    listing: str,
    batch_limit: int,
    after: str | None,
) -> tuple[list[dict], str | None]:
    """Fetch one page from a listing. Returns (posts, next_after)."""
    url = f"{MULTIREDDIT_BASE}/{listing}/.json"
    params: dict = {"limit": batch_limit}
    if after:
        params["after"] = after

    resp = _request_with_retry(url, params=params)
    body = resp.json()
    posts = body["data"]["children"]
    next_after = body["data"].get("after")
    return posts, next_after


# ── post extraction ───────────────────────────────────────────


def _extract_post(raw: dict) -> dict:
    d = raw["data"]
    return {
        "id": d.get("id"),
        "title": d.get("title"),
        "author": d.get("author"),
        "subreddit": d.get("subreddit"),
        "score": d.get("score"),
        "num_comments": d.get("num_comments"),
        "created_utc": d.get("created_utc"),
        "url": "https://www.reddit.com" + d.get("permalink", ""),
        "selftext": d.get("selftext", ""),
    }


# ── main crawler ──────────────────────────────────────────────


def crawl_posts(
    limit: int = 5000,
    output_file: str = "DataOutput/posts.jsonl",
    db_path: str = "DataOutput/crawl_state.db",
    listings: list[str] | None = None,
    queue: "multiprocessing.Queue | None" = None,
    continuous: bool = False,
    cycle_delay: int = 300,
) -> int:
    """
    Crawl posts from one or more listings and persist them.

    Parameters
    ──────────
    limit        : Max new posts to discover (per run / per cycle).
    output_file  : Path to JSONL output file.
    db_path      : Path to SQLite state database.
    listings     : Listings to crawl (default: hot, new, top, rising).
    queue        : If provided, push each new post dict into this queue
                   so comment workers can start immediately.
    continuous   : If True, loop indefinitely with `cycle_delay` pauses.
    cycle_delay  : Seconds to sleep between continuous cycles.

    Returns
    ───────
    Number of new posts discovered (across all cycles).
    """
    if listings is None:
        listings = ["hot", "new", "top", "rising"]

    setup_logging()
    log = get_logger("posts")

    db = CrawlDatabase(db_path)
    writer = JsonlWriter(output_file)

    grand_total = 0

    def _one_cycle() -> int:
        cycle_new = 0

        for listing in listings:
            log.info(f"[PostsCrawl] Listing: {listing}")

            cursor_key = f"cursor_{listing}"
            after = db.load_cursor(cursor_key) or None
            if after:
                log.info(f"  Resuming {listing} from cursor: {after}")

            fetched_this_listing = 0

            while fetched_this_listing < limit:
                batch_size = min(100, limit - fetched_this_listing)

                try:
                    raw_posts, next_after = _fetch_page(listing, batch_size, after)
                except Exception as exc:
                    log.error(f"  [{listing}] Page fetch failed: {exc}")
                    break

                if not raw_posts:
                    log.info(f"  [{listing}] No more posts.")
                    break

                new_batch: list[dict] = []
                skipped = 0

                for raw in raw_posts:
                    post = _extract_post(raw)
                    post_id = post.get("id")

                    if not post_id:
                        continue

                    if db.is_known(post_id):
                        skipped += 1
                        continue

                    db.mark_pending(
                        post_id,
                        subreddit=post.get("subreddit", ""),
                        created_at=float(post.get("created_utc") or 0),
                    )
                    new_batch.append(post)

                    if queue is not None:
                        queue.put(post)

                    fetched_this_listing += 1
                    cycle_new += 1

                    if fetched_this_listing >= limit:
                        break

                if new_batch:
                    writer.append(new_batch)

                log.info(
                    f"  [{listing}] page: {len(new_batch)} new, "
                    f"{skipped} skipped | listing total: {fetched_this_listing}"
                )

                # persist / clear cursor
                after = next_after
                db.save_cursor(cursor_key, after or "")

                if not after:
                    log.info(f"  [{listing}] End of listing reached.")
                    break

                time.sleep(MIN_DELAY_BETWEEN_REQUESTS)

        log.info(f"[PostsCrawl] Cycle complete. New this cycle: {cycle_new}")
        return cycle_new

    # ── run ───────────────────────────────────────────────────

    if continuous:
        log.info("[PostsCrawl] Continuous mode active.")
        while True:
            found = _one_cycle()
            grand_total += found
            log.info(
                f"[PostsCrawl] Sleeping {cycle_delay}s "
                f"before next cycle (grand total: {grand_total})..."
            )
            time.sleep(cycle_delay)
    else:
        grand_total = _one_cycle()

    db.close()
    log.info(f"[PostsCrawl] Done. Grand total new posts: {grand_total}")
    return grand_total


# ── CLI entrypoint ────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    setup_logging()
    parser = argparse.ArgumentParser(
        description="Crawl Reddit posts from multiple listings."
    )
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--output-file", default="DataOutput/posts.jsonl")
    parser.add_argument("--db-path", default="DataOutput/crawl_state.db")
    parser.add_argument(
        "--listings", default="hot,new,top,rising", help="Comma-separated listing types"
    )
    parser.add_argument("--continuous", action="store_true")
    parser.add_argument("--cycle-delay", type=int, default=300)
    args = parser.parse_args()

    crawl_posts(
        limit=args.limit,
        output_file=args.output_file,
        db_path=args.db_path,
        listings=args.listings.split(","),
        continuous=args.continuous,
        cycle_delay=args.cycle_delay,
    )

import multiprocessing
import os
import re
import sys
import time
from datetime import datetime

import requests
import urllib3

from Utils.logging_config import get_logger, setup_logging
from Utils.storage import CrawlDatabase, JsonlWriter, load_input

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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

DELAY_BETWEEN_REQUESTS = 15
DELAY_MORE_CHILDREN = 10
SENTINEL = None

def _request_with_retry(
    url: str,
    params: dict | None = None,
    max_retries: int = 10,
) -> requests.Response:
    log = get_logger("comments")
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

_MEDIA_DOMAINS = re.compile(
    r"https?://"
    r"(?:"
    r"i\.redd\.it"
    r"|v\.redd\.it"
    r"|preview\.redd\.it"
    r"|i\.imgur\.com"
    r"|imgur\.com"
    r"|gfycat\.com"
    r"|giphy\.com"
    r"|tenor\.com"
    r"|streamable\.com"
    r"|redgifs\.com"
    r"|media\.giphy\.com"
    r")",
    re.IGNORECASE,
)

_MEDIA_EXTENSIONS = re.compile(
    r"https?://\S+\.(?:jpg|jpeg|png|gif|gifv|webp|mp4|webm|mov)(?:\?[^\s]*)?",
    re.IGNORECASE,
)

_INLINE_IMAGE_MD = re.compile(r"!\[.*?\]\(https?://", re.IGNORECASE)

def has_media(text: str) -> bool:
    if not text:
        return False
    return bool(
        _MEDIA_DOMAINS.search(text)
        or _MEDIA_EXTENSIONS.search(text)
        or _INLINE_IMAGE_MD.search(text)
    )

def is_media_post(post_data: dict) -> bool:
    raw_body = (post_data.get("selftext") or "").strip()
    post_url = post_data.get("url", "") or ""
    post_hint = post_data.get("post_hint", "") or ""
    is_gallery = post_data.get("is_gallery", False)
    has_preview = "preview" in post_data
    has_media_metadata = "media_metadata" in post_data

    return any(
        [
            has_media(raw_body),
            has_media(post_url),
            post_hint in ("image", "hosted:video", "rich:video", "link"),
            is_gallery,
            has_preview,
            has_media_metadata,
        ]
    )

def expand_more_children(link_id: str, children_ids: list[str]) -> list[dict]:
    if not children_ids:
        return []

    log = get_logger("comments")
    all_items: list[dict] = []

    for chunk_start in range(0, len(children_ids), 100):
        chunk = children_ids[chunk_start : chunk_start + 100]
        params = {
            "api_type": "json",
            "link_id": link_id,
            "children": ",".join(chunk),
        }
        try:
            resp = _request_with_retry(
                "https://www.reddit.com/api/morechildren", params=params
            )
            things = resp.json().get("json", {}).get("data", {}).get("things", [])
            all_items.extend(t for t in things if t.get("kind") == "t1")
        except Exception as exc:
            log.warning(f"morechildren API error: {exc}")

        time.sleep(DELAY_MORE_CHILDREN)

    return all_items

def build_reply_tree(
    reply_children: list[dict],
    link_id: str,
    depth: int = 0,
) -> list[dict]:
    tree: list[dict] = []

    for item in reply_children:
        kind = item.get("kind")

        if kind == "more":
            more_ids = item["data"].get("children", [])
            if not more_ids:
                continue
            expanded = expand_more_children(link_id, more_ids)
            tree.extend(build_reply_tree(expanded, link_id, depth))
            continue

        if kind != "t1":
            continue

        d = item["data"]
        body = d.get("body", "")

        if has_media(body):
            continue

        nested_raw = d.get("replies", "")
        nested_children = []
        if nested_raw and isinstance(nested_raw, dict):
            nested_children = nested_raw["data"]["children"]

        clean_children = build_reply_tree(nested_children, link_id, depth + 1)

        tree.append(
            {
                "comment_id": d.get("id"),
                "author": d.get("author"),
                "body": body,
                "score": d.get("score"),
                "created_utc": d.get("created_utc"),
                "depth": depth,
                "permalink": "https://www.reddit.com" + d.get("permalink", ""),
                "reply_count": len(clean_children),
                "replies": clean_children,
            }
        )

    return tree

def fetch_comments(post_id: str, subreddit: str) -> list[dict]:
    log = get_logger("comments")
    url = f"https://www.reddit.com/r/{subreddit}/comments/{post_id}.json"
    link_id = f"t3_{post_id}"

    try:
        response = _request_with_retry(url)
        data = response.json()
    except Exception as exc:
        log.error(f"Could not fetch comments for post {post_id}: {exc}")
        raise

    if len(data) < 2:
        return []

    post_data = data[0]["data"]["children"][0]["data"]
    post_title = post_data.get("title", "-") or "-"
    raw_body = (post_data.get("selftext") or "").strip()

    if is_media_post(post_data):
        return []
    if raw_body in ("", "[removed]", "[deleted]"):
        return []

    post_body = raw_body
    top_level_items = data[1]["data"]["children"]
    result: list[dict] = []

    for item in top_level_items:
        if item["kind"] != "t1":
            continue

        d = item["data"]
        body = d.get("body", "")

        if has_media(body):
            continue

        replies_raw = d.get("replies", "")
        reply_children = []
        if replies_raw and isinstance(replies_raw, dict):
            reply_children = replies_raw["data"]["children"]

        clean_replies = build_reply_tree(reply_children, link_id, depth=1)

        if not clean_replies:
            continue

        result.append(
            {
                "comment_id": d.get("id"),
                "post_id": post_id,
                "subreddit": subreddit,
                "post_title": post_title,
                "post_body": post_body,
                "author": d.get("author"),
                "body": body,
                "score": d.get("score"),
                "created_utc": d.get("created_utc"),
                "depth": 0,
                "permalink": "https://www.reddit.com" + d.get("permalink", ""),
                "reply_count": len(clean_replies),
                "replies": clean_replies,
            }
        )

    return result

def comment_worker(
    queue: "multiprocessing.Queue",
    db_path: str,
    output_file: str,
    worker_id: int = 0,
) -> None:
  
    setup_logging()
    log = get_logger(f"worker-{worker_id}")
    db = CrawlDatabase(db_path)
    writer = JsonlWriter(output_file)

    log.info(f"[Worker {worker_id}] Started.")

    while True:
        post = queue.get()

        if post is SENTINEL:
            log.info(f"[Worker {worker_id}] Received sentinel. Exiting.")
            db.close()
            return

        post_id = post.get("id") or post.get("post_id", "")
        subreddit = post.get("subreddit", "")

        log.info(
            f"[Worker {worker_id}] Processing {post_id} "
            f"({subreddit}) — \"{(post.get('title') or '')[:55]}...\""
        )

        try:
            comments = fetch_comments(post_id, subreddit)
            writer.append(comments)
            db.mark_done(post_id)
            log.info(
                f"[Worker {worker_id}] {post_id} done " f"— {len(comments)} thread(s)"
            )
        except Exception as exc:
            log.error(f"[Worker {worker_id}] {post_id} failed: {exc}")
            db.mark_error(post_id)

        time.sleep(DELAY_BETWEEN_REQUESTS)

def crawl_comments(
    posts_file: str = "DataOutput/posts.jsonl",
    output_file: str = "DataOutput/comments.jsonl",
    db_path: str = "DataOutput/crawl_state.db",
    max_posts: int | None = 2500,
) -> list[dict]:

    setup_logging()
    log = get_logger("comments")

    try:
        posts = load_input(posts_file)
    except FileNotFoundError:
        log.error(f"Posts file not found: {posts_file}")
        sys.exit(1)

    if max_posts:
        posts = posts[:max_posts]

    db = CrawlDatabase(db_path)
    writer = JsonlWriter(output_file)

    log.info(f"[CommentCrawl] Loaded {len(posts)} posts from '{posts_file}'")
    log.info("[CommentCrawl] Starting sequential comment crawl...")

    all_comments: list[dict] = []
    start_time = datetime.utcnow()

    for idx, post in enumerate(posts, 1):
        post_id = post.get("id") or post.get("post_id", "")
        subreddit = post.get("subreddit", "")
        title = (post.get("title") or "")[:60]

        if not db.is_known(post_id):
            db.mark_pending(post_id, subreddit=subreddit)

        log.info(f'  [{idx:>4}/{len(posts)}] {post_id}  "{title}..."')

        try:
            comments = fetch_comments(post_id, subreddit)
            all_comments.extend(comments)
            writer.append(comments)
            db.mark_done(post_id)
            log.info(f"           -> {len(comments)} thread(s) kept")
        except Exception as exc:
            log.error(f"           -> ERROR: {exc}")
            db.mark_error(post_id)

        if idx < len(posts):
            time.sleep(DELAY_BETWEEN_REQUESTS)

    elapsed = (datetime.utcnow() - start_time).seconds
    log.info(
        f"[CommentCrawl] Done. {len(all_comments)} threads "
        f"-> '{output_file}' ({elapsed}s)"
    )

    db.close()
    return all_comments

if __name__ == "__main__":
    import argparse

    setup_logging()
    parser = argparse.ArgumentParser(
        description="Crawl Reddit comments recursively (text-only)."
    )
    parser.add_argument("--posts-file", default="DataOutput/posts.jsonl")
    parser.add_argument("--output-file", default="DataOutput/comments.jsonl")
    parser.add_argument("--db-path", default="DataOutput/crawl_state.db")
    parser.add_argument("--max-posts", type=int, default=500)
    args = parser.parse_args()

    crawl_comments(
        posts_file=args.posts_file,
        output_file=args.output_file,
        db_path=args.db_path,
        max_posts=args.max_posts,
    )

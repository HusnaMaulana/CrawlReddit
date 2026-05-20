import os
import re
import requests
import urllib3
import json
import time
import sys
from datetime import datetime
from Utils.json_utils import (
    append_json,
    load_existing_ids,
    load_json,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

PROXIES = {
    "http":  os.environ.get("HTTP_PROXY"),
    "https": os.environ.get("HTTPS_PROXY"),
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

DELAY_BETWEEN_REQUESTS = 2
DELAY_MORE_CHILDREN = 1


# ─────────────────────────────────────────────────────────────
# HTTP UTILS
# ─────────────────────────────────────────────────────────────

def _request_with_retry(url: str, params: dict | None = None, max_retries: int = 5) -> requests.Response:
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
                wait_time = int(resp.headers.get("Retry-After", 10 * (attempt + 1)))
                print(f"    [WARN] Rate limited (429). Waiting {wait_time}s (attempt {attempt+1}/{max_retries})...")
                time.sleep(wait_time)
                continue
                
            resp.raise_for_status()
            return resp
            
        except requests.exceptions.RequestException as e:
            if attempt == max_retries - 1:
                raise
            print(f"    [WARN] Request error: {e}. Retrying in 5s...")
            time.sleep(5)
    raise RuntimeError(f"Failed after {max_retries} retries.")


# ─────────────────────────────────────────────────────────────
# MEDIA DETECTION
# ─────────────────────────────────────────────────────────────

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

_INLINE_IMAGE_MD = re.compile(
    r"!\[.*?\]\(https?://",
    re.IGNORECASE
)


def has_media(text: str) -> bool:
    """
    Return True if text contains image/video/gif/media links.
    """
    if not text:
        return False

    return bool(
        _MEDIA_DOMAINS.search(text)
        or _MEDIA_EXTENSIONS.search(text)
        or _INLINE_IMAGE_MD.search(text)
    )


def is_media_post(post_data: dict) -> bool:
    """
    Detect whether a Reddit post is media/image/video/gallery based.
    """

    raw_body = (post_data.get("selftext") or "").strip()

    post_url = post_data.get("url", "") or ""
    post_hint = post_data.get("post_hint", "") or ""

    is_gallery = post_data.get("is_gallery", False)

    has_preview = "preview" in post_data
    has_media_metadata = "media_metadata" in post_data

    return any([
        has_media(raw_body),
        has_media(post_url),

        post_hint in (
            "image",
            "hosted:video",
            "rich:video",
            "link",
        ),

        is_gallery,
        has_preview,
        has_media_metadata,
    ])


# ─────────────────────────────────────────────────────────────
# MORECHILDREN API
# ─────────────────────────────────────────────────────────────

def expand_more_children(link_id: str, children_ids: list[str]) -> list[dict]:
    """
    Expand Reddit 'more' comment stubs recursively.
    """

    if not children_ids:
        return []

    all_items: list[dict] = []

    for chunk_start in range(0, len(children_ids), 100):

        chunk = children_ids[chunk_start: chunk_start + 100]

        params = {
            "api_type": "json",
            "link_id": link_id,
            "children": ",".join(chunk),
        }

        try:
            resp = _request_with_retry(
                "https://www.reddit.com/api/morechildren",
                params=params
            )

            data = resp.json()

            things = (
                data.get("json", {})
                .get("data", {})
                .get("things", [])
            )

            all_items.extend(
                t for t in things
                if t.get("kind") == "t1"
            )

        except Exception as e:
            print(f"    [WARN] morechildren API error: {e}")

        time.sleep(DELAY_MORE_CHILDREN)

    return all_items


# ─────────────────────────────────────────────────────────────
# RECURSIVE COMMENT TREE
# ─────────────────────────────────────────────────────────────

def build_reply_tree(
    reply_children: list[dict],
    link_id: str,
    depth: int = 0,
) -> list[dict]:

    tree: list[dict] = []

    for item in reply_children:

        kind = item.get("kind")

        # Expand "more"
        if kind == "more":

            more_ids = item["data"].get("children", [])

            if not more_ids:
                continue

            expanded = expand_more_children(link_id, more_ids)

            sub = build_reply_tree(expanded, link_id, depth)

            tree.extend(sub)

            continue

        if kind != "t1":
            continue

        d = item["data"]

        body = d.get("body", "")

        # Skip media comments
        if has_media(body):
            continue

        nested_raw = d.get("replies", "")

        nested_children: list[dict] = []

        if nested_raw and isinstance(nested_raw, dict):
            nested_children = nested_raw["data"]["children"]

        clean_children = build_reply_tree(
            nested_children,
            link_id,
            depth + 1,
        )

        tree.append({
            "comment_id": d.get("id"),
            "author": d.get("author"),
            "body": body,
            "score": d.get("score"),
            "created_utc": d.get("created_utc"),
            "depth": depth,
            "permalink": (
                "https://www.reddit.com"
                + d.get("permalink", "")
            ),
            "reply_count": len(clean_children),
            "replies": clean_children,
        })

    return tree


# ─────────────────────────────────────────────────────────────
# FETCH COMMENTS
# ─────────────────────────────────────────────────────────────

def fetch_comments(post_id: str, subreddit: str) -> list[dict]:

    url = (
        f"https://www.reddit.com/r/"
        f"{subreddit}/comments/{post_id}.json"
    )

    link_id = f"t3_{post_id}"

    try:

        response = _request_with_retry(url)

        data = response.json()

    except Exception as e:

        print(
            f"  [ERROR] Could not fetch comments "
            f"for post {post_id}: {e}"
        )

        return []

    if len(data) < 2:
        return []

    # ─────────────────────────────────────────
    # POST DATA
    # ─────────────────────────────────────────

    post_data = data[0]["data"]["children"][0]["data"]

    post_title = post_data.get("title", "-") or "-"

    raw_body = (post_data.get("selftext") or "").strip()

    # Skip media/image/video/gallery posts
    if is_media_post(post_data):
        return []

    # Skip deleted/empty posts
    if raw_body in ("", "[removed]", "[deleted]"):
        return []

    post_body = raw_body

    # ─────────────────────────────────────────
    # COMMENTS
    # ─────────────────────────────────────────

    top_level_items = data[1]["data"]["children"]

    result: list[dict] = []

    for item in top_level_items:

        if item["kind"] != "t1":
            continue

        d = item["data"]

        body = d.get("body", "")

        # Skip media comments
        if has_media(body):
            continue

        replies_raw = d.get("replies", "")

        reply_children = []

        if replies_raw and isinstance(replies_raw, dict):
            reply_children = replies_raw["data"]["children"]

        clean_replies = build_reply_tree(
            reply_children,
            link_id,
            depth=1,
        )

        # Keep only threads with replies
        if not clean_replies:
            continue

        result.append({
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

            "permalink": (
                "https://www.reddit.com"
                + d.get("permalink", "")
            ),

            "reply_count": len(clean_replies),
            "replies": clean_replies,
        })

    return result


# ─────────────────────────────────────────────────────────────
# MAIN CRAWLER
# ─────────────────────────────────────────────────────────────

def crawl_comments(
    posts_file: str = "DataOutput/reddit_posts.json",
    output_file: str = "DataOutput/reddit_comments.json",
    max_posts: int | None = 2500,
) -> list[dict]:

    try:
        posts = load_json(posts_file)

    except FileNotFoundError:

        print(f"[ERROR] Posts file not found: {posts_file}")

        sys.exit(1)

    existing_post_ids = load_existing_ids(
        output_file,
        id_field="post_id"
    )

    print(
        f"[INFO] Existing commented posts: "
        f"{len(existing_post_ids)}"
    )

    if max_posts:
        posts = posts[:max_posts]

    print(
        f"[INFO] Loaded {len(posts)} posts "
        f"from '{posts_file}'"
    )

    print(
        "[INFO] Starting recursive comment "
        "crawl (text-only mode)...\n"
    )

    all_comments: list[dict] = []

    start_time = datetime.utcnow()

    for idx, post in enumerate(posts, 1):

        post_id = post["id"]

        subreddit = post["subreddit"]

        title = post["title"][:60]

        if post_id in existing_post_ids:

            print(f"  [SKIP] {post_id} already crawled")

            continue

        print(
            f'  [{idx:>3}/{len(posts)}] '
            f'{post_id}  "{title}..."'
        )

        comments = fetch_comments(post_id, subreddit)

        all_comments.extend(comments)

        print(
            f"           -> "
            f"{len(comments)} thread(s) kept"
        )

        if idx < len(posts):
            time.sleep(DELAY_BETWEEN_REQUESTS)

    os.makedirs(
        os.path.dirname(output_file) or ".",
        exist_ok=True,
    )

    append_json(output_file, all_comments)

    elapsed = (
        datetime.utcnow() - start_time
    ).seconds

    print(
        f"\n[DONE] Saved {len(all_comments)} "
        f"comment threads -> '{output_file}' "
        f"({elapsed}s)"
    )

    return all_comments


# ─────────────────────────────────────────────────────────────
# ENTRYPOINT
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":

    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Crawl Reddit comments recursively "
            "(TEXT ONLY dataset mode)"
        )
    )

    parser.add_argument(
        "--posts-file",
        default="DataOutput/reddit_posts.json",
        help="Input posts JSON"
    )

    parser.add_argument(
        "--output-file",
        default="DataOutput/reddit_comments.json",
        help="Output comments JSON"
    )

    parser.add_argument(
        "--max-posts",
        type=int,
        default=500,
        help="Limit number of posts"
    )

    args = parser.parse_args()

    crawl_comments(
        posts_file=args.posts_file,
        output_file=args.output_file,
        max_posts=args.max_posts,
    )
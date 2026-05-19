import os
from Utils.json_utils import append_json, load_existing_ids
import requests
import urllib3

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


def crawl_posts(
    limit: int = 25,
    output_file: str = "DataOutput/reddit_posts.json",
) -> list[dict]:
    """
    Fetch posts from Reddit and save to `output_file`.
    Returns the collected post records.
    """
    url = f"https://www.reddit.com/user/chivalricsystems/m/indonesiasemua/hot/.json?limit={limit}"
    print(f"[Step 1] Fetching chivalricsystems/m/indonesiasemua/hot/.json?limit={limit} ...")

    existing_ids = load_existing_ids(output_file, "id")

    print(f"[INFO] Existing posts: {len(existing_ids)}")

    try:
        response = requests.get(
            url, headers=HEADERS, timeout=10, proxies=PROXIES, verify=False
        )
        response.raise_for_status()
        try:
            data = response.json()
        except Exception:
            raise RuntimeError(
                "Response is not valid JSON — Reddit may be blocked by your ISP.\n"
                "Tip: Set HTTPS_PROXY env var to route through a proxy, e.g.:\n"
                "     $env:HTTPS_PROXY='http://127.0.0.1:10809'"
            )
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Failed to fetch posts: {e}") from e

    posts = data["data"]["children"]
    results = []

    for post in posts:
        d = post["data"]

        post_data = {
            "id":           d.get("id"),
            "title":        d.get("title"),
            "author":       d.get("author"),
            "subreddit":    d.get("subreddit"),
            "score":        d.get("score"),
            "num_comments": d.get("num_comments"),
            "created_utc":  d.get("created_utc"),
            "url":          "https://www.reddit.com" + d.get("permalink", ""),
            "selftext":     d.get("selftext", ""),
        }

        if post_data["id"] in existing_ids:
            continue

        results.append(post_data)

    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    append_json(output_file, results)

    print(f"[INFO] New posts found: {len(results)}")
    print(f"[INFO] Appended to: '{output_file}'")
    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Crawl Reddit posts.")
    parser.add_argument("--limit",       type=int, default=25,                       help="Number of posts to fetch (max 100, default: 100)")
    parser.add_argument("--output-file", default="DataOutput/reddit_posts.json",     help="Output JSON file")
    args = parser.parse_args()

    crawl_posts(
        limit=args.limit,
        output_file=args.output_file,
    )


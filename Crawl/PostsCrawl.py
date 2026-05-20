import os
import time
from Utils.json_utils import append_json, load_existing_ids
import requests
import urllib3

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


def crawl_posts(
    limit: int = 2500,
    output_file: str = "DataOutput/reddit_posts.json",
) -> list[dict]:
    """
    Fetch posts from Reddit and save to `output_file`.
    Returns the collected post records.
    """
    existing_ids = set(load_existing_ids(output_file, "id"))

    print(f"[INFO] Existing posts: {len(existing_ids)}")

    results = []
    after = None
    fetched_count = 0

    while fetched_count < limit:
        batch_limit = min(100, limit - fetched_count)
        url = f"https://www.reddit.com/user/chivalricsystems/m/indonesiasemua/hot/.json?limit={batch_limit}"
        if after:
            url += f"&after={after}"
            
        print(f"[Step 1] Fetching {url} ...")

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
        if not posts:
            break

        for post in posts:
            d = post["data"]

            post_data = {
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
            
            fetched_count += 1

            if post_data["id"] not in existing_ids:
                results.append(post_data)
                existing_ids.add(post_data["id"])
                
            if fetched_count >= limit:
                break
                
        after = data["data"].get("after")
        if not after or fetched_count >= limit:
            break
            
        time.sleep(1)

    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    append_json(output_file, results)

    print(f"[INFO] New posts found: {len(results)}")
    print(f"[INFO] Appended to: '{output_file}'")
    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Crawl Reddit posts.")
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Number of posts to fetch (default: 500)",
    )
    parser.add_argument(
        "--output-file", default="DataOutput/reddit_posts.json", help="Output JSON file"
    )
    args = parser.parse_args()

    crawl_posts(
        limit=args.limit,
        output_file=args.output_file,
    )

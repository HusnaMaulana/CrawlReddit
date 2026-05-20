import os
import sys
import time
import json
from datetime import datetime, timezone

from Crawl.PostsCrawl import crawl_posts
from Crawl.CommentReplyCrawl import crawl_comments
from DataProcessing.UltraChatFormatv1 import process_data as process_data_v1
from DataProcessing.UltraChatFormatv2 import process_data as process_data_v2


def run_comment_step_wrapper(
    posts_file: str,
    output_file: str,
    max_posts: int | None,
) -> list[dict]:
    print(f"\n[Step 2] Crawling comments with replies ...")
    return crawl_comments(
        posts_file=posts_file,
        output_file=output_file,
        max_posts=max_posts,
    )


def run_pipeline(
    subreddit: str = "indonesia",
    listing: str = "new",
    limit: int = 2500,
    max_posts: int | None = 2500,
    posts_file: str = "DataOutput/reddit_posts.json",
    comments_file: str = "DataOutput/reddit_comments.json",
    summary_file: str = "DataOutput/pipeline_summary.json",
    dataset_jsonv1: str = "DataOutput/indonesia_ultrachat_stylev1.json",
    dataset_jsonv2: str = "DataOutput/indonesia_ultrachat_stylev2.json",
    delay_between_steps: int = 3,
) -> None:
    pipeline_start = datetime.now(timezone.utc)

    print("=" * 60)
    print("  Reddit Crawl Pipeline")
    print(f"  Started: {pipeline_start.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 60)

    step1_start = time.time()
    posts = crawl_posts(
        limit=limit,
        output_file=posts_file,
    )
    step1_elapsed = round(time.time() - step1_start, 1)

    print(f"         (waiting {delay_between_steps}s before Step 2)")
    time.sleep(delay_between_steps)

    step2_start = time.time()
    comments = run_comment_step_wrapper(
        posts_file=posts_file,
        output_file=comments_file,
        max_posts=max_posts,
    )
    step2_elapsed = round(time.time() - step2_start, 1)

    print(f"\n         (waiting {delay_between_steps}s before Step 3)")
    time.sleep(delay_between_steps)

    print("\n[Step 3] Data Processing ...")
    step3_start = time.time()
    dataset_v1 = process_data_v1(input_file=comments_file, output_file=dataset_jsonv1)
    dataset_v2 = process_data_v2(input_file=comments_file, output_file=dataset_jsonv2)
    step3_elapsed = round(time.time() - step3_start, 1)

    pipeline_end = datetime.now(timezone.utc)
    total_elapsed = round((pipeline_end - pipeline_start).total_seconds(), 1)

    summary = {
        "pipeline_run_at": pipeline_start.isoformat(),
        "subreddit": subreddit,
        "listing": listing,
        "posts_fetched": len(posts),
        "posts_file": posts_file,
        "comments_with_replies": len(comments),
        "comments_file": comments_file,
        "dataset_jsonv1": dataset_jsonv1,
        "dataset_jsonv2": dataset_jsonv2,
        "dataset_v1_size": len(dataset_v1) if dataset_v1 else 0,
        "dataset_v2_size": len(dataset_v2) if dataset_v2 else 0,
        "step1_seconds": step1_elapsed,
        "step2_seconds": step2_elapsed,
        "step3_seconds": step3_elapsed,
        "total_seconds": total_elapsed,
    }

    import os

    os.makedirs(os.path.dirname(summary_file) or ".", exist_ok=True)
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print("  Pipeline complete")
    print(f"  Posts crawled          : {len(posts)}")
    print(f"  Comments (with replies): {len(comments)}")
    print(f"  Dataset v1 size        : {len(dataset_v1) if dataset_v1 else 0}")
    print(f"  Dataset v2 size        : {len(dataset_v2) if dataset_v2 else 0}")
    print(f"  Total time             : {total_elapsed}s")
    print(f"  Summary saved to       : {summary_file}")
    print("=" * 60)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Reddit crawl pipeline: posts -> comments with replies"
    )
    parser.add_argument(
        "--subreddit", default="indonesia", help="Target subreddit (default: indonesia)"
    )
    parser.add_argument(
        "--listing", default="new", help="Listing type: new / hot / top (default: new)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=2500,
        help="Number of posts to fetch (default: 2500)",
    )
    parser.add_argument(
        "--max-posts",
        type=int,
        default=2500,
        help="Cap posts sent to comment crawler (default: 2500)",
    )
    parser.add_argument(
        "--posts-file",
        default="DataOutput/reddit_posts.json",
        help="Intermediate posts JSON file",
    )
    parser.add_argument(
        "--comments-file",
        default="DataOutput/reddit_comments.json",
        help="Output comments JSON file",
    )
    parser.add_argument(
        "--summary-file",
        default="DataOutput/pipeline_summary.json",
        help="Pipeline run summary JSON file",
    )
    parser.add_argument(
        "--datasetv1-json",
        default="DataOutput/indonesia_ultrachat_stylev1.json",
        help="Output dataset JSON file",
    )
    parser.add_argument(
        "--datasetv2-json",
        default="DataOutput/indonesia_ultrachat_stylev2.json",
        help="Output dataset JSON file",
    )
    parser.add_argument(
        "--step-delay",
        type=int,
        default=3,
        help="Seconds to wait between steps (default: 3)",
    )
    args = parser.parse_args()

    run_pipeline(
        subreddit=args.subreddit,
        listing=args.listing,
        limit=args.limit,
        max_posts=args.max_posts,
        posts_file=args.posts_file,
        comments_file=args.comments_file,
        summary_file=args.summary_file,
        dataset_jsonv1=args.datasetv1_json,
        dataset_jsonv2=args.datasetv2_json,
        delay_between_steps=args.step_delay,
    )

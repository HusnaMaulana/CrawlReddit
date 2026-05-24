"""
app.py — CLI entry point for the Reddit crawl pipeline.

Usage examples
──────────────
# Default run (4 workers, all listings, 2500 posts):
    python app.py

# Fast test run:
    python app.py --limit 10 --workers 2

# Resume a previous run (SQLite remembers which posts are done):
    python app.py --resume

# Run forever, cycling every 5 minutes:
    python app.py --continuous --cycle-delay 300

# Skip DataProcessing (just crawl):
    python app.py --skip-processing

# Custom proxy and 6 workers:
    python app.py --workers 6
    # (set HTTP_PROXY / HTTPS_PROXY environment variables)
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from Pipeline.Pipeline import run_pipeline
from Utils.logging_config import setup_logging

def main() -> None:
    setup_logging()

    parser = argparse.ArgumentParser(
        description="Reddit Crawl Pipeline — posts → comments (producer-consumer).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=2500,
        help="Max new posts to discover per run.",
    )
    parser.add_argument(
        "--listings",
        default="hot,new,top,rising",
        help="Comma-separated listing types to crawl.",
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of parallel comment-crawling worker processes.",
    )

    parser.add_argument(
        "--posts-file",
        default="DataOutput/posts.jsonl",
        help="JSONL file for crawled posts.",
    )
    parser.add_argument(
        "--comments-file",
        default="DataOutput/comments.jsonl",
        help="JSONL file for crawled comments.",
    )
    parser.add_argument(
        "--db-path",
        default="DataOutput/crawl_state.db",
        help="SQLite state database path.",
    )
    parser.add_argument(
        "--summary-file",
        default="DataOutput/pipeline_summary.json",
        help="Pipeline run summary JSON.",
    )
    parser.add_argument(
        "--datasetv1-json",
        default="DataOutput/indonesia_ultrachat_stylev1.json",
        help="Output path for v1 UltraChat dataset.",
    )
    parser.add_argument(
        "--datasetv2-json",
        default="DataOutput/indonesia_ultrachat_stylev2.json",
        help="Output path for v2 UltraChat dataset.",
    )

    parser.add_argument(
        "--continuous",
        action="store_true",
        help="Run in continuous loop mode (never exits).",
    )
    parser.add_argument(
        "--cycle-delay",
        type=int,
        default=300,
        help="Seconds between continuous cycles.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Resume from last checkpoint. Posts already in the SQLite DB "
            "are skipped automatically — this flag is a no-op (kept for "
            "clarity; dedup is always active)."
        ),
    )
    parser.add_argument(
        "--skip-processing",
        action="store_true",
        help="Skip UltraChat DataProcessing step (crawl only).",
    )
    parser.add_argument(
        "--step-delay",
        type=int,
        default=3,
        help="Seconds to wait before starting DataProcessing.",
    )

    args = parser.parse_args()

    run_pipeline(
        limit=args.limit,
        workers=args.workers,
        posts_file=args.posts_file,
        comments_file=args.comments_file,
        db_path=args.db_path,
        listings=args.listings.split(","),
        continuous=args.continuous,
        cycle_delay=args.cycle_delay,
        skip_processing=args.skip_processing,
        dataset_jsonv1=args.datasetv1_json,
        dataset_jsonv2=args.datasetv2_json,
        summary_file=args.summary_file,
        delay_between_steps=args.step_delay,
    )

if __name__ == "__main__":
    main()

"""
Pipeline.py — Producer-consumer Reddit crawl pipeline.

Architecture
────────────
1. On startup, re-enqueue any posts that were previously marked
   'pending' in SQLite (crash recovery).
2. Start N consumer worker processes, each reading from a shared Queue.
3. Run the post producer in the main process (crawl_posts pushes to Queue).
4. When the producer finishes, send N SENTINEL values into the Queue.
5. Wait for all workers to finish.
6. Run DataProcessing (UltraChat format) on the collected JSONL.
7. Write pipeline summary JSON.

Handles SIGINT (Ctrl+C) gracefully: drains the queue, lets workers
finish their current post, then exits cleanly.
"""

import json
import multiprocessing
import os
import signal
import sys
import time
from datetime import datetime, timezone

from Crawl.CommentReplyCrawl import comment_worker
from Crawl.PostsCrawl import SENTINEL, crawl_posts
from DataProcessing.UltraChatFormatv1 import process_data as process_v1
from DataProcessing.UltraChatFormatv2 import process_data as process_v2
from Utils.logging_config import get_logger, setup_logging
from Utils.storage import CrawlDatabase

# ── graceful shutdown flag ────────────────────────────────────

_SHUTDOWN = False


def _handle_sigint(signum, frame):  # noqa: ANN001
    global _SHUTDOWN
    log = get_logger()
    log.warning(
        "\n[Pipeline] SIGINT received — finishing current posts then exiting..."
    )
    _SHUTDOWN = True


# ── pipeline ──────────────────────────────────────────────────


def run_pipeline(
    limit: int = 5000,
    workers: int = 4,
    posts_file: str = "DataOutput/posts.jsonl",
    comments_file: str = "DataOutput/comments.jsonl",
    db_path: str = "DataOutput/crawl_state.db",
    listings: list[str] | None = None,
    continuous: bool = False,
    cycle_delay: int = 300,
    skip_processing: bool = False,
    dataset_jsonv1: str = "DataOutput/indonesia_ultrachat_stylev1.json",
    dataset_jsonv2: str = "DataOutput/indonesia_ultrachat_stylev2.json",
    summary_file: str = "DataOutput/pipeline_summary.json",
    delay_between_steps: int = 3,
) -> None:
    """
    Run the full pipeline end-to-end.

    Parameters
    ──────────
    limit           : Maximum new posts to discover per run.
    workers         : Number of parallel comment-crawling worker processes.
    posts_file      : JSONL path for post output.
    comments_file   : JSONL path for comment output.
    db_path         : SQLite state database path.
    listings        : Listing types to crawl (default: hot,new,top,rising).
    continuous      : Loop forever with `cycle_delay` between cycles.
    cycle_delay     : Seconds between continuous cycles.
    skip_processing : Skip the UltraChat formatting step.
    dataset_jsonv1  : Output path for v1 dataset.
    dataset_jsonv2  : Output path for v2 dataset.
    summary_file    : Path for pipeline run summary JSON.
    delay_between_steps : Seconds to wait before starting DataProcessing.
    """
    if listings is None:
        listings = ["hot", "new", "top", "rising"]

    setup_logging()
    log = get_logger()

    # ── graceful shutdown ──────────────────────────────────────
    signal.signal(signal.SIGINT, _handle_sigint)

    pipeline_start = datetime.now(timezone.utc)

    log.info("=" * 60)
    log.info("  Reddit Crawl Pipeline (producer-consumer)")
    log.info(f"  Started : {pipeline_start.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    log.info(f"  Workers : {workers}")
    log.info(f"  Listings: {', '.join(listings)}")
    log.info("=" * 60)

    # ── Step 0: crash recovery ─────────────────────────────────
    db = CrawlDatabase(db_path)
    pending = db.get_pending_posts()
    db.close()

    if pending:
        log.info(
            f"[Pipeline] Found {len(pending)} pending posts from previous run. "
            "They will be re-enqueued for comment crawling."
        )

    # ── Step 1+2: producer + consumers (concurrent) ────────────
    log.info(f"\n[Step 1] Starting {workers} comment worker(s)...")
    log.info("[Step 2] Starting post producer (crawl_posts)...")

    step12_start = time.time()

    # shared queue (bounded to avoid unbounded memory growth)
    queue: multiprocessing.Queue = multiprocessing.Queue(maxsize=200)

    # start worker processes
    worker_procs: list[multiprocessing.Process] = []
    for i in range(workers):
        p = multiprocessing.Process(
            target=comment_worker,
            args=(queue, db_path, comments_file, i),
            daemon=True,
            name=f"CommentWorker-{i}",
        )
        p.start()
        worker_procs.append(p)
        log.info(f"  Worker {i} started (pid={p.pid})")

    # re-enqueue any pending posts from a previous crashed run
    for post_stub in pending:
        queue.put(post_stub)
        log.info(f"  Re-enqueued pending post: {post_stub.get('id')}")

    # run producer (blocks until all posts are discovered)
    try:
        new_posts_count = crawl_posts(
            limit=limit,
            output_file=posts_file,
            db_path=db_path,
            listings=listings,
            queue=queue,
            continuous=continuous,
            cycle_delay=cycle_delay,
        )
    except Exception as exc:
        log.error(f"[Pipeline] Post producer failed: {exc}")
        new_posts_count = 0

    log.info(f"[Pipeline] Producer finished. {new_posts_count} new posts discovered.")

    # send poison pills — one per worker
    log.info(f"[Pipeline] Sending {workers} sentinel(s) to workers...")
    for _ in range(workers):
        queue.put(SENTINEL)

    # wait for all workers to drain the queue and exit
    log.info("[Pipeline] Waiting for workers to finish...")
    for p in worker_procs:
        p.join()
        log.info(f"  Worker {p.name} exited (code={p.exitcode})")

    step12_elapsed = round(time.time() - step12_start, 1)
    log.info(f"[Pipeline] Steps 1+2 complete in {step12_elapsed}s")

    if _SHUTDOWN:
        log.warning("[Pipeline] Shutdown requested — skipping DataProcessing.")
        return

    # ── Step 3: DataProcessing ─────────────────────────────────
    if skip_processing:
        log.info("[Step 3] Skipping DataProcessing (--skip-processing).")
        dataset_v1_size = 0
        dataset_v2_size = 0
        step3_elapsed = 0.0
    else:
        log.info(f"\n         (waiting {delay_between_steps}s before Step 3)")
        time.sleep(delay_between_steps)

        log.info("[Step 3] Running DataProcessing (UltraChat format)...")
        step3_start = time.time()

        try:
            dataset_v1 = process_v1(
                input_file=comments_file, output_file=dataset_jsonv1
            )
            dataset_v1_size = len(dataset_v1) if dataset_v1 else 0
        except Exception as exc:
            log.error(f"  DataProcessing v1 failed: {exc}")
            dataset_v1_size = 0

        try:
            dataset_v2 = process_v2(
                input_file=comments_file, output_file=dataset_jsonv2
            )
            dataset_v2_size = len(dataset_v2) if dataset_v2 else 0
        except Exception as exc:
            log.error(f"  DataProcessing v2 failed: {exc}")
            dataset_v2_size = 0

        step3_elapsed = round(time.time() - step3_start, 1)
        log.info(f"[Pipeline] Step 3 complete in {step3_elapsed}s")

    # ── Summary ────────────────────────────────────────────────
    pipeline_end = datetime.now(timezone.utc)
    total_elapsed = round((pipeline_end - pipeline_start).total_seconds(), 1)

    db2 = CrawlDatabase(db_path)
    db_counts = db2.count_by_status()
    db2.close()

    summary = {
        "pipeline_run_at": pipeline_start.isoformat(),
        "listings": listings,
        "workers": workers,
        "posts_discovered": new_posts_count,
        "posts_file": posts_file,
        "comments_file": comments_file,
        "db_path": db_path,
        "db_status_counts": db_counts,
        "dataset_jsonv1": dataset_jsonv1,
        "dataset_jsonv2": dataset_jsonv2,
        "dataset_v1_size": dataset_v1_size if not skip_processing else None,
        "dataset_v2_size": dataset_v2_size if not skip_processing else None,
        "step12_seconds": step12_elapsed,
        "step3_seconds": step3_elapsed if not skip_processing else None,
        "total_seconds": total_elapsed,
    }

    os.makedirs(os.path.dirname(summary_file) or ".", exist_ok=True)
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    log.info("\n" + "=" * 60)
    log.info("  Pipeline complete")
    log.info(f"  Posts discovered        : {new_posts_count}")
    log.info(f"  DB status               : {db_counts}")
    if not skip_processing:
        log.info(f"  Dataset v1 size         : {dataset_v1_size}")
        log.info(f"  Dataset v2 size         : {dataset_v2_size}")
    log.info(f"  Total time              : {total_elapsed}s")
    log.info(f"  Summary saved to        : {summary_file}")
    log.info("=" * 60)


# ── CLI ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    setup_logging()
    parser = argparse.ArgumentParser(
        description="Reddit crawl pipeline: posts -> comments (producer-consumer)"
    )
    parser.add_argument("--limit", type=int, default=2500)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--posts-file", default="DataOutput/posts.jsonl")
    parser.add_argument("--comments-file", default="DataOutput/comments.jsonl")
    parser.add_argument("--db-path", default="DataOutput/crawl_state.db")
    parser.add_argument("--listings", default="hot,new,top,rising")
    parser.add_argument("--continuous", action="store_true")
    parser.add_argument("--cycle-delay", type=int, default=300)
    parser.add_argument("--skip-processing", action="store_true")
    parser.add_argument(
        "--datasetv1-json", default="DataOutput/indonesia_ultrachat_stylev1.json"
    )
    parser.add_argument(
        "--datasetv2-json", default="DataOutput/indonesia_ultrachat_stylev2.json"
    )
    parser.add_argument("--summary-file", default="DataOutput/pipeline_summary.json")
    parser.add_argument("--step-delay", type=int, default=3)
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

import argparse
from Pipeline.Pipeline import run_pipeline

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Reddit Crawl Pipeline — posts then comments with replies."
    )
    parser.add_argument("--subreddit",     default="indonesia",                        help="Target subreddit (default: indonesia)")
    parser.add_argument("--listing",       default="new",                              help="Listing type: new / hot / top (default: new)")
    parser.add_argument("--limit",         type=int, default=100,                      help="Number of posts to fetch (max 100, default: 100)")
    parser.add_argument("--max-posts",     type=int, default=None,                     help="Cap posts sent to comment crawler (default: all)")
    parser.add_argument("--posts-file",    default="DataOutput/reddit_posts.json",     help="Intermediate posts JSON file")
    parser.add_argument("--comments-file", default="DataOutput/reddit_comments.json",  help="Output comments JSON file")
    parser.add_argument("--summary-file",  default="DataOutput/pipeline_summary.json", help="Pipeline run summary JSON file")
    parser.add_argument("--datasetv1-json",  default="DataOutput/indonesia_ultrachat_stylev1.json", help="Output dataset JSON file")
    parser.add_argument("--datasetv2-json",  default="DataOutput/indonesia_ultrachat_stylev2.json", help="Output dataset JSON file")
    parser.add_argument("--step-delay",    type=int, default=3,                        help="Seconds to wait between steps (default: 3)")
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
        delay_between_steps=args.step_delay
    )
"""Analyze the gap between posts.jsonl and comments.jsonl."""
import json
import sqlite3
from collections import Counter

print("=" * 60)
print("  PIPELINE GAP ANALYSIS")
print("=" * 60)

# 1. posts.jsonl
all_post_ids = []
with open("DataOutput/posts.jsonl", "r") as f:
    for line in f:
        line = line.strip()
        if line:
            data = json.loads(line)
            all_post_ids.append(data.get("id", ""))

unique_post_ids = set(all_post_ids)
dupes = {k: v for k, v in Counter(all_post_ids).items() if v > 1}

print(f"\n--- posts.jsonl ---")
print(f"  Total lines:      {len(all_post_ids)}")
print(f"  Unique post_ids:  {len(unique_post_ids)}")
print(f"  Duplicates:       {len(dupes)}")
if dupes:
    print(f"  Extra dup lines:  {sum(v for v in dupes.values()) - len(dupes)}")
    for pid, cnt in list(dupes.items())[:5]:
        print(f"    {pid}: {cnt}x")

# 2. comments.jsonl
comment_post_ids = set()
comment_lines = 0
with open("DataOutput/comments.jsonl", "r") as f:
    for line in f:
        line = line.strip()
        if line:
            comment_lines += 1
            data = json.loads(line)
            comment_post_ids.add(data.get("post_id", ""))

print(f"\n--- comments.jsonl ---")
print(f"  Total lines (comment threads): {comment_lines}")
print(f"  Unique post_ids represented:   {len(comment_post_ids)}")

# 3. Overlap
overlap = unique_post_ids & comment_post_ids
missing = unique_post_ids - comment_post_ids

print(f"\n--- Cross-reference ---")
print(f"  Posts WITH comments:    {len(overlap)}")
print(f"  Posts WITHOUT comments: {len(missing)}")

# 4. SQLite DB
conn = sqlite3.connect("DataOutput/crawl_state.db")
conn.row_factory = sqlite3.Row

rows = conn.execute("SELECT status, COUNT(*) as n FROM crawled_posts GROUP BY status").fetchall()
print(f"\n--- SQLite DB status ---")
for r in rows:
    print(f"  {r['status']}: {r['n']}")

total_db = conn.execute("SELECT COUNT(*) FROM crawled_posts").fetchone()[0]
print(f"  TOTAL: {total_db}")

errors = conn.execute("SELECT post_id, subreddit FROM crawled_posts WHERE status = 'error'").fetchall()
if errors:
    print(f"\n--- Error posts ({len(errors)}) ---")
    for r in errors[:10]:
        print(f"  {r['post_id']} ({r['subreddit']})")

pending = conn.execute("SELECT post_id, subreddit FROM crawled_posts WHERE status = 'pending'").fetchall()
if pending:
    print(f"\n--- Pending posts ({len(pending)}) ---")
    for r in pending[:10]:
        print(f"  {r['post_id']} ({r['subreddit']})")

# 5. Understand the filtering in fetch_comments
# Posts are skipped if: media post, empty/removed/deleted body, or no comment threads with replies
print(f"\n--- WHY posts can produce 0 comment lines ---")
print("  fetch_comments() returns [] (no lines written) when:")
print("  1. Post is a media post (image, video, gallery, etc.)")
print("  2. Post body is empty, [removed], or [deleted]")
print("  3. Post has no top-level comments with replies")
print("     (only comments WITH nested replies are kept)")
print()
print("  The DB marks ALL posts as 'done' regardless of whether")
print("  comments were found. So 'done' count = posts processed,")
print("  NOT posts with comments.")

# 6. Count how many posts were marked done but produced zero comments
done_ids = set()
done_rows = conn.execute("SELECT post_id FROM crawled_posts WHERE status='done'").fetchall()
for r in done_rows:
    done_ids.add(r['post_id'])

done_no_comments = done_ids - comment_post_ids
print(f"\n--- Summary ---")
print(f"  Posts marked 'done' in DB:          {len(done_ids)}")
print(f"  Posts 'done' WITH comment output:   {len(done_ids & comment_post_ids)}")
print(f"  Posts 'done' with NO comment output: {len(done_no_comments)}")
print(f"    (these were filtered out by fetch_comments)")

conn.close()

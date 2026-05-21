import json
from Crawl.CommentReplyCrawl import is_media_post, has_media

posts = []
with open("DataOutput/posts.jsonl", "r") as f:
    for line in f:
        line = line.strip()
        if line:
            posts.append(json.loads(line))

no_body_count = 0
media_count = 0
valid_posts = 0

for post in posts:
    raw_body = (post.get("selftext") or "").strip()
    
    if is_media_post(post):
        media_count += 1
        continue
        
    if raw_body in ("", "[removed]", "[deleted]"):
        no_body_count += 1
        continue
        
    valid_posts += 1

print(f"Total posts: {len(posts)}")
print(f"Media posts (skipped): {media_count}")
print(f"Empty/removed body (skipped): {no_body_count}")
print(f"Valid posts to fetch comments for: {valid_posts}")

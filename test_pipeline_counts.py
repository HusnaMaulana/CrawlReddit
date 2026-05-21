import json

comments = []
with open("DataOutput/comments.jsonl", "r") as f:
    for line in f:
        line = line.strip()
        if line:
            comments.append(json.loads(line))

print(f"Comments JSONL lines: {len(comments)}")

post_ids_with_comments = set(c.get("post_id") for c in comments)
print(f"Unique posts with valid comments: {len(post_ids_with_comments)}")

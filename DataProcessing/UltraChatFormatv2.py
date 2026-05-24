import json
import re
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from Utils.storage import load_input

sys.stdout.reconfigure(encoding="utf-8")

MAX_DEPTH = 6

BAD_TEXT = {"[deleted]", "[removed]", "", " "}

LOW_QUALITY_PATTERNS = [
    "upvote",
    "downvote",
]

MEDIA_ONLY = {"gif", "img", "video", "giphy"}

_EMOJI_RE = re.compile(
    "["
    "\U0001f600-\U0001f64f"
    "\U0001f300-\U0001f5ff"
    "\U0001f680-\U0001f6ff"
    "\U0001f1e0-\U0001f1ff"
    "\U0001f900-\U0001f9ff"
    "\U0001fa70-\U0001faff"
    "\U00002702-\U000027b0"
    "\U000024c2-\U0001f251"
    "\U0000200d"
    "\U0000fe0f"
    "]+",
    flags=re.UNICODE,
)

def clean_text(text):

    if not text:
        return ""

    text = re.sub(r"https?://\S+|www\.\S+", "", text)

    text = re.sub(r"!\[(?:gif|img|video)?\]\([^)]*\)", "", text, flags=re.IGNORECASE)

    text = re.sub(r"\((?:giphy|emote)[^)]*\)", "", text, flags=re.IGNORECASE)

    text = re.sub(r"!\s*(gif|img|video)\b", "", text, flags=re.IGNORECASE)

    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)

    text = re.sub(r"&amp;#x200B;|&gt;|&lt;|&amp;|&nbsp;|&#x200B;|#x200B;", " ", text)

    text = re.sub(r"(^|\s)>\s*", " ", text)

    text = re.sub(r"(\*{1,3}|_{1,3}|~{2})", "", text)

    text = re.sub(r"`{1,3}.*?`{1,3}", "", text)

    text = _EMOJI_RE.sub("", text)

    text = re.sub(r"[\u200b-\u200f\u202a-\u202e]", "", text)

    text = re.sub(r"\.{4,}", "...", text)
    text = re.sub(r"!{4,}", "!!!", text)
    text = re.sub(r"\?{4,}", "???", text)

    text = text.replace("\n", " ")
    text = text.replace("\r", " ")

    text = re.sub(r"\s+", " ", text).strip()

    return text

def is_valid(text):

    if not text:
        return False

    text_lower = text.lower().strip()

    if text_lower in BAD_TEXT:
        return False

    if text_lower in MEDIA_ONLY:
        return False

    if len(text_lower) < 3:
        return False

    for pattern in LOW_QUALITY_PATTERNS:
        if pattern in text_lower:
            return False

    alnum_count = sum(c.isalnum() for c in text)

    if alnum_count < 2:
        return False

    return True

def extract_chain(comment, chain=None, depth=0):

    if chain is None:
        chain = []

    if depth > MAX_DEPTH:
        return chain

    text = clean_text(comment.get("body", ""))

    if not is_valid(text):
        return chain

    chain.append(text)

    replies = comment.get("replies", [])

    if not replies:
        return chain

    for reply in replies:

        reply_text = clean_text(reply.get("body", ""))

        if is_valid(reply_text):

            return extract_chain(reply, chain, depth + 1)

    return chain

def process_data(input_file: str, output_file: str) -> list:
    try:
        data = load_input(input_file)
    except FileNotFoundError:
        print(f"[ERROR] Input file not found: {input_file}")
        sys.exit(1)

    dataset = []
    seen = set()

    for comment in data:
        chain = extract_chain(comment)

        if not chain:
            continue

        post_title = clean_text(comment.get("post_title", ""))
        post_body = clean_text(comment.get("post_body", ""))

        context_text = post_title
        if post_body and post_body != "-":
            context_text += f" {post_body}"

        if not context_text.strip():
            context_text = "-"

        full_chain = [context_text.strip()] + chain

        if len(full_chain) % 2 != 0:
            full_chain = full_chain[:-1]

        if len(full_chain) < 2:
            continue

        key = tuple(x.lower().strip() for x in full_chain)
        if key not in seen:
            dataset.append(full_chain)
            seen.add(key)

    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)

    return dataset

if __name__ == "__main__":
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    INPUT_FILE = os.path.join(SCRIPT_DIR, "..", "DataOutput", "comments.jsonl")
    OUTPUT_FILE = os.path.join(
        SCRIPT_DIR, "..", "DataOutput", "indonesia_ultrachat_stylev2.json"
    )

    dataset = process_data(INPUT_FILE, OUTPUT_FILE)

    print("=" * 50)
    print("DATASET PROCESSING COMPLETE")
    print("=" * 50)
    print(f"Total conversations: {len(dataset)}")
    print(f"\nSaved to: {OUTPUT_FILE}")
    print("Done.")

import json
import re
import sys
import os

# Add parent directory to sys.path so it can find Utils when run directly
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from Utils.json_utils import load_json

sys.stdout.reconfigure(encoding="utf-8")

# =====================================================
# CONFIG
# =====================================================

MAX_DEPTH = 6

BAD_TEXT = {"[deleted]", "[removed]", "", " "}

LOW_QUALITY_PATTERNS = [
    "upvote",
    "downvote",
]

MEDIA_ONLY = {"gif", "img", "video", "giphy"}

# =====================================================
# EMOJI REGEX
# =====================================================

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

# =====================================================
# CLEANING
# =====================================================


def clean_text(text):

    if not text:
        return ""

    # =========================================
    # REMOVE URLS
    # =========================================

    text = re.sub(r"https?://\S+|www\.\S+", "", text)

    # =========================================
    # REMOVE REDDIT GIF/IMAGE/VIDEO EMBEDS
    # =========================================

    # ![gif](giphy|xxxxx)
    text = re.sub(r"!\[(?:gif|img|video)?\]\([^)]*\)", "", text, flags=re.IGNORECASE)

    # standalone (giphy|xxxxx)
    text = re.sub(r"\((?:giphy|emote)[^)]*\)", "", text, flags=re.IGNORECASE)

    # remove bare !gif !img !video
    text = re.sub(r"!\s*(gif|img|video)\b", "", text, flags=re.IGNORECASE)

    # =========================================
    # REMOVE MARKDOWN LINKS
    # =========================================

    # [text](url) -> text
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)

    # =========================================
    # REMOVE HTML ENTITIES
    # =========================================

    text = re.sub(r"&gt;|&lt;|&amp;|&nbsp;|&#x200B;", " ", text)

    # =========================================
    # REMOVE BLOCKQUOTE SYMBOLS
    # =========================================

    text = re.sub(r"(^|\s)>\s*", " ", text)

    # =========================================
    # REMOVE MARKDOWN FORMATTING
    # =========================================

    # bold / italic / strike
    text = re.sub(r"(\*{1,3}|_{1,3}|~{2})", "", text)

    # inline code
    text = re.sub(r"`{1,3}.*?`{1,3}", "", text)

    # =========================================
    # REMOVE EMOJIS
    # =========================================

    text = _EMOJI_RE.sub("", text)

    # =========================================
    # REMOVE INVISIBLE UNICODE
    # =========================================

    text = re.sub(r"[\u200b-\u200f\u202a-\u202e]", "", text)

    # =========================================
    # REMOVE EXCESSIVE PUNCTUATION
    # =========================================

    text = re.sub(r"\.{4,}", "...", text)
    text = re.sub(r"!{4,}", "!!!", text)
    text = re.sub(r"\?{4,}", "???", text)

    # =========================================
    # NORMALIZE WHITESPACE
    # =========================================

    text = text.replace("\n", " ")
    text = text.replace("\r", " ")

    text = re.sub(r"\s+", " ", text).strip()

    return text


# =====================================================
# VALIDATION
# =====================================================


def is_valid(text):

    if not text:
        return False

    text_lower = text.lower().strip()

    # deleted / removed
    if text_lower in BAD_TEXT:
        return False

    # media only
    if text_lower in MEDIA_ONLY:
        return False

    # too short
    if len(text_lower) < 3:
        return False

    # low quality patterns
    for pattern in LOW_QUALITY_PATTERNS:
        if pattern in text_lower:
            return False

    # mostly punctuation
    alnum_count = sum(c.isalnum() for c in text)

    if alnum_count < 2:
        return False

    return True


# =====================================================
# EXTRACT SINGLE CONVERSATION CHAIN
# =====================================================


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

    # no replies
    if not replies:
        return chain

    # ONLY take first valid reply
    for reply in replies:

        reply_text = clean_text(reply.get("body", ""))

        if is_valid(reply_text):

            return extract_chain(reply, chain, depth + 1)

    return chain


def process_data(input_file: str, output_file: str) -> list:
    try:
        data = load_json(input_file)
    except FileNotFoundError:
        print(f"[ERROR] Input file not found: {input_file}")
        sys.exit(1)

    dataset = []
    seen = set()

    for comment in data:
        chain = extract_chain(comment)

        if not chain:
            continue

        # Build post content as first element
        post_title = clean_text(comment.get("post_title", ""))
        post_body = clean_text(comment.get("post_body", ""))

        context_text = post_title
        if post_body and post_body != "-":
            context_text += f" {post_body}"

        # Use "-" if both title and body are missing/invalid
        if not context_text.strip():
            context_text = "-"

        # Prepend post content as the first element
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
    INPUT_FILE = os.path.join(SCRIPT_DIR, "..", "DataOutput", "reddit_comments.json")
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

"""Text helpers that do not depend on the resume or the browser."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "into",
    "of",
    "on",
    "or",
    "our",
    "that",
    "the",
    "their",
    "to",
    "with",
    "your",
}


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def normalize_key(text: str) -> str:
    text = normalize_space(text).lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9+.#]+", " ", text)
    return normalize_space(text)


def sha256_text(text: str) -> str:
    normalized = normalize_space(text).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def content_words(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9+#.]{2,}", text.lower())
    return {word for word in words if word not in STOPWORDS}


def jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def unique_keep(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        key = normalize_key(item)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item.strip())
    return result


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", normalize_space(text))
    return [part.strip() for part in parts if part.strip()]


def numbers_in(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", text or ""))


def safe_filename(value: str, limit: int = 48) -> str:
    cleaned = re.sub(r"[^\w.-]+", "_", value.strip(), flags=re.UNICODE)
    cleaned = re.sub(r"_+", "_", cleaned).strip("._")
    return (cleaned or "item")[:limit]


def normalize_url(url: str) -> str:
    if not url:
        return ""
    base = url.split("#", 1)[0].strip()
    if "?" in base:
        path, query = base.split("?", 1)
        kept = []
        for part in query.split("&"):
            name = part.split("=", 1)[0].lower()
            if name.startswith("utm_") or name in {"src", "tracking", "xp"}:
                continue
            kept.append(part)
        base = path + (("?" + "&".join(kept)) if kept else "")
    return base.rstrip("/").lower()

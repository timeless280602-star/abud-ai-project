"""Lightweight keyword-based skill matching for ABUD."""

import re

from app.skills.registry import discover_skills

STOPWORDS = {
    "yang", "dan", "atau", "untuk", "dengan", "dari", "dalam",
    "ini", "itu", "saya", "aku", "gue", "lu", "kamu", "tolong",
    "bisa", "buat", "bantu", "dong", "ya", "please", "the", "and",
    "for", "with", "this", "that", "help", "make", "please",
}

MAX_QUERY_LENGTH = 2000
MAX_MATCHES = 3


def tokenize(text: str) -> set[str]:
    if not isinstance(text, str):
        return set()

    words = re.findall(r"[a-zA-Z0-9_+#.-]+", text.lower())

    return {
        word for word in words
        if len(word) >= 2 and word not in STOPWORDS
    }


def match_skills(message: str, skills_dir=None, limit=MAX_MATCHES) -> list[dict]:
    """Return relevant skill metadata ranked by keyword overlap."""

    if not isinstance(message, str) or not message.strip():
        return []

    if len(message) > MAX_QUERY_LENGTH:
        message = message[:MAX_QUERY_LENGTH]

    if not isinstance(limit, int) or isinstance(limit, bool):
        limit = MAX_MATCHES

    limit = max(1, min(limit, MAX_MATCHES))
    query_words = tokenize(message)

    if not query_words:
        return []

    matches = []

    for skill in discover_skills(skills_dir):
        name_words = tokenize(skill["name"])
        description_words = tokenize(skill["description"])

        name_hits = query_words & name_words
        description_hits = query_words & description_words

        score = (
            len(name_hits) * 3
            + len(description_hits)
        )

        if score <= 0:
            continue

        matches.append({
            **skill,
            "score": score,
            "matched_terms": sorted(name_hits | description_hits),
        })

    matches.sort(
        key=lambda item: (-item["score"], item["id"])
    )

    return matches[:limit]

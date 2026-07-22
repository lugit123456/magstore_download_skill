from __future__ import annotations

import re
import unicodedata
from datetime import date

from .models import MagazineConfig


MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def normalize_title(value: str | None) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", value).casefold()
    text = re.sub(r"[\W_]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def title_matches(title: str, magazine: MagazineConfig) -> bool:
    title_norm = normalize_title(title)
    target_norm = normalize_title(magazine.magazine_name)
    search_norm = normalize_title(magazine.search_term)
    candidates = [target_norm]
    if search_norm and search_norm != target_norm:
        candidates.append(search_norm)
    if magazine.match_mode == "exact":
        return any(title_norm == candidate for candidate in candidates)
    if magazine.match_mode == "prefix":
        return any(title_norm.startswith(candidate) for candidate in candidates)
    if magazine.match_mode == "contains":
        return any(candidate in title_norm for candidate in candidates)
    pattern = magazine.regex or magazine.magazine_name
    return re.search(pattern, title, flags=re.IGNORECASE) is not None


def extract_issue_id(url: str) -> str | None:
    match = re.search(r"/issue/([^/?#]+)", url)
    return match.group(1) if match else None


def extract_issue_date(text: str | None) -> date | None:
    if not text:
        return None
    match = re.search(
        r"\b("
        + "|".join(MONTHS)
        + r")\s+(\d{1,2})(?:st|nd|rd|th)?[,]?\s+(\d{4})\b",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    month = MONTHS[match.group(1).casefold()]
    day = int(match.group(2))
    year = int(match.group(3))
    try:
        return date(year, month, day)
    except ValueError:
        return None

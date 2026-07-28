"""
Lead triage persistence + negative/positive-filter integration.

Powers the dashboard's "Mark Relevant" / "Mark Negative" buttons:
  • sales_prospects.json — append-only list of leads the NBD team flagged
    as relevant (shown in the dashboard's "Sales Prospects" tab). Doubles as
    the POSITIVE filter: on the next pipeline run, posts from the same
    author/company bypass the smart-filter gates and get a ⭐ boost
    (see load_positive_signals / is_positive).
  • negative_list.json   — append-only list of rejected leads. On the next
    pipeline run, any post whose LinkedIn URL OR normalized content hash
    matches an entry here is dropped automatically (see apply_negative_filter).

Both files live under ./data/ (auto-created on first write).

JSON-on-disk is used instead of a database deliberately: the dashboard runs
locally for a small sales team, the files are easy to audit/commit, and there
is no service to keep alive between scans.
"""

import hashlib
import json
import os
import re
from datetime import datetime
from typing import Iterable

from agent.parser import LinkedInPost


DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
SALES_PROSPECTS_PATH = os.path.join(DATA_DIR, "sales_prospects.json")
NEGATIVE_LIST_PATH = os.path.join(DATA_DIR, "negative_list.json")


# ─── Content hashing ──────────────────────────────────────────────────────────
def content_hash(text: str) -> str:
    """
    Stable SHA-1 of normalized post text.

    Lowercased, non-alphanumeric stripped, first 200 chars. Lets us catch the
    same post cross-shared under different LinkedIn URLs (very common).
    """
    if not text:
        return ""
    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()[:200]
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def _post_content_hash(post: LinkedInPost) -> str:
    return content_hash(post.snippet or "")


# ─── Generic JSON list helpers ────────────────────────────────────────────────
def _ensure_data_dir() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)


def _load_list(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_list(path: str, items: list[dict]) -> None:
    _ensure_data_dir()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)


# ─── Negative list (read by the pipeline, written by the dashboard) ───────────
def load_negative_list() -> dict:
    """
    Return {urls: set[str], hashes: set[str]} from data/negative_list.json.
    Empty sets when the file doesn't exist yet (first-ever run).
    """
    urls: set[str] = set()
    hashes: set[str] = set()
    for item in _load_list(NEGATIVE_LIST_PATH):
        if item.get("url"):
            urls.add(item["url"])
        if item.get("content_hash"):
            hashes.add(item["content_hash"])
    return {"urls": urls, "hashes": hashes}


def is_negative(post: LinkedInPost, negative: dict) -> bool:
    """True if the post's URL or content hash is in the negative list."""
    if not negative:
        return False
    if post.url and post.url in negative.get("urls", ()):
        return True
    h = _post_content_hash(post)
    return bool(h) and h in negative.get("hashes", ())


def apply_negative_filter(posts: Iterable[LinkedInPost], negative: dict) -> tuple[list, int]:
    """
    Drop posts flagged in the negative list.
    Returns (survivors, dropped_count).
    """
    if not negative:
        return list(posts), 0
    survivors = [p for p in posts if not is_negative(p, negative)]
    return survivors, len(list(posts)) - len(survivors)


def add_negative(post: LinkedInPost | dict) -> dict:
    """
    Append a post to the negative list (deduped by URL).
    Accepts a LinkedInPost or a plain dict (from the dashboard POST body).
    Returns the persisted record.
    """
    record = _to_record(post)
    record["content_hash"] = record.get("content_hash") or content_hash(record.get("snippet", ""))
    items = _load_list(NEGATIVE_LIST_PATH)
    # Dedupe by URL (and by content hash when URL is missing)
    existing_urls = {i.get("url") for i in items if i.get("url")}
    existing_hashes = {i.get("content_hash") for i in items if i.get("content_hash")}
    if record["url"] and record["url"] in existing_urls:
        return record
    if record["content_hash"] and record["content_hash"] in existing_hashes:
        return record
    items.append(record)
    _save_list(NEGATIVE_LIST_PATH, items)
    return record


# ─── Sales prospects (written by the dashboard, read by the Prospects tab) ────
def load_sales_prospects() -> list[dict]:
    return _load_list(SALES_PROSPECTS_PATH)


def add_sales_prospect(post: LinkedInPost | dict) -> dict:
    """Append a post to the sales prospects list (deduped by URL)."""
    record = _to_record(post)
    items = _load_list(SALES_PROSPECTS_PATH)
    existing_urls = {i.get("url") for i in items if i.get("url")}
    if record["url"] and record["url"] in existing_urls:
        return record
    items.append(record)
    _save_list(SALES_PROSPECTS_PATH, items)
    return record


# ─── Positive signals (learned from relevant-marked leads) ────────────────────
def _norm_author_url(url: str) -> str:
    return (url or "").strip().lower().rstrip("/")


def _norm_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def load_positive_signals() -> dict:
    """
    Derive positive-filter signals from data/sales_prospects.json:
      {author_urls: set, authors: set, companies: set, benchmark: dict|None}

    author_urls is the primary (exact) signal. Author NAMES are only used for
    records that had no author_url — a bare name match is too loose otherwise.
    Company names shorter than 4 chars are ignored to avoid false matches.

    benchmark is a content profile built from the relevant-marked posts'
    text (see agent/benchmark.py) — the filter scores every new post against
    it so inclusion aligns with what the team has actually marked relevant.
    """
    from agent.benchmark import build_benchmark

    author_urls: set[str] = set()
    authors: set[str] = set()
    companies: set[str] = set()
    snippets: list[str] = []
    for item in _load_list(SALES_PROSPECTS_PATH):
        url = _norm_author_url(item.get("author_url", ""))
        if url:
            author_urls.add(url)
        else:
            name = _norm_name(item.get("author", ""))
            if name and name != "unknown":
                authors.add(name)
        company = _norm_name(item.get("company", ""))
        if len(company) >= 4:
            companies.add(company)
        if item.get("snippet"):
            snippets.append(item["snippet"])
    return {
        "author_urls": author_urls,
        "authors": authors,
        "companies": companies,
        "benchmark": build_benchmark(snippets),
    }


def is_positive(post: LinkedInPost, positive: dict) -> bool:
    """True if the post's author/company was previously marked relevant."""
    if not positive:
        return False
    url = _norm_author_url(getattr(post, "author_url", ""))
    if url and url in positive.get("author_urls", ()):
        return True
    name = _norm_name(getattr(post, "author_name", ""))
    if name and name in positive.get("authors", ()):
        return True
    company = _norm_name(getattr(post, "company_hint", ""))
    if company and company in positive.get("companies", ()):
        return True
    return False


def make_positive_signal() -> dict:
    """Moment-signal dict shown on dashboard cards for positive-filter matches."""
    return {
        "id": "known_relevant_lead",
        "label": "Previously Marked Relevant",
        "icon": "⭐",
        "score": 0,
        "matched_keywords": [],
        "service_tags": [],
    }


# ─── Shared record builder ────────────────────────────────────────────────────
def _to_record(post) -> dict:
    """Normalize either a LinkedInPost or a dashboard POST dict into a record."""
    if isinstance(post, dict):
        return {
            "url": post.get("url", ""),
            "title": post.get("title", ""),
            "author": post.get("author") or post.get("author_name", ""),
            "author_url": post.get("author_url", ""),
            "author_headline": post.get("author_headline", ""),
            "company": post.get("company") or post.get("company_hint", ""),
            "entity_type": post.get("entity_type", ""),
            "snippet": post.get("snippet", ""),
            "intent_score": post.get("intent_score", 0),
            "region": post.get("region", ""),
            "pitch_services": post.get("pitch_services", []),
            "moment_signals": post.get("moment_signals", []),
            "marked_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        }
    # LinkedInPost instance
    return {
        "url": post.url,
        "title": post.title,
        "author": post.author_name,
        "author_url": post.author_url,
        "author_headline": post.author_headline,
        "company": post.company_hint,
        "entity_type": post.entity_type,
        "snippet": post.snippet,
        "intent_score": post.intent_score,
        "region": getattr(post, "region", ""),
        "pitch_services": post.pitch_services,
        "moment_signals": post.moment_signals,
        "marked_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    }

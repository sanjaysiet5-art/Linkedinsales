"""
Parse raw Apify LinkedIn post items into LinkedInPost objects.

Apify gives us structured data the old SerpAPI/Google flow had to guess at:
  • content            — full post text (was: truncated Google snippet)
  • postedAt.date      — exact ISO timestamp (was: regex on "2 days ago")
  • author.type        — company vs profile (was: URL heuristics)
  • engagement         — likes / comments / shares
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class LinkedInPost:
    url: str
    title: str
    snippet: str              # full post text (name kept for downstream compat)
    author_name: str
    entity_type: str          # 'brand' | 'person' | 'article'
    company_hint: str         # best-guess company name
    timestamp_raw: str        # "21 minutes ago" or ISO date
    estimated_posted_at: Optional[datetime]   # exact post time (UTC, naive)
    keywords_matched: list[str] = field(default_factory=list)
    intent_score: int = 0
    moment_signals: list[dict] = field(default_factory=list)
    pitch_services: list[str] = field(default_factory=list)   # e.g. ["SEO", "PR", "Brand"]
    timeline: str = ""
    source_query: str = ""
    author_url: str = ""
    author_headline: str = ""  # author.info — job title / follower count
    likes: int = 0
    comments_count: int = 0
    shares: int = 0
    region: str = ""           # detected from text/headline, e.g. 'india' (see agent/region.py)
    contact_email: str = ""
    contact_phone: str = ""
    company_domain: str = ""
    company_size: str = ""
    company_funding: str = ""
    company_tech_stack: list[str] = field(default_factory=list)
    decision_makers: list[dict] = field(default_factory=list)
    apollo_contact_id: str = ""



def parse_posted_at(item: dict) -> Optional[datetime]:
    """Exact post time from Apify's postedAt object (naive UTC)."""
    posted = item.get("postedAt") or {}

    ts = posted.get("timestamp")
    if ts:
        try:
            return datetime.utcfromtimestamp(ts / 1000)
        except (ValueError, OSError, TypeError):
            pass

    date_str = posted.get("date") or ""
    if date_str:
        try:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            pass

    return None


def classify_author(item: dict) -> str:
    """Map Apify author.type to our entity types."""
    author_type = ((item.get("author") or {}).get("type") or "").lower()
    if author_type == "company":
        return "brand"
    if "/pulse/" in (item.get("linkedinUrl") or ""):
        return "article"
    return "person"


def is_within_timeline(post: "LinkedInPost", timeline: str) -> bool:
    """Precise post-filter using exact Apify timestamps."""
    from config.settings import TIMELINE_CONFIG
    max_hours = TIMELINE_CONFIG.get(timeline, {}).get("max_hours", 9999)
    if post.estimated_posted_at is None:
        return True   # Can't determine age → include by default
    age_hours = (datetime.utcnow() - post.estimated_posted_at).total_seconds() / 3600
    return age_hours <= max_hours


def parse_result(raw: dict) -> LinkedInPost:
    """Convert a raw Apify post item into a LinkedInPost."""
    author = raw.get("author") or {}
    engagement = raw.get("engagement") or {}
    posted = raw.get("postedAt") or {}

    url = raw.get("linkedinUrl", "") or raw.get("shareLinkedinUrl", "")
    content = (raw.get("content") or "").strip()
    author_name = author.get("name") or "Unknown"
    entity_type = classify_author(raw)

    posted_at = parse_posted_at(raw)
    ago_text = (posted.get("postedAgoText") or "").split("•")[0].strip()
    timestamp_raw = ago_text or posted.get("date", "")

    keyword = raw.get("_keyword", "")

    return LinkedInPost(
        url=url,
        title=f"{author_name} on LinkedIn",
        snippet=content,
        author_name=author_name,
        entity_type=entity_type,
        company_hint=author_name if entity_type == "brand" else "",
        timestamp_raw=timestamp_raw,
        estimated_posted_at=posted_at,
        keywords_matched=[keyword] if keyword else [],
        timeline=raw.get("_timeline", ""),
        source_query=raw.get("_query", ""),
        author_url=author.get("linkedinUrl", "") or "",
        author_headline=author.get("info", "") or "",
        likes=engagement.get("likes") or 0,
        comments_count=engagement.get("comments") or 0,
        shares=engagement.get("shares") or 0,
    )

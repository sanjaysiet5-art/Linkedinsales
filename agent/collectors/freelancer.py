"""
Freelancer.com project posts → buyers seeking a vendor (signal).

Uses Freelancer.com's public projects API (no key, no Apify cost). Most posts
are tiny, so anything whose max budget is under min_budget_usd is skipped.
"""

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import requests

from agent.collectors import ScanContext, make_post, clean_text, parse_iso
from config.sources import FREELANCER as CFG

# A project must list at least one skill Grapes actually sells — the search
# API matches loosely ("SEO" also returns logistics / accounting projects).
_MARKETING_SKILL = re.compile(
    r"marketing|seo|social|brand|logo|graphic|design|video|animation|3d|cgi|advertis|"
    r"\bads\b|adwords|public relations|\bpr\b|content|copywrit|website|wordpress|shopify|"
    r"influencer|photograph|event|motion|illustrat|packaging|\bui\b|\bux\b",
    re.IGNORECASE,
)

_CURRENCY_REGION = {"INR": "india", "AED": "uae", "SAR": "saudi", "GBP": "uk", "USD": "", "EUR": "europe"}


def _search(query: str, since_ts: int) -> list[dict]:
    resp = requests.get(CFG["api"], params={
        "query": query, "limit": CFG["per_search"], "full_description": "true",
        "job_details": "true", "sort_field": "time_updated", "from_time": since_ts,
    }, headers={"User-Agent": "Mozilla/5.0 (GrapesLeadEngine)"}, timeout=30)
    resp.raise_for_status()
    projects = (resp.json().get("result") or {}).get("projects") or []
    for p in projects:
        p["_query"] = query
    return projects


def _budget_usd(p: dict) -> tuple[float, str]:
    b = p.get("budget") or {}
    cur = p.get("currency") or {}
    rate = float(cur.get("exchange_rate") or 1.0)
    hi = float(b.get("maximum") or b.get("minimum") or 0)
    sign = cur.get("sign") or ""
    lo = b.get("minimum")
    label = f"{sign}{lo:,.0f}–{sign}{hi:,.0f} {cur.get('code', '')}".strip() if lo else f"{sign}{hi:,.0f}"
    return hi * rate, label


def normalize(projects: list[dict]) -> list:
    posts, seen = [], set()
    for p in projects:
        pid = p.get("id")
        if not pid or pid in seen:
            continue
        seen.add(pid)
        usd, label = _budget_usd(p)
        if usd < CFG["min_budget_usd"]:
            continue
        title = (p.get("title") or "").strip()
        if "commission" in title.lower():
            continue                          # "commission-only partner" = sales recruiting
        hourly = p.get("type") == "hourly"
        bids = (p.get("bid_stats") or {}).get("bid_count") or 0
        skills = [j.get("name") for j in (p.get("jobs") or []) if j.get("name")][:5]
        if skills and not any(_MARKETING_SKILL.search(sk) for sk in skills):
            continue                          # not a marketing / creative project
        code = (p.get("currency") or {}).get("code", "")
        score = 6 + (1 if usd >= 1000 else 0) + (1 if bids < 10 else 0)

        posts.append(make_post(
            source="freelancer", intent_mode="signal",
            url=f"https://www.freelancer.com/projects/{p.get('seo_url') or pid}",
            author_name=f"Freelancer.com client · {code}", entity_type="person",
            headline=" · ".join(skills),
            snippet=f"{title}. {clean_text(p.get('description') or p.get('preview_description') or '', 1200)}",
            score=min(score, 8), signal_label=f"Freelancer.com project · {label}",
            posted_at=parse_iso(p.get("time_submitted")),
            region=_CURRENCY_REGION.get(code, ""),
            hooks=[f"Budget: {label}{'/hr' if hourly else ''} (≈ ${usd:,.0f})",
                   f"{bids} bid(s) so far", "Skills: " + ", ".join(skills)],
            keyword=p.get("_query", ""),
        ))
    return posts


def collect(ctx: ScanContext):
    since = int((datetime.utcnow() - timedelta(hours=max(ctx.hours, 1))).timestamp())
    with ThreadPoolExecutor(max_workers=4) as ex:
        batches = list(ex.map(lambda q: _search(q, since), CFG["queries"]))
    projects = [p for b in batches for p in b]
    return normalize(projects), len(projects), 0.0

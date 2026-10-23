"""
Fresh budget signals (signal):
  • Product Hunt — products that just launched and need to grow.
  • Funding news — companies that just raised money (Google search, news-dated).

For funding headlines the company name is guessed from the title with a regex
("Delhi-based Protein Pantry raises ₹9 crore" → "Protein Pantry"); the AI
verifier's `company` field refines it when a key is set.
"""

import math
import re
from urllib.parse import urlparse
from datetime import datetime, timedelta

from agent.collectors import ScanContext, run_actor, make_post, domain_of, clean_text, parse_iso
from config.sources import PRODUCT_HUNT as PH, FUNDING_NEWS as FN, items_within

_PAGE_PRICE = 0.0045   # google-search-scraper: per results page


# ─── Product Hunt ─────────────────────────────────────────────────────────────
def normalize_product_hunt(items: list[dict]) -> list:
    posts, seen = [], set()
    for it in items:
        name = (it.get("name") or "").strip()
        if not name or name.lower() in seen or it.get("isPromoted"):
            continue
        seen.add(name.lower())
        site = (it.get("website") or {}).get("url") or ""
        votes = it.get("upvotesCount") or 0
        rank = it.get("dayRank")
        makers = [m.get("name") for m in (it.get("team") or []) if m.get("name")][:3]
        hooks = [f"Launched on Product Hunt {it.get('launchDate') or ''}".strip(),
                 f"{votes} upvotes" + (f" · #{rank} of the day" if rank else "")]
        if makers:
            hooks.append("Makers: " + ", ".join(makers))
        posts.append(make_post(
            source="product_hunt", intent_mode="signal",
            url=it.get("url") or "", author_name=name, company=name,
            headline=(it.get("tagline") or "")[:160],
            snippet=f"{name} just launched on Product Hunt — {it.get('tagline') or ''}. "
                    f"{clean_text(it.get('description') or '', 700)}",
            score=6 + (1 if votes >= 200 else 0),
            signal_label="New launch on Product Hunt",
            posted_at=parse_iso(it.get("launchDate")),
            domain=domain_of(site), hooks=hooks,
            service_tags=["Branding & Designing", "Social Media & Content Strategy"],
        ))
    return posts


def collect_product_hunt(ctx: ScanContext):
    days = min(max(math.ceil(ctx.hours / 24), 1), 7)
    end = datetime.utcnow().date()
    start = end - timedelta(days=days)
    n = items_within(ctx.budget("product_hunt"), PH["cost_per_item"], PH["per_day"] * days)
    if not n:
        return [], 0, 0.0
    items = run_actor(PH["actor"], {
        "target": "daily", "startDate": start.isoformat(), "endDate": end.isoformat(),
        "maxNbItemsToScrape": n, "shouldIncludePromotedListings": False,
    }, ctx.apify_token, max_items=n)
    return normalize_product_hunt(items), len(items), len(items) * PH["cost_per_item"]


# ─── Funding news ─────────────────────────────────────────────────────────────
_RAISE_VERB = r"(?:raises|raised|has raised|secures|secured|bags|bagged|closes|closed|nets|gets|lands)"
_COMPANY_BEFORE_VERB = re.compile(
    rf"(?:^|[-–:|,]\s*|based\s+)([A-Z][\w&.'’+-]*(?:\s+[A-Z0-9][\w&.'’+-]*){{0,3}})\s+{_RAISE_VERB}\b"
)
_ROUNDUP = re.compile(r"\b(?:this week|weekly|roundup|round-up|funding report|startups raised|"
                      r"top \d+|list of|funding tracker)\b", re.IGNORECASE)
_ROUND = re.compile(r"\b(pre-seed|seed|pre-series [a-e]|series [a-e]|bridge round|angel round)\b",
                    re.IGNORECASE)
_AMOUNT = re.compile(r"(?:[$₹€£]|rs\.?|inr|usd|aed)\s?[\d,.]+\s?(?:cr(?:ore)?|mn|million|m|bn|billion|lakh|k)?",
                     re.IGNORECASE)


def guess_company(title: str) -> str:
    m = _COMPANY_BEFORE_VERB.search(title or "")
    if not m:
        return ""
    name = re.sub(r"^(?:Delhi|Mumbai|Bengaluru|Bangalore|Pune|Chennai|Hyderabad|Gurugram|Noida|Dubai)\S*\s+",
                  "", m.group(1)).strip()
    return "" if name.lower() in {"startup", "the startup", "company", "it", "india", "indian"} else name


def normalize_funding(pages: list[dict]) -> list:
    posts, seen = [], set()
    for page in pages:
        query = ((page.get("searchQuery") or {}).get("term")) or ""
        for r in page.get("organicResults") or []:
            title = (r.get("title") or "").strip()
            url = r.get("url") or ""
            if not title or not url or url in seen or _ROUNDUP.search(title):
                continue
            seen.add(url)
            company = guess_company(title)
            if not company:
                continue                      # no single company to pitch (roundups, guides)
            text = f"{title}. {r.get('description') or ''}"
            rnd = _ROUND.search(text)
            amt = _AMOUNT.search(text)
            hooks = ["Just raised" + (f" {amt.group(0).strip()}" if amt else "")
                     + (f" ({rnd.group(1)})" if rnd else "")]
            host = (urlparse(url).hostname or "").removeprefix("www.")
            hooks.append(f"Source: {host}")
            posts.append(make_post(
                source="funding_news", intent_mode="signal",
                url=url, author_name=company, company=company, entity_type="brand",
                headline=f"In the news · {host}", snippet=clean_text(text, 800),
                score=7,
                signal_label="Recently funded" + (f" · {rnd.group(1)}" if rnd else ""),
                posted_at=parse_iso(r.get("date")),
                hooks=hooks, keyword=query,
                service_tags=["Branding & Designing", "Media Planning & Buying"],
            ))
    return posts


def collect_funding_news(ctx: ScanContext):
    days = min(max(math.ceil(ctx.hours / 24), 1), 7)
    n_queries = min(len(FN["queries"]),
                    int(max(ctx.budget("funding_news") - 0.001, 0) / (_PAGE_PRICE * FN["pages_per_query"])))
    if not n_queries:
        return [], 0, 0.0
    pages = run_actor(FN["actor"], {
        "queries": "\n".join(FN["queries"][:n_queries]),
        "maxPagesPerQuery": FN["pages_per_query"],
        "quickDateRange": f"d{days}",
        "countryCode": FN["country"],
    }, ctx.apify_token, max_charge_usd=0.5)
    raw = sum(len(p.get("organicResults") or []) for p in pages)
    return normalize_funding(pages), raw, len(pages) * _PAGE_PRICE

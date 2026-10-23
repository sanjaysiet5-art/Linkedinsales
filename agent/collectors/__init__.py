"""
Multi-source lead collectors.

Each collector pulls raw items from one source (via Apify, or a free public
API) and normalizes them into the same LinkedInPost schema the rest of the
pipeline already understands. Posts carry:

  • source       — collector key (config/sources.py SOURCES)
  • intent_mode  — 'explicit': the author asks for help in their own words,
                   so the LinkedIn regex gates + verifier rubric apply as-is.
                   'signal': a buying signal (hiring, ad spend, launch, funding,
                   freelance project). No "looking for an agency" text exists, so the
                   regex seeking-gate is skipped and the verifier uses the
                   signal rubric instead.
  • intent_score — set by the collector from source-specific evidence.
  • hooks        — personalization lines for outreach ("Running 12 Meta ads").

Collectors run in parallel threads (Apify does the work in the cloud). A
collector that errors or has no token returns [] — it never fails the scan.
"""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlparse

import requests

from agent.parser import LinkedInPost
from config.settings import APIFY_BASE_URL, RUN_POLL_SECONDS, RUN_TIMEOUT_SECONDS


@dataclass
class ScanContext:
    """What the user asked for, translated for non-LinkedIn sources."""
    hours: int                     # look-back window in hours
    service: str = ""              # one Grapes service, or "" for all
    apify_token: str = ""
    budgets: dict = field(default_factory=dict)   # source → USD allowance (config.sources.source_budgets)

    def budget(self, source: str, fallback: float = 1.0) -> float:
        return self.budgets.get(source, fallback)


@dataclass
class CollectorResult:
    source: str
    posts: list[LinkedInPost] = field(default_factory=list)
    raw_count: int = 0
    cost_usd: float = 0.0
    error: str = ""
    seconds: float = 0.0


# ─── Apify helper (generic actor run) ─────────────────────────────────────────
def run_actor(actor_id: str, run_input: dict, token: str,
              max_charge_usd: float | None = None, max_items: int | None = None) -> list[dict]:
    """Start an actor, wait for it, return its dataset items.
    max_items is Apify's hard cap on billable results for the run."""
    from agent.searcher import _wait_for_run, _fetch_dataset_items

    params = {"token": token}
    if max_items:
        params["maxItems"] = max(1, int(max_items))
    if max_charge_usd:
        params["maxTotalChargeUsd"] = max(0.5, round(max_charge_usd, 2))
    resp = requests.post(f"{APIFY_BASE_URL}/acts/{actor_id}/runs",
                         params=params, json=run_input, timeout=30)
    resp.raise_for_status()
    run_id = resp.json()["data"]["id"]
    dataset_id = _wait_for_run(run_id, token)
    return _fetch_dataset_items(dataset_id, token)


def run_actor_many(actor_id: str, inputs: list[dict], token: str,
                   max_workers: int = 6, **kw) -> list[dict]:
    """Run several inputs of the same actor concurrently; failed runs are skipped."""
    items: list[dict] = []
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(run_actor, actor_id, inp, token, **kw): inp for inp in inputs}
        for f in as_completed(futs):
            try:
                batch = f.result()
                for it in batch:
                    it["_input"] = futs[f]
                items.extend(batch)
            except Exception as e:  # noqa: BLE001 — one bad run must not sink the source
                errors.append(f"{type(e).__name__}: {e}")
    if errors and not items:
        raise RuntimeError(errors[0])
    return items


# ─── Small normalization helpers shared by collectors ─────────────────────────
_ISO_COUNTRY_REGION = {
    "IN": "india", "IND": "india", "AE": "uae", "ARE": "uae", "SA": "saudi", "SAU": "saudi",
    "GB": "uk", "GBR": "uk", "UK": "uk", "US": "us", "USA": "us",
    **{c: "europe" for c in (
        "DE", "DEU", "FR", "FRA", "NL", "NLD", "ES", "ESP", "IT", "ITA", "IE", "IRL",
        "BE", "BEL", "SE", "SWE", "DK", "DNK", "PT", "PRT", "AT", "AUT", "PL", "POL",
        "CH", "CHE", "NO", "NOR", "FI", "FIN")},
}


def region_from_country(code: str) -> str:
    return _ISO_COUNTRY_REGION.get((code or "").strip().upper(), "")


def domain_of(url: str) -> str:
    """'https://www.acme.com/x' → 'acme.com'. App-store / social links → ''."""
    if not url:
        return ""
    if "://" not in url:
        url = "http://" + url
    host = (urlparse(url).hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    if any(b in host for b in ("play.google.", "apps.apple.", "facebook.", "fb.me", "instagram.",
                               "wa.me", "whatsapp.", "linktr.ee", "bit.ly", "linkedin.")):
        return ""
    return host


def strip_query(url: str) -> str:
    return (url or "").split("?")[0]


def clean_text(text: str, limit: int = 1500) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\{\{[^}]*\}\}", "", text)          # ad templates like {{product.name}}
    text = re.sub(r"&(?:#\d+|\w+);", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:limit]


def company_key(name: str) -> str:
    """Normalized company name for cross-source merging."""
    n = re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower())
    n = re.sub(r"\b(?:pvt|private|ltd|limited|llc|inc|llp|co|company|india|the|group)\b", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def source_signal(source: str, label: str, score: int, service_tags=None) -> dict:
    """The moment_signal that tells the card WHY this source flagged the lead."""
    from config.sources import SOURCES
    return {
        "id": f"src_{source}",
        "label": label,
        "icon": SOURCES.get(source, {}).get("icon", "🔗"),
        "score": score,
        "matched_keywords": [],
        "service_tags": service_tags or [],
    }


def make_post(*, source: str, intent_mode: str, url: str, author_name: str,
              snippet: str, score: int, signal_label: str, entity_type: str = "brand",
              company: str = "", author_url: str = "", headline: str = "",
              posted_at: datetime | None = None, timestamp_raw: str = "",
              region: str = "", domain: str = "", size: str = "", phone: str = "",
              hooks: list[str] | None = None, keyword: str = "",
              service_tags: list[str] | None = None) -> LinkedInPost:
    from config.sources import SOURCES
    label = SOURCES.get(source, {}).get("label", source)
    p = LinkedInPost(
        url=url,
        title=f"{author_name} on {label}",
        snippet=snippet,
        author_name=author_name or "Unknown",
        entity_type=entity_type,
        company_hint=company,
        timestamp_raw=timestamp_raw or (posted_at.strftime("%Y-%m-%d") if posted_at else ""),
        estimated_posted_at=posted_at,
        keywords_matched=[keyword] if keyword else [],
        intent_score=score,
        source_query=keyword,
        author_url=author_url,
        author_headline=headline,
    )
    p.source = source
    p.intent_mode = intent_mode
    p.moment_signals = [source_signal(source, signal_label, score, service_tags)]
    p.hooks = hooks or []
    p.region = region
    p.company_domain = domain
    p.company_size = size
    p.contact_phone = phone
    return p


def parse_iso(ts) -> datetime | None:
    """ISO string / epoch seconds / epoch ms → naive UTC datetime."""
    if ts in (None, "", 0):
        return None
    try:
        if isinstance(ts, (int, float)) or (isinstance(ts, str) and ts.isdigit()):
            v = float(ts)
            return datetime.utcfromtimestamp(v / 1000 if v > 1e11 else v)
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).replace(tzinfo=None)
    except (ValueError, OSError, OverflowError):
        return None


# ─── Registry + parallel runner ───────────────────────────────────────────────
def _registry():
    from agent.collectors import (
        linkedin_jobs, meta_ads, upwork, freelancer, x_posts, launches,
    )
    return {
        "linkedin_job": linkedin_jobs.collect,
        "meta_ads":     meta_ads.collect,
        "upwork":       upwork.collect,
        "freelancer":   freelancer.collect,
        "x_post":       x_posts.collect,
        "product_hunt": launches.collect_product_hunt,
        "funding_news": launches.collect_funding_news,
    }


def run_collectors(sources: list[str], ctx: ScanContext, log=print) -> list[CollectorResult]:
    """Run every requested non-LinkedIn-post collector in parallel."""
    registry = _registry()
    todo = [s for s in sources if s in registry]
    results: list[CollectorResult] = []
    if not todo:
        return results

    def _one(key: str) -> CollectorResult:
        t0 = time.monotonic()
        res = CollectorResult(source=key)
        try:
            posts, raw_count, cost = registry[key](ctx)
            res.posts, res.raw_count, res.cost_usd = posts, raw_count, cost
        except Exception as e:  # noqa: BLE001 — a source outage never blanks the scan
            res.error = f"{type(e).__name__}: {e}"[:300]
        res.seconds = round(time.monotonic() - t0, 1)
        return res

    with ThreadPoolExecutor(max_workers=len(todo)) as ex:
        futs = [ex.submit(_one, k) for k in todo]
        for f in as_completed(futs):
            r = f.result()
            results.append(r)
            if r.error:
                log(f"  [collector] {r.source}: FAILED ({r.error})")
            else:
                log(f"  [collector] {r.source}: {r.raw_count} raw → {len(r.posts)} candidate lead(s)"
                    f" · ${r.cost_usd:.2f} · {r.seconds}s")
    return results


def merge_accounts(posts: list[LinkedInPost]) -> tuple[list[LinkedInPost], int]:
    """
    Merge signal leads for the same company found by different sources
    (e.g. hiring on LinkedIn AND running Meta ads). The strongest lead is kept,
    the others' signals + hooks are folded in, and the score gets +1 — an
    account showing several buying signals at once is a hotter lead.
    Explicit posts are never merged (each ask is its own conversation).
    """
    kept: list[LinkedInPost] = []
    by_key: dict[str, LinkedInPost] = {}
    merged = 0
    for p in sorted(posts, key=lambda x: x.intent_score, reverse=True):
        key = company_key(p.company_hint or p.author_name) if p.intent_mode == "signal" else ""
        if p.company_domain and p.intent_mode == "signal":
            key = p.company_domain
        if not key or len(key) < 3:
            kept.append(p)
            continue
        base = by_key.get(key)
        if base is None:
            by_key[key] = p
            kept.append(p)
            continue
        if base.source == p.source:
            # Same source, same company (e.g. two Upwork posts) — keep both.
            kept.append(p)
            continue
        merged += 1
        base.moment_signals += [s for s in p.moment_signals if s.get("id", "").startswith("src_")]
        base.hooks += [h for h in p.hooks if h not in base.hooks]
        base.company_domain = base.company_domain or p.company_domain
        base.company_size = base.company_size or p.company_size
        base.contact_phone = base.contact_phone or p.contact_phone
        if not getattr(base, "_multi_boosted", False):
            base.intent_score = min(base.intent_score + 1, 10)
            base._multi_boosted = True
            base.hooks.insert(0, "Multiple buying signals this week")
    return kept, merged

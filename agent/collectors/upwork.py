"""
Upwork project posts → clients actively seeking a vendor (signal).

oDesk and Elance merged into Upwork in 2015 (both domains 301 → upwork.com),
so this source covers all three. Upwork's terms require the engagement to run
through Upwork, so these leads are "bid on it" leads, not cold-outreach leads.
"""

import re

from agent.collectors import (
    ScanContext, run_actor_many, make_post, clean_text, parse_iso, region_from_country,
)
from config.sources import UPWORK as CFG, items_within

_NUM = re.compile(r"\d+(?:\.\d+)?")


def _budget(job: dict) -> tuple[float, bool]:
    """(max budget in USD, is_hourly). N/A → (0, hourly?)."""
    hourly = (job.get("jobType") or "").lower().startswith("hour")
    nums = [float(n) for n in _NUM.findall((job.get("budget") or "").replace(",", ""))]
    return (max(nums) if nums else 0.0), hourly


def qualifies(job: dict) -> bool:
    spent = float(job.get("clientTotalSpent") or 0)
    if not job.get("paymentVerified") and spent <= 0:
        return False                         # unverified client who never paid anyone
    if spent < CFG["min_client_spend"]:
        return False
    amount, hourly = _budget(job)
    if not hourly and 0 < amount < 100:
        return False                         # $30 micro-task, not an agency project
    if hourly and 0 < amount < 10:
        return False
    return True


def normalize(items: list[dict]) -> list:
    posts, seen = [], set()
    for job in items:
        jid = job.get("id") or job.get("url")
        if not jid or jid in seen or not qualifies(job):
            continue
        seen.add(jid)
        spent = float(job.get("clientTotalSpent") or 0)
        amount, hourly = _budget(job)
        score = 6
        if spent >= 5000:
            score += 1
        if (not hourly and amount >= 1000) or (hourly and amount >= 30):
            score += 1

        country = job.get("clientLocation") or ""
        client = job.get("clientName") or ""
        author = f"{client} (Upwork client)" if client else f"Upwork client · {country or 'unknown'}"
        budget = job.get("budget") or "N/A"
        hooks = ([f"Budget: {budget}{'/hr' if hourly else ''}"] if budget != "N/A" else []) + [
                 f"Client has spent ${spent:,.0f} on Upwork",
                 f"{job.get('proposals') or 0} proposals so far"]
        if job.get("clientHireRatePercent"):
            hooks.append(f"Client hire rate {job['clientHireRatePercent']}%")

        title = (job.get("title") or "").strip()
        posts.append(make_post(
            source="upwork", intent_mode="signal",
            url=job.get("url") or "",
            author_name=author, entity_type="person",   # first name only — not a company
            headline=" · ".join(x for x in (country, f"{job.get('experienceLevel') or ''} level",
                                            job.get("jobType") or "") if x.strip()),
            snippet=f"{title}. {clean_text(job.get('description') or '', 1200)}",
            score=score, signal_label="Upwork project" + (f" · {budget}" if budget != "N/A" else ""),
            posted_at=parse_iso(job.get("absoluteDate")),
            timestamp_raw=job.get("relativeDate") or "",
            region=region_from_country(country),
            hooks=hooks, keyword=(job.get("_input") or {}).get("query", ""),
        ))
    return posts


def collect(ctx: ScanContext):
    queries = CFG["queries"]
    budget_items = items_within(ctx.budget("upwork"), CFG["cost_per_item"],
                                len(queries) * CFG["per_search"])
    queries = queries[:budget_items]
    if not queries:
        return [], 0, 0.0
    per = max(1, budget_items // len(queries))
    hours = max(ctx.hours, 1)
    items = run_actor_many(CFG["actor"], [
        {"query": q, "perPage": per, "pagesToScrape": 1, "sort": "newest",
         "maxJobAge": {"value": hours, "unit": "hours"}}
        for q in queries
    ], ctx.apify_token, max_items=per)
    return normalize(items), len(items), len(items) * CFG["cost_per_item"]

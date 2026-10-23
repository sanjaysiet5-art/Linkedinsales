"""
X (Twitter) → explicit "recommend / looking for an agency" asks (explicit).

These are the same shape as LinkedIn intent posts, so they go through the
unchanged regex gates + verifier rubric.
"""

from datetime import datetime, timedelta

from agent.collectors import ScanContext, run_actor_many, make_post, clean_text, parse_iso
from config.sources import X_POSTS as CFG, items_within

_RUN_FEE = 0.0025      # scraper_one charges an init event per run


def normalize(items: list[dict], hours: int) -> list:
    cutoff = datetime.utcnow() - timedelta(hours=max(hours, 1) + 6)
    posts, seen = [], set()
    for t in items:
        url = t.get("postUrl") or ""
        text = clean_text(t.get("postText") or "", 1500)
        if not url or url in seen or not text:
            continue
        seen.add(url)
        posted = parse_iso(t.get("timestamp"))
        if posted and posted < cutoff:
            continue                          # the actor sometimes returns old top tweets
        author = t.get("author") or {}
        handle = author.get("screenName") or ""
        posts.append(make_post(
            source="x_post", intent_mode="explicit",
            url=url, author_name=author.get("name") or f"@{handle}", entity_type="person",
            author_url=f"https://x.com/{handle}" if handle else "",
            headline=f"@{handle}" if handle else "",
            snippet=text, score=0, signal_label="Asked on X",
            posted_at=posted,
            hooks=[f"Tweet · {t.get('replyCount') or 0} replies · {t.get('favouriteCount') or 0} likes"],
            keyword=(t.get("_input") or {}).get("query", "").strip('"'),
        ))
    return posts


def collect(ctx: ScanContext):
    queries = CFG["queries"]
    budget = ctx.budget("x_post") - len(queries) * _RUN_FEE
    budget_items = items_within(budget, CFG["cost_per_item"], len(queries) * CFG["per_search"])
    if budget_items < len(queries):
        return [], 0, 0.0
    per = budget_items // len(queries)
    items = run_actor_many(CFG["actor"], [
        {"query": q, "resultsCount": per, "searchType": "latest",
         "timeWindowHours": max(ctx.hours, 1)}
        for q in queries
    ], ctx.apify_token, max_items=per)
    return normalize(items, ctx.hours), len(items), len(items) * CFG["cost_per_item"] + len(queries) * _RUN_FEE

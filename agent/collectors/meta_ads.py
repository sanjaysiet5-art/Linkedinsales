"""
Meta Ad Library → brands already spending on Facebook/Instagram ads (signal).

One lead per advertiser. Ads are grouped by landing-page domain (a brand often
runs ads from several pages), falling back to page name. Pitch: better
creative, better ROAS, retargeting.
"""

from collections import Counter
from urllib.parse import quote

from agent.collectors import (
    ScanContext, run_actor_many, make_post, domain_of, clean_text, parse_iso,
    region_from_country,
)
from config.sources import META_ADS as CFG, items_within


def build_urls() -> list[dict]:
    return [
        {"url": ("https://www.facebook.com/ads/library/?active_status=active&ad_type=all"
                 f"&country={c}&q={quote(kw)}&search_type=keyword_unordered&media_type=all")}
        for c in CFG["countries"] for kw in CFG["keywords"]
    ]


def _country_of(item: dict) -> str:
    url = item.get("inputUrl") or ""
    if "country=" in url:
        return url.split("country=")[1].split("&")[0]
    return ""


def _keyword_of(item: dict) -> str:
    url = item.get("inputUrl") or ""
    if "q=" in url:
        from urllib.parse import unquote
        return unquote(url.split("q=")[1].split("&")[0])
    return ""


def normalize(items: list[dict]) -> list:
    groups: dict[str, list[dict]] = {}
    for ad in items:
        snap = ad.get("snapshot") or {}
        name = (ad.get("pageName") or snap.get("pageName") or "").strip()
        dom = domain_of(snap.get("linkUrl") or "")
        if not name or not dom:
            continue                        # app-install / DM-only ads have no brand site to pitch
        groups.setdefault(dom, []).append(ad)

    posts = []
    for dom, ads in groups.items():
        likes = max(((a.get("snapshot") or {}).get("pageLikeCount") or 0) for a in ads)
        if likes < CFG["min_page_likes"] or likes > CFG["max_page_likes"]:
            continue
        ads.sort(key=lambda a: a.get("startDateFormatted") or "")
        page_name = Counter(a.get("pageName") for a in ads).most_common(1)[0][0]
        snap = ads[-1].get("snapshot") or {}
        body = clean_text(((snap.get("body") or {}).get("text")) or
                          ((snap.get("cards") or [{}])[0].get("body") or ""), 400)
        n = len({a.get("adArchiveID") or a.get("adArchiveId") for a in ads})
        first = (ads[0].get("startDateFormatted") or "")[:10]
        ctas = Counter(((a.get("snapshot") or {}).get("ctaText") or "") for a in ads)
        country = _country_of(ads[0])
        page_id = ads[0].get("pageID") or ads[0].get("pageId") or ""
        categories = ", ".join(snap.get("pageCategories") or [])

        score = 6 + (1 if n >= 3 else 0)
        hooks = [f"Running {n} active Meta ad(s)" + (f" since {first}" if first else ""),
                 f"Landing page: {dom}"]
        cta = ctas.most_common(1)[0][0]
        if cta:
            hooks.append(f"Main CTA: {cta}")
        hooks.append(f"{likes:,} page likes")

        snippet = (f"{page_name} is running {n} active Meta ad(s) in {country or 'target market'}"
                   f"{' since ' + first if first else ''}. Sample ad copy: “{body}”")
        posts.append(make_post(
            source="meta_ads", intent_mode="signal",
            url=(f"https://www.facebook.com/ads/library/?active_status=active&ad_type=all"
                 f"&view_all_page_id={page_id}") if page_id else f"https://{dom}",
            author_name=page_name, company=page_name,
            author_url=(snap.get("pageProfileUri") or ""),
            headline=" · ".join(x for x in (categories, f"{likes:,} likes") if x),
            snippet=snippet, score=score,
            signal_label=f"Running {n} Meta ad(s)",
            posted_at=parse_iso(ads[-1].get("startDateFormatted")),
            timestamp_raw=f"ads live since {first}" if first else "",
            region=region_from_country(country),
            domain=dom, hooks=hooks, keyword=_keyword_of(ads[0]),
            service_tags=["Media Planning & Buying", "Social Media & Content Strategy"],
        ))
    return posts


def collect(ctx: ScanContext):
    urls = build_urls()
    budget_items = items_within(ctx.budget("meta_ads"), CFG["cost_per_item"],
                                len(urls) * CFG["per_search"])
    urls = urls[:budget_items]
    if not urls:
        return [], 0, 0.0
    per = max(1, budget_items // len(urls))
    # One run per search so resultsLimit is a per-search cap, not a shared total.
    items = run_actor_many(CFG["actor"], [
        {"startUrls": [u], "resultsLimit": per, "activeStatus": "active"} for u in urls
    ], ctx.apify_token, max_items=per)
    return normalize(items), len(items), len(items) * CFG["cost_per_item"]

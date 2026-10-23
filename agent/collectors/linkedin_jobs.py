"""
LinkedIn Jobs → companies hiring marketing roles (signal).

One lead per hiring company: several open marketing roles at the same company
are folded into one card ("Hiring 3 marketing roles"), which also bumps the
score — that company is building a whole function and may outsource part of it.
"""

from urllib.parse import quote

from agent.collectors import (
    ScanContext, run_actor, make_post, domain_of, strip_query, clean_text,
    parse_iso, company_key, region_from_country,
)
from config.sources import LINKEDIN_JOBS as CFG, items_within

# Job title keyword → Grapes service tag (drives the pitch pills)
_TITLE_SERVICE = [
    ("seo", "SEO"), ("social", "Social Media & Content Strategy"),
    ("content", "Social Media & Content Strategy"), ("performance", "Media Planning & Buying"),
    ("brand", "Branding & Designing"), ("pr ", "PR & Influencer Marketing"),
    ("influencer", "PR & Influencer Marketing"), ("ecommerce", "Website Design & Development"),
    ("digital marketing", "Media Planning & Buying"),
]


def titles_for(service: str) -> list[str]:
    by = CFG["titles_by_service"]
    if service in by:
        return by[service]
    seen, out = set(), []
    for titles in by.values():
        for t in titles:
            if t.lower() not in seen:
                seen.add(t.lower())
                out.append(t)
    return out


def build_urls(ctx: ScanContext) -> list[str]:
    secs = max(ctx.hours, 1) * 3600
    return [
        f"https://www.linkedin.com/jobs/search/?keywords={quote(t)}&location={quote(loc)}&f_TPR=r{secs}"
        for t in titles_for(ctx.service) for loc in CFG["locations"]
    ]


def _service_for(title: str) -> str:
    t = f"{title.lower()} "
    for kw, svc in _TITLE_SERVICE:
        if kw in t:
            return svc
    return ""


def _is_agency_or_recruiter(job: dict) -> bool:
    ind = (job.get("industries") or "").lower()
    return any(r in ind for r in CFG["reject_industries"])


def normalize(items: list[dict]) -> list:
    """Raw job items → one signal lead per hiring company."""
    groups: dict[str, list[dict]] = {}
    for job in items:
        name = (job.get("companyName") or "").strip()
        if not name or _is_agency_or_recruiter(job):
            continue
        groups.setdefault(company_key(name) or name.lower(), []).append(job)

    posts = []
    for jobs in groups.values():
        jobs.sort(key=lambda j: j.get("postedAt") or "", reverse=True)
        lead = jobs[0]
        company = lead["companyName"].strip()
        titles = list(dict.fromkeys(j.get("title", "").strip() for j in jobs if j.get("title")))
        employees = lead.get("companyEmployeesCount")
        try:
            employees = int(employees) if employees not in (None, "") else None
        except (TypeError, ValueError):
            employees = None

        score = 6
        if employees and 10 <= employees <= 500:
            score += 1                      # sweet-spot size: budget, no big in-house team
        elif employees and employees > 5000:
            score -= 1                      # enterprise: agency rosters are locked in at HQ
        if len(titles) > 1:
            score += 1                      # building out a marketing function
        score = min(score, 8)

        location = lead.get("location") or ""
        country = ((lead.get("companyAddress") or {}).get("addressCountry") or "")
        headline_parts = [lead.get("industries") or "",
                          f"{employees} employees" if employees else "", location]
        services = list(dict.fromkeys(s for s in (_service_for(t) for t in titles) if s))

        hooks = [f"Hiring {t}" for t in titles[:4]]
        if lead.get("applicantsCount"):
            hooks.append(f"{lead['applicantsCount']} applicants so far")
        if lead.get("postedAt"):
            hooks.append(f"Role posted {lead['postedAt']}")

        desc = clean_text(lead.get("descriptionText") or lead.get("descriptionHtml") or "", 900)
        role_str = titles[0] if len(titles) == 1 else f"{len(titles)} marketing roles ({', '.join(titles[:3])})"
        snippet = f"{company} is hiring: {role_str} — {location}. {desc}"

        posts.append(make_post(
            source="linkedin_job", intent_mode="signal",
            url=strip_query(lead.get("link") or ""),
            author_name=company, company=company,
            author_url=strip_query(lead.get("companyLinkedinUrl") or ""),
            headline=" · ".join(p for p in headline_parts if p),
            snippet=snippet, score=score,
            signal_label=f"Hiring: {role_str}"[:80],
            posted_at=parse_iso(lead.get("postedAt")),
            region=region_from_country(country),
            domain=domain_of(lead.get("companyWebsite") or ""),
            size=str(employees or ""),
            hooks=hooks, keyword=titles[0] if titles else "",
            service_tags=services,
        ))
    return posts


def collect(ctx: ScanContext):
    urls = build_urls(ctx)
    budget_items = items_within(ctx.budget("linkedin_job"), CFG["cost_per_item"],
                                len(urls) * CFG["per_search"])
    if budget_items < len(urls):
        urls = urls[:max(budget_items, 0)]         # tiny budget: fewer searches, ≥1 job each
    if not urls:
        return [], 0, 0.0
    per = max(1, budget_items // len(urls))
    items = run_actor(CFG["actor"], {
        "urls": urls, "limitPerSource": per, "scrapeCompany": True,
    }, ctx.apify_token, max_items=budget_items)
    return normalize(items), len(items), len(items) * CFG["cost_per_item"]

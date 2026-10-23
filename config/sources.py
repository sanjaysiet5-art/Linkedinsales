"""
Per-source configuration for the multi-source collectors (agent/collectors/).

Every source runs through Apify with the same APIFY_API_TOKEN as the LinkedIn
post search. Actor IDs, input shapes and prices were checked against the
Apify store on 2026-09-25 — actors change, so re-check a source's run success
rate on apify.com if it suddenly returns nothing.

Enable/disable sources with LEAD_SOURCES in .env (comma-separated keys), or
--sources on the CLI. Default: every source below.
"""

import os

# key → human label + icon (dashboard chip) + default on/off
SOURCES = {
    "linkedin_post": {"label": "LinkedIn Post",  "icon": "💬"},
    "linkedin_job":  {"label": "LinkedIn Job",   "icon": "💼"},
    "meta_ads":      {"label": "Meta Ads",       "icon": "📣"},
    "upwork":        {"label": "Upwork",         "icon": "🧑‍💻"},   # oDesk + Elance merged into Upwork
    "freelancer":    {"label": "Freelancer.com", "icon": "🛠️"},
    "x_post":        {"label": "X (Twitter)",    "icon": "𝕏"},
    "product_hunt":  {"label": "Product Hunt",   "icon": "🚀"},
    "funding_news":  {"label": "Funding News",   "icon": "💰"},
}


# ─── Per-scan Apify budget ─────────────────────────────────────────────────────
# Every scan is capped at SCAN_BUDGET_USD. Each source gets a share, turned into
# a hard maxItems cap on its Apify runs, so no source can overspend. Shares
# follow observed yield: LinkedIn posts carry the explicit RFP-style asks, jobs
# give the most leads per dollar, Meta ads the fewest. The unallocated 7% covers
# actor-start and "no result" fees. Disabled sources' shares are redistributed
# across the enabled ones (the total never exceeds 93% of the budget).
SCAN_BUDGET_USD = float(os.getenv("SCAN_BUDGET_USD", "5"))
BUDGET_SHARES = {
    "linkedin_post": 0.45,
    "linkedin_job":  0.22,
    "upwork":        0.13,
    "meta_ads":      0.09,
    "x_post":        0.02,
    "product_hunt":  0.01,
    "funding_news":  0.01,
    "freelancer":    0.0,    # free public API
}


def source_budgets(sources: list[str], total_usd: float | None = None) -> dict[str, float]:
    """USD allowance per enabled source for one scan."""
    total = SCAN_BUDGET_USD if total_usd is None else total_usd
    allocatable = total * sum(BUDGET_SHARES.values())
    shares = {k: BUDGET_SHARES.get(k, 0.0) for k in sources}
    s = sum(shares.values()) or 1.0
    return {k: round(allocatable * v / s, 4) for k, v in shares.items()}


def items_within(budget_usd: float, price: float, cap: int) -> int:
    """How many billable items a budget buys, never above the config cap."""
    return max(0, min(cap, int(budget_usd / price))) if price else cap


def enabled_sources(override: list[str] | None = None) -> list[str]:
    """Resolve which sources run: CLI/API override → LEAD_SOURCES env → all."""
    if override:
        keys = override
    else:
        env = os.getenv("LEAD_SOURCES", "").strip()
        keys = [k.strip() for k in env.split(",")] if env else list(SOURCES)
    return [k for k in keys if k in SOURCES]


# ─── LinkedIn Jobs — companies hiring marketing roles ─────────────────────────
# A company hiring an SEO executive has the budget and the need, and may
# outsource instead. Cost: $0.002/job.
LINKEDIN_JOBS = {
    "actor": "curious_coder~linkedin-jobs-scraper",
    "cost_per_item": 0.002,
    "locations": ["India", "United Arab Emirates", "Saudi Arabia"],
    "per_search": 25,          # jobs per title × location search
    # Titles per Grapes service. "All services" scans use the union.
    "titles_by_service": {
        "SEO": ["SEO Executive", "SEO Manager"],
        "Social Media & Content Strategy": ["Social Media Manager", "Content Marketing Manager"],
        "Media Planning & Buying": ["Performance Marketing Manager", "Digital Marketing Manager"],
        "Branding & Designing": ["Brand Manager"],
        "PR & Influencer Marketing": ["PR Manager", "Influencer Marketing Manager"],
        "Website Design & Development": ["Ecommerce Manager"],
        "Films & Campaigns": ["Head of Marketing"],
        "Events & Activations": ["Marketing Manager"],
        "AI/3D/CGI": ["Head of Marketing"],
    },
    # LinkedIn industries that mean the company IS an agency / recruiter.
    "reject_industries": [
        "advertising services", "marketing services", "public relations",
        "staffing and recruiting", "human resources services", "outsourcing",
    ],
}

# ─── Meta Ad Library — brands already spending on ads ────────────────────────
# Cost: $0.0058/ad. One lead per advertiser (ads are grouped by page).
META_ADS = {
    "actor": "apify~facebook-ads-scraper",
    "cost_per_item": 0.0058,
    "countries": ["IN"],       # AE keyword searches returned mostly non-brand pages in testing
    "keywords": [
        "shop now", "book a consultation", "admissions open", "new collection",
        "luxury apartments", "free delivery", "limited offer", "skincare",
    ],
    "per_search": 20,
    # Page-like bounds: tiny pages are hobbyists; megabrands have in-house agencies.
    "min_page_likes": 500,
    "max_page_likes": 2_000_000,
}

# ─── Upwork — clients actively seeking a vendor ───────────────────────────────
# Cost: $0.0035/job.
UPWORK = {
    "actor": "neatrat~upwork-job-scraper",
    "cost_per_item": 0.0035,
    "per_search": 30,
    "queries": [
        "social media marketing", "SEO", "branding", "website design",
        "video production", "Meta ads", "Google ads", "influencer marketing",
        "PR", "3D animation",
    ],
    "min_client_spend": 0,         # set e.g. 1000 to drop clients who never paid anyone
}

# ─── Freelancer.com — project posts (free public API, no key) ─────────────────
FREELANCER = {
    "api": "https://www.freelancer.com/api/projects/0.1/projects/active/",
    "per_search": 40,
    "queries": [
        "social media marketing", "SEO", "branding", "logo and brand identity",
        "website design", "video production", "facebook ads", "google ads",
        "influencer marketing", "public relations", "3D animation",
    ],
    "min_budget_usd": 300,         # max budget below this = hobby project, skipped
}

# ─── X (Twitter) — explicit "recommend an agency" asks ───────────────────────
# One actor run per query. Cost: $0.00025/tweet + $0.0025/run.
X_POSTS = {
    "actor": "scraper_one~x-posts-search",
    "cost_per_item": 0.00025,
    "per_search": 25,
    "queries": [
        "\"recommend a marketing agency\"", "\"looking for a marketing agency\"",
        "\"recommend an SEO agency\"", "\"looking for an SEO agency\"",
        "\"need a branding agency\"", "\"recommend a PR agency\"",
        "\"looking for a web designer\"", "\"looking for a social media agency\"",
    ],
}

# ─── Product Hunt — fresh launches that need growth ──────────────────────────
# Cost: $0.00165/product.
PRODUCT_HUNT = {
    "actor": "maximedupre~product-hunt-scraper",
    "cost_per_item": 0.00165,
    "per_day": 30,
}

# ─── Funding news — recently funded companies (Google search) ─────────────────
# Cost: $0.0045/results page (10 results).
FUNDING_NEWS = {
    "actor": "apify~google-search-scraper",
    "cost_per_item": 0.00045,
    "country": "in",
    "pages_per_query": 1,
    "queries": [
        "startup raises seed round India",
        "raises Series A funding India brand",
        "D2C brand raises funding",
        "startup raises funding Dubai",
        "secures pre-series A funding India",
    ],
}

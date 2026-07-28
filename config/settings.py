import os
from dotenv import load_dotenv

load_dotenv()

# Timeline → Apify postedLimit param + max age in hours for post-filter
# Apify supports 1h/24h/week natively; 3hr/2day/3day fetch the next-wider window
# and rely on the post-filter (exact timestamps make it precise now)
TIMELINE_CONFIG = {
    "1hr":   {"posted_limit": "1h",   "max_hours": 1},
    "3hr":   {"posted_limit": "24h",  "max_hours": 3},
    "1day":  {"posted_limit": "24h",  "max_hours": 24},
    "2day":  {"posted_limit": "week", "max_hours": 48},
    "3day":  {"posted_limit": "week", "max_hours": 72},
    "1week": {"posted_limit": "week", "max_hours": 168},
}

# Ordered windows used in --all-timelines mode (broadest single scan = 1week)
# Results are then bucketed into these display bands
TIMELINE_BUCKETS = [
    {"label": "Today (0–24 hrs)",    "min_hours": 0,   "max_hours": 24},
    {"label": "Yesterday (1–2 days)","min_hours": 24,  "max_hours": 48},
    {"label": "2–3 Days Ago",        "min_hours": 48,  "max_hours": 72},
    {"label": "This Week (3–7 days)","min_hours": 72,  "max_hours": 168},
]

# ─────────────────────────────────────────────────────────────────────────────
# AGENCY SALES SCORING FRAMEWORK
# Objective: surface companies that are likely to hire a digital marketing agency
# Services: SEO · SMO · SEM · PR · Brand Building · Media · Film · Creative
#
# Score tiers:
#   10  — Direct, explicit agency-hunt / RFP
#    9  — Imminent budget trigger (leadership hire, rebranding, funding)
#    8  — Campaign / launch requiring external creative/media muscle
#    7  — Service-specific pain → SEO / Paid / Social / PR gap
#    6  — Digital transformation / brand-building intent
#    5  — Film / video production need
#    4  — Event / sponsorship → PR + creative opportunity
#    3  — Market expansion → new audience, new content
#    2  — Passive brand signal (growing company, awards)
# ─────────────────────────────────────────────────────────────────────────────

MOMENT_SIGNALS = {

    # ── TIER 1: Active Agency Hunt ── Score 10 ────────────────────────────────
    "agency_search": {
        "keywords": [
            "looking for a digital agency", "looking for an agency", "agency recommendations",
            "recommend a marketing agency", "need a creative agency", "hiring an agency",
            "agency partner", "pitch us", "open to pitch", "invite agencies",
            "rfp", "request for proposal", "vendor shortlist", "agency evaluation",
            "searching for agency", "which agency", "good digital agency",
            "looking for marketing partner", "brand agency recommendations",
        ],
        "score": 10,
        "label": "Active Agency Hunt",
        "icon": "🚨",
        "service_tags": ["SEO", "SMO", "SEM", "PR", "Brand", "Creative", "Media", "Film"],
    },

    # ── TIER 2: New Marketing Leadership ── Score 9 ──────────────────────────
    # New CMOs/VPs almost always audit and change agencies within 90 days
    "new_marketing_leader": {
        "keywords": [
            "new cmo", "new chief marketing officer", "new vp marketing",
            "new head of marketing", "new marketing director", "joining as cmo",
            "appointed cmo", "hired as vp marketing", "our new cmo",
            "excited to join as", "thrilled to join", "starting as head of marketing",
            "first day as cmo", "new brand lead", "new creative director",
            "new chief brand officer", "new head of brand", "new head of communications",
            "new head of pr", "new communications director",
        ],
        "score": 9,
        "label": "New Marketing / Brand Leader",
        "icon": "👔",
        "service_tags": ["SEO", "SMO", "SEM", "PR", "Brand", "Creative", "Media"],
    },

    # ── TIER 2: Rebranding / Brand Refresh ── Score 9 ────────────────────────
    "rebranding": {
        "keywords": [
            "rebrand", "rebranding", "brand refresh", "new brand identity", "brand overhaul",
            "new logo", "new visual identity", "brand guidelines", "updated branding",
            "evolved brand", "brand transformation", "new positioning", "repositioning",
            "brand strategy", "brand audit", "refreshing our brand", "brand relaunch",
        ],
        "score": 9,
        "label": "Rebranding / Brand Refresh",
        "icon": "🎨",
        "service_tags": ["Brand", "Creative", "PR", "Film"],
    },

    # ── TIER 2: Fresh Funding (Budget Available) ── Score 9 ──────────────────
    "funding_received": {
        "keywords": [
            "raised", "series a", "series b", "series c", "series d", "series e",
            "funding round", "secured funding", "seed round", "pre-seed", "angel round",
            "raised $", "raised rs", "raised crore", "investment round",
            "closed our", "venture funding", "backed by", "growth capital",
        ],
        "score": 9,
        "label": "Funding Received (Budget Available)",
        "icon": "💰",
        "service_tags": ["SEO", "SEM", "Brand", "PR", "Media"],
    },

    # ── TIER 3: New Product / Brand / Market Launch ── Score 8 ───────────────
    "product_brand_launch": {
        "keywords": [
            "launching", "we launched", "introducing", "announcing our new",
            "new product launch", "now available", "just launched", "going live",
            "debut", "unveiling", "market launch", "product debut",
            "new brand launched", "brand launch", "campaign launch",
            "entering the market", "new market entry",
        ],
        "score": 8,
        "label": "Product / Brand Launch",
        "icon": "🚀",
        "service_tags": ["PR", "SEM", "SMO", "Creative", "Media", "Film"],
    },

    # ── TIER 3: Campaign Planning / Campaign Brief ── Score 8 ────────────────
    "campaign_planning": {
        "keywords": [
            "campaign planning", "campaign brief", "planning our campaign",
            "q4 campaign", "q1 campaign", "annual campaign", "brand campaign",
            "media campaign", "marketing campaign", "awareness campaign",
            "performance campaign", "digital campaign", "integrated campaign",
            "360 campaign", "atl campaign", "btl campaign", "festive campaign",
            "holiday campaign", "product campaign", "launch campaign",
        ],
        "score": 8,
        "label": "Campaign Planning",
        "icon": "📣",
        "service_tags": ["Creative", "Media", "SEM", "PR", "Film", "SMO"],
    },

    # ── TIER 4: SEO Pain / Organic Growth Need ── Score 7 ───────────────────
    "seo_need": {
        "keywords": [
            "organic traffic", "google ranking", "search ranking", "seo audit",
            "improve seo", "website not ranking", "need more organic", "keyword ranking",
            "search visibility", "google presence", "search engine", "website traffic drop",
            "lost rankings", "not ranking", "seo strategy", "technical seo",
            "on-page seo", "link building", "local seo", "improve search",
        ],
        "score": 7,
        "label": "SEO / Organic Growth Need",
        "icon": "🔍",
        "service_tags": ["SEO"],
    },

    # ── TIER 4: Paid Media / Performance Marketing Need ── Score 7 ───────────
    "sem_paid_need": {
        "keywords": [
            "google ads", "performance marketing", "paid search", "ppc", "media buying",
            "ad spend", "roas", "return on ad spend", "digital ads", "meta ads",
            "facebook ads", "instagram ads", "media plan", "media budget",
            "increase roas", "paid campaigns", "programmatic", "retargeting",
            "media agency", "performance agency",
        ],
        "score": 7,
        "label": "Paid Media / SEM Need",
        "icon": "💸",
        "service_tags": ["SEM"],
    },

    # ── TIER 4: Social Media / SMO Need ── Score 7 ───────────────────────────
    "smo_need": {
        "keywords": [
            "social media presence", "social media strategy", "grow our social",
            "social media management", "content strategy", "instagram growth",
            "linkedin presence", "social engagement", "community management",
            "social media agency", "content calendar", "social media plan",
            "influencer marketing", "creator marketing", "brand social",
            "improve engagement", "social media audit",
        ],
        "score": 7,
        "label": "Social Media / SMO Need",
        "icon": "📲",
        "service_tags": ["SMO"],
    },

    # ── TIER 4: PR / Media Relations Need ── Score 7 ────────────────────────
    "pr_need": {
        "keywords": [
            "pr agency", "public relations", "media relations", "press coverage",
            "media outreach", "press release", "reputation management", "brand reputation",
            "crisis communication", "media strategy", "earned media",
            "thought leadership", "spokesperson", "brand pr", "looking for pr",
            "get press", "media coverage", "journalist outreach",
        ],
        "score": 7,
        "label": "PR / Media Relations Need",
        "icon": "📰",
        "service_tags": ["PR"],
    },

    # ── TIER 5: Digital Transformation / Going Digital ── Score 6 ────────────
    "digital_transformation": {
        "keywords": [
            "digital transformation", "going digital", "digital presence",
            "online presence", "digital marketing strategy", "build our digital",
            "digital-first", "digital overhaul", "website redesign", "new website",
            "revamp website", "online visibility", "d2c launch", "direct to consumer",
            "e-commerce launch", "online store launch",
        ],
        "score": 6,
        "label": "Digital Transformation",
        "icon": "🌐",
        "service_tags": ["SEO", "SEM", "SMO", "Brand"],
    },

    # ── TIER 5: Film / Video Production Need ── Score 5 ─────────────────────
    "film_video_need": {
        "keywords": [
            "brand film", "ad film", "tvc", "television commercial", "video production",
            "corporate video", "explainer video", "product video", "brand video",
            "shoot", "film production", "video campaign", "reel", "brand reel",
            "documentary", "brand documentary", "web series brand", "content film",
        ],
        "score": 5,
        "label": "Film / Video Production Need",
        "icon": "🎬",
        "service_tags": ["Film", "Creative"],
    },

    # ── TIER 5: Creative / Design Need ── Score 5 ────────────────────────────
    "creative_design_need": {
        "keywords": [
            "creative agency", "design agency", "creative work", "creative campaign",
            "ad creative", "creative brief", "need creatives", "creative partner",
            "graphic design", "brand design", "marketing collateral", "packaging design",
            "ooh creative", "billboard design", "print campaign", "creative direction",
        ],
        "score": 5,
        "label": "Creative / Design Need",
        "icon": "✏️",
        "service_tags": ["Creative"],
    },

    # ── TIER 6: Event / Sponsorship → PR + Creative Opp ── Score 4 ───────────
    "event_sponsorship": {
        "keywords": [
            "sponsoring", "title sponsor", "event sponsor", "official sponsor",
            "brand sponsor", "conference", "summit", "expo", "trade show",
            "launch event", "brand event", "activation", "experiential marketing",
        ],
        "score": 4,
        "label": "Event / Sponsorship",
        "icon": "🎪",
        "service_tags": ["PR", "Creative", "Brand"],
    },

    # ── TIER 6: Market Expansion → New Audience, New Content ── Score 3 ──────
    "market_expansion": {
        "keywords": [
            "expanding to", "new market", "entering", "new geography", "new city",
            "new country", "pan india", "global expansion", "new audience",
            "new customer segment", "vernacular market", "regional expansion",
        ],
        "score": 3,
        "label": "Market Expansion",
        "icon": "🗺️",
        "service_tags": ["SEO", "SMO", "PR", "Media"],
    },

    # ── TIER 7: Passive Brand Signal ── Score 2 ──────────────────────────────
    "brand_growth_signal": {
        "keywords": [
            "fastest growing", "top brand", "emerging brand", "award", "recognized",
            "best company", "great place to work", "scaling up", "milestone",
            "anniversary", "years in business",
        ],
        "score": 2,
        "label": "Brand Growth Signal",
        "icon": "📊",
        "service_tags": ["Brand", "PR"],
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# Recommended seed keywords for agency prospecting
# (user can override via CLI --keywords)
# ─────────────────────────────────────────────────────────────────────────────
RECOMMENDED_KEYWORDS = [
    # Direct intent
    "looking for digital agency",
    "agency recommendations",
    "marketing agency partner",
    # Budget triggers
    "series a funding",
    "series b funding",
    "raised funding",
    # Leadership
    "new cmo appointed",
    "new head of marketing",
    # Launches
    "brand launch",
    "product launch campaign",
    # Service pain points
    "seo agency",
    "performance marketing agency",
    "pr agency",
    "creative agency",
    "brand film production",
]

# ─────────────────────────────────────────────────────────────────────────────
# Apify — LinkedIn post search (harvestapi/linkedin-post-search, no cookies)
# Pay-per-result (~$1.50 / 1,000 posts). One actor run handles many queries,
# so a full 110-keyword scan is ~6 runs instead of 110 Google searches.
# ─────────────────────────────────────────────────────────────────────────────
APIFY_TOKEN = os.getenv("APIFY_API_TOKEN", "")
APIFY_ACTOR_ID = "harvestapi~linkedin-post-search"
APIFY_BASE_URL = "https://api.apify.com/v2"

MAX_POSTS_PER_QUERY = 100     # newest-first per keyword; 110 kw × 100 ≈ $16.50/scan max
QUERIES_PER_RUN = 20         # keywords batched per actor run
RUN_POLL_SECONDS = 5         # poll interval while a run is in progress
RUN_TIMEOUT_SECONDS = 900    # give up on a single run after 15 min

# ─────────────────────────────────────────────────────────────────────────────
# AI Verifier — Gemini Flash semantic second-pass (precision backstop)
#
# Runs after the regex gates, judges each surviving post against the 9 services
# and drops anything that isn't a brand actively seeking to hire an agency.
# At ~50-100 survivors/day × gemini-2.0-flash this is well under $1/month.
# Set GOOGLE_API_KEY in .env to enable; leave ENABLED=True to use it when a key
# is present (it auto-falls-back to pass-through when the key is missing).
# ─────────────────────────────────────────────────────────────────────────────
VERIFIER = {
    "ENABLED":        os.getenv("VERIFIER_ENABLED", "true").lower() != "false",
    "API_KEY":        os.getenv("GOOGLE_API_KEY", ""),
    # gemini-flash-latest always points at the newest Flash model and avoids the
    # per-model-id quota exhaustion that hit gemini-2.0-flash on our key.
    "MODEL":          os.getenv("VERIFIER_MODEL", "gemini-flash-latest"),
    "BATCH_SIZE":     int(os.getenv("VERIFIER_BATCH_SIZE", "10")),
    "MIN_CONFIDENCE": int(os.getenv("VERIFIER_MIN_CONFIDENCE", "60")),
    "MAX_POSTS":      int(os.getenv("VERIFIER_MAX_POSTS", "100")),  # cost cap per run
}

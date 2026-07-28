# LinkedIn Sales Engine v4 — Extension Technical Spec

**Author:** Prepared for Sanjay Kumar / Grapesworldwide NBD
**Date:** 2026-07-21
**Status:** Draft for review
**Primary goal:** Solve the #1 bottleneck — **not enough leads** — by turning the single-source Apify pipeline into a **multi-source signal-fusion engine**, without sacrificing the precision that is the current system's moat.

---

## 0. Guiding Principles

1. **The funnel is sacred.** Every new lead source, no matter where it comes from, must normalize into the existing `LinkedInPost` schema and pass through the *unchanged* scorer → filter → benchmark → verifier gates. We add **breadth at the top**, never bypass precision at the bottom.
2. **Zero-infra bias, upgraded.** The current JSON-on-disk model is elegant for a small team but is now the ceiling on dedup, lifecycle, and analytics. We move to **SQLite** (still a single file, still committable, still no server) as the backbone — nothing else in Tier 1 works well without it.
3. **Additive, not destructive.** Every collector is behind a feature flag / env var. If a key is missing, that source silently no-ops (same pattern as the Apollo/Verifier graceful fallback you already use). A collector outage never blanks the dashboard.
4. **Cost-visible.** Every source reports its cost per run (you already do this for Apify at `$0.0015/result`). The digest shows total spend per scan.

---

## 1. Architecture Overview

### 1.1 Current flow (v3)
```
Apify actor ──▶ parse ──▶ score ──▶ 6-gate filter ──▶ benchmark ──▶ verifier ──▶ Apollo ──▶ exports/dashboard
   (1 source)
```

### 1.2 Proposed flow (v4)
```
┌─────────────── COLLECTORS (parallel, pluggable) ───────────────┐
│  Apify LinkedIn posts   (existing)                             │
│  LinkedIn Jobs          (new)                                  │
│  Google/News search     (new — WebSearch)                     │
│  Reddit / X threads     (new)                                 │
│  Target-account monitor (new — website/job-page watch)        │
└────────────────────────────┬───────────────────────────────────┘
                             ▼
                  Normalizer → LinkedInPost schema (source-tagged)
                             ▼
          Cross-run dedup  (SQLite: skip already-seen leads)
                             ▼
     score ─▶ 6-gate filter ─▶ benchmark ─▶ verifier   (UNCHANGED)
                             ▼
        ICP-Fit scoring  (Apollo firmographics → Intent × Fit)
                             ▼
              Apollo enrichment + decision-maker map
                             ▼
   Persist to SQLite (lifecycle) ─▶ Account rollup
                             ▼
┌──────────────── OUTPUTS ────────────────┐
│  Dashboard (existing, extended)         │
│  Slack digest + realtime alerts (new)   │
│  Email digest (new)                     │
│  CRM sync: HubSpot/Pipedrive/SF (new)   │
│  Gmail/Outlook outreach send (new)      │
└─────────────────────────────────────────┘
```

### 1.3 New directory layout
```
agent/
  collectors/                 # NEW — one module per source, common interface
    __init__.py               #   registry + Collector base class
    apify_posts.py            #   wraps existing searcher.py
    linkedin_jobs.py          #   NEW
    news_search.py            #   NEW (WebSearch/Google)
    social_threads.py         #   NEW (Reddit/X)
    account_monitor.py        #   NEW (website/job-page watch)
  store/                      # NEW — persistence backbone
    __init__.py
    db.py                     #   SQLite schema + migrations
    leads.py                  #   lead CRUD + lifecycle + cross-run dedup
    accounts.py               #   account rollup
  fit.py                      # NEW — ICP firmographic scoring
  integrations/               # NEW
    slack.py
    email_digest.py
    crm_hubspot.py            #   (or pipedrive/salesforce — see §6)
    gmail_send.py
  scheduler.py                # NEW — cron entrypoint
config/
  sources.py                  # NEW — per-source config + ICP definition
```

---

## 2. Tier 1 — Feature Specs (the lead-volume fixes)

### 2.1 Collector Framework (foundation)

**Problem:** Everything is hardwired to one Apify actor in `searcher.py`.

**Design:** A `Collector` abstract base class with a single contract:

```python
# agent/collectors/__init__.py
class Collector(ABC):
    name: str                      # "apify_posts", "linkedin_jobs", ...
    cost_per_result: float = 0.0

    def is_enabled(self) -> bool: ...          # key present? flag on?
    def collect(self, keywords: list[str], timeline: str,
                progress=None) -> list[dict]:   # returns RAW items
        ...
    def normalize(self, raw: dict) -> LinkedInPost:  # → common schema
        ...

def run_all_collectors(keywords, timeline, progress=None) -> list[LinkedInPost]:
    # iterate registry, skip disabled, tag each post with .source,
    # merge, return normalized posts BEFORE dedup/score
```

Each `LinkedInPost` gains one field: `source: str` (`"linkedin_post"`, `"linkedin_job"`, `"news"`, `"reddit"`, `"account_watch"`). The dashboard shows a source chip per card.

`run_pipeline()` in `main.py` changes exactly one line: the fetch block becomes `posts = run_all_collectors(...)`. Everything downstream is untouched.

**Effort:** ~1 day (framework + refactor existing Apify path into `apify_posts.py`).

---

### 2.2 Collector: LinkedIn Jobs  ⭐ highest-value new source

**Why:** A company posting a job for **Head of Marketing / Brand Manager / Growth Lead / Performance Marketing Manager** is the cleanest possible agency-budget signal — it's your existing Tier-2 `new_marketing_leader` signal, but sourced *before* the person even starts, and with a named hiring company attached. Job posts are structured, high-signal, and lower-noise than free-text posts.

**Source options (pick one at build time):**
- Apify `bebity/linkedin-jobs-scraper` or `misceres/linkedin-jobs-scraper` (consistent with your existing Apify billing/account).
- Fallback: Google Jobs via WebSearch.

**Mapping to signals:** New `MOMENT_SIGNALS` entries + a job→service map. E.g. a "Social Media Manager" opening → intent to build social capability → `SMO` pitch; "Brand Manager" → `Brand`; agency-side titles are rejected by the existing agency-author gate.

**Intent logic:** A job opening is a *medium* signal (score ~6–7), boosted to 8–9 when combined with a funding/rebrand signal on the same company (account rollup, §3.1). Filter gate reused as-is; the "active-seeking" gate is relaxed only for this source (a job post *is* the intent).

**Effort:** ~1.5 days.

---

### 2.3 Collector: News / Funding / Rebrand Search

**Why:** Funding, new-CMO, and rebrand news breaks in press before it hits LinkedIn posts. You already score these signals — this source feeds them from the primary channel.

**Design:** Use the `WebSearch` tool (already available in this environment) with rotating query templates per service + region, e.g.:
- `"raised Series A" OR "Series B" marketing OR brand India 2026`
- `"appointed CMO" OR "new head of marketing" <region>`
- `"rebrand" OR "new brand identity" launched <region>`

Each hit is fetched (`WebFetch`), summarized to a pseudo-post (company + event + date), and dropped into the funnel. The verifier is *especially* valuable here to strip noise. De-dup against LinkedIn posts by company name so you don't double-count.

**Effort:** ~1.5 days.

---

### 2.4 Collector: Social Threads (Reddit / X)

**Why:** `r/marketing`, `r/PPC`, `r/advertising`, `r/entrepreneur`, and X have recurring "can anyone recommend an agency for X" threads — pure intent, and virtually no agency competition watching them.

**Design:** Reddit public JSON API (no auth for read) with subreddit + keyword filters; optional X via API if a key exists. Normalize author + body into the schema. Region detection reused. These are noisier, so `min_confidence` on the verifier is raised for this source.

**Effort:** ~1 day (Reddit). X is optional/flagged.

---

### 2.5 Collector: Target-Account Monitor

**Why:** Proactive, not reactive. Maintain a watchlist of dream accounts (from `config/sources.py` or the SQLite `accounts` table). Periodically check their careers page + LinkedIn for the signals above. When a watched account starts hiring marketers or announces funding → instant alert.

**Design:** Lightweight scheduled diff of each account's job page / news. Feeds the same funnel with `source="account_watch"` and an automatic score boost (you *chose* these accounts).

**Effort:** ~1 day.

---

### 2.6 Persistence Backbone: SQLite Lead Store  ⭐ required foundation

**Problem:** Dedup is within-run only (`seen_urls`/`seen_content` in `run_pipeline`). The same lead resurfaces every run. No lifecycle. No history. `sales_prospects.json` / `negative_list.json` don't scale to analytics.

**Schema (`data/pipeline.db`):**

```sql
CREATE TABLE leads (
  id                INTEGER PRIMARY KEY,
  content_hash      TEXT UNIQUE,       -- reuse triage.content_hash()
  url               TEXT,
  source            TEXT,              -- linkedin_post | linkedin_job | news | reddit | account_watch
  author_name       TEXT,
  author_url        TEXT,
  company           TEXT,
  company_domain    TEXT,
  region            TEXT,
  snippet           TEXT,
  intent_score      INTEGER,
  fit_score         INTEGER,           -- NEW (§2.7)
  combined_score    REAL,              -- intent × fit
  pitch_services    TEXT,              -- JSON
  moment_signals    TEXT,              -- JSON
  verifier_reason   TEXT,
  contact_email     TEXT,
  decision_makers   TEXT,              -- JSON
  status            TEXT DEFAULT 'new',-- new|contacted|replied|qualified|won|lost|negative
  first_seen        TIMESTAMP,
  last_seen         TIMESTAMP,
  crm_id            TEXT,              -- external CRM record id once synced
  UNIQUE(content_hash)
);

CREATE TABLE accounts (
  domain            TEXT PRIMARY KEY,
  company           TEXT,
  size_band         TEXT,
  industry          TEXT,
  funding_stage     TEXT,
  is_watchlist      INTEGER DEFAULT 0,
  signal_count      INTEGER DEFAULT 0,
  last_signal_at    TIMESTAMP
);

CREATE TABLE events (            -- audit / analytics
  id INTEGER PRIMARY KEY, lead_id INTEGER, kind TEXT, meta TEXT, ts TIMESTAMP
);
```

**Cross-run dedup:** before scoring, drop any collected post whose `content_hash` already exists in `leads` **unless** its status warrants a re-surface (e.g. a `new` lead untouched for 30 days). This is the single biggest quality-of-life win — the team only ever sees genuinely new leads.

**Migration:** one-time importer folds existing `sales_prospects.json` (→ status `qualified`) and `negative_list.json` (→ status `negative`) into the DB. The positive/negative feedback loop and content benchmark keep working, now reading from SQLite.

**Effort:** ~2 days (schema, CRUD, dedup wiring, migration). **This should be built first** — collectors and integrations all depend on it.

---

### 2.7 ICP-Fit Scoring

**Problem:** `intent_score` is 100% text-signal. A score-10 RFP from a 2-person startup outranks a score-8 from a Series-B brand in your sweet spot. Wrong priority.

**Design:** New `agent/fit.py`. Define the ICP in `config/sources.py`:

```python
ICP = {
  "target_size_bands":   {"11-50": 0.8, "51-200": 1.0, "201-1000": 1.0, "1001+": 0.7, "1-10": 0.4},
  "target_industries":   ["consumer goods","d2c","fintech","hospitality","real estate","healthcare","ed-tech"],
  "target_regions":      {"india": 1.0, "uae": 1.0, "saudi": 0.9, "uk": 0.7, "us": 0.6},
  "funding_recency_boost": 0.2,   # funded < 12 months
}
```

`fit_score` (0–1) is computed from Apollo firmographics already fetched. **`combined_score = intent_score × (0.5 + 0.5 × fit_score)`** — fit modulates but never zeroes intent. Sort and digest rank by `combined_score`. Dashboard shows both.

**Effort:** ~1 day.

---

### 2.8 Scheduling + Multi-Channel Digest

**Problem:** Every scan is manual.

**Design:** `agent/scheduler.py` as a cron entrypoint (via the `scheduled-tasks` capability or system cron). Runs the full auto-keyword scan on a schedule (e.g. 07:30 daily), writes new leads to SQLite, and pushes a **ranked digest** to Slack + email:

> **11 new leads today · 3× score-10 RFP · est. Apify cost $4.20**
> 🚨 Acme (Series B, D2C, Mumbai) — "looking for a PR agency" — combined 9.4 → [view]
> …

Real-time path: any lead with `combined_score ≥ 9` fires an **immediate** Slack/WhatsApp alert, not just the daily roll-up.

**Effort:** ~1.5 days (scheduler + Slack + email; see §6 for integration detail).

---

## 3. Tier 2 — Differentiation

### 3.1 Account-Based Rollup
Group leads by `company_domain`. An account with **multiple signals in a short window** (funding + new-CMO + rebrand) is a far hotter lead than any single post. Dashboard gets an "Accounts" tab: company → signal timeline → decision-maker map (from Apollo) → aggregate score. **Effort:** ~1.5 days (depends on SQLite).

### 3.2 CRM Sync (HubSpot / Pipedrive / Salesforce)
One-click (and auto-on-qualify) push of a lead with full context — post, signals, drafts, decision-makers — into the CRM. `crm_id` stored back on the lead to prevent duplicates and enable status write-back. **Recommend starting with one CRM** — tell me which you use. **Effort:** ~1.5 days per CRM.

### 3.3 Closed-Loop Outreach (Gmail/Outlook)
Extend the existing draft-generation: send the approved draft via Gmail API (**per-send human approval required** — never auto-send), track opens/replies via webhook or polling, and write status back to SQLite (`contacted → replied`). **Effort:** ~2 days.

### 3.4 Competitor Displacement Radar
Activate the dormant `competitor_mentioned` hook in `scorer.py`. Feed a competitor-agency list; flag brands publicly praising/complaining about a rival = warm displacement targets. **Effort:** ~0.5 day.

---

## 4. Tier 3 — Intelligence & Polish
- **Analytics tab:** which signals/services/regions actually convert (needs a few weeks of SQLite `events` data). Source-ROI: cost per qualified lead per collector.
- **Enrichment fallback chain:** Apollo → Hunter.io → Clearbit so one provider's miss isn't a dead lead.
- **Benchmark hygiene:** auto-retire stale positive signals; drift detection.
- **WhatsApp/Telegram alerts** for score-10 leads.

## 5. Tier 4 — Frontier
- **Per-lead agentic research:** a sub-agent reads the company site + recent news + the prospect's last posts → hyper-personalized opener.
- **Predictive intent:** learn from won/lost which early signals precede a close; surface leading indicators before the RFP posts.

---

## 6. Integration Detail (you selected all four)

| Integration | Purpose | Auth | Notes |
|---|---|---|---|
| **Slack** | Daily digest + realtime score-9+ alerts | Incoming webhook or bot token | Simplest, build first. Channel per region optional. |
| **Email** | Daily digest to NBD team | SMTP or Gmail API | HTML digest reuses `reporter.export_html` styling. |
| **CRM** | Push qualified leads | OAuth / API key | **Confirm which CRM** (HubSpot vs Pipedrive vs Salesforce). Start with one. |
| **Gmail/Outlook send** | Execute approved outreach | OAuth | **Per-send approval enforced** — drafts never auto-send. Reply tracking writes back to SQLite. |
| **Apollo (existing)** | Enrichment + sequence hub | X-Api-Key | Keep as-is; CRM sync complements, doesn't replace. |

**Security note:** all sends (email, CRM writes) require explicit confirmation in the UI before the first external action; approval is per-action, not standing.

---

## 7. Recommended Build Order

| Phase | Features | Effort | Unlocks |
|---|---|---|---|
| **P0 — Foundation** | SQLite lead store (§2.6) + Collector framework (§2.1) | ~3 days | Everything below |
| **P1 — Volume** | LinkedIn Jobs (§2.2) + News search (§2.3) + cross-run dedup | ~3 days | **Solves your #1 pain** |
| **P2 — Automation** | Scheduler + Slack + Email digest (§2.8) | ~2 days | Always-on engine |
| **P3 — Quality** | ICP-Fit scoring (§2.7) + Account rollup (§3.1) | ~2.5 days | Right leads first |
| **P4 — Reach** | Reddit collector (§2.4) + Account monitor (§2.5) | ~2 days | More sources |
| **P5 — Revenue** | CRM sync (§3.2) + Gmail outreach (§3.3) | ~3.5 days | Closed loop |

**Total to a materially better engine:** P0–P2 ≈ **8 working days** gets you multi-source + automated + deduped — directly attacking the lead-volume bottleneck. P3+ compounds from there.

---

## 8. Risks & Mitigations
- **Source ToS / rate limits** — all scraping via Apify actors (managed) or public APIs; respect robots/rate limits; no credential-based LinkedIn scraping.
- **Precision dilution from noisy sources** — every source passes the existing filter+verifier; per-source `min_confidence` tuning; source chips make bad sources visible for quick disabling.
- **Cost creep** — per-source cost reporting in every digest; `MAX_POSTS` caps per collector; SQLite dedup means you never pay to re-verify a known lead.
- **SQLite migration risk** — one-way importer keeps JSON files intact as backup; DB is a single committable file.

---

## 9. Open Questions for You
1. **Which CRM** do you use (HubSpot / Pipedrive / Salesforce / other)? Shapes §3.2.
2. **Slack vs email** — which is the team's primary channel for the daily digest, or both equally?
3. **LinkedIn Jobs source** — OK to add another Apify actor (same billing), or prefer Google Jobs?
4. **Watchlist** — do you already have a list of dream/target accounts to seed §2.5?
5. **Scan cadence** — once daily at a fixed time, or multiple times/day for freshness?
```

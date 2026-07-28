## Add Region Filter to the Sales Pipeline Dashboard

### What you'll get
A region filter on the white-theme HTML dashboard for **6 regions + Unmapped**: 🇮🇳 India · 🇦🇪 Dubai/UAE · 🇸🇦 Saudi Arabia · 🇬🇧 UK · 🇺🇸 US · 🇪🇺 Europe · ❓ Unmapped. Region is auto-detected from each post's text + author headline. Unmatched leads stay visible under "Unmapped" (nothing lost). Regions combine with the existing filters (e.g. "India + Score 7+").

### Constraint driving the design
The Apify `harvestapi/linkedin-post-search` actor returns **no author location field** and has no country search filter (confirmed from its docs). So detection must be client-side, inferring region from post text + headline (e.g. "PAN India Hiring" → India, "based in Dubai" → UAE, "£" → UK).

### Implementation

**1. NEW `agent/region.py`** — region detection
- `REGIONS` dict: each region key → label, flag emoji, and a curated list of matcher tokens (cities, country names, currency symbols, currency codes, locale markers).
- `detect_region(post) -> str | None`: scans lowercased `snippet + author_headline` with word-boundary regex. Returns first match by priority order (most-specific regions checked first so generic "$"/"€" don't misfire). Returns `None` when unmatched.

**2. `agent/parser.py`** — add `region: str = ""` field to `LinkedInPost`.

**3. `main.py`** — after scoring, one loop calling `detect_region()` on every post (detection only; no filtering).

**4. `agent/reporter.py`** — in `export_html`:
- Add `data-region` attribute to each `.card`.
- Add region filter buttons (grouped after service filters): All Regions / India / Dubai-UAE / Saudi / UK / US / Europe / Unmapped.
- Extend `filterCards()` JS to track an active region separately and AND-combine it with the existing type/score/service filter.
- Show a small `🇮🇳 India` region badge on each card's meta row.
- Add `region` to both `export_json` and `export_csv` field lists.

### Edge cases
- No match → empty region → "Unmapped" bucket (your choice).
- Multiple regions → highest-priority specific token wins.
- Currency symbols ($) are weak signals — only used when no stronger geographic token matched.
- Old JSON exports without `region` → default to `""` gracefully.

### Out of scope
No CLI flag (dashboard-only, per your choice). No change to Apify search call. Terminal output unchanged.

### Verification
Re-render `outputs/_preview_white_dashboard.html` from existing real JSON to confirm cards tag correctly, all 7 region buttons work in combination with existing filters, and no Python errors. Spot-check: the "PAN India Hiring" founder post → 🇮🇳 India.

### Files changed
| File | Change |
|---|---|
| `agent/region.py` | NEW — region patterns + `detect_region()` |
| `agent/parser.py` | Add `region: str = ""` field |
| `main.py` | Call `detect_region()` after scoring |
| `agent/reporter.py` | Card `data-region`, region buttons, JS filter logic, region badge, JSON/CSV export field |
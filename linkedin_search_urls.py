#!/usr/bin/env python3
"""
LinkedIn Search URL Builder — Grapesworldwide Edition
=====================================================

Generates LinkedIn content-search URLs (sorted by date, past-24h freshness)
for brand-voice RFP phrases. Outputs an HTML dashboard with clickable links so
the BD team can manually open each search every morning and respond to fresh
agency RFPs from brands.

Why brand-voice only?
    LinkedIn's free content search can't filter by author type (brand vs
    agency vs job poster). A phrase like "looking for a creative agency"
    matches BOTH brand RFPs AND job posts like "Looking for a Creative
    Agency Manager — apply now". To eliminate hiring-post noise, we use ONLY
    phrases that brands use to ask for agencies but agencies-hiring-employees
    almost never write:

      ✓ "we are looking to partner with a creative agency"  (first-person brand voice)
      ✓ "drop a recommendation in the comments"              (community asking)
      ✓ "RFP for branding agency"                            (explicit RFP language)
      ✓ "agency for our real estate brand"                   ("our brand" framing)

    Bare phrases like "creative agency" / "branding agency" / "looking for
    SEO agency" are excluded — they're contaminated by job posts and agency
    self-promo.

Usage:
    python3 linkedin_search_urls.py                          # All 4 sections, past-24h
    python3 linkedin_search_urls.py --rfp-only               # RFP-Explicit + First-Person only
    python3 linkedin_search_urls.py --freshness past-week    # Wider window
    python3 linkedin_search_urls.py --open                   # Auto-open HTML
    python3 linkedin_search_urls.py --print                  # Terminal output
"""

import argparse
import os
import sys
import webbrowser
from datetime import datetime
from urllib.parse import quote


# ─── URL builder ──────────────────────────────────────────────────────────────

VALID_FRESHNESS = ["past-24h", "past-week", "past-month"]
_SORT_BY_DATE = quote('["date_posted"]')


def build_url(keyword: str, freshness: str = "past-24h") -> str:
    """
    Build a LinkedIn content-search URL.

    Format mirrors LinkedIn's UI exactly: plain unquoted keyword,
    sortBy=date_posted, datePosted freshness window. No boolean operators
    (LinkedIn restricted those to Sales Nav / Recruiter in 2023+).
    """
    date_filter = quote(f'["{freshness}"]')
    return (
        "https://www.linkedin.com/search/results/content/"
        f"?keywords={quote(keyword)}"
        "&origin=FACETED_SEARCH"
        f"&sortBy={_SORT_BY_DATE}"
        f"&datePosted={date_filter}"
    )


# ─── BRAND-VOICE PHRASE LIBRARY ───────────────────────────────────────────────
# Every phrase here passes this test:
#   "Would an agency hiring an employee ever write this?"  →  NO
#   "Would an agency promoting its own work ever write this?"  →  NO
#   "Is this language a brand uses when soliciting agency partners?"  →  YES

# ─── Tier 1 ─ RFP-Explicit Phrases ────────────────────────────────────────────
# RFP language flows from brand → agency. Job posts and agency promos never
# use "RFP for [agency type]" or "calling all creative agencies" framings.
RFP_EXPLICIT_PHRASES: list[str] = [
    "RFP for creative agency",
    "RFP for branding agency",
    "RFP for marketing agency",
    "RFP for digital agency",
    "RFP for PR agency",
    "RFP for media agency",
    "RFP for advertising agency",
    "RFP for creative services",
    "RFP for marketing services",
    "RFP for branding services",
    "open RFP for agency",
    "we are issuing an RFP",
    "we have issued an RFP",
    "issuing an RFP to agencies",
    "agency pitch invitation",
    "open call for creative agencies",
    "open call to creative agencies",
    "calling all creative agencies",
    "calling all branding agencies",
    "calling all marketing agencies",
    "calling all digital agencies",
]

# ─── Tier 1 ─ First-Person Brand Voice ────────────────────────────────────────
# "We", "our brand", "our company" + agency ask. Agencies don't refer to
# themselves needing an agency (they ARE the agency). Job posts say "we are
# hiring a [role]", never "we are looking to partner with an agency".
FIRST_PERSON_BRAND_PHRASES: list[str] = [
    "we are looking to partner with a creative agency",
    "we're looking to partner with a creative agency",
    "we are looking to partner with a branding agency",
    "we're looking to partner with a branding agency",
    "we are looking to partner with a marketing agency",
    "we're looking to partner with a marketing agency",
    "we are looking to partner with a digital agency",
    "we're looking to partner with a digital agency",
    "we are looking to partner with an agency",
    "we're looking to partner with an agency",
    "we want to partner with an agency",
    "we are looking for a creative agency",
    "we're looking for a creative agency",
    "we are looking for a branding agency",
    "we're looking for a branding agency",
    "we are looking for a marketing agency",
    "we're looking for a marketing agency",
    "we are looking for a digital agency",
    "we're looking for a digital agency",
    "we are looking for a PR agency",
    "we are looking for an event agency",
    "we are looking for an agency partner",
    "we are evaluating agencies",
    "we are inviting agencies to pitch",
    "our brand is looking for an agency",
    "our brand needs a creative agency",
    "our brand needs a branding agency",
    "our company is looking for an agency",
]

# ─── Tier 1 ─ Community Recommendation Asks ───────────────────────────────────
# Brands soliciting agency recs from their network. "Drop a recommendation",
# "tag your favourite", "if you've worked with" — these conversational patterns
# are diagnostic of brand-side asking.
COMMUNITY_ASKING_PHRASES: list[str] = [
    "drop a recommendation in the comments",
    "drop your agency recommendations",
    "drop agency recommendations below",
    "share your agency recommendations",
    "share your favourite agency",
    "share your favorite agency",
    "would love agency recommendations",
    "tag your favourite agency",
    "tag your favorite agency",
    "tag the best creative agency",
    "tag the best branding agency",
    "tag your best creative agency",
    "if you have worked with a great agency",
    "if you've worked with a great agency",
    "looking for an agency specializing in",
    "looking for a creative agency specializing in",
    "looking for a branding agency specializing in",
    "looking forward to connecting with the best agencies",
]

# ─── Tier 1 ─ Industry-Vertical × Brand Voice ─────────────────────────────────
# Brand industry qualifier + "our brand" / "for our launch" / "experienced in
# [vertical]" framing. Each phrase is unambiguous — only a brand would write it.
INDUSTRY_BRAND_VOICE_PHRASES: list[str] = [
    # Real estate
    "agency for our real estate brand",
    "creative agency for real estate launch",
    "agency experienced in real estate branding",
    "agency experienced in real estate marketing",
    # FMCG
    "agency for our FMCG brand",
    "creative agency for our FMCG launch",
    "agency experienced in FMCG marketing",
    # Fintech
    "agency for our fintech brand",
    "agency experienced in fintech marketing",
    # Healthcare / Pharma
    "agency for our healthcare brand",
    "agency for our pharma brand",
    "agency experienced in healthcare marketing",
    "agency experienced in pharma marketing",
    # D2C
    "agency for our D2C brand",
    "agency experienced in D2C marketing",
    "creative agency for our D2C launch",
    # Luxury
    "agency for our luxury brand",
    "agency experienced in luxury branding",
    # EV / Automobile
    "agency for our EV brand",
    "agency for our automobile brand",
    "agency experienced in automobile marketing",
    # Hospitality
    "agency for our hospitality brand",
    "agency for our hotel brand",
    "agency experienced in hospitality marketing",
    # B2B / SaaS
    "agency for our SaaS brand",
    "agency for our B2B brand",
    "agency experienced in B2B SaaS marketing",
    # EdTech
    "agency for our edtech brand",
    "agency experienced in edtech marketing",
]


# ─── Output sections ──────────────────────────────────────────────────────────

def build_sections(rfp_only: bool) -> list[dict]:
    """
    Returns ordered list of sections to render. Each section:
      {title, icon, tier, keywords, is_rfp}
    """
    sections: list[dict] = [
        {
            "title": "RFP-Explicit Phrases",
            "icon": "🚨",
            "tier": "Tier 1 · Highest precision · 'RFP for…', 'open call', 'calling all agencies'",
            "keywords": RFP_EXPLICIT_PHRASES,
            "is_rfp": True,
        },
        {
            "title": "First-Person Brand Voice",
            "icon": "🗣️",
            "tier": "Tier 1 · 'We are looking to partner with…', 'our brand needs…' — pure brand voice",
            "keywords": FIRST_PERSON_BRAND_PHRASES,
            "is_rfp": True,
        },
    ]
    if rfp_only:
        return sections

    sections.extend([
        {
            "title": "Community Recommendation Asks",
            "icon": "💬",
            "tier": "Tier 1 · 'Drop a recommendation', 'tag the best agency', 'if you've worked with…'",
            "keywords": COMMUNITY_ASKING_PHRASES,
            "is_rfp": True,
        },
        {
            "title": "Industry-Vertical Brand Voice",
            "icon": "🏢",
            "tier": "Tier 1 · 'Agency for our [vertical] brand', 'experienced in [vertical] marketing'",
            "keywords": INDUSTRY_BRAND_VOICE_PHRASES,
            "is_rfp": True,
        },
    ])
    return sections


# ─── HTML rendering ───────────────────────────────────────────────────────────

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>LinkedIn RFP Search URLs — Grapesworldwide</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    max-width: 1100px; margin: 24px auto; padding: 0 20px;
    color: #1d1d1f; background: #f5f5f7;
  }}
  h1 {{ margin: 0 0 4px; font-size: 24px; }}
  .meta {{
    color: #555; font-size: 14px; margin-bottom: 20px;
    padding: 10px 14px; background: white; border-radius: 8px;
    border: 1px solid #e5e5e5;
  }}
  .meta strong {{ color: #0a66c2; }}
  .filter-box {{
    width: 100%; padding: 12px 16px; font-size: 15px;
    border: 2px solid #ddd; border-radius: 10px; margin-bottom: 16px;
    background: white; transition: border-color 0.15s;
  }}
  .filter-box:focus {{ outline: none; border-color: #0a66c2; }}
  .nav {{
    margin-bottom: 20px; padding: 12px; background: white;
    border: 1px solid #e5e5e5; border-radius: 8px;
    display: flex; flex-wrap: wrap; gap: 8px;
  }}
  .nav a {{
    text-decoration: none; color: #0a66c2; font-size: 13px;
    padding: 4px 10px; border-radius: 6px; background: #f0f7ff;
  }}
  .nav a:hover {{ background: #d6e9ff; }}
  .section {{
    background: white; border: 2px solid #ff6b6b;
    background: linear-gradient(180deg, #fff5f5 0%, #ffffff 60%);
    border-radius: 12px; padding: 18px 22px; margin-bottom: 16px;
    scroll-margin-top: 20px;
  }}
  .section h2 {{ margin: 0 0 4px; font-size: 18px; color: #c92020; display: flex; align-items: center; gap: 8px; }}
  .section .tier {{ font-size: 12px; color: #888; margin-bottom: 12px; font-weight: 500; }}
  .section-controls {{ margin-bottom: 12px; display: flex; gap: 8px; flex-wrap: wrap; }}
  .open-btn {{
    background: white; color: #0a66c2; border: 1px solid #0a66c2;
    padding: 6px 14px; border-radius: 8px; font-size: 13px;
    cursor: pointer; font-weight: 500; transition: all 0.1s;
  }}
  .open-btn:hover {{ background: #0a66c2; color: white; }}
  .copy-btn {{
    background: white; color: #555; border: 1px solid #ccc;
    padding: 6px 14px; border-radius: 8px; font-size: 13px;
    cursor: pointer; transition: all 0.1s;
  }}
  .copy-btn:hover {{ background: #f0f0f0; }}
  .kw-list {{ list-style: none; padding: 0; margin: 0; }}
  .kw-list li {{
    padding: 8px 0; border-bottom: 1px solid #f0f0f0;
    display: flex; justify-content: space-between; align-items: center; gap: 12px;
  }}
  .kw-list li:last-child {{ border-bottom: none; }}
  .kw-text {{ flex: 1; font-size: 14px; }}
  .kw-num {{ color: #aaa; font-size: 12px; margin-right: 8px; }}
  .kw-link {{
    background: #0a66c2; color: white; text-decoration: none;
    padding: 6px 14px; border-radius: 16px; font-size: 13px;
    font-weight: 500; white-space: nowrap; transition: background 0.1s;
  }}
  .kw-link:hover {{ background: #084d8f; }}
  .footer {{ margin-top: 32px; padding: 16px; text-align: center;
            color: #888; font-size: 12px; }}
  .approach {{ margin-top: 10px; padding: 10px 14px; background: #e8f5e9;
              border-left: 3px solid #2e7d32; border-radius: 4px;
              font-size: 12px; color: #1b5e20; }}
  .approach code {{ background: rgba(0,0,0,0.05); padding: 1px 6px;
                    border-radius: 3px; margin: 0 2px; font-size: 11px;
                    font-family: ui-monospace, "SF Mono", Menlo, monospace; }}
  .approach strong {{ color: #1b5e20; }}
</style>
</head>
<body>

<h1>🔎 LinkedIn RFP Search URLs — Brand-Voice Only</h1>
<div class="meta">
  Generated <strong>{ts}</strong> · Freshness <strong>{freshness}</strong> ·
  <strong>{total}</strong> brand-voice keyword URL(s) across <strong>{n_sections}</strong> section(s) ·
  Sorted by date posted (newest first)
  <br><span style="color:#666; font-size:13px">
    Each link opens LinkedIn's native content search in a new tab.
  </span>
  <div class="approach">
    <strong>🎯 Brand-voice filtering at the keyword level.</strong>
    Since LinkedIn's free content search can't filter by author type, we use
    <em>only</em> phrases that brands write but agencies-hiring-employees
    almost never do — e.g. <code>we are looking to partner with</code>,
    <code>RFP for creative agency</code>, <code>drop a recommendation</code>,
    <code>agency for our [vertical] brand</code>. Ambiguous phrases like
    <code>looking for SEO agency</code> or <code>creative agency</code> are
    intentionally excluded — they pull in hiring posts and agency self-promo.
  </div>
</div>

<input type="text" class="filter-box"
       placeholder="🔍 Filter keywords inline (e.g. 'rfp', 'real estate', 'creative')…"
       oninput="filterKeywords(this.value)" />

<div class="nav">
  <strong style="margin-right:6px; font-size:13px;">Jump to:</strong>
  {nav_html}
</div>

{sections_html}

<div class="footer">
  Generated by <code>linkedin_search_urls.py</code> · Grapesworldwide BD Intelligence
</div>

<script>
function filterKeywords(q) {{
  q = q.toLowerCase().trim();
  document.querySelectorAll('.section').forEach(section => {{
    let visibleCount = 0;
    section.querySelectorAll('.kw-list li').forEach(li => {{
      const txt = li.querySelector('.kw-text').textContent.toLowerCase();
      const match = !q || txt.includes(q);
      li.style.display = match ? '' : 'none';
      if (match) visibleCount++;
    }});
    section.style.display = (visibleCount > 0 || !q) ? '' : 'none';
  }});
}}

function openSection(btn, limit) {{
  const links = btn.closest('.section').querySelectorAll('.kw-link');
  const n = Math.min(limit, links.length);
  if (!confirm(`Open ${{n}} LinkedIn search tab(s)?\\n\\n(Browsers may block popups — allow them for this page.)`)) return;
  for (let i = 0; i < n; i++) {{
    window.open(links[i].href, '_blank', 'noopener,noreferrer');
  }}
}}

function copyUrls(btn) {{
  const links = btn.closest('.section').querySelectorAll('.kw-link');
  const text = Array.from(links).map((a, i) => {{
    const kw = a.closest('li').querySelector('.kw-text').textContent.replace(/^\\d+\\.\\s*/, '');
    return `${{kw}}\\n  ${{a.href}}`;
  }}).join('\\n\\n');
  navigator.clipboard.writeText(text).then(() => {{
    const orig = btn.textContent;
    btn.textContent = '✓ Copied';
    setTimeout(() => btn.textContent = orig, 1500);
  }});
}}
</script>
</body>
</html>"""


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text).strip("-").lower()


def render_section_html(section: dict, freshness: str) -> str:
    kws = section["keywords"]
    if not kws:
        return ""

    items = "\n".join(
        f'  <li>'
        f'<span class="kw-text"><span class="kw-num">{i+1}.</span>{kw}</span>'
        f'<a class="kw-link" href="{build_url(kw, freshness)}" target="_blank" rel="noopener">Open ↗</a>'
        f'</li>'
        for i, kw in enumerate(kws)
    )
    anchor = _slug(section["title"])
    n = len(kws)
    open_n = min(5, n)
    return (
        f'<div class="section" id="{anchor}">'
        f'  <h2>{section["icon"]} {section["title"]} <span style="font-weight:400;font-size:13px;color:#888">({n})</span></h2>'
        f'  <div class="tier">{section["tier"]}</div>'
        f'  <div class="section-controls">'
        f'    <button class="open-btn" onclick="openSection(this, {open_n})">Open top {open_n} in new tabs</button>'
        f'    <button class="copy-btn" onclick="copyUrls(this)">Copy URLs as text</button>'
        f'  </div>'
        f'  <ul class="kw-list">{items}</ul>'
        f'</div>'
    )


def render_html(sections: list[dict], freshness: str) -> str:
    nav_html = " ".join(
        f'<a href="#{_slug(s["title"])}">{s["icon"]} {s["title"]} ({len(s["keywords"])})</a>'
        for s in sections if s["keywords"]
    )
    sections_html = "\n".join(render_section_html(s, freshness) for s in sections)
    return HTML_TEMPLATE.format(
        ts=datetime.now().strftime("%Y-%m-%d %H:%M"),
        freshness=freshness,
        total=sum(len(s["keywords"]) for s in sections),
        n_sections=sum(1 for s in sections if s["keywords"]),
        nav_html=nav_html,
        sections_html=sections_html,
    )


# ─── Terminal output ──────────────────────────────────────────────────────────

def print_to_terminal(sections: list[dict], freshness: str):
    print(f"\nLinkedIn RFP Search URLs · Brand-voice only · Freshness: {freshness}")
    print(f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
    for section in sections:
        kws = section["keywords"]
        if not kws:
            continue
        print(f"─── {section['icon']} {section['title']} ({len(kws)}) ───")
        print(f"    {section['tier']}\n")
        for i, kw in enumerate(kws, 1):
            print(f"  {i}. {kw}")
            print(f"     {build_url(kw, freshness)}\n")


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Generate LinkedIn search URLs (past-24h, sorted by date) "
                    "for brand-voice phrases that only brands seeking agencies "
                    "would post (not job posts, not agency self-promo)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # All 4 brand-voice sections, past-24h, save HTML
  python3 linkedin_search_urls.py

  # Only the highest-precision sections (RFP-Explicit + First-Person)
  python3 linkedin_search_urls.py --rfp-only --open

  # Wider window
  python3 linkedin_search_urls.py --freshness past-week --open

  # Terminal output
  python3 linkedin_search_urls.py --print
        """,
    )
    parser.add_argument("--freshness", choices=VALID_FRESHNESS, default="past-24h",
                        help="LinkedIn date filter (default: past-24h)")
    parser.add_argument("--rfp-only", action="store_true",
                        help="Show only RFP-Explicit + First-Person Brand Voice sections (highest precision)")
    parser.add_argument("--output-dir", default="outputs",
                        help="Where to save HTML (default: outputs/)")
    parser.add_argument("--open", action="store_true", dest="open_in_browser",
                        help="Auto-open generated HTML in default browser")
    parser.add_argument("--print", action="store_true", dest="print_only",
                        help="Print URLs to terminal instead of writing HTML")

    args = parser.parse_args()
    sections = build_sections(args.rfp_only)
    total = sum(len(s["keywords"]) for s in sections)

    if total == 0:
        print("✗ No keywords matched your filters.", file=sys.stderr)
        sys.exit(1)

    if args.print_only:
        print_to_terminal(sections, args.freshness)
        return

    os.makedirs(args.output_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    scope = "rfp" if args.rfp_only else "all"
    path = os.path.join(args.output_dir, f"linkedin_urls_{args.freshness}_{scope}_{ts}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(render_html(sections, args.freshness))

    abs_path = os.path.abspath(path)
    print(f"✓ Generated {total} brand-voice URL(s) across {sum(1 for s in sections if s['keywords'])} section(s)")
    print(f"  → {abs_path}")
    print(f"  Freshness: {args.freshness}")

    if args.open_in_browser:
        webbrowser.open(f"file://{abs_path}")
        print("✓ Opened in default browser")


if __name__ == "__main__":
    main()

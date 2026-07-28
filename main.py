#!/usr/bin/env python3
"""
LinkedIn Sales Pipeline Agent — Grapesworldwide Edition
Finds brands actively seeking digital agency services across 9 service lines.

Usage:
  python main.py --auto-keywords                        # Full scan, all 9 services
  python main.py --auto-keywords --service "SEO"        # One service only
  python main.py --keywords "branding agency" --timeline 1day
  python main.py                                        # Interactive mode
"""

import argparse
import os
import sys
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table
from rich import box

from agent.searcher import search_linkedin_posts, search_all_timelines
from agent.parser import parse_result, is_within_timeline
from agent.scorer import score_post
from agent.filter import apply_smart_filter
from agent.region import detect_region
from agent.triage import load_negative_list, apply_negative_filter, load_positive_signals
from agent import reporter
from config.keywords import (
    get_all_keywords, get_keywords_for_service, get_service_list,
    GRAPES_KEYWORDS, UNIVERSAL_INTENT_KEYWORDS, QUICK_SCAN_KEYWORDS,
)
from config.settings import TIMELINE_CONFIG, TIMELINE_BUCKETS

load_dotenv()
console = Console()

VALID_TIMELINES = ["1hr", "3hr", "1day", "2day", "3day", "1week"]


# ─────────────────────────────────────────────────────────────────────────────
# Timeline bucketing helper
# ─────────────────────────────────────────────────────────────────────────────

def bucket_posts(posts):
    """
    Group posts into display bands: Today / Yesterday / 2-3 days / This week.
    Posts with unknown timestamps go into the last bucket.
    """
    now = datetime.now(timezone.utc)
    buckets: dict[str, list] = {b["label"]: [] for b in TIMELINE_BUCKETS}
    buckets["Unknown Age"] = []

    for post in posts:
        if post.estimated_posted_at is None:
            buckets["Unknown Age"].append(post)
            continue
        # Make the stored datetime timezone-aware if it isn't
        est = post.estimated_posted_at
        if est.tzinfo is None:
            est = est.replace(tzinfo=timezone.utc)
        age_hours = (now - est).total_seconds() / 3600
        placed = False
        for b in TIMELINE_BUCKETS:
            if b["min_hours"] <= age_hours < b["max_hours"]:
                buckets[b["label"]].append(post)
                placed = True
                break
        if not placed:
            buckets["Unknown Age"].append(post)

    return buckets


# ─────────────────────────────────────────────────────────────────────────────
# Core pipeline
# ─────────────────────────────────────────────────────────────────────────────

def _skip_reason(vstats: dict, verifier_cfg: dict) -> str:
    """Human-readable reason for the verifier skipping (shown in console)."""
    if not verifier_cfg.get("ENABLED"):
        return "disabled in config"
    if not verifier_cfg.get("API_KEY"):
        return "no GOOGLE_API_KEY set in .env"
    if vstats.get("errors"):
        return f"{vstats['errors']} API error(s)"
    return "no candidates to verify"

def run_pipeline(
    keywords: list[str],
    timeline: str | None,
    api_key: str,
    competitors: list[str] = None,
    output_dir: str = "outputs",
    export_formats: list[str] = None,
    show_all: bool = False,
    min_score: int = 0,
    all_timelines: bool = False,
    service_label: str = "",
    verify: bool = True,
    progress_callback = None,
) -> list:
    os.makedirs(output_dir, exist_ok=True)
    export_formats = export_formats or []

    # Clean / deduplicate keywords
    cleaned: list[str] = []
    seen_kw: set[str] = set()
    for kw in keywords:
        for part in (kw.split(",") if "," in kw else [kw]):
            part = part.strip()
            if part and part.lower() not in seen_kw:
                seen_kw.add(part.lower())
                cleaned.append(part)
    keywords = cleaned

    console.print(f"\n[blue]Scanning LinkedIn (via Apify) for [bold]{len(keywords)}[/] keywords"
                  f"{' · ' + service_label if service_label else ''}"
                  f" · [bold]{'all timelines (1 week window)' if all_timelines else timeline}[/][/]\n")

    # ── Fetch ──────────────────────────────────────────────────────────────────
    all_raw: list[dict] = []

    if all_timelines:
        console.print(f"  [dim]→ Running broadest scan (1 week) across all {len(keywords)} keywords…[/]")

        def _progress(batch_i, batch_total, items_so_far):
            if progress_callback:
                try:
                    progress_callback(batch_i, batch_total, items_so_far, "searching")
                except Exception:
                    pass
            console.print(f"  [dim]Batch {batch_i}/{batch_total} done · {items_so_far} posts so far[/]")

        try:
            all_raw = search_all_timelines(keywords, api_key, progress=_progress)
            console.print(f"  [dim]Found {len(all_raw)} raw results[/]")
        except RuntimeError as e:
            console.print(f"  [red]Error: {e}[/]")
    else:
        total_kws = len(keywords)
        for idx, kw in enumerate(keywords, 1):
            if progress_callback:
                try:
                    progress_callback(idx, total_kws, len(all_raw), "searching")
                except Exception:
                    pass
            console.print(f"  [dim]→ Searching:[/] [cyan]{kw}[/]")
            try:
                results = search_linkedin_posts(kw, timeline, api_key)
                console.print(f"    [dim]{len(results)} results[/]")
                all_raw.extend(results)
            except RuntimeError as e:
                console.print(f"    [red]Error: {e}[/]")

    # ── Deduplicate (by URL, then by content — catches cross-posted text) ──────
    seen_urls: set[str] = set()
    seen_content: set[str] = set()
    unique_raw = []
    for r in all_raw:
        url = r.get("linkedinUrl", "")
        content_key = "".join((r.get("content") or "").lower().split())[:100]
        if not url or url in seen_urls:
            continue
        if content_key and content_key in seen_content:
            continue
        seen_urls.add(url)
        if content_key:
            seen_content.add(content_key)
        unique_raw.append(r)

    console.print(f"\n[dim]Unique results: {len(unique_raw)}[/]")

    # ── Parse ──────────────────────────────────────────────────────────────────
    posts = [parse_result(r) for r in unique_raw]

    # ── Timeline post-filter ───────────────────────────────────────────────────
    if not all_timelines and timeline:
        posts = [p for p in posts if is_within_timeline(p, timeline)]

    # ── Score ──────────────────────────────────────────────────────────────────
    posts = [score_post(p, competitors) for p in posts]

    # ── Smart filter (job posts, agency promos, no-intent) ────────────────────
    # Positive signals (from leads the team marked relevant) let posts from
    # known-good authors/companies bypass the rejection gates with a ⭐ boost.
    positive = load_positive_signals()
    posts, filter_stats = apply_smart_filter(posts, positive=positive)

    # ── Region detection (inferred from post text + author headline) ───────────
    # Detection only — never filters posts out. Powers the dashboard's region filter.
    for p in posts:
        p.region = detect_region(p)

    console.print(
        f"[dim]After smart filter: [green]{filter_stats['passed']} qualified[/]  "
        f"(removed {filter_stats['agency_authors']} agency authors · "
        f"{filter_stats['articles']} articles · "
        f"{filter_stats['job_posts']} job posts · "
        f"{filter_stats['agency_content']} agency content · "
        f"{filter_stats['thought_leadership']} thought leadership · "
        f"{filter_stats['no_intent']} no-intent)[/]\n"
    )

    if filter_stats.get("positive_included"):
        known = len(positive["author_urls"]) + len(positive["authors"]) + len(positive["companies"])
        console.print(
            f"[dim]Positive filter: [green]{filter_stats['positive_included']}[/] post(s) "
            f"from previously-relevant leads included with a ⭐ boost "
            f"({known} known-good signals on file)[/]\n"
        )

    if filter_stats.get("benchmark_boosted") or filter_stats.get("benchmark_rescued"):
        bench = positive.get("benchmark") or {}
        console.print(
            f"[dim]Content benchmark ({bench.get('doc_count', 0)} relevant posts learned): "
            f"[green]{filter_stats['benchmark_boosted']}[/] boosted 📈 · "
            f"[green]{filter_stats['benchmark_rescued']}[/] rescued on resemblance[/]\n"
        )

    # ── Negative list filter (posts the team previously marked irrelevant) ─────
    # Reads data/negative_list.json; auto-drops any post matching by URL or by
    # content hash (catches cross-posts of the same text under different URLs).
    negative = load_negative_list()
    if negative.get("urls") or negative.get("hashes"):
        posts, dropped = apply_negative_filter(posts, negative)
        if dropped:
            console.print(
                f"[dim]Negative list: removed [red]{dropped}[/] previously-rejected "
                f"post(s) ({len(negative['urls'])} URLs · {len(negative['hashes'])} "
                f"content hashes on file)[/]\n"
            )

    # ── Min score filter (positive-filter matches are exempt) ─────────────────
    if min_score > 0:
        posts = [p for p in posts
                 if p.intent_score >= min_score or getattr(p, "positive_match", False)]

    # ── AI verifier (Gemini Flash semantic precision backstop) ─────────────────
    # Runs AFTER every regex gate so it only judges true candidates (cheap).
    # Reads GOOGLE_API_KEY from .env; auto-skips (passes posts through) when no
    # key is set or VERIFIER_ENABLED=false. Drop --no-verify on the CLI to skip.
    if verify:
        from config.settings import VERIFIER
        from agent.verifier import verify_posts
        pre_count = len(posts)
        posts, vstats = verify_posts(
            posts,
            api_key=VERIFIER["API_KEY"],
            model=VERIFIER["MODEL"],
            batch_size=VERIFIER["BATCH_SIZE"],
            min_confidence=VERIFIER["MIN_CONFIDENCE"],
            max_posts=VERIFIER["MAX_POSTS"],
            enabled=VERIFIER["ENABLED"],
            progress_callback=progress_callback,
        )
        if vstats["verified"] + vstats["cached"] > 0 or vstats["skipped"] > 0:
            if vstats["skipped"] and not vstats["verified"]:
                console.print(
                    f"[dim]AI verifier: skipped ({_skip_reason(vstats, VERIFIER)}) "
                    f"— regex-filtered leads passed through[/]\n"
                )
            else:
                console.print(
                    f"[dim]AI verifier ({VERIFIER['MODEL']}): "
                    f"[green]{vstats['relevant']}[/] relevant · "
                    f"[red]{vstats['rejected']}[/] rejected · "
                    f"{vstats['cached']} cached · "
                    f"{vstats['skipped']} skipped "
                    f"(~{int(vstats['ms_per_post'])}ms/post · {vstats['batches']} batch(es))[/]\n"
                )
                
    # ── Apollo Enrichment ──────────────────────────────────────────────────────
    from agent.apollo import ApolloClient
    apollo = ApolloClient()
    if apollo.is_enabled() and posts:
        console.print(f"[dim]Apollo.io: Enriching contact & firmographics for {len(posts)} verified lead(s)…[/]")
        for idx, p in enumerate(posts, 1):
            company_name = p.company_hint
            if not company_name and p.entity_type == "brand":
                company_name = p.author_name
            
            # Match person
            person_data = apollo.match_person(p.author_name, p.author_url, company_name)
            if person_data:
                p.contact_email = person_data.get("email") or ""
                p.contact_phone = person_data.get("phone_number") or ""
                p.apollo_contact_id = person_data.get("id") or ""
                
                org = person_data.get("organization") or {}
                if org:
                    p.company_domain = org.get("primary_domain") or org.get("website") or ""
                    if not p.company_hint:
                        p.company_hint = org.get("name") or ""
            
            # If we have domain or company name, enrich organization
            if p.company_domain or company_name:
                org_data = apollo.enrich_organization(domain=p.company_domain, name=company_name)
                if org_data:
                    p.company_domain = org_data.get("primary_domain") or org_data.get("website") or p.company_domain
                    p.company_size = str(org_data.get("estimated_num_employees") or "")
                    p.company_tech_stack = org_data.get("technology_names") or []
                    
                    funding_events = org_data.get("funding_events") or []
                    if funding_events:
                        latest_funding = funding_events[0]
                        amt = latest_funding.get("amount") or ""
                        round_type = latest_funding.get("funding_round_type") or ""
                        p.company_funding = f"{round_type} {amt}".strip()
            
            # Search decision makers
            if p.company_domain:
                dms = apollo.search_decision_makers(p.company_domain)
                p.decision_makers = [{
                    "name": f"{dm.get('first_name', '')} {dm.get('last_name', '')}".strip(),
                    "title": dm.get("title") or "",
                    "email": dm.get("email") or "",
                    "linkedin_url": dm.get("linkedin_url") or "",
                    "id": dm.get("id") or ""
                } for dm in dms]

    # ── Sort ───────────────────────────────────────────────────────────────────
    posts.sort(key=lambda p: (p.intent_score, p.estimated_posted_at or datetime.min), reverse=True)


    # ── Terminal report ────────────────────────────────────────────────────────
    reporter.print_header(keywords, "all timelines" if all_timelines else timeline, len(posts))

    if posts:
        if all_timelines:
            _print_bucketed(posts, show_all)
        else:
            reporter.print_posts(posts if show_all else posts[:10])
            if not show_all and len(posts) > 10:
                console.print(f"[dim]… {len(posts) - 10} more. Use --show-all to display all.[/]\n")
        reporter.print_summary_table(posts)

    # ── Exports ────────────────────────────────────────────────────────────────
    raw_results_count = len(all_raw) if 'all_raw' in locals() else 0
    apify_cost_usd = raw_results_count * 0.0015
    pipeline_metadata = {
        "apify_raw_results": raw_results_count,
        "apify_cost_usd": apify_cost_usd
    }

    exported = []
    if "json" in export_formats or not export_formats:
        path = reporter.export_json(posts, output_dir, metadata=pipeline_metadata)
        exported.append(("JSON", path))
    if "csv" in export_formats:
        path = reporter.export_csv(posts, output_dir)
        exported.append(("CSV", path))
    if "html" in export_formats or not export_formats:
        label = service_label or ("All Services" if not keywords else ", ".join(keywords[:3]))
        path = reporter.export_html(posts, output_dir,
                                    keywords if len(keywords) <= 5 else [label],
                                    "all timelines" if all_timelines else timeline)
        exported.append(("HTML Dashboard", path))

    if exported:
        console.print("[bold green]Exports saved:[/]")
        for fmt, path in exported:
            console.print(f"  [green]✓[/] {fmt}: [blue underline]{os.path.abspath(path)}[/]")
        console.print()

    return posts


def _print_bucketed(posts, show_all: bool):
    """Print posts grouped by recency bucket."""
    buckets = bucket_posts(posts)
    for bucket_label, bucket_items in buckets.items():
        if not bucket_items:
            continue
        console.print(f"\n[bold yellow]━━━ {bucket_label} ({len(bucket_items)} posts) ━━━[/]\n")
        display = bucket_items if show_all else bucket_items[:5]
        reporter.print_posts(display)
        if not show_all and len(bucket_items) > 5:
            console.print(f"[dim]  … {len(bucket_items) - 5} more in this window. Use --show-all.[/]\n")


# ─────────────────────────────────────────────────────────────────────────────
# Interactive mode
# ─────────────────────────────────────────────────────────────────────────────

def interactive_mode():
    console.print("\n[bold blue]╔════════════════════════════════════════════╗[/]")
    console.print("[bold blue]║  LinkedIn Sales Pipeline — Grapesworldwide ║[/]")
    console.print("[bold blue]║  Agency Prospect Intelligence Engine       ║[/]")
    console.print("[bold blue]╚════════════════════════════════════════════╝[/]\n")

    api_key = os.getenv("APIFY_API_TOKEN") or Prompt.ask("[yellow]Enter your Apify API token[/]")
    if not api_key:
        console.print("[red]Apify API token required. Set APIFY_API_TOKEN in .env[/]")
        sys.exit(1)

    console.print("\n[bold]Mode:[/]")
    console.print("  1. Auto-keywords — scan all Grapesworldwide service keywords (recommended)")
    console.print("  2. Service-specific — pick one service")
    console.print("  3. Quick scan — broad scan across all services (30 keywords)")
    console.print("  4. Manual keywords — enter your own")
    mode = Prompt.ask("Choose", choices=["1", "2", "3", "4"], default="1")

    service_label = ""
    if mode == "1":
        keywords = get_all_keywords()
        service_label = "All 9 Services"
    elif mode == "2":
        services = get_service_list()
        console.print("\n[bold]Services:[/]")
        for i, s in enumerate(services, 1):
            console.print(f"  {i:02d}. {s}")
        choice = Prompt.ask("Choose (number)", default="1")
        idx = int(choice) - 1
        service_label = services[idx]
        keywords = get_keywords_for_service(service_label)
        console.print(f"[dim]Using {len(keywords)} keywords for {service_label}[/]")
    elif mode == "3":
        keywords = QUICK_SCAN_KEYWORDS
        service_label = "Quick Scan (All Services)"
        console.print(f"[dim]Using {len(keywords)} broad keywords for Quick Scan[/]")
    else:
        kw_input = Prompt.ask("[cyan]Enter keywords (comma-separated)[/]")
        keywords = [k.strip() for k in kw_input.split(",") if k.strip()]

    console.print("\n[bold]Timeline mode:[/]")
    console.print("  1. All timelines — scan 1 week, bucketed by Today / Yesterday / 2-3 days / This week")
    console.print("  2. Specific timeline — 1hr / 3hr / 1day / 2day / 3day / 1week")
    tl_mode = Prompt.ask("Choose", choices=["1", "2"], default="1")

    all_timelines = False
    timeline = "1week"
    if tl_mode == "1":
        all_timelines = True
    else:
        timeline = Prompt.ask("Timeline", choices=VALID_TIMELINES, default="1day")

    min_score_str = Prompt.ask("\n[dim]Minimum intent score (0=all, 7=high-intent only)[/]", default="5")
    min_score = int(min_score_str)

    console.print()
    run_pipeline(
        keywords=keywords,
        timeline=timeline,
        api_key=api_key,
        output_dir="outputs",
        export_formats=["json", "csv", "html"],
        show_all=False,
        min_score=min_score,
        all_timelines=all_timelines,
        service_label=service_label,
        verify=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="LinkedIn Sales Pipeline — Grapesworldwide Agency Prospect Intelligence",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full auto-scan across all 9 service keywords, all timelines:
  python main.py --auto-keywords --api-key YOUR_KEY

  # Single service:
  python main.py --auto-keywords --service "PR & Influencer Marketing" --api-key YOUR_KEY

  # Manual keywords, specific timeline:
  python main.py --keywords "branding agency" "ad film agency" --timeline 2day

  # High-intent only (score 7+):
  python main.py --auto-keywords --min-score 7 --export csv html

  # Interactive guided mode:
  python main.py
        """,
    )
    parser.add_argument("--auto-keywords", action="store_true",
                        help="Use Grapesworldwide's curated keyword library (all 9 services)")
    parser.add_argument("--quick-scan", action="store_true",
                        help="Quick scan for all Services using a curated list of broad keywords (max 30)")
    parser.add_argument("--service",
                        help="Restrict auto-keywords to one service (e.g. 'SEO', 'PR & Influencer Marketing')")
    parser.add_argument("--keywords", nargs="+",
                        help="Manual keywords (overrides --auto-keywords)")
    parser.add_argument("--timeline", choices=VALID_TIMELINES, default="1day",
                        help="Time window when NOT using --all-timelines (default: 1day)")
    parser.add_argument("--all-timelines", action="store_true",
                        help="Scan 1-week window and bucket results by Today/Yesterday/2-3 days/This week")
    parser.add_argument("--api-key", default=os.getenv("APIFY_API_TOKEN", ""),
                        help="Apify API token (or set APIFY_API_TOKEN in .env)")
    parser.add_argument("--competitors", nargs="+", default=[],
                        help="Competitor agency names to flag")
    parser.add_argument("--min-score", type=int, default=5,
                        help="Minimum intent score to display (default: 5, range 1-10)")
    parser.add_argument("--show-all", action="store_true",
                        help="Print all qualifying posts in detail (default: top 10 per bucket)")
    parser.add_argument("--export", nargs="+", choices=["json", "csv", "html"],
                        help="Export formats (default: json + html)")
    parser.add_argument("--output-dir", default="outputs",
                        help="Output directory (default: outputs/)")
    parser.add_argument("--list-keywords", action="store_true",
                        help="Print all auto-curated keywords and exit")
    parser.add_argument("--no-verify", action="store_true",
                        help="Skip the Gemini Flash AI verifier (regex-only, no API cost)")

    args = parser.parse_args()

    # --list-keywords: just show the keyword library and exit
    if args.list_keywords:
        _print_keyword_library()
        return

    # No args → interactive mode
    if not args.auto_keywords and not args.keywords and not args.quick_scan:
        interactive_mode()
        return

    api_key = args.api_key
    if not api_key:
        console.print("[red]Apify API token required. Pass --api-key or set APIFY_API_TOKEN in .env[/]")
        sys.exit(1)

    # Determine keywords
    if args.keywords:
        keywords = args.keywords
        service_label = ""
    elif args.quick_scan:
        keywords = QUICK_SCAN_KEYWORDS
        service_label = "Quick Scan (All Services)"
        console.print(f"[dim]Using {len(keywords)} broad keywords for Quick Scan[/]")
    elif args.service:
        keywords = get_keywords_for_service(args.service)
        service_label = args.service
        console.print(f"[dim]Using {len(keywords)} keywords for service: {service_label}[/]")
    else:
        keywords = get_all_keywords()
        service_label = "All 9 Grapesworldwide Services"
        console.print(f"[dim]Using {len(keywords)} auto-curated keywords across all services[/]")

    run_pipeline(
        keywords=keywords,
        timeline=args.timeline,
        api_key=api_key,
        competitors=args.competitors,
        output_dir=args.output_dir,
        export_formats=args.export or [],
        show_all=args.show_all,
        min_score=args.min_score,
        all_timelines=args.all_timelines,
        service_label=service_label,
        verify=not args.no_verify,
    )


def _print_keyword_library():
    """Pretty-print the curated keyword library."""
    console.print("\n[bold blue]Grapesworldwide — Auto-Curated Keyword Library[/]\n")

    table = Table(box=box.ROUNDED, border_style="blue", show_lines=True)
    table.add_column("Service", style="bold cyan", width=30)
    table.add_column("Keywords", width=70)

    for service, kws in GRAPES_KEYWORDS.items():
        table.add_row(service, "\n".join(f"• {k}" for k in kws))

    console.print(table)
    console.print(f"\n[dim]+ {len(UNIVERSAL_INTENT_KEYWORDS)} universal intent keywords[/]")
    console.print(f"[dim]Total: {len(get_all_keywords())} unique keywords[/]\n")


if __name__ == "__main__":
    main()

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

from agent.searcher import search_linkedin_posts, search_linkedin_posts_batch, search_all_timelines
from agent.parser import parse_result, is_within_timeline
from agent.scorer import score_post
from agent.filter import apply_smart_filter, is_agency_author
from agent.region import detect_region
from agent.triage import load_negative_list, apply_negative_filter, load_positive_signals
from agent import reporter
from config.keywords import (
    get_all_keywords, get_keywords_for_service, get_service_list,
    GRAPES_KEYWORDS, UNIVERSAL_INTENT_KEYWORDS, QUICK_SCAN_KEYWORDS,
)
from config.settings import TIMELINE_CONFIG, TIMELINE_BUCKETS
from config.sources import SOURCES, enabled_sources, source_budgets, SCAN_BUDGET_USD
from config.settings import APIFY_POST_PRICE

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
    sources: list[str] | None = None,
    budget_usd: float | None = None,
) -> list:
    os.makedirs(output_dir, exist_ok=True)
    sources = enabled_sources(sources)
    budget_usd = SCAN_BUDGET_USD if budget_usd is None else budget_usd
    budgets = source_budgets(sources, budget_usd)
    # $0.001 is charged per keyword that finds nothing — reserve it up front.
    post_items = int(max(budgets.get("linkedin_post", 0) - 0.001 * len(keywords), 0) / APIFY_POST_PRICE)
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
                  f" · [bold]{'all timelines (1 week window)' if all_timelines else timeline}[/][/]")
    console.print(f"[blue]Sources: [bold]{', '.join(SOURCES[s]['label'] for s in sources)}[/][/]")
    console.print(f"[blue]Apify budget: [bold]${budget_usd:.2f}[/] max · "
                  + " · ".join(f"{SOURCES[k]['label']} ${v:.2f}" for k, v in budgets.items() if v)
                  + (f" · LinkedIn posts ≤{post_items}" if "linkedin_post" in sources else "") + "[/]\n")

    # ── Other sources (jobs, ads, freelance, X, launches, funding) ─────────────
    # Started first and run in background threads while the LinkedIn post
    # search runs, so extra sources add little wall-clock time.
    from concurrent.futures import ThreadPoolExecutor
    from agent.collectors import ScanContext, run_collectors, merge_accounts
    other_sources = [s for s in sources if s != "linkedin_post"]
    hours = 168 if all_timelines else TIMELINE_CONFIG.get(timeline, {}).get("max_hours", 24)
    ctx = ScanContext(hours=hours, service=service_label, apify_token=api_key, budgets=budgets)
    done_sources: list[str] = []

    def _collector_log(msg: str):
        console.print(f"[dim]{msg}[/]")
        done_sources.append(msg)
        if progress_callback:
            try:
                progress_callback(len(done_sources), len(other_sources), 0, "collecting",
                                  status_note=msg.replace("[collector] ", "").strip())
            except Exception:
                pass

    pool = ThreadPoolExecutor(max_workers=1)
    collectors_future = pool.submit(run_collectors, other_sources, ctx, _collector_log)

    # ── Fetch ──────────────────────────────────────────────────────────────────
    all_raw: list[dict] = []

    if "linkedin_post" not in sources:
        console.print("  [dim]→ LinkedIn post search disabled for this scan[/]")
    elif all_timelines:
        console.print(f"  [dim]→ Running broadest scan (1 week) across all {len(keywords)} keywords…[/]")

        def _progress(batch_i, batch_total, items_so_far, status_note=""):
            if progress_callback:
                try:
                    progress_callback(batch_i, batch_total, items_so_far, "searching", status_note=status_note)
                except Exception:
                    pass
            console.print(f"  [dim]Batch {batch_i}/{batch_total} · {items_so_far} posts · {status_note}[/]")

        try:
            all_raw = search_all_timelines(keywords, api_key, progress=_progress,
                                           max_items_total=post_items)
            console.print(f"  [dim]Found {len(all_raw)} raw results[/]")
        except RuntimeError as e:
            console.print(f"  [red]Error: {e}[/]")
    else:
        console.print(f"  [dim]→ Running scan across {len(keywords)} keywords ({timeline})…[/]")

        def _progress(batch_i, batch_total, items_so_far, status_note=""):
            if progress_callback:
                try:
                    progress_callback(batch_i, batch_total, items_so_far, "searching", status_note=status_note)
                except Exception:
                    pass
            console.print(f"  [dim]Batch {batch_i}/{batch_total} · {items_so_far} posts · {status_note}[/]")

        try:
            all_raw = search_linkedin_posts_batch(keywords, timeline, api_key, progress=_progress,
                                                  max_items_total=post_items)
            console.print(f"  [dim]Found {len(all_raw)} raw results[/]")
        except RuntimeError as e:
            console.print(f"  [red]Error: {e}[/]")

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

    # ── Collect the other sources' results (they ran in parallel) ─────────────
    if other_sources:
        console.print(f"[dim]Waiting for {len(other_sources)} other source(s) to finish…[/]")
    collector_results = collectors_future.result()
    pool.shutdown(wait=False)
    source_stats: dict[str, dict] = {
        "linkedin_post": {"raw": len(all_raw), "candidates": len(posts),
                          "cost_usd": round(len(all_raw) * APIFY_POST_PRICE + 0.001 * len(keywords), 3),
                          "error": ""},
    } if "linkedin_post" in sources else {}
    seen_lead_urls = {p.url for p in posts}
    for r in collector_results:
        source_stats[r.source] = {"raw": r.raw_count, "candidates": len(r.posts),
                                  "cost_usd": round(r.cost_usd, 3), "error": r.error}
        for p in r.posts:
            if p.url and p.url in seen_lead_urls:
                continue
            seen_lead_urls.add(p.url)
            posts.append(p)

    explicit = [p for p in posts if p.intent_mode == "explicit"]
    signals = [p for p in posts if p.intent_mode == "signal"]

    # ── Timeline post-filter (explicit asks only — signal collectors already
    #    applied their own window; an ad's start date is not its freshness) ────
    if not all_timelines and timeline:
        explicit = [p for p in explicit if is_within_timeline(p, timeline)]

    # ── Score ──────────────────────────────────────────────────────────────────
    explicit = [score_post(p, competitors) for p in explicit]
    for p in signals:
        # Signal leads keep their collector score; pitch tags come from the source.
        if not p.pitch_services:
            p.pitch_services = list(dict.fromkeys(
                t for s in p.moment_signals for t in s.get("service_tags", [])))

    # ── Smart filter (job posts, agency promos, no-intent) ────────────────────
    # Positive signals (from leads the team marked relevant) let posts from
    # known-good authors/companies bypass the rejection gates with a ⭐ boost.
    positive = load_positive_signals()
    explicit, filter_stats = apply_smart_filter(explicit, positive=positive)

    # Signal leads have no "looking for an agency" text, so only the
    # agency/seller gate applies (a marketing agency hiring or running ads is
    # a competitor, not a prospect). The AI verifier does the rest.
    signal_agencies = [p for p in signals if p.entity_type == "brand" and is_agency_author(p)]
    signals = [p for p in signals if not (p.entity_type == "brand" and is_agency_author(p))]
    filter_stats["signal_agency_authors"] = len(signal_agencies)
    posts = explicit + signals

    # ── Region detection (inferred from post text + author headline) ───────────
    # Detection only — never filters posts out. Powers the dashboard's region filter.
    # Collectors that know the country (jobs, ads, freelance) set it already.
    for p in posts:
        p.region = p.region or detect_region(p)

    console.print(
        f"[dim]After smart filter: [green]{filter_stats['passed']} qualified[/]  "
        f"(removed {filter_stats['agency_authors']} agency authors · "
        f"{filter_stats['articles']} articles · "
        f"{filter_stats['job_posts']} job posts · "
        f"{filter_stats['agency_content']} agency content · "
        f"{filter_stats['thought_leadership']} thought leadership · "
        f"{filter_stats['no_intent']} no-intent)[/]"
    )
    if signals or signal_agencies:
        console.print(f"[dim]Signal leads (jobs/ads/freelance/launches/funding): "
                      f"[green]{len(signals)}[/] kept · {len(signal_agencies)} agency/seller removed[/]")
    console.print()

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
                
    # ── Cross-source account merge ─────────────────────────────────────────────
    # Same company hiring on LinkedIn AND running Meta ads → one hotter lead.
    posts, merged = merge_accounts(posts)
    if merged:
        console.print(f"[dim]Account merge: folded {merged} duplicate company signal(s) "
                      f"into multi-signal leads (+1 score)[/]\n")

    # ── Apollo Enrichment ──────────────────────────────────────────────────────
    from agent.apollo import ApolloClient
    apollo = ApolloClient()
    if apollo.is_enabled() and posts:
        # Highest-intent leads first; cap keeps Apollo credits bounded now that
        # several sources feed the pipeline.
        posts.sort(key=lambda p: p.intent_score, reverse=True)
        apollo_cap = int(os.getenv("APOLLO_MAX_LEADS", "200"))
        to_enrich = posts[:apollo_cap]
        console.print(f"[dim]Apollo.io: Enriching contact & firmographics for {len(to_enrich)} "
                      f"of {len(posts)} verified lead(s)…[/]")
        for idx, p in enumerate(to_enrich, 1):
            company_name = p.company_hint
            if not company_name and p.entity_type == "brand":
                company_name = p.author_name
            if p.intent_mode == "signal" and not (company_name or p.company_domain):
                continue                    # anonymous marketplace client — nothing to enrich

            # Match person (explicit asks only — a signal lead's "author" is a
            # company or an anonymous client, so the decision-maker search below
            # is what finds the person to contact)
            person_data = (apollo.match_person(p.author_name, p.author_url, company_name)
                           if p.intent_mode == "explicit" else None)
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
                    p.company_size = str(org_data.get("estimated_num_employees") or p.company_size or "")
                    p.company_tech_stack = org_data.get("technology_names") or []
                    
                    funding_events = org_data.get("funding_events") or []
                    if funding_events:
                        latest_funding = funding_events[0]
                        amt = latest_funding.get("amount") or ""
                        round_type = latest_funding.get("funding_round_type") or ""
                        p.company_funding = f"{round_type} {amt}".strip()
            
            # Key people (CEO/COO/CMO/Head of Marketing) are looked up on demand from the
            # dashboard card (agent/contacts.py), so scans don't spend Apollo/Apify credits on them.

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
    for key, st in source_stats.items():
        st["qualified"] = sum(1 for p in posts if p.source == key)
    raw_results_count = sum(st["raw"] for st in source_stats.values())
    apify_cost_usd = sum(st["cost_usd"] for st in source_stats.values())
    pipeline_metadata = {
        "apify_raw_results": raw_results_count,
        "apify_cost_usd": apify_cost_usd,
        "sources": source_stats,
    }
    _print_source_table(source_stats)

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


def _print_source_table(source_stats: dict):
    """Per-source yield: raw items → candidates → qualified leads, and cost."""
    if not source_stats:
        return
    table = Table(title="Leads by source", box=box.ROUNDED, border_style="blue")
    for col in ("Source", "Raw", "Candidates", "Qualified", "Cost (USD)", "Status"):
        table.add_column(col, justify="left" if col in ("Source", "Status") else "right")
    for key, st in source_stats.items():
        meta = SOURCES.get(key, {})
        table.add_row(f"{meta.get('icon', '')} {meta.get('label', key)}", str(st["raw"]),
                      str(st["candidates"]), f"[bold green]{st.get('qualified', 0)}[/]",
                      f"${st['cost_usd']:.2f}", f"[red]{st['error'][:60]}[/]" if st["error"] else "ok")
    table.add_row("[bold]Total[/]", str(sum(s["raw"] for s in source_stats.values())),
                  str(sum(s["candidates"] for s in source_stats.values())),
                  f"[bold green]{sum(s.get('qualified', 0) for s in source_stats.values())}[/]",
                  f"${sum(s['cost_usd'] for s in source_stats.values()):.2f}", "")
    console.print(table)
    console.print()


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
    parser.add_argument("--budget", type=float, default=None,
                        help=f"Max Apify spend for this scan in USD (default: SCAN_BUDGET_USD or ${SCAN_BUDGET_USD:.0f})")
    parser.add_argument("--sources", nargs="+", choices=list(SOURCES),
                        help="Lead sources to scan (default: LEAD_SOURCES in .env, else all). "
                             "e.g. --sources linkedin_post linkedin_job meta_ads")

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
        sources=args.sources,
        budget_usd=args.budget,
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

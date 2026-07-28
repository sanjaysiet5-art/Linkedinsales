import json
import csv
import os
import html as html_lib
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box
from agent.parser import LinkedInPost
from agent.region import REGIONS, region_flag, region_label

console = Console()


SCORE_COLOR = {
    range(9, 11): "bold red",
    range(7, 9):  "bold yellow",
    range(5, 7):  "green",
    range(1, 5):  "dim",
}

ENTITY_STYLE = {
    "brand":   ("🏢", "cyan"),
    "person":  ("👤", "magenta"),
    "article": ("📰", "blue"),
}


def _score_color(score: int) -> str:
    for r, color in SCORE_COLOR.items():
        if score in r:
            return color
    return "white"


def _short_snippet(text: str, max_len: int = 160) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len].rsplit(" ", 1)[0] + "…"


def print_header(keywords: list[str], timeline: str, total: int):
    lines = [
        f"[bold white]Keywords:[/]  [cyan]{', '.join(keywords)}[/]",
        f"[bold white]Timeline:[/]  [yellow]{timeline}[/]",
        f"[bold white]Posts found:[/] [green]{total}[/]",
        f"[bold white]Run at:[/]    [dim]{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}[/]",
    ]
    console.print(Panel("\n".join(lines), title="[bold blue]LinkedIn Sales Pipeline[/]",
                        subtitle="[dim]Powered by Apify · direct LinkedIn post search[/]",
                        border_style="blue", expand=False))
    console.print()


def print_posts(posts: list[LinkedInPost]):
    if not posts:
        console.print("[yellow]No posts found for the given keywords and timeline.[/]")
        return

    for i, post in enumerate(posts, 1):
        icon, entity_color = ENTITY_STYLE.get(post.entity_type, ("🔗", "white"))
        score_style = _score_color(post.intent_score)

        # Header line
        entity_label = post.entity_type.upper()
        name_display = post.author_name or "Unknown"
        if post.company_hint and post.company_hint != post.author_name:
            name_display += f" @ {post.company_hint}"

        header = Text()
        header.append(f"{icon} {entity_label} — ", style=entity_color)
        header.append(name_display, style=f"bold {entity_color}")
        header.append(f"   Score: {post.intent_score}/10", style=score_style)

        # Signals
        signal_text = ""
        if post.moment_signals:
            signal_parts = [f"{s['icon']} {s['label']}" for s in post.moment_signals[:3]]
            signal_text = "  |  ".join(signal_parts)

        # Build panel content
        content_lines = []

        snippet = _short_snippet(post.snippet)
        content_lines.append(f"[white]{snippet}[/]")
        content_lines.append("")

        meta_bits = []
        if post.timestamp_raw:
            meta_bits.append(f"⏱  {post.timestamp_raw}")
        engagement = post.likes + post.comments_count + post.shares
        if engagement:
            meta_bits.append(f"👍 {post.likes} · 💬 {post.comments_count} · 🔁 {post.shares}")
        if meta_bits:
            content_lines.append(f"[dim]{'   '.join(meta_bits)}[/]")
        if post.author_headline:
            content_lines.append(f"[dim]{post.author_headline[:80]}[/]")
        if signal_text:
            content_lines.append(f"[yellow]🎯 {signal_text}[/]")
        if post.pitch_services:
            services_str = "  ".join(f"[bold green]{s}[/]" for s in post.pitch_services)
            content_lines.append(f"[dim]Pitch:[/] {services_str}")
        content_lines.append(f"[blue underline]{post.url}[/]")

        border_color = "red" if post.intent_score >= 9 else (
            "yellow" if post.intent_score >= 7 else "dim"
        )

        console.print(Panel(
            "\n".join(content_lines),
            title=header,
            border_style=border_color,
            padding=(0, 1),
        ))

    console.print()


def print_summary_table(posts: list[LinkedInPost]):
    table = Table(
        title="Top Posts by Intent Score",
        box=box.ROUNDED,
        show_lines=True,
        border_style="blue",
    )
    table.add_column("#",             style="dim", width=4)
    table.add_column("Score",         style="bold", width=7)
    table.add_column("Type",          width=8)
    table.add_column("Author / Brand", width=26)
    table.add_column("Top Signal",    width=26)
    table.add_column("Pitch",         width=28, style="green")
    table.add_column("Engage",        width=10, style="dim")
    table.add_column("Time",          width=12, style="dim")
    table.add_column("URL",           width=44, style="blue")

    top = sorted(posts, key=lambda p: p.intent_score, reverse=True)[:20]
    for i, post in enumerate(top, 1):
        icon, _ = ENTITY_STYLE.get(post.entity_type, ("🔗", "white"))
        score_str = f"[{_score_color(post.intent_score)}]{post.intent_score}/10[/]"
        top_signal = post.moment_signals[0]["icon"] + " " + post.moment_signals[0]["label"] \
            if post.moment_signals else "—"
        pitch_str = " · ".join(post.pitch_services[:4]) if post.pitch_services else "—"
        table.add_row(
            str(i),
            score_str,
            f"{icon} {post.entity_type}",
            (post.author_name or "")[:24],
            top_signal[:24],
            pitch_str[:26],
            f"👍{post.likes} 💬{post.comments_count}",
            post.timestamp_raw[:10] or "—",
            post.url[:42],
        )
    console.print(table)
    console.print()


def export_json(posts: list[LinkedInPost], output_dir: str, filename: str = None, metadata: dict = None) -> str:
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    fname = filename or f"pipeline_{ts}.json"
    path = os.path.join(output_dir, fname)

    data = []
    for p in posts:
        data.append({
            "url": p.url,
            "title": p.title,
            "snippet": p.snippet,
            "author": p.author_name,
            "entity_type": p.entity_type,
            "company": p.company_hint,
            "timestamp_raw": p.timestamp_raw,
            "estimated_posted_at": p.estimated_posted_at.isoformat() if p.estimated_posted_at else None,
            "keywords_matched": p.keywords_matched,
            "intent_score": p.intent_score,
            "moment_signals": p.moment_signals,
            "pitch_services": p.pitch_services,
            "timeline": p.timeline,
            "author_url": p.author_url,
            "author_headline": p.author_headline,
            "likes": p.likes,
            "comments": p.comments_count,
            "shares": p.shares,
            "region": getattr(p, "region", "") or "",
            "ai_verdict": getattr(p, "ai_verdict", None),
            "contact_email": getattr(p, "contact_email", ""),
            "contact_phone": getattr(p, "contact_phone", ""),
            "company_domain": getattr(p, "company_domain", ""),
            "company_size": getattr(p, "company_size", ""),
            "company_funding": getattr(p, "company_funding", ""),
            "company_tech_stack": getattr(p, "company_tech_stack", []),
            "decision_makers": getattr(p, "decision_makers", []),
            "apollo_contact_id": getattr(p, "apollo_contact_id", ""),
        })


    output_data = {
        "metadata": metadata or {},
        "posts": data
    } if metadata is not None else data

    with open(path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    return path


def export_csv(posts: list[LinkedInPost], output_dir: str, filename: str = None) -> str:
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    fname = filename or f"pipeline_{ts}.csv"
    path = os.path.join(output_dir, fname)

    fieldnames = ["intent_score", "entity_type", "author", "author_headline", "author_url",
                  "company", "timestamp_raw", "likes", "comments", "shares",
                  "top_signal", "pitch_services", "keywords_matched", "url", "snippet", "region"]

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for p in sorted(posts, key=lambda x: x.intent_score, reverse=True):
            top_sig = p.moment_signals[0]["label"] if p.moment_signals else ""
            writer.writerow({
                "intent_score": p.intent_score,
                "entity_type": p.entity_type,
                "author": p.author_name,
                "author_headline": p.author_headline,
                "author_url": p.author_url,
                "company": p.company_hint,
                "timestamp_raw": p.timestamp_raw,
                "likes": p.likes,
                "comments": p.comments_count,
                "shares": p.shares,
                "top_signal": top_sig,
                "pitch_services": " | ".join(p.pitch_services),
                "keywords_matched": "; ".join(p.keywords_matched),
                "url": p.url,
                "snippet": p.snippet[:500],
                "region": getattr(p, "region", "") or "",
            })
    return path


def export_html(posts: list[LinkedInPost], output_dir: str, keywords: list[str],
                timeline: str, filename: str = None,
                persist_base_url: str | None = None) -> str:
    """
    Render the pipeline dashboard and write it to output_dir.

    Static mode (persist_base_url=None): a self-contained file the team opens
    directly via file://. No triage buttons, no Prospects/Negative tabs.

    Server mode (persist_base_url=""): buttons POST to relative /api/triage/...
    routes and the extra tabs are populated via /api/prospects & /api/negative.
    Pass "" (empty) for a same-origin local server, or a full base URL.
    """
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    fname = filename or f"pipeline_{ts}.html"
    path = os.path.join(output_dir, fname)
    html = render_html_string(posts, keywords=keywords, timeline=timeline,
                              persist_base_url=persist_base_url)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def render_html_string(posts: list[LinkedInPost], keywords: list[str],
                       timeline: str, persist_base_url: str | None = None,
                       triaged: dict | None = None) -> str:
    """
    Build the dashboard HTML as a string (no disk write).

    Static mode (persist_base_url=None): no triage buttons, no extra tabs —
    identical to the historical output the team is used to.

    Server mode (persist_base_url="" or a base URL): injects the triage
    actions row on every card + the Sales Prospects / Negative List tabs.

    triaged — optional {"prospect_urls": set, "negative_urls": set}. Cards for
    posts already triaged render their status instead of the buttons, so the
    team's marks survive a page reload.
    """
    server_mode = persist_base_url is not None
    api_base = persist_base_url if persist_base_url else ""
    prospect_urls = (triaged or {}).get("prospect_urls", set())
    negative_urls = (triaged or {}).get("negative_urls", set())

    sorted_posts = sorted(posts, key=lambda p: p.intent_score, reverse=True)

    def score_badge_color(score):
        if score >= 9: return "#ef4444"
        if score >= 7: return "#f59e0b"
        if score >= 5: return "#10b981"
        return "#6b7280"

    def entity_badge(etype):
        m = {"brand": ("🏢", "#06b6d4"), "person": ("👤", "#a855f7"), "article": ("📰", "#3b82f6")}
        return m.get(etype, ("🔗", "#6b7280"))

    # Service tag → pill colour
    SERVICE_COLORS = {
        "SEO":     "#10b981",
        "SEM":     "#f59e0b",
        "SMO":     "#8b5cf6",
        "PR":      "#3b82f6",
        "Brand":   "#ec4899",
        "Creative":"#f97316",
        "Media":   "#06b6d4",
        "Film":    "#ef4444",
    }

    cards_html = ""
    for idx, p in enumerate(sorted_posts):
        icon, color = entity_badge(p.entity_type)
        sc = score_badge_color(p.intent_score)
        sigs = " ".join(
            f'<span class="signal">{s["icon"]} {s["label"]}</span>'
            for s in p.moment_signals[:3]
        )
        pitch_pills = " ".join(
            f'<span class="pitch-pill" style="background:{SERVICE_COLORS.get(s, "#475569")}">{s}</span>'
            for s in p.pitch_services
        )
        snippet_escaped = p.snippet.replace("<", "&lt;").replace(">", "&gt;")
        kws = ", ".join(p.keywords_matched)
        service_data = " ".join(p.pitch_services).lower()
        author_html = p.author_name or 'Unknown'
        if p.author_url:
            author_html = f'<a href="{p.author_url}" target="_blank" style="color:inherit">{author_html}</a>'
        headline_escaped = (p.author_headline or "").replace("<", "&lt;").replace(">", "&gt;")
        region_key = getattr(p, "region", "") or ""
        region_badge = (
            f'<span class="region-tag">{region_flag(region_key)} {region_label(region_key)}</span>'
            if region_key else '<span class="region-tag unmapped">❓ Unmapped</span>'
        )
        # Compact payload for the triage POST body (HTML-attribute safe).
        payload = json.dumps({
            "url": p.url,
            "title": p.title,
            "author": p.author_name,
            "author_url": p.author_url,
            "author_headline": p.author_headline,
            "company": p.company_hint,
            "entity_type": p.entity_type,
            "snippet": p.snippet,
            "intent_score": p.intent_score,
            "region": region_key,
            "pitch_services": p.pitch_services,
            "moment_signals": p.moment_signals,
        })
        payload_attr = html_lib.escape(payload, quote=True)
        # Triage actions row — only rendered in server mode. Posts already
        # triaged show their persisted status instead of the buttons.
        actions_row = ""
        if server_mode:
            if p.url and p.url in prospect_urls:
                actions_row = f"""
          <div class="triage-actions" id="triage-{idx}">
            <div class="triage-status ok-relevant">✓ In Sales Prospects</div>
          </div>"""
            elif p.url and p.url in negative_urls:
                actions_row = f"""
          <div class="triage-actions" id="triage-{idx}">
            <div class="triage-status ok-negative">✗ Sent to Negative List</div>
          </div>"""
            else:
                actions_row = f"""
          <div class="triage-actions" id="triage-{idx}">
            <button class="triage-btn relevant" onclick="triage('relevant', {idx})">✅ Mark Relevant</button>
            <button class="triage-btn negative" onclick="triage('negative', {idx})">❌ Mark Negative</button>
          </div>"""
          
        # Apollo section variables
        email = getattr(p, "contact_email", "")
        phone = getattr(p, "contact_phone", "")
        domain = getattr(p, "company_domain", "")
        size = getattr(p, "company_size", "")
        funding = getattr(p, "company_funding", "")
        tech_stack = getattr(p, "company_tech_stack", [])
        dms = getattr(p, "decision_makers", [])
        contact_id = getattr(p, "apollo_contact_id", "")
        
        apollo_contact_html = ""
        if email or phone:
            apollo_contact_html = f"""
            <div class="apollo-contact-info">
              {f'<span class="apollo-email" onclick="revealContact(this, \'{email}\')" style="cursor:pointer; color:var(--accent); font-weight: 500;">📧 Click to reveal Email</span>' if email else ''}
              {f'<span class="apollo-phone">📞 {phone}</span>' if phone else ''}
            </div>
            """
            
        apollo_company_html = ""
        if domain or size or funding:
            apollo_company_html = f"""
            <div class="apollo-company-info">
              {f'<span>🌐 <strong>Domain:</strong> <a href="https://{domain}" target="_blank" style="color:var(--accent); text-decoration:none;">{domain}</a></span>' if domain else ''}
              {f'<span>👥 <strong>Size:</strong> {size} emp</span>' if size else ''}
              {f'<span>💰 <strong>Funding:</strong> {funding}</span>' if funding else ''}
            </div>
            """
            
        apollo_tech_html = ""
        if tech_stack:
            tech_badges = " ".join(f'<span class="tech-badge">{t}</span>' for t in tech_stack[:6])
            apollo_tech_html = f"""
            <div class="apollo-tech-stack">
              <span class="tech-label">Tech Stack:</span> {tech_badges}
            </div>
            """
            
        apollo_dms_html = ""
        if dms:
            dm_list = []
            for dm in dms:
                name_str = dm.get("name") or ""
                title_str = dm.get("title") or ""
                email_str = f"({dm.get('email')})" if dm.get("email") else "(No Email)"
                dm_list.append(f'<div class="dm-item"><strong>{name_str}</strong> - {title_str} {email_str}</div>')
            dm_items = "".join(dm_list)
            apollo_dms_html = f"""
            <div class="apollo-dms">
              <div class="dms-title" onclick="toggleDms({idx})" style="cursor:pointer; font-weight:600; color:var(--accent); font-size:12.5px; margin-top:8px;">👥 Decision-Makers ({len(dms)}) ▾</div>
              <div class="dms-list hidden" id="dms-list-{idx}">
                {dm_items}
              </div>
            </div>
            """

            
        apollo_seq_html = ""
        if email and server_mode:
            apollo_seq_html = f"""
            <div class="apollo-sequence-action" style="margin-top:10px; display:flex; gap:8px;">
              <select class="seq-select" id="seq-select-{idx}" style="padding: 4px 8px; border-radius: 6px; border: 1px solid var(--line-strong); font-size: 12px; flex-grow: 1;">
                <option value="">-- Enroll in Sequence --</option>
              </select>
              <button class="seq-btn triage-btn relevant" onclick="enrollSequence({idx}, \'{contact_id}\', \'{email}\', \'{p.author_name}\')" style="flex: 0; padding: 4px 10px; font-size: 12px; height: auto; border-radius: 6px;">Enroll</button>
            </div>
            """

        cards_html += f"""
        <div class="card" id="card-{idx}" data-score="{p.intent_score}" data-type="{p.entity_type}" data-services="{service_data}" data-region="{region_key}" data-payload="{payload_attr}">
          <div class="card-header">
            <div class="entity-badge" style="color:{color}">{icon} {p.entity_type.upper()}</div>
            <div class="author">{author_html}{' @ ' + p.company_hint if p.company_hint and p.company_hint != p.author_name else ''}</div>
            <div class="score-badge" style="background:{sc}">{p.intent_score}/10</div>
          </div>
          {f'<div class="headline">{headline_escaped[:100]}</div>' if headline_escaped else ''}
          <div class="snippet">{snippet_escaped[:400]}{'…' if len(p.snippet) > 400 else ''}</div>
          <div class="meta">
            <span class="time">⏱ {p.timestamp_raw or 'Unknown time'}</span>
            <span class="engage">👍 {p.likes} · 💬 {p.comments_count} · 🔁 {p.shares}</span>
            <span class="kw">🔑 {kws}</span>
          </div>
          {f'<div class="signals">{sigs}</div>' if sigs else ''}
          {f'<div class="pitch-row"><span class="pitch-label">Pitch:</span> {pitch_pills}</div>' if pitch_pills else ''}
          <div class="region-row">{region_badge}</div>
          {apollo_contact_html}
          {apollo_company_html}
          {apollo_tech_html}
          {apollo_dms_html}
          {apollo_seq_html}
          <a class="post-link" href="{p.url}" target="_blank">View LinkedIn Post →</a>
          {actions_row}
        </div>
        """


    brand_count  = sum(1 for p in posts if p.entity_type == "brand")
    person_count = sum(1 for p in posts if p.entity_type == "person")
    high_intent  = sum(1 for p in posts if p.intent_score >= 7)

    # ── Theme ────────────────────────────────────────────────────────────────
    # Kept in plain (non-f-string) blocks so CSS/JS braces stay literal and the
    # template below stays readable.
    CSS = """
    :root {
      --bg: #ffffff;
      --canvas: #f7f8fa;
      --ink: #0f172a;
      --ink-soft: #334155;
      --muted: #64748b;
      --faint: #94a3b8;
      --line: #eef1f5;
      --line-strong: #e2e8f0;
      --accent: #4f46e5;
      --accent-2: #8b5cf6;
      --accent-soft: #eef2ff;
      --shadow-sm: 0 1px 2px rgba(15,23,42,.04), 0 1px 3px rgba(15,23,42,.05);
      --shadow-lg: 0 18px 40px rgba(15,23,42,.09), 0 6px 12px rgba(15,23,42,.05);
      --radius: 14px;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Inter', sans-serif;
      background: var(--bg);
      color: var(--ink-soft);
      min-height: 100vh;
      padding: 44px 24px 72px;
      -webkit-font-smoothing: antialiased;
      letter-spacing: -.011em;
    }
    .wrap { max-width: 1320px; margin: 0 auto; }

    /* Header */
    .header { text-align: center; margin-bottom: 36px; }
    .eyebrow {
      display: inline-flex; align-items: center; gap: 8px;
      font-size: 11.5px; font-weight: 600; letter-spacing: .09em; text-transform: uppercase;
      color: var(--accent); background: var(--accent-soft);
      padding: 6px 14px; border-radius: 999px; margin-bottom: 18px;
    }
    .header h1 {
      font-size: 34px; font-weight: 700; color: var(--ink);
      letter-spacing: -.032em; margin-bottom: 12px;
    }
    .header .meta { color: var(--muted); font-size: 14px; }
    .header .meta strong { color: var(--ink-soft); font-weight: 600; }
    .header .meta .dot { color: #cbd5e1; margin: 0 12px; font-weight: 400; }

    /* Stats strip */
    .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 30px; }
    .stat {
      background: #fff; border: 1px solid var(--line); border-radius: var(--radius);
      padding: 22px 24px; box-shadow: var(--shadow-sm); position: relative; overflow: hidden;
    }
    .stat::before {
      content: ""; position: absolute; left: 0; top: 14px; bottom: 14px; width: 3px;
      background: linear-gradient(180deg, var(--accent), var(--accent-2)); border-radius: 3px;
    }
    .stat .num { font-size: 34px; font-weight: 700; color: var(--ink); letter-spacing: -.03em; line-height: 1; }
    .stat .lbl {
      font-size: 11.5px; color: var(--muted); margin-top: 9px;
      text-transform: uppercase; letter-spacing: .07em; font-weight: 600;
    }

    /* Filters */
    .filters {
      display: flex; gap: 9px; margin-bottom: 26px; flex-wrap: wrap;
      padding: 12px; background: var(--canvas); border: 1px solid var(--line);
      border-radius: var(--radius); align-items: center;
    }
    .filters .sep { flex: 1 1 auto; }
    .filter-btn {
      background: #fff; border: 1px solid var(--line-strong); color: var(--muted);
      padding: 8px 15px; border-radius: 999px; cursor: pointer;
      font-size: 13px; font-weight: 500; transition: all .18s ease;
    }
    .filter-btn:hover { border-color: var(--accent); color: var(--accent); }
    .filter-btn.active {
      background: var(--accent); border-color: var(--accent); color: #fff;
      box-shadow: 0 6px 14px rgba(79,70,229,.22);
    }

    /* Cards */
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(400px, 1fr)); gap: 18px; }
    .card {
      background: #fff; border: 1px solid var(--line); border-radius: var(--radius);
      padding: 20px; box-shadow: var(--shadow-sm);
      transition: transform .2s ease, box-shadow .2s ease, border-color .2s ease;
      display: flex; flex-direction: column;
    }
    .card:hover { transform: translateY(-3px); box-shadow: var(--shadow-lg); border-color: var(--line-strong); }
    .card[data-score="10"], .card[data-score="9"] { border-left: 3px solid #ef4444; }
    .card[data-score="8"], .card[data-score="7"] { border-left: 3px solid #f59e0b; }
    .card-header { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
    .entity-badge {
      font-size: 10.5px; font-weight: 700; text-transform: uppercase; letter-spacing: .06em;
      background: var(--canvas); border: 1px solid var(--line); padding: 4px 9px; border-radius: 7px;
    }
    .author { flex: 1; font-weight: 600; font-size: 14.5px; color: var(--ink); min-width: 0; }
    .author a { color: inherit; text-decoration: none; }
    .author a:hover { color: var(--accent); }
    .headline { font-size: 12.5px; color: var(--muted); margin-bottom: 8px; }
    .score-badge {
      color: #fff; padding: 4px 11px; border-radius: 999px;
      font-size: 12.5px; font-weight: 700; white-space: nowrap;
      box-shadow: 0 2px 6px rgba(15,23,42,.14);
    }
    .snippet { font-size: 14px; color: var(--ink-soft); line-height: 1.62; margin: 10px 0 12px; }
    .meta { display: flex; gap: 14px; font-size: 12px; color: var(--faint); margin: 6px 0 10px; flex-wrap: wrap; }
    .signals { display: flex; gap: 8px; flex-wrap: wrap; margin: 10px 0; }
    .signal {
      background: var(--accent-soft); color: var(--accent);
      padding: 4px 11px; border-radius: 999px; font-size: 12px; font-weight: 500;
    }
    .pitch-row { display: flex; align-items: center; gap: 8px; margin: 10px 0; flex-wrap: wrap; }
    .pitch-label {
      font-size: 10.5px; color: var(--faint); text-transform: uppercase;
      letter-spacing: .07em; font-weight: 600;
    }
    .pitch-pill { color: #fff; padding: 3px 10px; border-radius: 999px; font-size: 11px; font-weight: 600; letter-spacing: .02em; }
    .region-row { margin: 10px 0 4px; }
    .region-tag {
      display: inline-flex; align-items: center; gap: 4px;
      background: #f0fdf4; color: #15803d; border: 1px solid #bbf7d0;
      padding: 3px 11px; border-radius: 999px; font-size: 12px; font-weight: 600;
    }
    .region-tag.unmapped { background: #f8fafc; color: var(--faint); border-color: var(--line-strong); }
    .filters .region-group { display: inline-flex; gap: 9px; flex-wrap: wrap; align-items: center; }
    .filters .region-label {
      font-size: 10.5px; color: var(--faint); text-transform: uppercase;
      letter-spacing: .07em; font-weight: 600; margin-right: 2px;
    }
    .filter-btn.region-btn.region-active {
      background: #0f766e; border-color: #0f766e; color: #fff;
      box-shadow: 0 6px 14px rgba(15,118,110,.22);
    }
    .post-link {
      display: inline-flex; align-items: center; gap: 6px;
      margin-top: auto; padding-top: 14px;
      color: var(--accent); text-decoration: none;
      font-size: 13px; font-weight: 600; transition: gap .18s ease, color .18s ease;
    }
    .post-link:hover { gap: 10px; color: #4338ca; }

    /* Triage tabs + actions (server mode only) */
    .tabs { display: flex; gap: 8px; margin-bottom: 22px; flex-wrap: wrap; }
    .tab-btn {
      display: inline-flex; align-items: center; gap: 8px;
      background: #fff; border: 1px solid var(--line-strong); color: var(--muted);
      padding: 9px 18px; border-radius: 999px; cursor: pointer;
      font-size: 13.5px; font-weight: 600; transition: all .18s ease;
    }
    .tab-btn:hover { border-color: var(--accent); color: var(--accent); }
    .tab-btn.tab-active {
      background: var(--ink); border-color: var(--ink); color: #fff;
    }
    .tab-btn .count {
      background: rgba(15,23,42,.08); color: var(--ink); padding: 1px 8px;
      border-radius: 999px; font-size: 11.5px; font-weight: 700;
    }
    .tab-btn.tab-active .count { background: rgba(255,255,255,.18); color: #fff; }
    .tab-panel { display: none; }
    .tab-panel.tab-active { display: block; }

    .triage-actions { display: flex; gap: 8px; margin-top: 14px; padding-top: 14px;
                      border-top: 1px solid var(--line); }
    .triage-btn {
      flex: 1; padding: 9px 12px; border-radius: 9px; cursor: pointer;
      font-size: 12.5px; font-weight: 600; transition: all .15s ease; border: 1px solid transparent;
    }
    .triage-btn.relevant { background: #ecfdf5; color: #047857; border-color: #a7f3d0; }
    .triage-btn.relevant:hover { background: #10b981; color: #fff; border-color: #10b981; }
    .triage-btn.negative { background: #fef2f2; color: #b91c1c; border-color: #fecaca; }
    .triage-btn.negative:hover { background: #ef4444; color: #fff; border-color: #ef4444; }
    .triage-status {
      flex: 1; text-align: center; padding: 9px 12px; border-radius: 9px;
      font-size: 12.5px; font-weight: 600;
    }
    .triage-status.ok-relevant { background: #ecfdf5; color: #047857; }
    .triage-status.ok-negative { background: #fef2f2; color: #b91c1c; }
    .triage-status.pending { background: var(--canvas); color: var(--faint); }
    .triage-status.error { background: #fef3c7; color: #92400e; }

    .marked-at { font-size: 11.5px; color: var(--faint); margin-top: 4px; }
    .empty-state {
      text-align: center; padding: 60px 20px; color: var(--faint);
      background: var(--canvas); border: 1px dashed var(--line-strong);
      border-radius: var(--radius); font-size: 14px;
    }
    .prospect-meta {
      font-size: 11.5px; color: var(--faint); margin-top: 8px;
      display: flex; gap: 12px; flex-wrap: wrap; align-items: center;
    }
    .prospect-meta .score-mini {
      background: var(--accent-soft); color: var(--accent); padding: 2px 9px;
      border-radius: 999px; font-weight: 700;
    }
    .hidden { display: none !important; }

    /* Apollo CSS */
    .apollo-contact-info {
      display: flex;
      gap: 12px;
      font-size: 13px;
      margin: 8px 0;
      background: var(--accent-soft);
      padding: 6px 12px;
      border-radius: 8px;
      border: 1px solid var(--line-strong);
    }
    .apollo-company-info {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      font-size: 12px;
      margin: 8px 0;
      color: var(--ink-soft);
    }
    .apollo-tech-stack {
      margin: 8px 0;
      font-size: 12px;
    }
    .tech-label {
      font-weight: 600;
      color: var(--muted);
      margin-right: 6px;
    }
    .tech-badge {
      display: inline-block;
      background: var(--canvas);
      color: var(--ink-soft);
      padding: 2px 8px;
      border-radius: 6px;
      font-size: 11px;
      margin: 2px;
      border: 1px solid var(--line-strong);
    }
    .apollo-dms {
      margin-top: 8px;
      border-top: 1px dashed var(--line-strong);
      padding-top: 6px;
    }
    .dms-list {
      background: var(--canvas);
      padding: 8px;
      border-radius: 8px;
      margin-top: 6px;
      font-size: 11.5px;
      display: flex;
      flex-direction: column;
      gap: 4px;
    }
    .dm-item {
      padding: 4px 0;
      border-bottom: 1px solid var(--line);
    }
    .dm-item:last-child {
      border-bottom: none;
    }

    @media (max-width: 900px) { .stats { grid-template-columns: repeat(2, 1fr); } }
    @media (max-width: 600px) { .grid { grid-template-columns: 1fr; } .header h1 { font-size: 26px; } }

    """

    JS = """
    function revealContact(elem, email) {
      elem.innerText = "📧 " + email;
      elem.style.color = "var(--ink-soft)";
      elem.style.cursor = "default";
      elem.removeAttribute("onclick");
    }

    function toggleDms(idx) {
      const list = document.getElementById('dms-list-' + idx);
      if (list) {
        list.classList.toggle('hidden');
      }
    }

    async function loadSequences() {
      try {
        const base = (window.API_BASE || '') || '';
        const resp = await fetch(base + '/api/apollo/sequences');
        const seqs = await resp.json();
        const selects = document.querySelectorAll('.seq-select');
        selects.forEach(select => {
          seqs.forEach(seq => {
            const opt = document.createElement('option');
            opt.value = seq.id;
            opt.textContent = seq.name;
            select.appendChild(opt);
          });
        });
      } catch (e) {
        console.error('Failed to load sequences', e);
      }
    }

    async function enrollSequence(idx, contactId, email, name) {
      const select = document.getElementById('seq-select-' + idx);
      const seqId = select ? select.value : '';
      if (!seqId) {
        alert('Please select a sequence first.');
        return;
      }
      const btn = select.nextElementSibling;
      const originalText = btn.innerText;
      btn.innerText = 'Enrolling...';
      btn.disabled = true;
      try {
        const base = (window.API_BASE || '') || '';
        const resp = await fetch(base + '/api/apollo/enroll', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            contact_id: contactId,
            sequence_id: seqId,
            email: email,
            name: name
          })
        });
        const res = await resp.json();
        if (res.ok) {
          btn.innerText = 'Enrolled! ✓';
          btn.style.background = '#ecfdf5';
          btn.style.color = '#047857';
        } else {
          alert('Failed to enroll: ' + res.error);
          btn.innerText = originalText;
          btn.disabled = false;
        }
      } catch (e) {
        alert('Error enrolling in sequence: ' + e);
        btn.innerText = originalText;
        btn.disabled = false;
      }
    }

    document.addEventListener('DOMContentLoaded', () => {
      loadSequences();
    });

    // Two independent filter axes, AND-combined on every card.
    let activeCategory = 'all';

    let activeRegion = 'all';

    const entityFilters = ['ent-brand','ent-person','ent-article'];
    const serviceFilters = ['seo','sem','smo','pr','brand','creative','media','film'];

    function matchesCategory(card, type) {
      const services = (card.dataset.services || '').toLowerCase();
      return type === 'all'
        || (type === 'ent-brand'   && card.dataset.type === 'brand')
        || (type === 'ent-person'  && card.dataset.type === 'person')
        || (type === 'ent-article' && card.dataset.type === 'article')
        || (type === 'high'        && parseInt(card.dataset.score) >= 7)
        || (serviceFilters.includes(type) && services.includes(type));
    }

    function matchesRegion(card, type) {
      if (type === 'all') return true;
      const region = card.dataset.region || '';
      if (type === 'unmapped') return !region;
      return region === type;
    }

    function applyFilters() {
      document.querySelectorAll('.card').forEach(card => {
        const show = matchesCategory(card, activeCategory) && matchesRegion(card, activeRegion);
        card.classList.toggle('hidden', !show);
      });
    }

    function filterCards(type, btn) {
      activeCategory = type;
      document.querySelectorAll('.filters .filter-btn:not(.region-btn)').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      applyFilters();
    }

    function filterRegion(type, btn) {
      activeRegion = type;
      document.querySelectorAll('.region-btn').forEach(b => b.classList.remove('region-active'));
      btn.classList.add('region-active');
      applyFilters();
    }
    """

    # Triage + tab logic — only injected in server mode.
    TRIAGE_JS = """
    const API_BASE = "__API_BASE__";

    async function triage(kind, idx) {
      const card = document.getElementById('card-' + idx);
      const actions = document.getElementById('triage-' + idx);
      if (!card || !actions) return;
      const payload = JSON.parse(card.dataset.payload || '{}');

      actions.innerHTML = '<div class="triage-status pending">Saving…</div>';
      try {
        const resp = await fetch(API_BASE + '/api/triage/' + kind, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(payload),
        });
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const okClass = kind === 'relevant' ? 'ok-relevant' : 'ok-negative';
        const label = kind === 'relevant' ? '✓ In Sales Prospects' : '✗ Sent to Negative List';
        actions.innerHTML = '<div class="triage-status ' + okClass + '">' + label + '</div>';
        refreshTabCounts();
      } catch (e) {
        actions.innerHTML = '<div class="triage-status error">⚠ Save failed — retry</div>';
      }
    }

    function switchTab(name, btn) {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('tab-active'));
      btn.classList.add('tab-active');
      document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('tab-active'));
      document.getElementById('panel-' + name).classList.add('tab-active');
      if (name === 'prospects') loadProspects();
      if (name === 'negative')  loadNegative();
    }

    async function loadProspects() {
      const panel = document.getElementById('panel-prospects');
      try {
        const resp = await fetch(API_BASE + '/api/prospects');
        const items = await resp.json();
        if (!items.length) {
          panel.innerHTML = emptyState('No leads marked relevant yet. Click ✅ Mark Relevant on any lead.');
          return;
        }
        panel.innerHTML = '<div class="grid">' + items.map(prospectCard).join('') + '</div>';
      } catch (e) {
        panel.innerHTML = emptyState('Could not load prospects.');
      }
    }

    async function loadNegative() {
      const panel = document.getElementById('panel-negative');
      try {
        const resp = await fetch(API_BASE + '/api/negative');
        const items = await resp.json();
        if (!items.length) {
          panel.innerHTML = emptyState('No leads marked negative. Click ❌ Mark Negative to suppress repeats.');
          return;
        }
        panel.innerHTML = '<div class="grid">' + items.map(negativeCard).join('') + '</div>';
      } catch (e) {
        panel.innerHTML = emptyState('Could not load negative list.');
      }
    }

    async function refreshTabCounts() {
      try {
        const [pr, nr] = await Promise.all([
          fetch(API_BASE + '/api/prospects').then(r => r.json()),
          fetch(API_BASE + '/api/negative').then(r => r.json()),
        ]);
        document.getElementById('count-prospects').textContent = pr.length;
        document.getElementById('count-negative').textContent = nr.length;
      } catch (e) { /* counts are best-effort */ }
    }

    function prospectCard(p) {
      const snip = (p.snippet || '').slice(0, 280) + ((p.snippet || '').length > 280 ? '…' : '');
      const regionTag = p.region ? regionBadge(p.region) : '<span class="region-tag unmapped">❓ Unmapped</span>';
      return '<div class="card">'
        + '<div class="card-header"><div class="entity-badge">' + esc(p.entity_type || 'lead').toUpperCase() + '</div>'
        + '<div class="author">' + esc(p.author || 'Unknown') + '</div>'
        + '<div class="score-mini">' + (p.intent_score || 0) + '/10</div></div>'
        + '<div class="snippet">' + esc(snip) + '</div>'
        + '<div class="region-row">' + regionTag + '</div>'
        + '<div class="prospect-meta"><span>📅 Marked ' + esc(p.marked_at || '') + '</span>'
        + '<a class="post-link" href="' + esc(p.url || '#') + '" target="_blank">Open on LinkedIn →</a></div>'
        + '</div>';
    }

    function negativeCard(p) {
      const snip = (p.snippet || '').slice(0, 220) + ((p.snippet || '').length > 220 ? '…' : '');
      return '<div class="card" style="opacity:.82">'
        + '<div class="card-header"><div class="entity-badge">🚫 BLOCKED</div>'
        + '<div class="author">' + esc(p.author || 'Unknown') + '</div></div>'
        + '<div class="snippet">' + esc(snip) + '</div>'
        + '<div class="prospect-meta"><span>📅 Rejected ' + esc(p.marked_at || '') + '</span></div>'
        + '</div>';
    }

    function regionBadge(key) {
      const map = {india:['🇮🇳','India'], uae:['🇦🇪','Dubai / UAE'], saudi:['🇸🇦','Saudi Arabia'],
                   uk:['🇬🇧','United Kingdom'], us:['🇺🇸','United States'], europe:['🇪🇺','Europe']};
      const m = map[key] || ['❓','Unmapped'];
      return '<span class="region-tag">' + m[0] + ' ' + m[1] + '</span>';
    }

    function emptyState(msg) {
      return '<div class="empty-state">' + msg + '</div>';
    }
    function esc(s) {
      return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    }

    document.addEventListener('DOMContentLoaded', refreshTabCounts);
    """.replace("__API_BASE__", api_base)

    # Pre-render the tab bar (server mode only). In static mode, only the
    # Leads panel is shown and the tab bar is hidden.
    if server_mode:
        JS += "\n" + TRIAGE_JS

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LinkedIn Sales Pipeline — {', '.join(keywords)}</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  <div class="header">
    <div class="eyebrow">⚡ Sales Intelligence</div>
    <h1>LinkedIn Sales Pipeline</h1>
    <div class="meta">
      <span><strong>Keywords:</strong> {', '.join(keywords)}</span>
      <span class="dot">·</span>
      <span><strong>Timeline:</strong> {timeline}</span>
      <span class="dot">·</span>
      <span><strong>Generated:</strong> {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</span>
    </div>
  </div>

  <div class="stats">
    <div class="stat"><div class="num">{len(posts)}</div><div class="lbl">Total Posts</div></div>
    <div class="stat"><div class="num">{brand_count}</div><div class="lbl">Brand Posts</div></div>
    <div class="stat"><div class="num">{person_count}</div><div class="lbl">Person Posts</div></div>
    <div class="stat"><div class="num">{high_intent}</div><div class="lbl">High Intent · 7+</div></div>
  </div>

  <div class="filters">
    <button class="filter-btn active" onclick="filterCards('all', this)">All Posts</button>
    <button class="filter-btn" onclick="filterCards('ent-brand', this)">🏢 Brands</button>
    <button class="filter-btn" onclick="filterCards('ent-person', this)">👤 People</button>
    <button class="filter-btn" onclick="filterCards('high', this)">🚨 Score 7+</button>
    <span class="sep"></span>
    <button class="filter-btn" onclick="filterCards('seo', this)">🔍 SEO</button>
    <button class="filter-btn" onclick="filterCards('sem', this)">💸 SEM</button>
    <button class="filter-btn" onclick="filterCards('smo', this)">📲 SMO</button>
    <button class="filter-btn" onclick="filterCards('pr', this)">📰 PR</button>
    <button class="filter-btn" onclick="filterCards('brand', this)">🎨 Brand</button>
    <button class="filter-btn" onclick="filterCards('film', this)">🎬 Film</button>
    <button class="filter-btn" onclick="filterCards('creative', this)">✏️ Creative</button>
    <span class="sep"></span>
    <span class="region-group">
      <span class="region-label">Region</span>
      <button class="filter-btn region-btn region-active" onclick="filterRegion('all', this)">🌍 All</button>
      <button class="filter-btn region-btn" onclick="filterRegion('india', this)">🇮🇳 India</button>
      <button class="filter-btn region-btn" onclick="filterRegion('uae', this)">🇦🇪 Dubai/UAE</button>
      <button class="filter-btn region-btn" onclick="filterRegion('saudi', this)">🇸🇦 Saudi</button>
      <button class="filter-btn region-btn" onclick="filterRegion('uk', this)">🇬🇧 UK</button>
      <button class="filter-btn region-btn" onclick="filterRegion('us', this)">🇺🇸 US</button>
      <button class="filter-btn region-btn" onclick="filterRegion('europe', this)">🇪🇺 Europe</button>
      <button class="filter-btn region-btn" onclick="filterRegion('unmapped', this)">❓ Unmapped</button>
    </span>
  </div>

  {f'''<div class="tabs">
    <button class="tab-btn tab-active" onclick="switchTab('leads', this)">⚡ Today's Leads</button>
    <button class="tab-btn" onclick="switchTab('prospects', this)">✅ Sales Prospects <span class="count" id="count-prospects">0</span></button>
    <button class="tab-btn" onclick="switchTab('negative', this)">❌ Negative List <span class="count" id="count-negative">0</span></button>
  </div>''' if server_mode else ''}

  <div class="tab-panel tab-active" id="panel-leads">
    <div class="grid" id="grid">
{cards_html}
    </div>
  </div>
  {f'''<div class="tab-panel" id="panel-prospects"></div>
  <div class="tab-panel" id="panel-negative"></div>''' if server_mode else ''}
</div>

<script>{JS}</script>
</body>
</html>"""

    return html

#!/usr/bin/env python3
"""
Local dashboard server for the LinkedIn Sales Pipeline.

Workflow
  1. Serve + Triage + Run: python dashboard_server.py
  2. Open:                  http://localhost:5000
"""

from dotenv import load_dotenv
load_dotenv()

import argparse
import glob
import json
import os
import threading
import time

from flask import Flask, jsonify, request, Response

from agent.parser import LinkedInPost
from agent.region import detect_region
from agent import reporter
from agent.triage import (
    add_negative, add_sales_prospect,
    load_negative_list, load_sales_prospects, load_positive_signals,
    NEGATIVE_LIST_PATH, SALES_PROSPECTS_PATH,
)

app = Flask(__name__)

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")

# Global scan status
scan_status = {
    "status": "idle",  # "idle", "running", "error"
    "message": ""
}


# ─── Background Scan Thread ──────────────────────────────────────────────────
def bg_scan(mode, service, timeline, min_score, manual_keywords):
    global scan_status
    try:
        scan_status["status"] = "running"
        scan_status["message"] = "Initializing scan pipeline... (0%)"

        apify_key = os.getenv("APIFY_API_TOKEN")
        if not apify_key:
            raise ValueError("APIFY_API_TOKEN is not set in your .env file")

        # Resolve keywords and service label
        from config.keywords import get_all_keywords, get_keywords_for_service, QUICK_SCAN_KEYWORDS
        
        service_label = ""
        if mode == "1":
            keywords = get_all_keywords()
            service_label = "All Services"
        elif mode == "2":
            if not service:
                raise ValueError("Service selection is required for Service-Specific mode")
            keywords = get_keywords_for_service(service)
            service_label = service
        elif mode == "3":
            keywords = QUICK_SCAN_KEYWORDS
            service_label = "Quick Scan"
        elif mode == "4":
            if not manual_keywords:
                raise ValueError("Keywords list cannot be empty in Manual mode")
            keywords = [k.strip() for k in manual_keywords.split(",") if k.strip()]
        else:
            raise ValueError(f"Invalid mode value: {mode}")

        scan_status["message"] = f"Searching LinkedIn for {len(keywords)} keywords (Timeline: {timeline})... (5%)"

        def progress_callback(current, total, items_so_far, phase):
            global scan_status
            if phase == "searching":
                pct = 5 + int((current / total) * 70)  # search phase represents 5% to 75%
                scan_status["message"] = f"Searching LinkedIn (Batch {current}/{total}): {items_so_far} posts found so far... ({pct}%)"
            elif phase == "verifying":
                pct = 75 + int((current / total) * 20)  # verifying phase represents 75% to 95%
                scan_status["message"] = f"AI Verifier running (Batch {current}/{total})... ({pct}%)"

        from main import run_pipeline
        run_pipeline(
            keywords=keywords,
            timeline=timeline if timeline != "all" else "1week",
            api_key=apify_key,
            output_dir=OUTPUT_DIR,
            export_formats=["json", "csv", "html"],
            show_all=False,
            min_score=min_score,
            all_timelines=(timeline == "all"),
            service_label=service_label,
            verify=True,
            progress_callback=progress_callback
        )

        scan_status["status"] = "idle"
        scan_status["message"] = "Scan completed successfully!"
    except Exception as e:
        import traceback
        traceback.print_exc()
        scan_status["status"] = "error"
        scan_status["message"] = f"Scan failed: {str(e)}"


# ─── Latest run discovery ────────────────────────────────────────────────────
def _latest_pipeline_json() -> str | None:
    """Return the path to the most recently modified outputs/pipeline_*.json."""
    candidates = sorted(
        glob.glob(os.path.join(OUTPUT_DIR, "pipeline_*.json")),
        key=os.path.getmtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _load_posts_from_json(path: str) -> tuple[list[LinkedInPost], list[str], str, dict]:
    """Reconstruct LinkedInPost objects + the keywords/timeline from a run JSON."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    posts_data = data
    metadata = {}
    if isinstance(data, dict):
        posts_data = data.get("posts", [])
        metadata = data.get("metadata", {})

    posts: list[LinkedInPost] = []
    for d in posts_data:
        p = LinkedInPost(
            url=d.get("url", ""), title=d.get("title", ""), snippet=d.get("snippet", ""),
            author_name=d.get("author") or "Unknown", entity_type=d.get("entity_type", "person"),
            company_hint=d.get("company") or "", timestamp_raw=d.get("timestamp_raw") or "",
            estimated_posted_at=None,
            keywords_matched=d.get("keywords_matched", []),
            intent_score=d.get("intent_score", 0),
            moment_signals=d.get("moment_signals", []),
            pitch_services=d.get("pitch_services", []),
            author_url=d.get("author_url", ""),
            author_headline=d.get("author_headline", ""),
            likes=d.get("likes", 0), comments_count=d.get("comments", 0), shares=d.get("shares", 0),
        )
        p.region = d.get("region") or detect_region(p)
        p.contact_email = d.get("contact_email", "")
        p.contact_phone = d.get("contact_phone", "")
        p.company_domain = d.get("company_domain", "")
        p.company_size = d.get("company_size", "")
        p.company_funding = d.get("company_funding", "")
        p.company_tech_stack = d.get("company_tech_stack", [])
        p.decision_makers = d.get("decision_makers", [])
        p.apollo_contact_id = d.get("apollo_contact_id", "")
        posts.append(p)


    label = os.path.basename(path)
    return posts, [label], "all timelines", metadata


# ─── Routes ──────────────────────────────────────────────────────────────────
@app.route("/")
def index() -> Response:
    latest = _latest_pipeline_json()
    if not latest:
        # Render a template asking to start a scan
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>LinkedIn Sales Pipeline — New Scan</title>
<style>
  :root {{ --bg: #ffffff; --canvas: #f7f8fa; --ink: #0f172a; --ink-soft: #334155; --muted: #64748b; --accent: #4f46e5; --accent-soft: #eef2ff; --radius: 14px; --line: #eef1f5; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: var(--canvas); padding: 50px; text-align: center; color: var(--ink-soft); }}
  .card {{ background: #fff; max-width: 600px; margin: 0 auto; padding: 40px; border-radius: var(--radius); border: 1px solid var(--line); box-shadow: 0 4px 12px rgba(0,0,0,0.05); }}
  h2 {{ margin-bottom: 12px; color: var(--ink); }}
  p {{ color: var(--muted); margin-bottom: 24px; }}
  select, input {{ padding: 10px 14px; border-radius: 8px; border: 1px solid #ddd; margin-bottom: 16px; width: 100%; font-size: 14px; }}
  label {{ font-size: 12px; font-weight: 600; text-transform: uppercase; display: block; text-align: left; margin-bottom: 6px; color: var(--muted); }}
  button {{ background: var(--accent); color: white; border: none; padding: 12px 24px; border-radius: 8px; font-size: 15px; font-weight: 600; cursor: pointer; transition: background 0.2s; }}
  button:hover {{ background: #4338ca; }}
  .overlay {{ display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(15,23,42,0.7); backdrop-filter: blur(4px); justify-content: center; align-items: center; z-index: 9999; }}
  .overlay-content {{ background: white; padding: 40px; border-radius: var(--radius); text-align: center; max-width: 400px; width: 90%; }}
  .spinner {{ width: 40px; height: 40px; border: 4px solid #eee; border-top-color: var(--accent); border-radius: 50%; animation: spin 1s linear infinite; margin: 0 auto 20px; }}
  @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
</style>
</head>
<body>
<div class="card">
  <h2>Welcome to LinkedIn Sales Pipeline</h2>
  <p>No previous runs found. Please configure and start your first search scan below.</p>
  
  <div style="text-align: left;">
    <label>Scan Mode</label>
    <select id="scan-mode" onchange="toggleMode()">
      <option value="1">Auto-Keywords (All 9 Services)</option>
      <option value="2">Service-Specific</option>
      <option value="3">Quick Scan (Broad Keywords)</option>
      <option value="4">Manual Keywords</option>
    </select>
    
    <div id="div-service" style="display:none;">
      <label>Service Category</label>
      <select id="scan-service">
        <option value="Branding & Designing">Branding & Designing</option>
        <option value="AI/3D/CGI">AI/3D/CGI</option>
        <option value="Films & Campaigns">Films & Campaigns</option>
        <option value="Social Media & Content Strategy">Social Media & Content Strategy</option>
        <option value="Website Design & Development">Website Design & Development</option>
        <option value="SEO">SEO</option>
        <option value="Media Planning & Buying">Media Planning & Buying</option>
        <option value="PR & Influencer Marketing">PR & Influencer Marketing</option>
        <option value="Events & Activations">Events & Activations</option>
      </select>
    </div>
    
    <div id="div-manual" style="display:none;">
      <label>Manual Keywords (comma-separated)</label>
      <input type="text" id="scan-manual" placeholder="e.g. branding agency, seo marketing">
    </div>
    
    <label>Time Window</label>
    <select id="scan-timeline">
      <option value="1day">1 Day</option>
      <option value="3hr">3 Hours</option>
      <option value="1hr">1 Hour</option>
      <option value="2day">2 Days</option>
      <option value="3day">3 Days</option>
      <option value="1week">1 Week</option>
      <option value="all">All Timelines (1 Week Bucketed)</option>
    </select>
    
    <label>Minimum Intent Score</label>
    <select id="scan-score">
      <option value="5">5 (Default)</option>
      <option value="0">0 (All)</option>
      <option value="3">3</option>
      <option value="7">7 (High-Intent)</option>
    </select>
  </div>
  
  <button id="btn-start" onclick="trigger()">Start Scan 🚀</button>
</div>

<div class="overlay" id="overlay">
  <div class="overlay-content">
    <div class="spinner"></div>
    <h3>Running Pipeline Scan...</h3>
    <p id="status-msg">Please wait while we search LinkedIn and run AI verification.</p>
  </div>
</div>

<script>
  function toggleMode() {{
    const mode = document.getElementById('scan-mode').value;
    document.getElementById('div-service').style.display = (mode === '2') ? 'block' : 'none';
    document.getElementById('div-manual').style.display = (mode === '4') ? 'block' : 'none';
  }}
  
  function trigger() {{
    const mode = document.getElementById('scan-mode').value;
    const service = document.getElementById('scan-service').value;
    const timeline = document.getElementById('scan-timeline').value;
    const min_score = document.getElementById('scan-score').value;
    const manual_keywords = document.getElementById('scan-manual').value;
    
    document.getElementById('btn-start').disabled = true;
    document.getElementById('overlay').style.display = 'flex';
    
    fetch('/api/scan', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ mode, service, timeline, min_score, manual_keywords }})
    }})
    .then(res => res.json())
    .then(data => {{
      if (data.ok) {{
        poll();
      }} else {{
        alert('Failed: ' + data.error);
        document.getElementById('btn-start').disabled = false;
        document.getElementById('overlay').style.display = 'none';
      }}
    }});
  }}
  
  function poll() {{
    setInterval(() => {{
      fetch('/api/scan/status')
      .then(res => res.json())
      .then(data => {{
        if (data.status === 'running') {{
          document.getElementById('status-msg').innerText = data.message;
        }} else if (data.status === 'idle') {{
          location.reload();
        }} else if (data.status === 'error') {{
          alert('Error: ' + data.message);
          location.reload();
        }}
      }});
    }}, 2000);
  }}
</script>
</body>
</html>"""
        return Response(html, mimetype="text/html")

    posts, keywords, timeline, metadata = _load_posts_from_json(latest)

    prospect_urls = {i.get("url") for i in load_sales_prospects() if i.get("url")}
    negative_urls = {i.get("url") for i in _load_list_raw(NEGATIVE_LIST_PATH) if i.get("url")}

    # Exclude already triaged leads from "Today's Leads"
    filtered_posts = [p for p in posts if p.url not in prospect_urls and p.url not in negative_urls]

    triaged = {
        "prospect_urls": prospect_urls,
        "negative_urls": negative_urls,
    }

    html = reporter.render_html_string(
        filtered_posts, keywords=keywords, timeline=timeline, persist_base_url="",
        triaged=triaged,
    )

    # Inject cost info at the top header
    cost_val = metadata.get("apify_cost_usd", 0.0)
    raw_val = metadata.get("apify_raw_results", 0)
    cost_html = f'<span><strong>Apify Cost:</strong> ${cost_val:.3f} ({raw_val} results)</span><span class="dot">·</span><span><strong>Generated:</strong>'
    html = html.replace('<span><strong>Generated:</strong>', cost_html, 1)

    # ─── INJECT CONTROL PANEL HTML & JS & CSS ─────────────────────────────────
    control_panel_html = """
  <div class="scan-card">
    <div class="scan-card-header">
      <h3>Run New Scan 🚀</h3>
      <span class="scan-status-badge idle" id="scan-status-text">Ready</span>
    </div>
    
    <div class="scan-form">
      <div class="form-group">
        <label for="scan-mode">Mode</label>
        <select id="scan-mode" onchange="toggleModeFields()">
          <option value="1">Auto-Keywords (All 9 Services)</option>
          <option value="2">Service-Specific</option>
          <option value="3">Quick Scan (Broad Keywords)</option>
          <option value="4">Manual Keywords</option>
        </select>
      </div>
      
      <div class="form-group" id="group-service" style="display:none;">
        <label for="scan-service">Service</label>
        <select id="scan-service">
          <option value="Branding & Designing">Branding & Designing</option>
          <option value="AI/3D/CGI">AI/3D/CGI</option>
          <option value="Films & Campaigns">Films & Campaigns</option>
          <option value="Social Media & Content Strategy">Social Media & Content Strategy</option>
          <option value="Website Design & Development">Website Design & Development</option>
          <option value="SEO">SEO</option>
          <option value="Media Planning & Buying">Media Planning & Buying</option>
          <option value="PR & Influencer Marketing">PR & Influencer Marketing</option>
          <option value="Events & Activations">Events & Activations</option>
        </select>
      </div>
      
      <div class="form-group" id="group-manual" style="display:none; flex-grow: 1;">
        <label for="scan-manual">Keywords (comma-separated)</label>
        <input type="text" id="scan-manual" placeholder="e.g. branding agency, seo marketing">
      </div>
      
      <div class="form-group">
        <label for="scan-timeline">Timeline</label>
        <select id="scan-timeline">
          <option value="1day">1 Day</option>
          <option value="3hr">3 Hours</option>
          <option value="1hr">1 Hour</option>
          <option value="2day">2 Days</option>
          <option value="3day">3 Days</option>
          <option value="1week">1 Week</option>
          <option value="all">All Timelines (1 Week Bucketed)</option>
        </select>
      </div>
      
      <div class="form-group">
        <label for="scan-score">Min Score (0-10)</label>
        <select id="scan-score">
          <option value="5">5 (Default)</option>
          <option value="0">0 (All)</option>
          <option value="3">3</option>
          <option value="7">7 (High-Intent)</option>
        </select>
      </div>
      
      <button class="scan-submit-btn" id="start-scan-btn" onclick="triggerScan()">Start Scan</button>
    </div>
  </div>

  <div class="overlay" id="loading-overlay">
    <div class="overlay-content">
      <div class="spinner"></div>
      <h3 id="overlay-title">Scanning LinkedIn...</h3>
      <p id="overlay-msg">Please wait while the pipeline runs.</p>
    </div>
  </div>
    """

    control_panel_css = """
    /* Scan Card Styling */
    .scan-card {
      background: #fff;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 20px 24px;
      box-shadow: var(--shadow-sm);
      margin-bottom: 26px;
    }
    .scan-card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 16px;
      border-bottom: 1px solid var(--line);
      padding-bottom: 10px;
    }
    .scan-card-header h3 {
      font-size: 16px;
      font-weight: 700;
      color: var(--ink);
    }
    .scan-status-badge {
      font-size: 11px;
      font-weight: 600;
      padding: 4px 10px;
      border-radius: 99px;
      text-transform: uppercase;
      letter-spacing: .05em;
    }
    .scan-status-badge.idle {
      background: var(--accent-soft);
      color: var(--accent);
    }
    .scan-status-badge.running {
      background: #fef3c7;
      color: #d97706;
      animation: pulse 1.5s infinite;
    }
    .scan-status-badge.error {
      background: #fee2e2;
      color: #dc2626;
    }
    @keyframes pulse {
      0% { opacity: 0.6; }
      50% { opacity: 1; }
      100% { opacity: 0.6; }
    }
    .scan-form {
      display: flex;
      gap: 16px;
      align-items: flex-end;
      flex-wrap: wrap;
    }
    .form-group {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .form-group label {
      font-size: 11px;
      font-weight: 600;
      text-transform: uppercase;
      color: var(--muted);
      letter-spacing: .05em;
    }
    .form-group select, .form-group input {
      padding: 8px 12px;
      border-radius: 8px;
      border: 1px solid var(--line-strong);
      font-family: inherit;
      font-size: 13.5px;
      color: var(--ink-soft);
      outline: none;
      background: #fff;
      min-width: 150px;
    }
    .form-group input {
      width: 100%;
    }
    .form-group select:focus, .form-group input:focus {
      border-color: var(--accent);
    }
    .scan-submit-btn {
      background: var(--accent);
      color: #fff;
      border: none;
      padding: 10px 20px;
      border-radius: 8px;
      font-weight: 600;
      cursor: pointer;
      font-size: 13.5px;
      transition: all 0.2s;
      height: 38px;
    }
    .scan-submit-btn:hover {
      background: var(--accent-2);
    }
    /* Loading Overlay */
    .overlay {
      display: none;
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      bottom: 0;
      background: rgba(15, 23, 42, 0.7);
      backdrop-filter: blur(4px);
      z-index: 99999;
      justify-content: center;
      align-items: center;
    }
    .overlay-content {
      background: #fff;
      padding: 40px;
      border-radius: var(--radius);
      text-align: center;
      max-width: 450px;
      width: 90%;
      box-shadow: var(--shadow-lg);
    }
    .spinner {
      width: 50px;
      height: 50px;
      border: 4px solid var(--line-strong);
      border-top-color: var(--accent);
      border-radius: 50%;
      animation: spin 1s linear infinite;
      margin: 0 auto 20px;
    }
    @keyframes spin {
      to { transform: rotate(360deg); }
    }
    .overlay-content h3 {
      font-size: 20px;
      color: var(--ink);
      margin-bottom: 10px;
    }
    .overlay-content p {
      color: var(--muted);
      font-size: 14px;
    }
    .draft-container {
      background: var(--canvas);
      border-radius: var(--radius);
      padding: 16px;
      margin-top: 15px;
      border: 1px solid var(--line-strong);
      text-align: left;
    }
    .draft-section {
      margin-bottom: 12px;
    }
    .draft-section:last-child {
      margin-bottom: 0;
    }
    .draft-section label {
      font-size: 10px;
      font-weight: 700;
      text-transform: uppercase;
      color: var(--muted);
      display: block;
      margin-bottom: 4px;
      letter-spacing: .05em;
    }
    .draft-section textarea {
      width: 100%;
      border-radius: 8px;
      border: 1px solid var(--line-strong);
      padding: 8px 12px;
      font-size: 12px;
      font-family: inherit;
      color: var(--ink-soft);
      resize: vertical;
      background: #fff;
      outline: none;
    }
    .draft-section textarea:focus {
      border-color: var(--accent);
    }
    .copy-btn {
      background: #fff;
      border: 1px solid var(--line-strong);
      padding: 4px 8px;
      border-radius: 6px;
      font-size: 11px;
      cursor: pointer;
      margin-top: 4px;
      font-weight: 600;
      color: var(--ink-soft);
      display: inline-flex;
      align-items: center;
      gap: 4px;
      transition: all 0.2s;
    }
    .copy-btn:hover {
      background: var(--canvas);
      border-color: var(--muted);
    }
    """

    control_panel_js = """
    function toggleModeFields() {
      const mode = document.getElementById('scan-mode').value;
      document.getElementById('group-service').style.display = (mode === '2') ? 'block' : 'none';
      document.getElementById('group-manual').style.display = (mode === '4') ? 'block' : 'none';
    }

    function triggerScan() {
      const mode = document.getElementById('scan-mode').value;
      const service = document.getElementById('scan-service').value;
      const timeline = document.getElementById('scan-timeline').value;
      const min_score = document.getElementById('scan-score').value;
      const manual_keywords = document.getElementById('scan-manual').value;
      
      const btn = document.getElementById('start-scan-btn');
      btn.disabled = true;
      btn.innerText = 'Starting...';
      
      fetch('/api/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode, service, timeline, min_score, manual_keywords })
      })
      .then(res => res.json())
      .then(data => {
        if (data.ok) {
          pollScanStatus();
        } else {
          alert('Error starting scan: ' + data.error);
          btn.disabled = false;
          btn.innerText = 'Start Scan';
        }
      })
      .catch(err => {
        alert('Request failed: ' + err);
        btn.disabled = false;
        btn.innerText = 'Start Scan';
      });
    }

    function pollScanStatus() {
      const overlay = document.getElementById('loading-overlay');
      const overlayTitle = document.getElementById('overlay-title');
      const overlayMsg = document.getElementById('overlay-msg');
      const badge = document.getElementById('scan-status-text');
      
      overlay.style.display = 'flex';
      
      const timer = setInterval(() => {
        fetch('/api/scan/status')
        .then(res => res.json())
        .then(status => {
          badge.innerText = status.status.toUpperCase();
          badge.className = 'scan-status-badge ' + status.status;
          
          if (status.status === 'running') {
            overlayMsg.innerText = status.message || 'Please wait while the pipeline runs.';
          } else {
            clearInterval(timer);
            overlay.style.display = 'none';
            if (status.status === 'idle') {
              location.reload();
            } else if (status.status === 'error') {
              alert('Scan failed: ' + status.message);
              const btn = document.getElementById('start-scan-btn');
              if (btn) {
                btn.disabled = false;
                btn.innerText = 'Start Scan';
              }
            }
          }
        })
        .catch(err => {
          console.error('Error polling status:', err);
        });
      }, 2000);
    }

    // Initial status check in case a scan is already running on page load
    document.addEventListener('DOMContentLoaded', () => {
      fetch('/api/scan/status')
      .then(res => res.json())
      .then(status => {
        if (status.status === 'running') {
          pollScanStatus();
        }
      });
    });

    async function loadProspects() {
      const panel = document.getElementById('panel-prospects');
      try {
        const resp = await fetch(API_BASE + '/api/prospects');
        const items = await resp.json();
        if (!items.length) {
          panel.innerHTML = emptyState('No leads marked relevant yet. Click ✅ Mark Relevant on any lead.');
          return;
        }
        panel.innerHTML = `
          <div style="margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center; background: #fff; border: 1px solid var(--line); padding: 15px 20px; border-radius: var(--radius); box-shadow: var(--shadow-sm);">
            <h4 style="font-size: 16px; font-weight: 700; color: var(--ink); margin: 0;">Saved Sales Prospects</h4>
            <button onclick="downloadProspectsCSV()" class="scan-submit-btn" style="height: 36px; padding: 0 16px; display: inline-flex; align-items: center; gap: 8px;">
              <span>📥 Export CSV Table</span>
            </button>
          </div>
          <div class="grid">${items.map(prospectCard).join('')}</div>
        `;
      } catch (e) {
        panel.innerHTML = emptyState('Could not load prospects.');
      }
    }

    function downloadProspectsCSV() {
      fetch(API_BASE + '/api/prospects')
      .then(res => res.json())
      .then(data => {
        if (!data.length) {
          alert('No prospects to export.');
          return;
        }
        const headers = ['intent_score', 'author', 'author_headline', 'author_url', 'company', 'url', 'snippet', 'region', 'pitch_services', 'marked_at'];
        let csvContent = headers.join(',') + '\\n';
        
        data.forEach(row => {
          let values = headers.map(header => {
            let val = row[header] || '';
            if (Array.isArray(val)) val = val.join(' | ');
            val = String(val).replace(/"/g, '""');
            return `"${val}"`;
          });
          csvContent += values.join(',') + '\\n';
        });
        
        const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
        const link = document.createElement('a');
        const url = URL.createObjectURL(blob);
        link.setAttribute('href', url);
        link.setAttribute('download', 'sales_prospects_' + new Date().toISOString().slice(0,10) + '.csv');
        link.style.visibility = 'hidden';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
      });
    }

    function prospectCard(p) {
      const snip = (p.snippet || '').slice(0, 280) + ((p.snippet || '').length > 280 ? '…' : '');
      const regionTag = p.region ? regionBadge(p.region) : '<span class="region-tag unmapped">❓ Unmapped</span>';
      const containerId = 'draft-' + p.url.replace(/[^a-zA-Z0-9]/g, '');
      
      return '<div class="card">'
        + '<div class="card-header"><div class="entity-badge">' + esc(p.entity_type || 'lead').toUpperCase() + '</div>'
        + '<div class="author">' + esc(p.author || 'Unknown') + '</div>'
        + '<div class="score-mini">' + (p.intent_score || 0) + '/10</div></div>'
        + '<div class="snippet">' + esc(snip) + '</div>'
        + '<div class="region-row">' + regionTag + '</div>'
        + '<div class="prospect-meta"><span>📅 Marked ' + esc(p.marked_at || '') + '</span>'
        + '<a class="post-link" href="' + esc(p.url || '#') + '" target="_blank">Open on LinkedIn →</a></div>'
        + '<button onclick="draftOutreach(`' + p.url + '`, this)" class="scan-submit-btn" style="height:32px; font-size:12px; padding:0 12px; margin-top:10px; width:100%; justify-content:center; display:flex; align-items:center;">Outreach Drafts ✉️</button>'
        + '<div class="draft-container" id="' + containerId + '" style="display:none;"></div>'
        + '</div>';
    }

    async function draftOutreach(url, btn) {
      const containerId = 'draft-' + url.replace(/[^a-zA-Z0-9]/g, '');
      let container = document.getElementById(containerId);
      
      if (container.style.display === 'block') {
        container.style.display = 'none';
        btn.innerText = 'Outreach Drafts ✉️';
        return;
      }
      
      if (container.innerHTML !== '') {
        container.style.display = 'block';
        btn.innerText = 'Hide Drafts ✕';
        return;
      }
      
      btn.disabled = true;
      btn.innerText = 'Drafting...';
      
      try {
        const resp = await fetch('/api/drafts', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url })
        });
        const res = await resp.json();
        
        if (!res.ok) throw new Error(res.error);
        
        const drafts = res.drafts;
        container.innerHTML = `
          <div class="draft-section" style="margin-top:10px;">
            <label>Email Pitch</label>
            <textarea id="email-subject-${containerId}" style="min-height:35px; font-weight:bold; margin-bottom:5px;" readonly>Subject: ${drafts.email_subject}</textarea>
            <textarea id="email-body-${containerId}" style="min-height:120px;" readonly>${drafts.email_body}</textarea>
            <button class="copy-btn" onclick="copyText('email-body-${containerId}')">📋 Copy Email</button>
          </div>
          <div class="draft-section" style="margin-top:10px;">
            <label>LinkedIn Comment Response</label>
            <textarea id="comment-${containerId}" style="min-height:80px;" readonly>${drafts.linkedin_comment}</textarea>
            <button class="copy-btn" onclick="copyText('comment-${containerId}')">📋 Copy Comment</button>
          </div>
        `;
        container.style.display = 'block';
        btn.disabled = false;
        btn.innerText = 'Hide Drafts ✕';
      } catch (e) {
        alert('Draft generation failed: ' + e.message);
        btn.disabled = false;
        btn.innerText = 'Outreach Drafts ✉️';
      }
    }

    function copyText(id) {
      const el = document.getElementById(id);
      el.select();
      document.execCommand('copy');
      alert('Copied to clipboard!');
    }
    """

    # Inject CSS
    css_target = "</style>"
    html = html.replace(css_target, f"{control_panel_css}\n{css_target}", 1)

    # Inject HTML Control Panel just above stats
    html_target = '<div class="stats">'
    html = html.replace(html_target, f"{control_panel_html}\n{html_target}", 1)

    # Inject JS
    js_target = "</script>"
    html = html.replace(js_target, f"{control_panel_js}\n{js_target}", 1)

    return Response(html, mimetype="text/html")


@app.route("/api/scan", methods=["POST"])
def api_scan():
    global scan_status
    if scan_status["status"] == "running":
        return jsonify({"ok": False, "error": "A scan is already running"}), 400

    payload = request.get_json(silent=True) or {}
    mode = payload.get("mode", "1")
    service = payload.get("service", "")
    timeline = payload.get("timeline", "1day")
    min_score = int(payload.get("min_score", 5))
    manual_keywords = payload.get("manual_keywords", "")

    t = threading.Thread(
        target=bg_scan,
        args=(mode, service, timeline, min_score, manual_keywords)
    )
    t.daemon = True
    t.start()

    return jsonify({"ok": True, "message": "Scan started"})


@app.route("/api/scan/status")
def api_scan_status():
    return jsonify(scan_status)


@app.route("/api/triage/relevant", methods=["POST"])
def triage_relevant():
    payload = request.get_json(silent=True) or {}
    record = add_sales_prospect(payload)
    return jsonify({"ok": True, "record": record, "count": len(load_sales_prospects())})


@app.route("/api/triage/negative", methods=["POST"])
def triage_negative():
    payload = request.get_json(silent=True) or {}
    record = add_negative(payload)
    return jsonify({"ok": True, "record": record, "count": len(_load_list_raw(NEGATIVE_LIST_PATH))})


@app.route("/api/prospects")
def api_prospects():
    return jsonify(load_sales_prospects())


@app.route("/api/negative")
def api_negative():
    return jsonify(_load_list_raw(NEGATIVE_LIST_PATH))


@app.route("/api/positive")
def api_positive():
    """Signals the positive filter will use on the next pipeline run."""
    signals = load_positive_signals()
    benchmark = signals.get("benchmark") or {}
    return jsonify({
        "author_urls": sorted(signals["author_urls"]),
        "authors": sorted(signals["authors"]),
        "companies": sorted(signals["companies"]),
        "benchmark_posts": benchmark.get("doc_count", 0),
    })


SYSTEM_DRAFT_PROMPT = """You are a senior B2B sales outreach strategist for a premium digital agency called Grapesworldwide.

Your job: Write a hyper-personalized cold outreach email AND a personalized LinkedIn comment response.

Rubric for outreach email:
- Subject line must be short, relevant, and engaging.
- Address the author directly by name.
- Explicitly reference their post content (e.g. "I saw your post looking for an SEO agency for...").
- Pitch Grapesworldwide's relevant capabilities (e.g. SEO, SMO, Website Dev, Branding, Creative, AI, Media) matching their request.
- Keep the overall length under 150 words. Be professional and avoid boilerplate/filler.
- End with a clean, low-friction Call-To-Action (CTA) inviting a brief chat or case-study exchange.

Rubric for LinkedIn comment response:
- Short, engaging, and professional (under 60 words).
- Address their request directly, highlight fit, and invite them to connect or check their inbox.
"""

@app.route("/api/drafts", methods=["POST"])
def api_drafts():
    payload = request.get_json(silent=True) or {}
    url = payload.get("url")
    if not url:
        return jsonify({"ok": False, "error": "URL is required"}), 400

    # Find the prospect
    prospects = load_sales_prospects()
    prospect = None
    for p in prospects:
        if p.get("url") == url:
            prospect = p
            break
            
    if not prospect:
        return jsonify({"ok": False, "error": "Prospect not found"}), 404

    # Call Gemini to generate drafts
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return jsonify({"ok": False, "error": "GOOGLE_API_KEY is not set in .env"}), 500

    try:
        from google import genai
        from pydantic import BaseModel
        
        class OutreachDrafts(BaseModel):
            email_subject: str
            email_body: str
            linkedin_comment: str

        client = genai.Client(api_key=api_key)
        
        user_prompt = f"""
Author: {prospect.get('author', 'Unknown')}
Headline: {prospect.get('author_headline', '')}
Company: {prospect.get('company', '')}
Service of Interest: {', '.join(prospect.get('pitch_services', []))}
LinkedIn Post Content:
{prospect.get('snippet', '')}
"""
        
        resp = client.models.generate_content(
            model="gemini-flash-latest",
            contents=user_prompt,
            config={
                "response_mime_type": "application/json",
                "response_schema": OutreachDrafts,
                "system_instruction": SYSTEM_DRAFT_PROMPT,
                "temperature": 0.2,
            },
        )
        data = json.loads(resp.text)
        return jsonify({"ok": True, "drafts": data})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/apollo/sequences")
def api_apollo_sequences():
    from agent.apollo import ApolloClient
    client = ApolloClient()
    return jsonify(client.get_sequences())


@app.route("/api/apollo/enroll", methods=["POST"])
def api_apollo_enroll():
    payload = request.get_json(silent=True) or {}
    contact_id = payload.get("contact_id")
    sequence_id = payload.get("sequence_id")
    email = payload.get("email")
    name = payload.get("name")
    
    if not sequence_id:
        return jsonify({"ok": False, "error": "sequence_id is required"}), 400
        
    from agent.apollo import ApolloClient
    client = ApolloClient()
    
    # If contact_id is missing but we have email/name, create contact first
    if not contact_id and email:
        first = name.split()[0] if name else "Unknown"
        last = name.split()[1] if name and len(name.split()) > 1 else "Unknown"
        contact = client.create_contact(first, last, email)
        if contact:
            contact_id = contact.get("id")
            
    if not contact_id:
        return jsonify({"ok": False, "error": "No Apollo contact ID found or could be created."}), 400
        
    success = client.enroll_in_sequence(contact_id, sequence_id)
    if success:
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Apollo API failed to enroll contact in sequence."}), 500


def _load_list_raw(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


if __name__ == "__main__":


    ap = argparse.ArgumentParser(description="LinkedIn Sales Pipeline dashboard server")
    ap.add_argument("--port", type=int, default=5000,
                    help="Port to serve on (default 5000; macOS AirPlay may occupy 5000 — try 5001)")
    args = ap.parse_args()

    print("\n  LinkedIn Sales Pipeline — Web Dashboard & Run Server")
    print("  ───────────────────────────────────────────────────")
    latest = _latest_pipeline_json()
    if latest:
        print(f"  Serving latest run: {os.path.basename(latest)}")
    else:
        print("  ⚠ No pipeline_*.json found in outputs/ — run or trigger a scan.")
    print(f"  Prospects: {SALES_PROSPECTS_PATH}")
    print(f"  Negative:  {NEGATIVE_LIST_PATH}")
    print(f"  Open: http://localhost:{args.port}\n")
    # Listen on 0.0.0.0 on Render (or if HOST env var is set), otherwise default to local 127.0.0.1
    host_ip = os.environ.get("HOST", "0.0.0.0" if os.environ.get("RENDER") else "127.0.0.1")
    app.run(host=host_ip, port=args.port, debug=False)

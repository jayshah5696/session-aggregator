"""HTML report generator for sagg insights.

Generates a standalone HTML file with all CSS inline — no external
dependencies, shareable, dark-mode aware. Bar charts rendered as CSS divs.
"""

from __future__ import annotations

import html


def render_html_report(report: dict) -> str:
    """Render an InsightsReport dict as a standalone HTML file.

    Args:
        report: InsightsReport dict from generate_insights().

    Returns:
        Complete HTML document as a string.
    """
    sections = []
    sections.append(_render_header(report))
    sections.append(_render_at_a_glance(report.get("at_a_glance", {})))
    sections.append(_render_tool_comparison(report.get("tool_comparison", {})))
    sections.append(_render_friction(report.get("friction_analysis", {})))
    sections.append(_render_suggestions(report.get("suggestions", {})))
    sections.append(_render_trends(report.get("trends", {})))
    sections.append(_render_project_areas(report.get("project_areas", [])))
    sections.append(_render_impressive_workflows(report.get("impressive_workflows", [])))

    # LLM narrative — only if present
    llm = report.get("llm_narrative")
    if llm:
        sections.append(_render_llm_narrative(llm))

    sections.append(_render_fun_ending(report.get("fun_ending", {})))
    sections.append(_render_footer())

    body = "\n".join(s for s in sections if s)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>sagg insights report</title>
{_css()}
</head>
<body>
<div class="container">
{body}
</div>
{_js()}
</body>
</html>"""


def _css() -> str:
    return """<style>
:root {
  --bg: #ffffff;
  --fg: #1a1a1a;
  --muted: #6b7280;
  --border: #e5e7eb;
  --card-bg: #f9fafb;
  --accent: #2563eb;
  --accent-light: #dbeafe;
  --success: #16a34a;
  --warning: #d97706;
  --danger: #dc2626;
  --bar-bg: #e5e7eb;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #111827;
    --fg: #f3f4f6;
    --muted: #9ca3af;
    --border: #374151;
    --card-bg: #1f2937;
    --accent: #60a5fa;
    --accent-light: #1e3a5f;
    --bar-bg: #374151;
  }
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  background: var(--bg);
  color: var(--fg);
  line-height: 1.6;
  font-size: 15px;
}
.container { max-width: 900px; margin: 0 auto; padding: 2rem 1.5rem; }
h1 { font-size: 1.5rem; font-weight: 700; margin-bottom: 0.25rem; }
h2 { font-size: 1.15rem; font-weight: 600; margin: 2rem 0 0.75rem; border-bottom: 1px solid var(--border); padding-bottom: 0.4rem; }
h3 { font-size: 1rem; font-weight: 600; margin: 1.25rem 0 0.5rem; }
.subtitle { color: var(--muted); font-size: 0.9rem; margin-bottom: 1.5rem; }
.card {
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 1rem 1.25rem;
  margin-bottom: 1rem;
}
.card-yellow { border-left: 4px solid var(--warning); }
.card-green { border-left: 4px solid var(--success); }
.card-blue { border-left: 4px solid var(--accent); }
.label { font-weight: 600; font-size: 0.85rem; text-transform: uppercase; color: var(--muted); letter-spacing: 0.03em; }
.value { margin-top: 0.2rem; }
table { width: 100%; border-collapse: collapse; margin: 0.75rem 0; font-size: 0.9rem; }
th { text-align: left; font-weight: 600; padding: 0.5rem 0.75rem; border-bottom: 2px solid var(--border); }
td { padding: 0.5rem 0.75rem; border-bottom: 1px solid var(--border); }
tr:last-child td { border-bottom: none; }
.bar-container { background: var(--bar-bg); border-radius: 4px; height: 20px; overflow: hidden; }
.bar { height: 100%; border-radius: 4px; transition: width 0.3s; }
.bar-success { background: var(--success); }
.bar-warning { background: var(--warning); }
.bar-danger { background: var(--danger); }
.bar-accent { background: var(--accent); }
.suggestion-card {
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 0.75rem 1rem;
  margin-bottom: 0.75rem;
  position: relative;
}
.suggestion-target { font-size: 0.8rem; font-weight: 600; color: var(--accent); margin-bottom: 0.25rem; }
.suggestion-text { font-size: 0.9rem; }
.suggestion-why { font-size: 0.8rem; color: var(--muted); margin-top: 0.25rem; }
.copy-btn {
  position: absolute;
  top: 0.5rem;
  right: 0.5rem;
  background: var(--border);
  border: none;
  border-radius: 4px;
  padding: 0.25rem 0.5rem;
  font-size: 0.75rem;
  cursor: pointer;
  color: var(--fg);
}
.copy-btn:hover { background: var(--accent-light); }
.trend-badge {
  display: inline-block;
  padding: 0.15rem 0.5rem;
  border-radius: 12px;
  font-size: 0.8rem;
  font-weight: 500;
}
.trend-improving { background: #dcfce7; color: #166534; }
.trend-worsening { background: #fef2f2; color: #991b1b; }
.trend-stable { background: #f3f4f6; color: #374151; }
@media (prefers-color-scheme: dark) {
  .trend-improving { background: #14532d; color: #86efac; }
  .trend-worsening { background: #450a0a; color: #fca5a5; }
  .trend-stable { background: #374151; color: #d1d5db; }
}
.footer { margin-top: 3rem; padding-top: 1rem; border-top: 1px solid var(--border); color: var(--muted); font-size: 0.8rem; text-align: center; }
@media (max-width: 600px) {
  .container { padding: 1rem; }
  table { font-size: 0.8rem; }
  th, td { padding: 0.35rem 0.5rem; }
}
</style>"""


def _js() -> str:
    return """<script>
function copyText(text) {
  if (navigator.clipboard) {
    navigator.clipboard.writeText(text).then(function() {
      // Brief visual feedback could be added here
    });
  }
}
</script>"""


def _esc(s: str) -> str:
    return html.escape(str(s)) if s else ""


def _render_header(report: dict) -> str:
    total = report.get("total_sessions", 0)
    facets = report.get("total_facets", 0)
    tools = report.get("tool_comparison", {}).get("tools_analyzed", [])
    sessions_per = report.get("tool_comparison", {}).get("sessions_per_tool", {})

    tool_parts = []
    for t in tools:
        count = sessions_per.get(t, 0)
        tool_parts.append(f"{_esc(t)} ({count})")

    tool_str = " &middot; ".join(tool_parts) if tool_parts else "No tools"

    r_start = report.get("range_start", "")[:10]
    r_end = report.get("range_end", "")[:10]

    return f"""<h1>sagg insights</h1>
<p class="subtitle">{total} sessions analyzed &middot; {r_start} to {r_end}<br>{tool_str}</p>"""


def _render_at_a_glance(glance: dict) -> str:
    if not glance.get("whats_working"):
        return ""

    parts = []
    for label, key in [("Working", "whats_working"), ("Hindering", "whats_hindering"), ("Quick win", "quick_wins")]:
        val = glance.get(key, "")
        if val:
            parts.append(f'<div class="label">{label}</div><div class="value">{_esc(val)}</div><br>')

    return f"""<h2>At a Glance</h2>
<div class="card card-yellow">
{"".join(parts)}
</div>"""


def _render_tool_comparison(tc: dict) -> str:
    metrics = tc.get("tool_metrics", [])
    if not metrics:
        return ""

    best_for = tc.get("best_for", {})
    rows = []
    for m in metrics:
        tool = m["tool"]
        sr = m.get("success_rate", 0)
        sr_pct = f"{sr:.0%}"
        fr = m.get("avg_friction_score", 0)

        # Bar color
        if sr >= 0.8:
            bar_cls = "bar-success"
        elif sr >= 0.6:
            bar_cls = "bar-warning"
        else:
            bar_cls = "bar-danger"

        bar_width = f"{sr * 100:.0f}%"

        best_tasks = [t for t, tool_name in best_for.items() if tool_name == tool]
        best_str = ", ".join(best_tasks[:2]) if best_tasks else "&mdash;"

        rows.append(f"""<tr>
<td><strong>{_esc(tool)}</strong></td>
<td>{m.get('session_count', 0)}</td>
<td>
  <div style="display:flex;align-items:center;gap:0.5rem;">
    <div class="bar-container" style="width:80px;"><div class="bar {bar_cls}" style="width:{bar_width};"></div></div>
    <span>{sr_pct}</span>
  </div>
</td>
<td>{fr:.2f}</td>
<td>{best_str}</td>
</tr>""")

    narrative = _esc(tc.get("narrative", ""))

    return f"""<h2>Tool Comparison</h2>
<table>
<thead><tr><th>Tool</th><th>Sessions</th><th>Success</th><th>Friction</th><th>Best For</th></tr></thead>
<tbody>{"".join(rows)}</tbody>
</table>
<p style="color:var(--muted);font-size:0.85rem;margin-top:0.5rem;">{narrative}</p>"""


def _render_friction(friction: dict) -> str:
    patterns = friction.get("top_friction_patterns", [])
    if not patterns:
        return ""

    items = []
    for p in patterns[:7]:
        cat = _esc(p.get("category", "").replace("_", " ").title())
        count = p.get("count", 0)
        tools = ", ".join(p.get("affected_tools", []))
        items.append(f'<tr><td>{cat}</td><td>{count}</td><td>{_esc(tools)}</td></tr>')

    by_tool = friction.get("friction_by_tool", {})
    tool_rows = []
    for tool, score in sorted(by_tool.items(), key=lambda x: -x[1]):
        bar_w = f"{min(score * 200, 100):.0f}%"
        tool_rows.append(f"""<tr>
<td>{_esc(tool)}</td>
<td>
  <div style="display:flex;align-items:center;gap:0.5rem;">
    <div class="bar-container" style="width:120px;"><div class="bar bar-warning" style="width:{bar_w};"></div></div>
    <span>{score:.2f}</span>
  </div>
</td></tr>""")

    return f"""<h2>Friction Analysis</h2>
<h3>Top Friction Patterns</h3>
<table>
<thead><tr><th>Category</th><th>Count</th><th>Affected Tools</th></tr></thead>
<tbody>{"".join(items)}</tbody>
</table>
{"<h3>Friction by Tool</h3><table><tbody>" + "".join(tool_rows) + "</tbody></table>" if tool_rows else ""}"""


def _render_suggestions(suggestions: dict) -> str:
    agents = suggestions.get("agents_md_additions", [])
    recs = suggestions.get("tool_recommendations", [])

    if not agents and not recs:
        return ""

    parts = ["<h2>Suggestions</h2>"]

    if agents:
        parts.append("<h3>Config File Additions</h3>")
        for s in agents[:10]:
            target = _esc(s.get("target_file", ""))
            addition = _esc(s.get("addition", ""))
            why = _esc(s.get("why", ""))
            parts.append(f"""<div class="suggestion-card">
<button class="copy-btn" onclick="copyText('{addition.replace("'", "\\'")}')">Copy</button>
<div class="suggestion-target">{target}</div>
<div class="suggestion-text">{addition}</div>
<div class="suggestion-why">Why: {why}</div>
</div>""")

    if recs:
        parts.append("<h3>Tool Recommendations</h3>")
        rows = []
        for r in recs[:8]:
            task = _esc(r.get("task_type", ""))
            tool = _esc(r.get("recommended_tool", ""))
            conf = r.get("confidence", 0)
            dots = int(conf * 5)
            conf_str = ("&#9679;" * dots) + ("&#9675;" * (5 - dots))
            rows.append(f"<tr><td>{task}</td><td><strong>{tool}</strong></td><td>{conf_str}</td></tr>")
        parts.append(f"""<table>
<thead><tr><th>Task Type</th><th>Recommended Tool</th><th>Confidence</th></tr></thead>
<tbody>{"".join(rows)}</tbody>
</table>""")

    return "\n".join(parts)


def _render_trends(trends: dict) -> str:
    daily = trends.get("sessions_per_day", {})
    friction_trend = trends.get("friction_trend", "stable")
    productivity_trend = trends.get("productivity_trend", "stable")

    parts = ["<h2>Trends</h2>"]

    # Activity chart (simple CSS bars)
    if daily:
        max_count = max(daily.values()) if daily else 1
        bars = []
        for date, count in sorted(daily.items()):
            h = max(4, int(count / max_count * 60))
            label = date[-5:]  # MM-DD
            bars.append(
                f'<div style="display:flex;flex-direction:column;align-items:center;gap:2px;">'
                f'<div style="width:16px;height:{h}px;background:var(--accent);border-radius:2px;"></div>'
                f'<span style="font-size:0.65rem;color:var(--muted);">{label}</span>'
                f'</div>'
            )
        parts.append(
            f'<div style="display:flex;align-items:flex-end;gap:4px;margin:1rem 0;height:80px;">'
            + "".join(bars)
            + '</div>'
        )

    # Trend badges
    def badge(label: str, trend: str) -> str:
        cls = f"trend-{trend}"
        arrow = {"improving": "&uarr;", "worsening": "&darr;", "stable": "&rarr;"}.get(trend, "")
        return f'<span class="trend-badge {cls}">{label}: {arrow} {trend}</span>'

    parts.append(f'<div style="display:flex;gap:0.75rem;margin-top:0.75rem;">')
    parts.append(badge("Friction", friction_trend))
    parts.append(badge("Productivity", productivity_trend))
    parts.append('</div>')

    return "\n".join(parts)


def _render_project_areas(areas: list[dict]) -> str:
    if not areas:
        return ""

    rows = []
    for a in areas[:8]:
        name = _esc(a.get("name", ""))
        count = a.get("session_count", 0)
        sr = a.get("success_rate", 0)
        tools = ", ".join(a.get("primary_tools", []))
        rows.append(f"<tr><td>{name}</td><td>{count}</td><td>{sr:.0%}</td><td>{_esc(tools)}</td></tr>")

    return f"""<h2>Project Areas</h2>
<table>
<thead><tr><th>Area</th><th>Sessions</th><th>Success</th><th>Tools</th></tr></thead>
<tbody>{"".join(rows)}</tbody>
</table>"""


def _render_impressive_workflows(workflows: list[dict]) -> str:
    if not workflows:
        return ""

    items = []
    for w in workflows[:5]:
        title = _esc(w.get("title", ""))
        desc = _esc(w.get("description", ""))
        items.append(f'<div class="card card-green"><strong>{title}</strong><br><span style="color:var(--muted);">{desc}</span></div>')

    return f"<h2>Impressive Workflows</h2>\n" + "\n".join(items)


def _render_llm_narrative(llm: dict) -> str:
    parts = ["<h2>AI-Generated Narrative</h2>"]

    summary = llm.get("executive_summary", "")
    if summary:
        parts.append(f'<div class="card card-blue"><p>{_esc(summary)}</p></div>')

    tool_narratives = llm.get("tool_narratives", {})
    for tool, narrative in tool_narratives.items():
        parts.append(f"<h3>{_esc(tool)}</h3><p>{_esc(narrative)}</p>")

    recs = llm.get("workflow_recommendations", [])
    if recs:
        parts.append("<h3>Workflow Recommendations</h3><ul>")
        for r in recs:
            parts.append(f"<li>{_esc(str(r))}</li>")
        parts.append("</ul>")

    return "\n".join(parts)


def _render_fun_ending(fun: dict) -> str:
    headline = fun.get("headline", "")
    detail = fun.get("detail", "")
    if not headline:
        return ""

    return f"""<div class="card card-yellow" style="margin-top:2rem;">
<strong>{_esc(headline)}</strong><br>
<span style="color:var(--muted);">{_esc(detail)}</span>
</div>"""


def _render_footer() -> str:
    return '<div class="footer">Generated by sagg &middot; Session Aggregator</div>'

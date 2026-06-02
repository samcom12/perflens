from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .io import utc_now
from .models import (
    OptimizationPlan,
    ProfileReport,
    ScanReport,
    ValidationReport,
)


def generate_dashboard(
    output_dir: str | Path,
    scan: ScanReport,
    plan: OptimizationPlan,
    profile: ProfileReport | None = None,
    validation: ValidationReport | None = None,
) -> Path:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    html_path = target / "index.html"
    html_path.write_text(
        _render(scan=scan, plan=plan, profile=profile, validation=validation),
        encoding="utf-8",
    )
    return html_path


def _render(
    scan: ScanReport,
    plan: OptimizationPlan,
    profile: ProfileReport | None,
    validation: ValidationReport | None,
) -> str:
    language_rows = _language_rows(scan.language_counts)
    findings_rows = _finding_rows(scan)
    hotspot_rows = _hotspot_rows(profile)
    action_rows = _action_rows(plan)
    validation_rows = _validation_rows(validation)
    summary = {
        "files": len(scan.files),
        "findings": len(scan.findings),
        "hotspots": len(profile.hotspots) if profile else 0,
        "actions": len(plan.actions),
        "validation": "passed" if validation and validation.passed else "not passed" if validation else "not run",
    }
    summary_json = html.escape(json.dumps(summary))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>perflens dashboard</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #202124;
      --muted: #5f6368;
      --line: #dadce0;
      --panel: #ffffff;
      --back: #f7f8fa;
      --accent: #0b57d0;
      --good: #137333;
      --warn: #b06000;
      --bad: #b3261e;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Arial, Helvetica, sans-serif;
      color: var(--ink);
      background: var(--back);
    }}
    header {{
      padding: 24px 28px 18px;
      border-bottom: 1px solid var(--line);
      background: #fff;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 28px;
      line-height: 1.2;
      letter-spacing: 0;
    }}
    h2 {{
      margin: 0 0 14px;
      font-size: 18px;
      letter-spacing: 0;
    }}
    main {{
      width: min(1180px, calc(100vw - 32px));
      margin: 22px auto 42px;
    }}
    section {{
      margin: 0 0 22px;
      padding: 20px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    .summary {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 12px;
    }}
    .metric {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      background: #fbfcff;
    }}
    .metric b {{
      display: block;
      font-size: 24px;
      line-height: 1.1;
      margin-bottom: 4px;
    }}
    .metric span, .muted {{
      color: var(--muted);
      font-size: 13px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
      gap: 22px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }}
    th, td {{
      padding: 9px 8px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
    }}
    th {{
      color: var(--muted);
      font-weight: 600;
      background: #f8fafd;
    }}
    code {{
      font-family: Consolas, Monaco, monospace;
      font-size: 12px;
    }}
    .bar {{
      min-width: 120px;
      height: 10px;
      background: #e8eaed;
      border-radius: 8px;
      overflow: hidden;
    }}
    .bar > span {{
      display: block;
      height: 100%;
      background: var(--accent);
    }}
    .priority {{
      display: inline-block;
      min-width: 32px;
      padding: 3px 7px;
      border-radius: 999px;
      color: #fff;
      background: var(--accent);
      text-align: center;
      font-weight: 700;
    }}
    .passed {{ color: var(--good); font-weight: 700; }}
    .failed {{ color: var(--bad); font-weight: 700; }}
    @media (max-width: 780px) {{
      header {{ padding: 20px 16px 14px; }}
      main {{ width: calc(100vw - 20px); }}
      section {{ padding: 14px; }}
      .grid {{ grid-template-columns: 1fr; }}
      table {{ font-size: 12px; }}
      th, td {{ padding: 8px 6px; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>perflens dashboard</h1>
    <div class="muted">Generated {html.escape(utc_now())} | Hardware target: {html.escape(plan.hardware_id)}</div>
  </header>
  <main data-summary="{summary_json}">
    <section>
      <div class="summary">
        <div class="metric"><b>{len(scan.files)}</b><span>source files</span></div>
        <div class="metric"><b>{len(scan.findings)}</b><span>static findings</span></div>
        <div class="metric"><b>{len(profile.hotspots) if profile else 0}</b><span>profile hotspots</span></div>
        <div class="metric"><b>{len(plan.actions)}</b><span>optimization actions</span></div>
        <div class="metric"><b>{_validation_label(validation)}</b><span>validation status</span></div>
      </div>
    </section>
    <div class="grid">
      <section>
        <h2>Language Mix</h2>
        <table><tbody>{language_rows}</tbody></table>
      </section>
      <section>
        <h2>Top Hotspots</h2>
        <table>
          <thead><tr><th>Function</th><th>Location</th><th>Metric</th></tr></thead>
          <tbody>{hotspot_rows}</tbody>
        </table>
      </section>
    </div>
    <section>
      <h2>Ranked Optimization Actions</h2>
      <table>
        <thead><tr><th>Priority</th><th>Action</th><th>Files</th><th>Evidence</th></tr></thead>
        <tbody>{action_rows}</tbody>
      </table>
    </section>
    <section>
      <h2>Static Findings</h2>
      <table>
        <thead><tr><th>Location</th><th>Kind</th><th>Severity</th><th>Message</th></tr></thead>
        <tbody>{findings_rows}</tbody>
      </table>
    </section>
    <section>
      <h2>Validation And Benchmarks</h2>
      <table>
        <thead><tr><th>Name</th><th>Kind</th><th>Status</th><th>Seconds</th><th>Command</th></tr></thead>
        <tbody>{validation_rows}</tbody>
      </table>
    </section>
  </main>
</body>
</html>
"""


def _language_rows(counts: dict[str, int]) -> str:
    if not counts:
        return "<tr><td>No source files found.</td></tr>"
    max_count = max(counts.values())
    rows = []
    for language, count in sorted(counts.items()):
        width = int((count / max_count) * 100) if max_count else 0
        rows.append(
            "<tr>"
            f"<td>{html.escape(language)}</td>"
            f"<td>{count}</td>"
            f"<td><div class=\"bar\"><span style=\"width:{width}%\"></span></div></td>"
            "</tr>"
        )
    return "".join(rows)


def _hotspot_rows(profile: ProfileReport | None) -> str:
    if not profile or not profile.hotspots:
        return "<tr><td colspan=\"3\">No profile hotspots loaded.</td></tr>"
    rows = []
    for hotspot in profile.hotspots[:10]:
        location = hotspot.file or ""
        if hotspot.line:
            location = f"{location}:{hotspot.line}"
        rows.append(
            "<tr>"
            f"<td>{html.escape(hotspot.function)}</td>"
            f"<td><code>{html.escape(location)}</code></td>"
            f"<td>{html.escape(hotspot.metric)} {hotspot.value:g}{html.escape(hotspot.unit)}</td>"
            "</tr>"
        )
    return "".join(rows)


def _action_rows(plan: OptimizationPlan) -> str:
    if not plan.actions:
        return "<tr><td colspan=\"4\">No optimization actions generated.</td></tr>"
    rows = []
    for action in plan.actions:
        files = "<br>".join(f"<code>{html.escape(item)}</code>" for item in action.files)
        evidence = "<br>".join(html.escape(item) for item in action.evidence[:3])
        rows.append(
            "<tr>"
            f"<td><span class=\"priority\">{action.priority}</span></td>"
            f"<td><b>{html.escape(action.title)}</b><br><span class=\"muted\">{html.escape(action.suggested_change)}</span></td>"
            f"<td>{files}</td>"
            f"<td>{evidence}</td>"
            "</tr>"
        )
    return "".join(rows)


def _finding_rows(scan: ScanReport) -> str:
    if not scan.findings:
        return "<tr><td colspan=\"4\">No static findings.</td></tr>"
    rows = []
    for finding in scan.findings[:100]:
        rows.append(
            "<tr>"
            f"<td><code>{html.escape(finding.path)}:{finding.line}</code></td>"
            f"<td>{html.escape(finding.kind)}</td>"
            f"<td>{html.escape(finding.severity)}</td>"
            f"<td>{html.escape(finding.message)}</td>"
            "</tr>"
        )
    return "".join(rows)


def _validation_rows(validation: ValidationReport | None) -> str:
    if not validation:
        return "<tr><td colspan=\"5\">Validation was not run.</td></tr>"
    rows = []
    for result in validation.commands + validation.benchmarks:
        status = "passed" if result.passed else "failed"
        rows.append(
            "<tr>"
            f"<td>{html.escape(result.name)}</td>"
            f"<td>{html.escape(result.kind)}</td>"
            f"<td class=\"{status}\">{status}</td>"
            f"<td>{result.duration_seconds:g}</td>"
            f"<td><code>{html.escape(result.command)}</code></td>"
            "</tr>"
        )
    return "".join(rows) or "<tr><td colspan=\"5\">No validation commands configured.</td></tr>"


def _validation_label(validation: ValidationReport | None) -> str:
    if not validation:
        return "not run"
    return "passed" if validation.passed else "failed"


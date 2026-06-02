"""
PerfLens Benchmark Dashboard — FastAPI + Plotly.

Endpoints:
  GET  /                    → HTML dashboard
  GET  /api/runs            → list all benchmark runs
  GET  /api/runs/{id}       → single run detail
  POST /api/runs            → record a new benchmark run
  GET  /api/chart/timeline  → runtime timeline Plotly JSON
  GET  /api/chart/roofline  → roofline model Plotly JSON
  GET  /api/chart/speedup   → speedup bar chart Plotly JSON
  GET  /api/chart/hotspots  → top hotspot flame-style chart
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

import plotly.graph_objects as go
import plotly.io as pio


# ── DB helpers ────────────────────────────────────────────────────────────────

_DEFAULT_DB = Path("perflens_benchmarks.db")


def _init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS benchmark_run (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        label       TEXT NOT NULL,
        source_file TEXT,
        hw_profile  TEXT,
        iteration   INTEGER DEFAULT 0,
        runtime_ms  REAL,
        speedup     REAL,
        timestamp   TEXT,
        metadata    TEXT
    );
    CREATE TABLE IF NOT EXISTS hotspot (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id      INTEGER REFERENCES benchmark_run(id),
        function    TEXT,
        cpu_pct     REAL,
        cpu_ms      REAL,
        ai          REAL,
        gflops      REAL
    );
    CREATE TABLE IF NOT EXISTS roofline_point (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id      INTEGER REFERENCES benchmark_run(id),
        label       TEXT,
        ai          REAL,
        gflops      REAL,
        peak_gflops REAL,
        peak_bw_gbs REAL
    );
    """)
    conn.commit()


@contextmanager
def _get_conn(db_path: Path) -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    _init_db(conn)
    try:
        yield conn
    finally:
        conn.close()


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class HotspotIn(BaseModel):
    function: str
    cpu_pct: float = 0.0
    cpu_ms: float = 0.0
    ai: Optional[float] = None
    gflops: Optional[float] = None


class RooflinePointIn(BaseModel):
    label: str
    ai: float
    gflops: float
    peak_gflops: Optional[float] = None
    peak_bw_gbs: Optional[float] = None


class BenchmarkRunIn(BaseModel):
    label: str
    source_file: Optional[str] = None
    hw_profile: Optional[str] = None
    iteration: int = 0
    runtime_ms: Optional[float] = None
    speedup: Optional[float] = None
    metadata: Optional[dict] = None
    hotspots: list[HotspotIn] = []
    roofline_points: list[RooflinePointIn] = []


# ── App factory ───────────────────────────────────────────────────────────────

def create_app(db_path: Optional[Path] = None) -> FastAPI:
    db = db_path or _DEFAULT_DB
    app = FastAPI(title="PerfLens Dashboard", version="0.1.0")

    # ── Routes ────────────────────────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return _render_dashboard_html()

    @app.get("/api/runs")
    async def list_runs():
        with _get_conn(db) as conn:
            rows = conn.execute(
                "SELECT * FROM benchmark_run ORDER BY id DESC LIMIT 200"
            ).fetchall()
        return [dict(r) for r in rows]

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: int):
        with _get_conn(db) as conn:
            row = conn.execute(
                "SELECT * FROM benchmark_run WHERE id=?", (run_id,)
            ).fetchone()
            if not row:
                raise HTTPException(404, "Run not found")
            hotspots = conn.execute(
                "SELECT * FROM hotspot WHERE run_id=?", (run_id,)
            ).fetchall()
            roofline = conn.execute(
                "SELECT * FROM roofline_point WHERE run_id=?", (run_id,)
            ).fetchall()
        return {
            **dict(row),
            "hotspots": [dict(h) for h in hotspots],
            "roofline_points": [dict(r) for r in roofline],
        }

    @app.post("/api/runs", status_code=201)
    async def create_run(payload: BenchmarkRunIn):
        with _get_conn(db) as conn:
            cur = conn.execute(
                """INSERT INTO benchmark_run
                   (label, source_file, hw_profile, iteration, runtime_ms, speedup, timestamp, metadata)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    payload.label,
                    payload.source_file,
                    payload.hw_profile,
                    payload.iteration,
                    payload.runtime_ms,
                    payload.speedup,
                    datetime.now(timezone.utc).isoformat(),
                    json.dumps(payload.metadata or {}),
                ),
            )
            run_id = cur.lastrowid

            for h in payload.hotspots:
                conn.execute(
                    "INSERT INTO hotspot (run_id, function, cpu_pct, cpu_ms, ai, gflops) VALUES (?,?,?,?,?,?)",
                    (run_id, h.function, h.cpu_pct, h.cpu_ms, h.ai, h.gflops),
                )
            for r in payload.roofline_points:
                conn.execute(
                    "INSERT INTO roofline_point (run_id, label, ai, gflops, peak_gflops, peak_bw_gbs) VALUES (?,?,?,?,?,?)",
                    (run_id, r.label, r.ai, r.gflops, r.peak_gflops, r.peak_bw_gbs),
                )
            conn.commit()
        return {"id": run_id}

    @app.get("/api/chart/timeline")
    async def chart_timeline(source_file: Optional[str] = None):
        with _get_conn(db) as conn:
            q = "SELECT label, iteration, runtime_ms, speedup, timestamp FROM benchmark_run"
            params: tuple = ()
            if source_file:
                q += " WHERE source_file=?"
                params = (source_file,)
            q += " ORDER BY id ASC"
            rows = conn.execute(q, params).fetchall()

        fig = _make_timeline_chart([dict(r) for r in rows])
        return JSONResponse(json.loads(pio.to_json(fig)))

    @app.get("/api/chart/speedup")
    async def chart_speedup():
        with _get_conn(db) as conn:
            rows = conn.execute(
                "SELECT label, iteration, speedup FROM benchmark_run WHERE speedup IS NOT NULL ORDER BY id ASC"
            ).fetchall()
        fig = _make_speedup_chart([dict(r) for r in rows])
        return JSONResponse(json.loads(pio.to_json(fig)))

    @app.get("/api/chart/roofline")
    async def chart_roofline(run_id: Optional[int] = None):
        with _get_conn(db) as conn:
            q = "SELECT * FROM roofline_point"
            params: tuple = ()
            if run_id:
                q += " WHERE run_id=?"
                params = (run_id,)
            rows = conn.execute(q, params).fetchall()
        fig = _make_roofline_chart([dict(r) for r in rows])
        return JSONResponse(json.loads(pio.to_json(fig)))

    @app.get("/api/chart/hotspots")
    async def chart_hotspots(run_id: Optional[int] = None):
        with _get_conn(db) as conn:
            q = "SELECT * FROM hotspot"
            params: tuple = ()
            if run_id:
                q += " WHERE run_id=?"
                params = (run_id,)
            q += " ORDER BY cpu_pct DESC LIMIT 20"
            rows = conn.execute(q, params).fetchall()
        fig = _make_hotspot_chart([dict(r) for r in rows])
        return JSONResponse(json.loads(pio.to_json(fig)))

    return app


# ── Chart builders ────────────────────────────────────────────────────────────

def _make_timeline_chart(rows: list[dict]) -> go.Figure:
    labels     = [r["label"] for r in rows]
    runtimes   = [r["runtime_ms"] for r in rows]
    iterations = [r["iteration"] for r in rows]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=list(range(len(rows))), y=runtimes,
        mode="lines+markers",
        name="Runtime (ms)",
        text=labels,
        hovertemplate="<b>%{text}</b><br>Iteration: %{customdata}<br>Runtime: %{y:.1f} ms",
        customdata=iterations,
        line=dict(color="#00b4d8", width=2),
        marker=dict(size=8),
    ))
    fig.update_layout(
        title="Runtime Over Optimization Iterations",
        xaxis_title="Run Index",
        yaxis_title="Runtime (ms)",
        plot_bgcolor="#1a1a2e",
        paper_bgcolor="#16213e",
        font=dict(color="#eaeaea"),
        hovermode="x unified",
    )
    return fig


def _make_speedup_chart(rows: list[dict]) -> go.Figure:
    labels  = [f"{r['label']} (iter {r['iteration']})" for r in rows]
    speedup = [r["speedup"] for r in rows]
    colors  = ["#ef4444" if s < 1 else "#22c55e" for s in speedup]

    fig = go.Figure(go.Bar(
        x=labels, y=speedup, marker_color=colors,
        text=[f"{s:.2f}×" for s in speedup],
        textposition="outside",
        hovertemplate="<b>%{x}</b><br>Speedup: %{y:.2f}×",
    ))
    fig.add_hline(y=1.0, line_dash="dash", line_color="gray",
                  annotation_text="Baseline (1×)")
    fig.update_layout(
        title="Speedup per Optimization Run",
        xaxis_title="Run",
        yaxis_title="Speedup (×)",
        plot_bgcolor="#1a1a2e",
        paper_bgcolor="#16213e",
        font=dict(color="#eaeaea"),
    )
    return fig


def _make_roofline_chart(rows: list[dict]) -> go.Figure:
    fig = go.Figure()

    # Draw peak roofline lines if we have data
    if rows and rows[0].get("peak_gflops") and rows[0].get("peak_bw_gbs"):
        import numpy as np
        peak_gf  = rows[0]["peak_gflops"]
        peak_bw  = rows[0]["peak_bw_gbs"]
        ai_range = np.logspace(-2, 4, 200)
        roof_y   = np.minimum(peak_bw * ai_range, peak_gf)
        fig.add_trace(go.Scatter(
            x=ai_range, y=roof_y,
            mode="lines", name="Roofline",
            line=dict(color="#f59e0b", width=2, dash="dot"),
        ))

    # Scatter actual data points
    if rows:
        fig.add_trace(go.Scatter(
            x=[r["ai"] for r in rows],
            y=[r["gflops"] for r in rows],
            mode="markers+text",
            name="Kernels",
            text=[r["label"] for r in rows],
            textposition="top center",
            marker=dict(size=10, color="#00b4d8",
                        symbol="circle", line=dict(width=1, color="#fff")),
            hovertemplate="<b>%{text}</b><br>AI: %{x:.2f} FLOP/B<br>GFLOP/s: %{y:.1f}",
        ))

    fig.update_layout(
        title="Roofline Model",
        xaxis=dict(title="Arithmetic Intensity (FLOP/Byte)", type="log"),
        yaxis=dict(title="Performance (GFLOP/s)", type="log"),
        plot_bgcolor="#1a1a2e",
        paper_bgcolor="#16213e",
        font=dict(color="#eaeaea"),
    )
    return fig


def _make_hotspot_chart(rows: list[dict]) -> go.Figure:
    if not rows:
        return go.Figure()

    functions = [r["function"][:30] for r in rows]
    cpu_pcts  = [r["cpu_pct"] for r in rows]
    cpu_ms    = [r["cpu_ms"] for r in rows]

    colors = [
        f"rgba({max(0, 220 - int(p * 2))}, {max(0, 60 - int(p))}, {min(255, 40 + int(p * 2))}, 0.85)"
        for p in cpu_pcts
    ]

    fig = go.Figure(go.Bar(
        x=cpu_pcts[::-1],
        y=functions[::-1],
        orientation="h",
        marker_color=colors[::-1],
        text=[f"{p:.1f}% ({m:.0f}ms)" for p, m in zip(cpu_pcts[::-1], cpu_ms[::-1])],
        textposition="inside",
        hovertemplate="<b>%{y}</b><br>CPU: %{x:.1f}%",
    ))
    fig.update_layout(
        title="Top Hotspots by CPU Time",
        xaxis_title="CPU Time (%)",
        yaxis_title="Function",
        plot_bgcolor="#1a1a2e",
        paper_bgcolor="#16213e",
        font=dict(color="#eaeaea"),
        height=max(300, len(rows) * 35),
    )
    return fig


# ── Dashboard HTML ────────────────────────────────────────────────────────────

def _render_dashboard_html() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>PerfLens Dashboard</title>
  <script src="https://cdn.plot.ly/plotly-2.30.0.min.js"></script>
  <style>
    :root {
      --bg: #0d1117; --surface: #161b22; --border: #30363d;
      --accent: #00b4d8; --text: #c9d1d9; --muted: #8b949e;
      --green: #22c55e; --red: #ef4444; --yellow: #f59e0b;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', system-ui, sans-serif; }
    header {
      background: var(--surface); border-bottom: 1px solid var(--border);
      padding: 1rem 2rem; display: flex; align-items: center; gap: 1rem;
    }
    header h1 { font-size: 1.5rem; color: var(--accent); }
    header span { color: var(--muted); font-size: 0.85rem; }
    .main { padding: 2rem; display: grid; gap: 1.5rem; }
    .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; }
    .card {
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 8px; padding: 1.25rem; overflow: hidden;
    }
    .card h2 { font-size: 1rem; color: var(--accent); margin-bottom: 1rem; }
    .chart-container { width: 100%; min-height: 320px; }
    .stats { display: flex; gap: 1.5rem; flex-wrap: wrap; }
    .stat {
      background: var(--bg); border: 1px solid var(--border);
      border-radius: 6px; padding: 0.75rem 1.25rem; min-width: 140px;
    }
    .stat .value { font-size: 1.75rem; font-weight: 700; color: var(--accent); }
    .stat .label { font-size: 0.75rem; color: var(--muted); margin-top: 2px; }
    table { width: 100%; border-collapse: collapse; font-size: 0.875rem; }
    th { text-align: left; padding: 0.5rem 0.75rem; color: var(--muted);
         border-bottom: 1px solid var(--border); font-weight: 500; }
    td { padding: 0.5rem 0.75rem; border-bottom: 1px solid var(--border); }
    tr:hover td { background: rgba(255,255,255,0.03); }
    .badge {
      display: inline-block; padding: 0.2rem 0.5rem; border-radius: 4px;
      font-size: 0.7rem; font-weight: 600;
    }
    .badge.pass  { background: rgba(34,197,94,0.15); color: var(--green); }
    .badge.warn  { background: rgba(245,158,11,0.15); color: var(--yellow); }
    .badge.fail  { background: rgba(239,68,68,0.15);  color: var(--red); }
    .refresh-btn {
      background: var(--accent); color: #000; border: none; border-radius: 6px;
      padding: 0.4rem 1rem; cursor: pointer; font-weight: 600; margin-left: auto;
    }
    .refresh-btn:hover { opacity: 0.85; }
  </style>
</head>
<body>
  <header>
    <span style="font-size:1.8rem">🔬</span>
    <h1>PerfLens</h1>
    <span>Automated HPC Optimization Dashboard</span>
    <button class="refresh-btn" onclick="loadAll()">↻ Refresh</button>
  </header>

  <div class="main">
    <!-- Stats row -->
    <div class="stats" id="stats">
      <div class="stat"><div class="value" id="stat-runs">—</div><div class="label">Total Runs</div></div>
      <div class="stat"><div class="value" id="stat-best">—</div><div class="label">Best Speedup</div></div>
      <div class="stat"><div class="value" id="stat-iter">—</div><div class="label">Max Iterations</div></div>
      <div class="stat"><div class="value" id="stat-files">—</div><div class="label">Source Files</div></div>
    </div>

    <!-- Charts row 1 -->
    <div class="grid-2">
      <div class="card">
        <h2>⏱ Runtime Timeline</h2>
        <div class="chart-container" id="chart-timeline"></div>
      </div>
      <div class="card">
        <h2>🚀 Speedup per Run</h2>
        <div class="chart-container" id="chart-speedup"></div>
      </div>
    </div>

    <!-- Charts row 2 -->
    <div class="grid-2">
      <div class="card">
        <h2>📐 Roofline Model</h2>
        <div class="chart-container" id="chart-roofline"></div>
      </div>
      <div class="card">
        <h2>🔥 Top Hotspots</h2>
        <div class="chart-container" id="chart-hotspots"></div>
      </div>
    </div>

    <!-- Runs table -->
    <div class="card">
      <h2>📋 Benchmark Runs</h2>
      <table id="runs-table">
        <thead>
          <tr>
            <th>#</th><th>Label</th><th>File</th><th>HW</th>
            <th>Iter</th><th>Runtime (ms)</th><th>Speedup</th><th>Timestamp</th>
          </tr>
        </thead>
        <tbody id="runs-body"></tbody>
      </table>
    </div>
  </div>

<script>
const API = '';

async function fetchJSON(url) {
  const r = await fetch(API + url);
  if (!r.ok) return null;
  return r.json();
}

function renderChart(divId, figJson) {
  if (!figJson) return;
  const el = document.getElementById(divId);
  Plotly.react(el, figJson.data, {
    ...figJson.layout,
    responsive: true,
    margin: { t: 30, l: 55, r: 20, b: 55 },
  }, { responsive: true, displayModeBar: false });
}

function speedupBadge(s) {
  if (s == null) return '<span class="badge warn">N/A</span>';
  const cls = s >= 2 ? 'pass' : s >= 1 ? 'warn' : 'fail';
  return `<span class="badge ${cls}">${s.toFixed(2)}×</span>`;
}

async function loadAll() {
  const [runs, timeline, speedup, roofline, hotspots] = await Promise.all([
    fetchJSON('/api/runs'),
    fetchJSON('/api/chart/timeline'),
    fetchJSON('/api/chart/speedup'),
    fetchJSON('/api/chart/roofline'),
    fetchJSON('/api/chart/hotspots'),
  ]);

  // Stats
  if (runs) {
    document.getElementById('stat-runs').textContent = runs.length;
    const speedups = runs.map(r => r.speedup).filter(Boolean);
    document.getElementById('stat-best').textContent = speedups.length
      ? Math.max(...speedups).toFixed(2) + '×' : '—';
    document.getElementById('stat-iter').textContent = runs.length
      ? Math.max(...runs.map(r => r.iteration || 0)) : '—';
    const files = new Set(runs.map(r => r.source_file).filter(Boolean));
    document.getElementById('stat-files').textContent = files.size || '—';

    // Table
    const tbody = document.getElementById('runs-body');
    tbody.innerHTML = runs.slice(0, 50).map(r => `
      <tr>
        <td>${r.id}</td>
        <td>${r.label}</td>
        <td><code style="font-size:0.75rem">${r.source_file || '—'}</code></td>
        <td>${r.hw_profile || '—'}</td>
        <td>${r.iteration}</td>
        <td>${r.runtime_ms != null ? r.runtime_ms.toFixed(1) : '—'}</td>
        <td>${speedupBadge(r.speedup)}</td>
        <td style="color:var(--muted);font-size:0.75rem">${(r.timestamp||'').replace('T',' ').slice(0,19)}</td>
      </tr>
    `).join('');
  }

  renderChart('chart-timeline', timeline);
  renderChart('chart-speedup',  speedup);
  renderChart('chart-roofline', roofline);
  renderChart('chart-hotspots', hotspots);
}

loadAll();
setInterval(loadAll, 30000);  // auto-refresh every 30s
</script>
</body>
</html>"""

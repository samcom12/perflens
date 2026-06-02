"""
HPCToolkit database parser.

HPCToolkit stores results in a directory with:
  - experiment.xml  — call-path profile (CCT)
  - HPCTOOLKIT-<app>-measurements/  — raw measurement data

This parser reads experiment.xml directly and optionally invokes
`hpcproftt` to export CSV summaries.

Reference: https://hpctoolkit.org/man/hpcproftt.html
"""

from __future__ import annotations

import csv
import io
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

from perflens.profiler.models import Hotspot, ProfileData


class HPCToolkitParser:
    """Parse HPCToolkit experiment.xml or hpcproftt CSV output."""

    def parse(
        self,
        report_path: Optional[Path],
        source: Optional[Path] = None,
    ) -> ProfileData:

        if report_path is None:
            report_path = self._auto_discover()

        if report_path is None:
            return self._empty(source)

        # Directory → look for experiment.xml
        if report_path.is_dir():
            xml_path = report_path / "experiment.xml"
            if not xml_path.exists():
                # Try hpcproftt to export
                xml_path = self._run_hpcproftt(report_path)

            if xml_path and xml_path.exists():
                return self._parse_xml(xml_path, source)
            return self._empty(source)

        # File — detect format
        if report_path.suffix.lower() == ".xml":
            return self._parse_xml(report_path, source)
        elif report_path.suffix.lower() == ".csv":
            return self._parse_csv(report_path, source)

        return self._empty(source)

    # ── XML (experiment.xml) ─────────────────────────────────────────────────

    def _parse_xml(self, path: Path, source: Optional[Path]) -> ProfileData:
        tree = ET.parse(str(path))
        root = tree.getroot()

        # Metric definitions
        metrics: dict[str, str] = {}
        for m in root.iter("Metric"):
            mid  = m.attrib.get("i", m.attrib.get("id", ""))
            name = m.attrib.get("n", m.attrib.get("name", ""))
            metrics[mid] = name

        # Find the primary CYCLES / TIME metric index
        time_mid = self._find_metric(metrics, ["REALTIME (sec)", "CYCLES", "WALLCLOCK", "TIME"])
        cpu_mid  = self._find_metric(metrics, ["CPU_CLK_UNHALTED", "CPU_CYCLES"])

        hotspots: list[Hotspot] = []
        total_time = 0.0

        for proc in root.iter("Procedure"):
            name = proc.attrib.get("n", proc.attrib.get("name", "unknown"))
            for pf in proc.iter("PF"):
                mv_map = self._collect_metrics(pf)
                t = self._metric_val(mv_map, time_mid)
                if t <= 0:
                    t = self._metric_val(mv_map, cpu_mid) / 1e9  # cycles → ~seconds
                t_ms = t * 1000
                total_time += t_ms

                # Source file
                src_file = pf.attrib.get("f", None)
                start_ln = int(pf.attrib.get("l", "0"))

                hotspots.append(Hotspot(
                    function=name,
                    module=pf.attrib.get("a", ""),
                    source_file=src_file,
                    start_line=start_ln,
                    cpu_time_pct=0.0,
                    cpu_time_ms=t_ms,
                    cpi=None,
                    llc_miss_rate=None,
                    mem_bound_pct=None,
                    compute_bound_pct=None,
                    vectorization_pct=None,
                    gflops=None,
                    arithmetic_intensity=None,
                    metadata=dict(pf.attrib),
                ))

        for h in hotspots:
            h.cpu_time_pct = (h.cpu_time_ms / total_time * 100) if total_time > 0 else 0.0

        return ProfileData(
            tool="hpctoolkit",
            source=source,
            report_path=path,
            total_time_ms=total_time,
            hotspots=sorted(hotspots, key=lambda h: h.cpu_time_ms, reverse=True),
        )

    # ── CSV (hpcproftt -T s output) ──────────────────────────────────────────

    def _parse_csv(self, path: Path, source: Optional[Path]) -> ProfileData:
        raw = path.read_text(errors="replace")
        # hpcproftt CSV has a comment header starting with '#'
        lines = [l for l in raw.splitlines() if not l.startswith("#")]
        reader = csv.DictReader(io.StringIO("\n".join(lines)))

        hotspots: list[Hotspot] = []
        total_time = 0.0

        for row in reader:
            # Column names vary; try common ones
            name = (row.get("Procedure") or row.get("Function") or row.get("Name") or "unknown").strip()
            t_ms = self._float(row.get("Inclusive Time (ms)") or row.get("REALTIME (sec)") or "0")
            if "sec" in "".join(row.keys()).lower():
                t_ms *= 1000
            total_time += t_ms

            hotspots.append(Hotspot(
                function=name,
                module=row.get("Module", row.get("Binary", "")),
                source_file=row.get("File", row.get("Source File")),
                start_line=int(self._float(row.get("Line", "0"))),
                cpu_time_pct=0.0,
                cpu_time_ms=t_ms,
                cpi=None, llc_miss_rate=None,
                mem_bound_pct=None, compute_bound_pct=None,
                vectorization_pct=None, gflops=None, arithmetic_intensity=None,
                metadata=dict(row),
            ))

        for h in hotspots:
            h.cpu_time_pct = (h.cpu_time_ms / total_time * 100) if total_time > 0 else 0.0

        return ProfileData(
            tool="hpctoolkit",
            source=source,
            report_path=path,
            total_time_ms=total_time,
            hotspots=sorted(hotspots, key=lambda h: h.cpu_time_ms, reverse=True),
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _find_metric(metrics: dict[str, str], candidates: list[str]) -> Optional[str]:
        for mid, name in metrics.items():
            for c in candidates:
                if c.lower() in name.lower():
                    return mid
        return None

    @staticmethod
    def _collect_metrics(pf_node) -> dict[str, float]:
        result: dict[str, float] = {}
        for mv in pf_node.iter("M"):
            mid = mv.attrib.get("n", mv.attrib.get("id", ""))
            val_str = mv.attrib.get("v", "0")
            try:
                result[mid] = float(val_str)
            except ValueError:
                pass
        return result

    @staticmethod
    def _metric_val(mv_map: dict[str, float], mid: Optional[str]) -> float:
        if mid is None:
            return 0.0
        return mv_map.get(mid, 0.0)

    @staticmethod
    def _auto_discover() -> Optional[Path]:
        # Look for HPCToolkit database directories
        for pattern in ["*.hpctoolkit", "hpctoolkit-*", "measurements"]:
            results = sorted(Path(".").glob(pattern))
            if results:
                return results[-1]
        return None

    @staticmethod
    def _run_hpcproftt(db_dir: Path) -> Optional[Path]:
        hpcproftt = shutil.which("hpcproftt")
        if not hpcproftt:
            return None
        out = Path("/tmp/perflens_hpctoolkit.xml")
        try:
            subprocess.run(
                [hpcproftt, "-T", "s", str(db_dir)],
                stdout=out.open("w"), check=True, stderr=subprocess.DEVNULL,
            )
            return out
        except Exception:
            return None

    @staticmethod
    def _float(v: Optional[str]) -> float:
        if not v:
            return 0.0
        v = re.sub(r"[,%\s]", "", str(v))
        try:
            return float(v)
        except ValueError:
            return 0.0

    @staticmethod
    def _empty(source: Optional[Path]) -> ProfileData:
        return ProfileData(
            tool="hpctoolkit", source=source, report_path=None,
            total_time_ms=0.0, hotspots=[], roofline_points=[],
        )

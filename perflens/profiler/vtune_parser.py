"""
Intel VTune Profiler report parser.

Supports two VTune export formats:
  1. CSV  — `vtune -report hotspots -format csv -r <result_dir>`
  2. XML  — `vtune -report hotspots -format xml  -r <result_dir>`

If no report is provided, attempts to discover a VTune result directory in the
current working directory and run `vtune -report` automatically.

Column name mapping covers VTune 2021–2024 naming conventions.
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

from perflens.profiler.models import Hotspot, ProfileData, RooflinePoint


# VTune CSV column aliases → canonical names
_COLUMN_ALIASES: dict[str, str] = {
    # Function column
    "function":                          "function",
    "function (full)":                   "function",
    "symbol":                            "function",
    # Module
    "module":                            "module",
    "binary":                            "module",
    # Source file / line
    "source file":                       "source_file",
    "source location":                   "source_file",
    "start line":                        "start_line",
    "line":                              "start_line",
    # Time
    "cpu time":                          "cpu_time_ms",
    "cpu time (ms)":                     "cpu_time_ms",
    "self cpu time":                     "cpu_time_ms",
    "elapsed time":                      "cpu_time_ms",
    "cpu time:self":                     "cpu_time_ms",
    "cpu time (effective)":              "cpu_time_ms",
    # CPI / IPC
    "cpi rate":                          "cpi",
    "cpi":                               "cpi",
    "ipc":                               "ipc",
    # Cache
    "l3 cache miss rate":                "llc_miss_rate",
    "llc miss rate":                     "llc_miss_rate",
    "l3 bound":                          "mem_bound_pct",
    # Top-Down Microarchitecture Analysis
    "memory bound":                      "mem_bound_pct",
    "memory bound (%)":                  "mem_bound_pct",
    "core bound":                        "compute_bound_pct",
    "compute bound":                     "compute_bound_pct",
    # Vectorization
    "vectorization (%)" :                "vectorization_pct",
    "fp arith scalar single-precision":  "scalar_fp_pct",
    # Arithmetic intensity / GFLOP
    "arithmetic intensity":              "arithmetic_intensity",
    "gflops":                            "gflops",
}


def _norm_col(col: str) -> str:
    return col.strip().lower()


class VTuneParser:
    """Parse VTune hotspot / general-exploration / memory-access reports."""

    def parse(
        self,
        report_path: Optional[Path],
        source: Optional[Path] = None,
    ) -> ProfileData:

        if report_path is None:
            report_path = self._auto_discover()

        if report_path is None:
            return self._empty(source)

        suffix = report_path.suffix.lower()
        if suffix == ".csv":
            return self._parse_csv(report_path, source)
        elif suffix in (".xml", ".xsl"):
            return self._parse_xml(report_path, source)
        else:
            # Try CSV first
            try:
                return self._parse_csv(report_path, source)
            except Exception:
                return self._empty(source)

    # ── CSV ─────────────────────────────────────────────────────────────────

    def _parse_csv(self, path: Path, source: Optional[Path]) -> ProfileData:
        raw = path.read_text(errors="replace")

        # VTune CSV may have metadata lines before the header; find the header
        lines = raw.splitlines()
        header_idx = 0
        for i, line in enumerate(lines):
            if "Function" in line or "CPU Time" in line or "Symbol" in line:
                header_idx = i
                break

        csv_text = "\n".join(lines[header_idx:])
        reader = csv.DictReader(io.StringIO(csv_text))

        # Build alias → field mapping for this file's actual columns
        col_map: dict[str, str] = {}
        if reader.fieldnames:
            for raw_col in reader.fieldnames:
                canon = _COLUMN_ALIASES.get(_norm_col(raw_col))
                if canon:
                    col_map[raw_col] = canon

        hotspots: list[Hotspot] = []
        total_time = 0.0

        for row in reader:
            mapped: dict[str, str] = {col_map[k]: v for k, v in row.items() if k in col_map}

            cpu_ms = self._float(mapped.get("cpu_time_ms", "0"))
            if cpu_ms == 0 and "ipc" in mapped:
                continue  # skip summary rows

            total_time += cpu_ms
            hotspots.append(Hotspot(
                function=mapped.get("function", "unknown"),
                module=mapped.get("module", ""),
                source_file=mapped.get("source_file"),
                start_line=int(self._float(mapped.get("start_line", "0"))),
                cpu_time_pct=0.0,          # computed after total is known
                cpu_time_ms=cpu_ms,
                cpi=self._opt_float(mapped.get("cpi")),
                llc_miss_rate=self._opt_pct(mapped.get("llc_miss_rate")),
                mem_bound_pct=self._opt_pct(mapped.get("mem_bound_pct")),
                compute_bound_pct=self._opt_pct(mapped.get("compute_bound_pct")),
                vectorization_pct=self._opt_pct(mapped.get("vectorization_pct")),
                gflops=self._opt_float(mapped.get("gflops")),
                arithmetic_intensity=self._opt_float(mapped.get("arithmetic_intensity")),
                metadata=dict(row),
            ))

        # Back-fill percentages
        for h in hotspots:
            h.cpu_time_pct = (h.cpu_time_ms / total_time * 100) if total_time > 0 else 0.0

        # Build roofline points for any hotspot with AI data
        roofline = [
            RooflinePoint(
                label=h.function,
                arithmetic_intensity=h.arithmetic_intensity,
                achieved_gflops=h.gflops or 0.0,
            )
            for h in hotspots
            if h.arithmetic_intensity is not None and h.gflops is not None
        ]

        return ProfileData(
            tool="vtune",
            source=source,
            report_path=path,
            total_time_ms=total_time,
            hotspots=sorted(hotspots, key=lambda h: h.cpu_time_ms, reverse=True),
            roofline_points=roofline,
        )

    # ── XML ─────────────────────────────────────────────────────────────────

    def _parse_xml(self, path: Path, source: Optional[Path]) -> ProfileData:
        tree = ET.parse(str(path))
        root = tree.getroot()

        hotspots: list[Hotspot] = []
        total_time = 0.0

        # VTune XML structure varies by version; handle common layouts
        for func in root.iter("function"):
            name   = func.attrib.get("name", func.attrib.get("id", "unknown"))
            module = func.attrib.get("module", "")

            cpu_ms = self._float(func.attrib.get("cpuTime",
                                  func.findtext("cpuTime") or "0"))
            total_time += cpu_ms

            h = Hotspot(
                function=name,
                module=module,
                source_file=func.attrib.get("sourceFile"),
                start_line=int(self._float(func.attrib.get("startLine", "0"))),
                cpu_time_pct=0.0,
                cpu_time_ms=cpu_ms,
                cpi=self._opt_float(func.attrib.get("cpiRate")),
                llc_miss_rate=self._opt_pct(func.attrib.get("l3CacheMissRate")),
                mem_bound_pct=self._opt_pct(func.attrib.get("memoryBound")),
                compute_bound_pct=self._opt_pct(func.attrib.get("coreBound")),
                vectorization_pct=self._opt_pct(func.attrib.get("vectorizationPct")),
                gflops=self._opt_float(func.attrib.get("gflops")),
                arithmetic_intensity=self._opt_float(func.attrib.get("arithmeticIntensity")),
            )
            hotspots.append(h)

        for h in hotspots:
            h.cpu_time_pct = (h.cpu_time_ms / total_time * 100) if total_time > 0 else 0.0

        return ProfileData(
            tool="vtune",
            source=source,
            report_path=path,
            total_time_ms=total_time,
            hotspots=sorted(hotspots, key=lambda h: h.cpu_time_ms, reverse=True),
        )

    # ── Auto-discovery ───────────────────────────────────────────────────────

    def _auto_discover(self) -> Optional[Path]:
        """Try to find a VTune result directory and export CSV from it."""
        vtune = shutil.which("vtune")
        if not vtune:
            return None

        # Look for r???hs directories (VTune default names)
        results = sorted(Path(".").glob("r???hs"))
        if not results:
            results = sorted(Path(".").glob("vtune_*"))
        if not results:
            return None

        result_dir = results[-1]
        out_csv = Path("/tmp/perflens_vtune_hotspots.csv")
        try:
            subprocess.run(
                [vtune, "-report", "hotspots", "-format", "csv",
                 "-r", str(result_dir), "-report-output", str(out_csv)],
                check=True, capture_output=True,
            )
            return out_csv if out_csv.exists() else None
        except subprocess.CalledProcessError:
            return None

    # ── Helpers ──────────────────────────────────────────────────────────────

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
    def _opt_float(v: Optional[str]) -> Optional[float]:
        if v is None or str(v).strip() in ("", "-", "N/A", "n/a"):
            return None
        v = re.sub(r"[,%\s]", "", str(v))
        try:
            return float(v)
        except ValueError:
            return None

    @staticmethod
    def _opt_pct(v: Optional[str]) -> Optional[float]:
        """Parse percentage string '12.3%' → 0.123"""
        if v is None or str(v).strip() in ("", "-", "N/A"):
            return None
        v = re.sub(r"[%\s]", "", str(v))
        try:
            return float(v) / 100.0
        except ValueError:
            return None

    @staticmethod
    def _empty(source: Optional[Path]) -> ProfileData:
        return ProfileData(
            tool="vtune", source=source, report_path=None,
            total_time_ms=0.0, hotspots=[], roofline_points=[],
        )

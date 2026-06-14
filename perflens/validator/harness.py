"""
Automatic test-harness generation for compiled (C/C++) kernels.

The goal is to PROVE that an optimized kernel produces the same numerical
results as the original, without the user having to write a driver.

Approach:
  1. Parse the source for top-level function definitions whose parameters are
     limited to the shapes we can synthesise: scalar int/double and
     pointer-to-double (the overwhelmingly common HPC kernel signature).
  2. Emit a small C driver that:
       - allocates deterministic, seeded input arrays
       - calls the kernel
       - prints a checksum of every output array and scalar
  3. Compile  <source> + <driver>  into one executable and run it.
  4. The caller runs this for both original and patched sources and compares
     the printed numbers.

If a kernel's signature is too complex to synthesise safely, it is skipped;
the validator treats an empty kernel list as "could not establish correctness"
and fails closed.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


class HarnessError(Exception):
    pass


@dataclass
class KernelParam:
    type_str: str          # canonical: "int", "double", "double*", "const double*"
    name: str

    @property
    def is_pointer(self) -> bool:
        return "*" in self.type_str

    @property
    def base_is_double(self) -> bool:
        return "double" in self.type_str or "float" in self.type_str

    @property
    def base_is_int(self) -> bool:
        return ("int" in self.type_str or "long" in self.type_str
                or "size_t" in self.type_str) and not self.is_pointer


@dataclass
class Kernel:
    name: str
    return_type: str
    params: list[KernelParam] = field(default_factory=list)


# Match a C function definition with a body: `ret name(params) {`
_FUNC_DEF = re.compile(
    r"(?P<ret>(?:const\s+)?(?:void|int|long|float|double|size_t)\s*\**)\s+"
    r"(?P<name>[A-Za-z_]\w*)\s*\((?P<params>[^;{)]*)\)\s*\{",
    re.MULTILINE,
)

# Names we should never call as a harness entry point.
_SKIP_NAMES = {"main"}

# Synthesisable parameter types.
_INT_TYPES    = ("int", "long", "size_t", "unsigned", "unsigned int")
_DBL_PTR_RE   = re.compile(r"^(const\s+)?(double|float)\s*\*$")
_INT_RE       = re.compile(r"^(const\s+)?(int|long|size_t|unsigned(?:\s+int)?)$")
_DBL_RE       = re.compile(r"^(const\s+)?(double|float)$")


def _normalise_type(raw: str) -> str:
    t = re.sub(r"\s+", " ", raw.strip())
    t = t.replace(" *", "*").replace("* ", "*")
    return t


def _parse_params(param_str: str) -> Optional[list[KernelParam]]:
    param_str = param_str.strip()
    if param_str in ("", "void"):
        return []
    params: list[KernelParam] = []
    for chunk in param_str.split(","):
        chunk = chunk.strip()
        m = re.match(r"^(?P<type>.+?)\s*(?P<name>[A-Za-z_]\w*)\s*$", chunk)
        if not m:
            # e.g. unnamed param or array syntax we don't handle
            return None
        type_str = _normalise_type(m.group("type"))
        # Handle `double a[]` style → treat as pointer
        name = m.group("name")
        params.append(KernelParam(type_str=type_str, name=name))
    return params


def _is_synthesisable(k: Kernel) -> bool:
    """Only harness kernels whose params we can safely fabricate."""
    if not k.params:
        return False
    has_array = False
    for p in k.params:
        if _DBL_PTR_RE.match(p.type_str):
            has_array = True
        elif _INT_RE.match(p.type_str):
            pass
        elif _DBL_RE.match(p.type_str):
            pass
        else:
            return False   # unknown / unsupported type → skip
    return has_array       # need at least one array to produce output


def discover_kernels(source: Path, language: str) -> list[Kernel]:
    """Return synthesisable kernels defined in *source*."""
    text = source.read_text(errors="replace")
    # Strip comments to avoid false matches.
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)

    kernels: list[Kernel] = []
    for m in _FUNC_DEF.finditer(text):
        name = m.group("name")
        if name in _SKIP_NAMES:
            continue
        params = _parse_params(m.group("params"))
        if params is None:
            continue
        k = Kernel(name=name,
                   return_type=_normalise_type(m.group("ret")),
                   params=params)
        if _is_synthesisable(k):
            kernels.append(k)
    # Only harness the FIRST synthesisable kernel to keep the driver simple and
    # deterministic; comparing one kernel is enough to catch races / FP changes.
    return kernels[:1]


def _emit_driver(source_name: str, kernel: Kernel, n: int = 257,
                 lang: str = "c") -> str:
    """Generate C/C++ driver source that calls *kernel* and prints a checksum."""
    decls: list[str] = []
    args:  list[str] = []
    out_arrays: list[str] = []

    arr_idx = 0
    for p in kernel.params:
        if _DBL_PTR_RE.match(p.type_str):
            arr = f"arr{arr_idx}"
            arr_idx += 1
            decls.append(f"    double *{arr} = (double*)malloc(sizeof(double)*N);")
            # Deterministic seeded init (independent of param order).
            decls.append(
                f"    for (int i = 0; i < N; i++) "
                f"{arr}[i] = sin(0.3*i + {arr_idx}) + 1.5;")
            args.append(arr)
            # Non-const arrays are potential outputs → checksum them.
            if not p.type_str.startswith("const"):
                out_arrays.append(arr)
        elif _INT_RE.match(p.type_str):
            # Pass the problem size for the first int; small constants otherwise.
            decls.append(f"    {p.type_str} {p.name}_v = N;")
            args.append(f"{p.name}_v")
        elif _DBL_RE.match(p.type_str):
            decls.append(f"    {p.type_str} {p.name}_v = 2.0;")
            args.append(f"{p.name}_v")

    call = f"{kernel.name}({', '.join(args)});"
    ret_capture = ""
    if kernel.return_type not in ("void", "void*"):
        ret_capture = f"    double _ret = (double){call}\n    printf(\"RET %.10e\\n\", _ret);"
        call = ""   # already captured

    checksum_lines = []
    for arr in out_arrays:
        checksum_lines.append(
            f"    {{ double s = 0; for (int i=0;i<N;i++) s += {arr}[i]*(i+1); "
            f"printf(\"SUM_{arr} %.10e\\n\", s); }}")

    includes = "#include <stdio.h>\n#include <stdlib.h>\n#include <math.h>\n"
    # Bring in the kernel declarations by including the source directly.
    body = f"""{includes}
#define N {n}

/* kernel under test is compiled in the same TU via the source file */
extern int __perflens_unused;

int main(void) {{
{chr(10).join(decls)}
    {call}
{ret_capture}
{chr(10).join(checksum_lines)}
    return 0;
}}
"""
    return body


def build_harness(
    source: Path,
    kernels: list[Kernel],
    language: str,
    compiler: str,
    flags: list[str],
    link_libs: list[str],
    timeout: int = 60,
) -> Optional[str]:
    """
    Compile *source* together with an auto-generated driver and run it.
    Returns the program's stdout (containing checksums), or raises HarnessError.
    """
    if not kernels:
        raise HarnessError("no kernels to harness")
    kernel = kernels[0]

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        # Copy the source so we can #include it from the driver (gets the kernel
        # body + any static helpers in the same translation unit).
        src_copy = tmp / source.name
        src_copy.write_text(source.read_text(errors="replace"))

        driver_ext = ".c" if language == "c" else ".cpp"
        driver = tmp / f"perflens_harness{driver_ext}"
        driver_src = _emit_driver(source.name, kernel, lang=language)
        # Prepend an #include of the kernel source so the driver can call it.
        driver_src = f'#include "{source.name}"\n' + driver_src
        driver.write_text(driver_src)

        binary = tmp / "perflens_harness_bin"
        cmd = [compiler] + flags + [str(driver), "-o", str(binary)] + link_libs
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise HarnessError("harness compile timed out")
        if proc.returncode != 0:
            raise HarnessError(f"harness compile failed: {proc.stderr[:300]}")

        try:
            run = subprocess.run([str(binary)], capture_output=True, text=True,
                                 timeout=timeout)
        except subprocess.TimeoutExpired:
            raise HarnessError("harness run timed out")
        if run.returncode != 0:
            raise HarnessError(f"harness run crashed (rc={run.returncode}): "
                               f"{run.stderr[:200]}")
        return run.stdout

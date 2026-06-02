from __future__ import annotations

import argparse
import math
import time


def kernel(values: list[float]) -> list[float]:
    output: list[float] = []
    for value in values:
        output.append(math.sqrt(value) + math.sin(value))
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", action="store_true")
    args = parser.parse_args()

    values = [float(item) for item in range(20000 if args.benchmark else 100)]
    started = time.perf_counter()
    output = kernel(values)
    duration = time.perf_counter() - started
    if args.benchmark:
        print(f"benchmark_seconds={duration:.6f}")
    else:
        print(f"checksum={sum(output):.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


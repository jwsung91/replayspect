"""Where a defect fired, computed after the run from the device log (the Uno build does not write it).

The device log's inputs (its ``recv`` lines, at their milliseconds) are fed to the native harness built
with the same defect and with ``-DLIFT_FIRED_LOG=1``. The harness runs the same ``lift_device.h`` as
the Uno, so it fires where the Uno fired, provided it does what the Uno did. That is checked first:
every ``send``, ``state`` and ``effect`` line of the device log must come out of the harness in the
same millisecond (as a multiset per millisecond). If they differ, the points are not trusted.

Usage (development machine, a C++ compiler; not the Orin):
    python3 fired_points.py DEVICE_LOG --defect N        (N: 0 none, or 1 2 4 5 9 10 11)
Prints one JSON line per firing, {"t_ms": T, "defect": "MN", "req_id": ID}, and exits 0; exits 1, naming
the first difference, when the harness does not reproduce the log; 2 on bad input.
Truth material: run it outside the repository, after the analysis it scores.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

HARNESS = Path(__file__).with_name("harness.cpp")
_LINE = re.compile(r"^\S+ # (\d+) (recv|send|state|effect) (.*)$")
_FIRED = re.compile(r"^(\d+) LOG defect fired (M\d+) (\S+)$")


def build(defect: int, out_dir: str | Path, cxx: str | None = None) -> Path:
    """The harness with ``-DLIFT_DEFECT=defect -DLIFT_FIRED_LOG=1``."""
    cxx = cxx or shutil.which("g++") or shutil.which("c++") or shutil.which("clang++")
    if cxx is None:
        raise RuntimeError("no C++ compiler")
    exe = Path(out_dir) / f"harness-fired-{defect}"
    subprocess.run([cxx, "-std=c++11", "-O1", f"-DLIFT_DEFECT={defect}", "-DLIFT_FIRED_LOG=1", "-o", str(exe),
                    str(HARNESS)], check=True)
    return exe


def read(text: str) -> list[tuple[int, str, str]]:
    """The device log's (ms, kind, rest) for recv, send, state and effect lines, in order."""
    out = []
    for line in text.splitlines():
        m = _LINE.match(line)
        if m:
            out.append((int(m[1]), m[2], m[3]))
    return out


def fired_points(text: str, exe: str | Path) -> tuple[list[dict], str | None]:
    """``(points, problem)``: the firings, and None, or the first difference between harness and log."""
    log = read(text)
    if not log:
        return [], "no recv, send, state or effect line"
    feed = "".join(f"{ms} {rest}\n" for ms, kind, rest in log if kind == "recv") + f"END {log[-1][0]}\n"
    out = subprocess.run([str(exe)], input=feed, capture_output=True, text=True, check=True).stdout.splitlines()
    got: Counter = Counter()
    points = []
    for row in out:
        f = _FIRED.match(row)
        if f:
            points.append({"t_ms": int(f[1]), "defect": f[2], "req_id": f[3]})
            continue
        t, kind, body = row.split(" ", 2)
        if kind == "LOG" and body.split(" ", 1)[0] in ("send", "state", "effect"):
            got[(int(t), body)] += 1
    want = Counter((ms, f"{kind} {rest}") for ms, kind, rest in log if kind != "recv")
    if got != want:
        miss, extra = sorted(want - got), sorted(got - want)
        first = min(miss[:1] + extra[:1])
        side = "in the device log, not from the harness" if miss[:1] == [first] else "from the harness, not in the log"
        return points, f"the harness does not reproduce the device log: {first[0]} ms '{first[1]}' {side}"
    return points, None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("device_log")
    ap.add_argument("--defect", type=int, required=True, help="the build's defect number (0: none)")
    ap.add_argument("--cxx", help="C++ compiler (default: g++, c++ or clang++)")
    args = ap.parse_args(argv)
    try:
        text = Path(args.device_log).read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as d:
            points, problem = fired_points(text, build(args.defect, d, args.cxx))
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"fired_points: {exc}", file=sys.stderr)
        return 2
    if problem:
        print(f"fired_points: {problem}", file=sys.stderr)
        return 1
    for p in points:
        print(json.dumps(p, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

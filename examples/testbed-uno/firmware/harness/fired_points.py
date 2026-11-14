"""Where a defect fired, computed after the run from the device log (the Uno build does not write it).

The device log's inputs (its ``recv`` lines, at their milliseconds) are fed to the native harness built
with the same defect and with ``-DLIFT_FIRED_LOG=1``. The harness runs the same ``lift_device.h`` as
the Uno, so it fires where the Uno fired, provided it does what the Uno did. That is checked first:
every ``send``, ``state`` and ``effect`` line of the device log must come out of the harness in the
same millisecond (as a multiset per millisecond). If they differ, the points are not trusted.

With ``--reference DIR`` it answers the same question for a change nobody named (the blind group):
the firmware this script sits in (``../lift_uno/lift_device.h``, changed) and the one in ``DIR``
(a copy of ``examples/testbed-uno/firmware``, unchanged) are both run on the device log's inputs,
after checking that the changed one reproduces the log, and the first output line where they differ
is where the change first acted. No defect switch or "defect fired" line is needed.

Usage (development machine or the operator's computer, a C++ compiler; not the Orin):
    python3 fired_points.py DEVICE_LOG --defect N        (N: 0 none, or 1 2 4 5 9 10 11)
    python3 fired_points.py DEVICE_LOG --reference DIR   (this tree changed, DIR unchanged; --defect 0)
Prints one JSON line per firing, {"t_ms": T, "defect": "MN", "req_id": ID}; with --reference, one JSON
line {"t_ms", "req_id", "changed", "reference"} for the first difference, or {"difference": null} when
the change did not act on this log's inputs. Exits 0; 1, naming the first difference, when the harness
does not reproduce the log; 2 on bad input.
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


def build(defect: int, out_dir: str | Path, cxx: str | None = None, harness: str | Path = HARNESS,
          name: str | None = None) -> Path:
    """The harness (this tree's, or ``harness``) with ``-DLIFT_DEFECT=defect -DLIFT_FIRED_LOG=1``."""
    cxx = cxx or shutil.which("g++") or shutil.which("c++") or shutil.which("clang++")
    if cxx is None:
        raise RuntimeError("no C++ compiler")
    exe = Path(out_dir) / (name or f"harness-fired-{defect}")
    subprocess.run([cxx, "-std=c++11", "-O1", f"-DLIFT_DEFECT={defect}", "-DLIFT_FIRED_LOG=1", "-o", str(exe),
                    str(harness)], check=True)
    return exe


def read(text: str) -> list[tuple[int, str, str]]:
    """The device log's (ms, kind, rest) for recv, send, state and effect lines, in order."""
    out = []
    for line in text.splitlines():
        m = _LINE.match(line)
        if m:
            out.append((int(m[1]), m[2], m[3]))
    return out


def _feed(log: list[tuple[int, str, str]]) -> str:
    return "".join(f"{ms} {rest}\n" for ms, kind, rest in log if kind == "recv") + f"END {log[-1][0]}\n"


def _run(exe: str | Path, feed: str) -> list[str]:
    return subprocess.run([str(exe)], input=feed, capture_output=True, text=True, check=True).stdout.splitlines()


def fired_points(text: str, exe: str | Path) -> tuple[list[dict], str | None]:
    """``(points, problem)``: the firings, and None, or the first difference between harness and log."""
    log = read(text)
    if not log:
        return [], "no recv, send, state or effect line"
    out = _run(exe, _feed(log))
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


def _req_id(kind: str, body: str) -> str | None:
    """The request id of a harness output line: the word after the message (OUT) or after the
    event's kind and name (LOG), when there is one."""
    words = body.split()
    i = 1 if kind == "OUT" else 2
    return words[i] if len(words) > i and "=" not in words[i] else None


def first_difference(text: str, changed: str | Path, reference: str | Path) -> tuple[dict | None, str | None]:
    """``(difference, problem)``: where the changed harness first differs from the reference one on the
    device log's inputs (None when they never differ), after checking that the changed one
    reproduces the log; or the problem."""
    _, problem = fired_points(text, changed)
    if problem:
        return None, problem
    feed = _feed(read(text))
    # behaviour only: the build line and the fired lines say what was built, not what it did
    a, b = ([r for r in _run(x, feed) if " LOG defect fired " not in r and " LOG build " not in r]
            for x in (changed, reference))
    for i in range(max(len(a), len(b))):
        x = a[i] if i < len(a) else None
        y = b[i] if i < len(b) else None
        if x != y:
            lines = [r.split(" ", 2) for r in (x, y) if r is not None]
            t, kind, body = min(lines, key=lambda r: int(r[0]))  # the earlier of the two
            return {"t_ms": int(t), "req_id": _req_id(kind, body), "changed": x, "reference": y}, None
    return None, None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("device_log")
    ap.add_argument("--defect", type=int, help="the build's defect number (0: none; default 0)")
    ap.add_argument("--reference", metavar="DIR",
                    help="an unchanged copy of examples/testbed-uno/firmware: report where this tree's "
                         "(changed) firmware first acts differently on the log's inputs")
    ap.add_argument("--cxx", help="C++ compiler (default: g++, c++ or clang++)")
    args = ap.parse_args(argv)
    if args.defect is None and args.reference is None:
        ap.error("give --defect N, or --reference DIR")
    try:
        text = Path(args.device_log).read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as d:
            changed = build(args.defect or 0, d, args.cxx)
            if args.reference:
                ref_h = Path(args.reference) / "harness" / "harness.cpp"
                if not ref_h.is_file():
                    raise OSError(f"--reference: no {ref_h}")
                ref = build(0, d, args.cxx, ref_h, "harness-reference")
                diff, problem = first_difference(text, changed, ref)
                points = [diff if diff is not None else {"difference": None}]
            else:
                points, problem = fired_points(text, changed)
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

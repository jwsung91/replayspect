"""After an upload: does the board run the expected system and build? (WP6/7c stage 1)

Opens the port (which resets the board), reads its boot lines for a few seconds, and checks the build
line: its system (no ``system=`` field: lift.v0) and its defect field. Run it only after an upload.
Before one, the flash script checks only that the port is the system's path in boards.env: on its
first flash a board does not yet carry the firmware it is meant for.

Usage (on the Orin):  python3 board_check.py --port /dev/serial/by-id/... --expect-system turntable.v0
Exit status 0 when both match, 3 when the build line names another system or build, 4 when no build line
came (a blank board, or the wrong baud rate). Prints only what the line says, to the operator's terminal.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fault_link import build_fields  # noqa: E402


def check(lines: list[str], expect_system: str, expect_build: str) -> tuple[int, str]:
    """``(exit status, what was found)`` from the board's boot lines."""
    for line in lines:
        parts = line.split()
        if line.startswith("#") and len(parts) >= 3 and parts[2] == "build":
            system, defect = build_fields(line)
            found = f"{system} defect={defect}"
            return (0 if (system, defect) == (expect_system, expect_build) else 3), found
    return 4, "no build line"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--expect-system", required=True, choices=["lift.v0", "turntable.v0"])
    ap.add_argument("--expect-build", default="none", help="the build line's defect field (default none)")
    ap.add_argument("--seconds", type=float, default=3.0)
    args = ap.parse_args(argv)
    import serial  # pyserial

    with serial.Serial(args.port, args.baud, timeout=0.1) as port:  # opening resets the Uno
        end, buf = time.monotonic() + args.seconds, b""
        while time.monotonic() < end:
            buf += port.read(256)
            code, found = check(buf.decode("ascii", "replace").splitlines(), args.expect_system, args.expect_build)
            if code != 4 and buf.endswith(b"\n"):
                break
    code, found = check(buf.decode("ascii", "replace").splitlines(), args.expect_system, args.expect_build)
    print(f"{'ok' if code == 0 else 'WRONG' if code == 3 else 'NO BUILD LINE'}: {found}; expected "
          f"{args.expect_system} defect={args.expect_build}")
    return code


if __name__ == "__main__":
    sys.exit(main())

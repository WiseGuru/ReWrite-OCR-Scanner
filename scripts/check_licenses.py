"""CI gate: fail loudly if any installed dependency carries a copyleft
license with no permissive alternative.

License expressions with OR pass when any branch is acceptable (PySide6 is
'LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only'; we elect the LGPL branch
and link dynamically). AND expressions require every part to be acceptable.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys

ALLOWED_PATTERNS = [
    r"^MIT\b", r"^MIT-CMU$", r"^BSD", r"^0BSD$", r"^Apache", r"^PSF",
    r"^Python Software Foundation", r"^LGPL", r"^GNU Library or Lesser",
    r"^Zlib$", r"^CC0-1\.0$", r"^ISC", r"^Unlicense$", r"^The Unlicense",
    r"^HPND", r"^Historical Permission",
    # pypdfium2 metadata names its own licenses then defers to PDFium's
    # (BSD-3-Clause and Apache-2.0).
    r"^dependency licenses$",
]
# Our own package, plus build-time-only tools that never ship in any
# distributed artifact. PyInstaller is GPL-2.0 with the bootloader
# exception, which explicitly does not extend to the bundled output.
IGNORED_PACKAGES = {
    "rewrite-ocr-scanner",
    "pyinstaller",
    "pyinstaller-hooks-contrib",
}


def branch_ok(branch: str) -> bool:
    parts = [p.strip() for p in re.split(r"\bAND\b|,", branch) if p.strip()]
    return all(
        any(re.search(pat, part, re.IGNORECASE) for pat in ALLOWED_PATTERNS)
        for part in parts
    )


def license_ok(expression: str) -> bool:
    return any(branch_ok(b) for b in re.split(r"\bOR\b", expression))


def main() -> int:
    raw = subprocess.run(
        [sys.executable, "-m", "piplicenses", "--format=json"],
        capture_output=True, text=True, check=True,
    ).stdout
    failures = []
    for entry in json.loads(raw):
        name = entry["Name"]
        if name.lower() in IGNORED_PACKAGES:
            continue
        expression = entry["License"]
        if "AGPL" in expression.upper():
            failures.append((name, expression))
            continue
        if not license_ok(expression):
            failures.append((name, expression))
    if failures:
        print("License gate FAILED for:")
        for name, expression in failures:
            print(f"  {name}: {expression}")
        return 1
    print("License gate passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

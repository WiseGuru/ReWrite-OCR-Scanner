"""CI gate: no em dashes or en dashes in tracked source and docs.

House style replaces the 'label em-dash expansion' construction with a
colon; ranges use a plain hyphen. This script is the character-level check
documenting that rule, so the two dash characters appear here as escapes.
"""

from __future__ import annotations

import subprocess
import sys

DASHES = ("—", "–")  # em dash, en dash
CHECKED_SUFFIXES = (".py", ".md", ".toml", ".json", ".yml", ".yaml", ".spec")
EXEMPT = {
    # The project specification is quoted source material from its author.
    "ocr-app-spec.md",
    # This file: the dash characters are its subject.
    "scripts/check_dashes.py",
}


def main() -> int:
    # Untracked-but-not-ignored files count too. Listing only tracked files
    # meant every new file passed locally and failed in CI on the commit that
    # first tracked it, which is the worst possible time to find out.
    files = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    failures = []
    for path in files:
        if not path.endswith(CHECKED_SUFFIXES) or path in EXEMPT:
            continue
        try:
            text = open(path, encoding="utf-8").read()
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if any(d in line for d in DASHES):
                failures.append(f"{path}:{i}: {line.strip()[:80]}")
    if failures:
        print("Dash gate FAILED:")
        print("\n".join(failures))
        return 1
    print("Dash gate passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

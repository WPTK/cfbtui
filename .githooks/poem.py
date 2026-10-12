"""Commit-message poem checks shared by the commit-msg and pre-push hooks.

Usage:
    python .githooks/poem.py check-file PATH   # commit-msg: validate one message file
    python .githooks/poem.py check-push        # pre-push: reads ref lines on stdin

Exit code 1 means the commit (or push) is refused.
"""
from __future__ import annotations

import re
import subprocess
import sys

# Form name -> expected poem line count (None = not checked).
FORMS: dict[str, int | None] = {
    "haiku": 3,
    "tanka": 5,
    "villanelle": 19,
    "sestina": 39,
    "duplex": 14,
    "cleave": None,
}
ALIASES = {"tanku": "tanka", "cleave poem": "cleave"}

# Only these trailer keys are recognised, so a poem line that happens to
# contain "word: more" is never mistaken for metadata.
KNOWN_TRAILERS = ("poetic-form", "co-authored-by", "signed-off-by")
TRAILER_RE = re.compile(r"^([A-Za-z][A-Za-z-]*):\s*(.*)$")
ZERO_SHA = "0" * 40


def normalize_form(value: str) -> str:
    v = " ".join(value.strip().lower().split())
    return ALIASES.get(v, v)


def split_message(text: str) -> tuple[list[str], dict[str, str]]:
    """Return (poem_lines, trailers).

    Git comment lines are ignored. A trailer is any line whose key is in
    KNOWN_TRAILERS, wherever it sits, so a blank line between trailers does
    not hide the form. Everything else that is non-blank is the poem.
    """
    lines = [ln.rstrip("\r") for ln in text.splitlines() if not ln.startswith("#")]
    trailers: dict[str, str] = {}
    poem: list[str] = []
    for ln in lines:
        m = TRAILER_RE.match(ln)
        if m and m.group(1).lower() in KNOWN_TRAILERS:
            trailers[m.group(1).lower()] = m.group(2)
        elif ln.strip():
            poem.append(ln)
    return poem, trailers


def check(text: str) -> tuple[list[str], list[str]]:
    """Return (errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []
    poem, trailers = split_message(text)
    raw = trailers.get("poetic-form")
    if raw is None:
        errors.append("missing `Poetic-Form:` trailer (one of: " + ", ".join(FORMS) + ")")
        return errors, warnings
    form = normalize_form(raw)
    if form not in FORMS:
        errors.append(f"unknown poetic form {raw!r}; expected one of: " + ", ".join(FORMS))
        return errors, warnings
    expected = FORMS[form]
    if not poem:
        errors.append("the commit message has no poem")
    elif expected is not None and len(poem) != expected:
        warnings.append(f"a {form} has {expected} lines; this message has {len(poem)}")
    return errors, warnings


def check_file(path: str) -> int:
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    errors, warnings = check(text)
    for w in warnings:
        print(f"poem: warning: {w}", file=sys.stderr)
    for e in errors:
        print(f"poem: error: {e}", file=sys.stderr)
    if errors:
        print("poem: commit refused. Every commit is a poem with a `Poetic-Form:` trailer.", file=sys.stderr)
        return 1
    return 0


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def check_push() -> int:
    bad: list[tuple[str, str]] = []
    for line in sys.stdin:
        parts = line.split()
        if len(parts) != 4:
            continue
        _local_ref, local_sha, _remote_ref, remote_sha = parts
        if local_sha == ZERO_SHA:
            continue  # branch deletion
        if remote_sha == ZERO_SHA:
            rev_args = [local_sha, "--not", "--remotes"]
        else:
            rev_args = [f"{remote_sha}..{local_sha}"]
        shas = _git("rev-list", *rev_args).split()
        for sha in shas:
            msg = _git("log", "-1", "--format=%B", sha)
            errors, _ = check(msg)
            if errors:
                bad.append((sha[:10], "; ".join(errors)))
    for sha, why in bad:
        print(f"poem: {sha}: {why}", file=sys.stderr)
    if bad:
        print("poem: push refused. Amend or rebase so every commit declares its poetic form.", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "check-file":
        return check_file(argv[1])
    if len(argv) >= 1 and argv[0] == "check-push":
        return check_push()
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

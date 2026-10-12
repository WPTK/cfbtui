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

TRAILER_RE = re.compile(r"^([A-Za-z][A-Za-z-]*):\s*(.*)$")
ZERO_SHA = "0" * 40


def normalize_form(value: str) -> str:
    v = value.strip().lower()
    v = re.sub(r"\s+poem$", "", v)
    return v


def split_message(text: str) -> tuple[list[str], dict[str, str]]:
    """Return (poem_lines, trailers). Comment lines are ignored; the trailer
    block is the final paragraph when every line in it looks like `Key: value`."""
    lines = [ln.rstrip("\r") for ln in text.splitlines() if not ln.startswith("#")]
    # Drop trailing blank lines.
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return [], {}
    # Find the last paragraph.
    idx = len(lines)
    while idx > 0 and lines[idx - 1].strip():
        idx -= 1
    last_para = lines[idx:]
    trailers: dict[str, str] = {}
    if last_para and all(TRAILER_RE.match(ln) for ln in last_para):
        for ln in last_para:
            m = TRAILER_RE.match(ln)
            assert m
            trailers[m.group(1).lower()] = m.group(2)
        body = lines[:idx]
    else:
        body = lines
    poem = [ln for ln in body if ln.strip()]
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

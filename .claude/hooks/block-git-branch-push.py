#!/usr/bin/env python3
"""PreToolUse guard: stop Claude from creating git branches or pushing.

Reads the Bash tool-call JSON from stdin, inspects the command (including
compound commands joined by &&, ||, ; or |), and exits 2 (blocking the tool)
if it would create a branch or push to a remote. Everything else — read-only
git, commit, status, diff, reset, checkout/switch to an EXISTING branch,
branch deletion — is allowed.
"""
import sys
import json
import re


def load_command() -> str:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return ""  # can't parse -> don't block
    return (data.get("tool_input") or {}).get("command", "") or ""


def violation(segment: str):
    """Return a human label if this single command segment is blocked, else None."""
    s = re.sub(r"\s+", " ", segment).strip()

    if re.search(r"\bgit\s+push\b", s):
        return "git push"
    if re.search(r"\bgit\s+checkout\s+-b\b", s, re.IGNORECASE):
        return "git checkout -b (branch creation)"
    if re.search(r"\bgit\s+switch\s+(-c|-C|--create)\b", s):
        return "git switch -c (branch creation)"
    if re.search(r"\bgit\s+worktree\s+add\b", s):
        return "git worktree add (creates a branch/worktree)"

    # `git branch <name>` creates a branch. Allow listing (no positional arg)
    # and deletion (-d/-D/--delete).
    m = re.search(r"\bgit\s+branch\b(.*)$", s)
    if m:
        toks = m.group(1).strip().split()
        is_delete = any(t in ("-d", "-D", "--delete") for t in toks)
        has_name = any(not t.startswith("-") for t in toks)
        if toks and has_name and not is_delete:
            return "git branch <name> (branch creation)"
    return None


def main() -> int:
    cmd = load_command()
    if not cmd:
        return 0
    # Split on command separators AND newlines so that e.g. `git branch` (list)
    # followed by a newline + another command isn't misread as `git branch <name>`.
    for segment in re.split(r"&&|\|\||;|\||\n|\r", cmd):
        hit = violation(segment)
        if hit:
            sys.stderr.write(
                f"BLOCKED: '{hit}' is disabled for Claude in this project.\n"
                "Creating branches and pushing to GitHub must be done manually by you.\n"
                "Please run this command yourself in your terminal.\n"
            )
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

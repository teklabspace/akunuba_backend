#!/usr/bin/env python3
"""PreToolUse guard: stop Claude from committing, pushing, or creating branches.

Reads the Bash/PowerShell tool-call JSON from stdin, inspects the command
(including compound commands joined by &&, ||, ; or |), and exits 2 (blocking
the tool) if it would:
  - git commit (any form)
  - git push
  - create a branch (git branch <name>, git checkout -b, git switch -c,
    git worktree add)
  - publish to GitHub (gh pr create/merge, gh repo create/fork/delete)

Everything else — read-only git (status, log, diff, branch listing), add,
restore, reset, checkout/switch to an EXISTING branch, branch deletion — is
allowed. These write operations are intended to be performed manually by the
user, not by Claude.
"""
import sys
import json
import re


def load_command() -> str:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return ""  # can't parse -> don't block
    # Both the Bash and PowerShell tools carry the command under tool_input.command.
    return (data.get("tool_input") or {}).get("command", "") or ""


# Matches `git` optionally followed by global flags (e.g. `-C <path>`, `-c k=v`,
# `--no-pager`) before the given subcommand, so forms like `git -C repo commit`
# are still caught.
_GIT_GLOBAL_FLAGS = r"(?:\s+-{1,2}\S+(?:\s+\S+)?)*"


def _git_subcommand(s: str, sub: str) -> bool:
    return re.search(rf"\bgit\b{_GIT_GLOBAL_FLAGS}\s+{sub}\b", s, re.IGNORECASE) is not None


def violation(segment: str):
    """Return a human label if this single command segment is blocked, else None."""
    s = re.sub(r"\s+", " ", segment).strip()

    if _git_subcommand(s, "commit"):
        return "git commit"
    if _git_subcommand(s, "push"):
        return "git push"
    if re.search(r"\bgit\s+checkout\s+-b\b", s, re.IGNORECASE):
        return "git checkout -b (branch creation)"
    if re.search(r"\bgit\s+switch\s+(-c|-C|--create)\b", s):
        return "git switch -c (branch creation)"
    if re.search(r"\bgit\s+worktree\s+add\b", s):
        return "git worktree add (creates a branch/worktree)"
    if re.search(r"\bgh\s+pr\s+(create|merge)\b", s, re.IGNORECASE):
        return "gh pr create/merge (publishes to GitHub)"
    if re.search(r"\bgh\s+repo\s+(create|fork|delete)\b", s, re.IGNORECASE):
        return "gh repo create/fork/delete"

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
                "Committing, pushing, and creating branches must be done manually by you.\n"
                "Please run this command yourself in your terminal.\n"
            )
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

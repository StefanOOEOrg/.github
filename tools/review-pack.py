#!/usr/bin/env python3
"""Generate the review pack for one pull request: the context a review needs, nothing else.

Usage: review-pack.py <owner/repo> <pr>

Prints one Markdown document to stdout and writes nothing to GitHub: every call is a
read-only ``gh`` call. A fork PR is therefore read through the API only - the script
never checks out a branch and never runs the code of a pull request.

Text that comes from issues and pull requests is data, not instruction: HTML comments
and invisible Unicode characters are removed, every block is fenced with a fence that
the text cannot close itself, and its length is capped.

The pack carries the goal and acceptance criteria of the task linked with
``Closes #<n>``, the parent feature (``Part of #<n>``) as "why", its out-of-scope
section, the CI result, the findings of earlier formal reviews, the round number
(counted from the Lead's *changes requested* reviews), the changed files outside the
task's ``Allowed files`` and the matching rows of ``LESSONS.md``.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
import sys
import unicodedata

LEAD = os.environ.get("LEAD_LOGIN", "StefanOOELeadBot")
GH_TIMEOUT = 60  # seconds per gh call; a hung call must not block the review run
MAX_TEXT = 4000  # characters per fenced block
MAX_TITLE = 200  # characters per heading or bullet
FAILED_STATES = {
    "FAILURE",
    "CANCELLED",
    "TIMED_OUT",
    "ACTION_REQUIRED",
    "ERROR",
    "STALE",
}
PASSED_STATES = {"SUCCESS", "NEUTRAL", "SKIPPED"}
PR_FIELDS = (
    "number,title,body,url,baseRefName,headRefName,isCrossRepository,"
    "headRepositoryOwner,files,reviews,statusCheckRollup"
)
ISSUE_FIELDS = "number,title,body,url,state"
CLOSES = re.compile(
    r"(?im)^\s*(?:closes|fixes|resolves)\s+(?:[\w.-]+/[\w.-]+)?#(\d+)\b"
)
PART_OF = re.compile(r"(?im)^\s*part of\s+(?:[\w.-]+/[\w.-]+)?#(\d+)\b")
HEADING = re.compile(r"^(#{2,3})\s+(.*?)\s*$")
TABLE_RULE = re.compile(r"\|[\s:|-]+\|")


def gh(*args: str) -> str:
    """Run one read-only ``gh`` call and return stdout.

    Only ``gh pr view``, ``gh issue view`` and ``gh api .../contents/`` are used, so
    nothing is written and a fork PR is only read through the API.
    """
    result = subprocess.run(
        ["gh", *args], check=True, capture_output=True, text=True, timeout=GH_TIMEOUT
    )
    return result.stdout


def clean(text: str, limit: int = MAX_TEXT) -> str:
    """Remove HTML comments and invisible Unicode, then cap the length."""
    text = re.sub(r"<!--.*?-->", "", text or "", flags=re.DOTALL)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cf").strip()
    if len(text) > limit:
        text = text[:limit] + f"\n… (truncated, {len(text)} characters)"
    return text


def one_line(text: str, limit: int = MAX_TITLE) -> str:
    """Sanitize a title and flatten it to one line."""
    return re.sub(r"\s+", " ", clean(text, limit)).strip()


def fenced(text: str, limit: int = MAX_TEXT) -> str:
    """Return the text as a fenced block that its own backticks cannot close."""
    body = clean(text, limit)
    runs = [len(run) for run in re.findall(r"`+", body)]
    fence = "`" * max(3, (max(runs) + 1) if runs else 3)
    return f"{fence}\n{body}\n{fence}"


def section(body: str, *names: str) -> str:
    """Return the text below a Markdown heading with one of the given names."""
    wanted = {name.lower() for name in names}
    collected: list[str] = []
    active = False
    for line in (body or "").splitlines():
        heading = HEADING.match(line)
        if heading:
            if active:
                break
            active = heading.group(2).strip().lower() in wanted
            continue
        if active:
            collected.append(line)
    return "\n".join(collected).strip()


def round_number(reviews: list[dict]) -> tuple[int, int]:
    """Return (round, changes requested) counted from the Lead's formal reviews."""
    changes = sum(
        1
        for review in reviews
        if (review.get("author") or {}).get("login") == LEAD
        and review.get("state") == "CHANGES_REQUESTED"
    )
    return changes + 1, changes


def allowed_files(task_body: str) -> list[str]:
    """Return the backticked paths on every line that speaks about 'Allowed files'."""
    patterns: list[str] = []
    for line in (task_body or "").splitlines():
        if "allowed files" in line.lower():
            patterns += re.findall(r"`([^`]+)`", line)
    return patterns


def lessons_rows(text: str, changed: list[str]) -> list[str]:
    """Return the table header and the rows that name a changed file or its directory."""
    tokens: set[str] = set()
    for path in changed:
        tokens.add(path)
        tokens.add(path.rsplit("/", 1)[-1])
        if "/" in path:
            tokens.add(path.split("/", 1)[0] + "/")
    table = [line for line in (text or "").splitlines() if line.strip().startswith("|")]
    if not table:
        return []
    header = table[0]
    rows = [row for row in table[1:] if not TABLE_RULE.fullmatch(row.strip())]
    matched = [row for row in rows if any(token in row for token in tokens)]
    return [header, *matched] if matched else []


def check_state(entry: dict) -> str:
    """Return the state of one status check, upper-cased."""
    return (entry.get("conclusion") or entry.get("state") or "PENDING").upper()


def ci_summary(rollup: list[dict]) -> tuple[str, list[tuple[str, str]]]:
    """Return (verdict, rows) for the status check rollup of the head commit."""
    if not rollup:
        return "no checks reported", []
    states = [check_state(entry) for entry in rollup]
    rows = [
        (entry.get("name") or entry.get("context") or "check", check_state(entry))
        for entry in rollup
    ]
    if any(state in FAILED_STATES for state in states):
        return "red", rows
    if all(state in PASSED_STATES for state in states):
        return f"green — {len(states)}/{len(states)} checks passed", rows
    return "pending", rows


def issue_heading(number: int, issue: dict | None) -> str:
    """Return '#<n> <title>' for a linked issue."""
    if not issue:
        return f"#{number}"
    return f"#{number} {one_line(issue.get('title') or '')}".strip()


def add_issue_section(
    lines: list[str], heading: str, body: str, names: tuple[str, ...]
) -> None:
    """Append a section with one fenced section of an issue body."""
    text = section(body, *names)
    lines += [
        f"## {heading}",
        fenced(text) if text else "_No such section in the issue._",
        "",
    ]


def header_lines(
    repo: str,
    number: int,
    pull: dict,
    task: dict | None,
    feature: dict | None,
    task_ref: int | None,
    feature_ref: int | None,
) -> list[str]:
    """Return the title block: branch, round, CI, linked task and, for a fork, the source."""
    round_value, changes = round_number(pull.get("reviews") or [])
    verdict, _ = ci_summary(pull.get("statusCheckRollup") or [])
    owner = (pull.get("headRepositoryOwner") or {}).get("login") or repo
    lines = [
        f"# Review pack — {repo}#{number}",
        "",
        f"**{one_line(pull.get('title') or '')}** — {pull.get('url') or ''}",
        "",
        f"- Branch: `{pull.get('headRefName') or '?'}` → `{pull.get('baseRefName') or '?'}`",
        f"- Round: {round_value} ({changes} changes requested by @{LEAD})",
        f"- CI: {verdict}",
    ]
    if task_ref is None:
        lines.append("- Task: none — the PR body carries no `Closes #<n>` line")
    else:
        lines.append(f"- Task: {issue_heading(task_ref, task)}")
    if feature_ref is not None:
        lines.append(f"- Parent feature: {issue_heading(feature_ref, feature)}")
    if pull.get("isCrossRepository"):
        lines.append(
            f"- Source: fork (@{owner}) — read through the GitHub API only, "
            "nothing checked out or run"
        )
    return [*lines, ""]


def ci_lines(rollup: list[dict]) -> list[str]:
    """Return the CI section as a table of the status checks."""
    _, check_rows = ci_summary(rollup)
    lines = ["## CI result", ""]
    if check_rows:
        lines += ["| Check | Result |", "|---|---|"]
        lines += [f"| `{name}` | {state} |" for name, state in check_rows]
    else:
        lines.append("_No status checks reported for the head commit._")
    return [*lines, ""]


def findings_lines(reviews: list[dict]) -> list[str]:
    """Return the findings of the formal changes-requested and comment reviews."""
    lines = ["## Findings of earlier rounds", ""]
    found = lead_round = 0
    for review in sorted(reviews, key=lambda item: item.get("submittedAt") or ""):
        body = clean(review.get("body") or "", MAX_TEXT)
        if not body or review.get("state") not in ("CHANGES_REQUESTED", "COMMENTED"):
            continue
        login = (review.get("author") or {}).get("login") or "unknown"
        state = (review.get("state") or "").lower().replace("_", " ")
        when = (review.get("submittedAt") or "")[:16].replace("T", " ")
        label = f"### {when} · @{login} · {state}"
        if login == LEAD and review.get("state") == "CHANGES_REQUESTED":
            lead_round += 1
            label += f" (round {lead_round})"
        lines += [label, "", fenced(review.get("body") or "", MAX_TEXT), ""]
        found += 1
    if not found:
        lines += ["_No changes-requested or comment review of an earlier round._", ""]
    return lines


def scope_lines(task_ref: int | None, task_body: str, changed: list[str]) -> list[str]:
    """Return the changed files that the task's allowed-files patterns do not cover."""
    lines = ["## Changed files outside the task's allowed files", ""]
    patterns = allowed_files(task_body) if task_ref is not None else []
    if task_ref is None:
        lines.append("_Scope not checked: no linked task._")
    elif not patterns:
        lines.append(
            "_The task has no `Allowed files` line, so the changed files cannot be "
            "checked against it._"
        )
    else:
        outside = [
            path
            for path in changed
            if not any(fnmatch.fnmatch(path, pattern) for pattern in patterns)
        ]
        if outside:
            lines += [f"- `{path}`" for path in outside]
        else:
            lines.append(
                "_None — every changed file matches the task's allowed files._"
            )
    return [*lines, ""]


def lessons_lines(text: str, changed: list[str]) -> list[str]:
    """Return the rows of LESSONS.md that name a changed file or its directory."""
    lines = ["## LESSONS.md — matching rows", ""]
    rows = lessons_rows(text, changed)
    if rows:
        lines += rows
    else:
        lines.append("_No LESSONS.md row names a changed file or its directory._")
    return [*lines, ""]


def render(
    repo: str,
    number: int,
    pull: dict,
    task: dict | None,
    feature: dict | None,
    task_ref: int | None,
    feature_ref: int | None,
    lessons_text: str,
) -> str:
    """Render the Markdown review pack."""
    task_body = (task or {}).get("body") or ""
    changed = [item.get("path") or "" for item in pull.get("files") or []]
    lines = header_lines(repo, number, pull, task, feature, task_ref, feature_ref)

    if task_ref is None:
        lines += [
            "## Goal of the task",
            "_No linked task: the PR body has no `Closes #<n>` line._",
            "",
            "## Acceptance criteria",
            "_No linked task._",
            "",
        ]
    else:
        add_issue_section(
            lines, "Goal of the task", task_body, ("goal", "problem", "bug")
        )
        add_issue_section(
            lines, "Acceptance criteria", task_body, ("acceptance criteria",)
        )

    feature_body = (feature or {}).get("body") or ""
    if feature_ref is None:
        lines += [
            "## Why (parent feature)",
            "_No parent feature linked in the task (`Part of #<n>` missing)._",
            "",
            "## Out of scope",
            "_No parent feature linked._",
            "",
        ]
    else:
        add_issue_section(lines, "Why (parent feature)", feature_body, ("goal", "why"))
        add_issue_section(lines, "Out of scope", feature_body, ("out of scope",))

    lines += ci_lines(pull.get("statusCheckRollup") or [])
    lines += findings_lines(pull.get("reviews") or [])
    lines += scope_lines(task_ref, task_body, changed)
    lines += lessons_lines(lessons_text, changed)
    return "\n".join(lines).rstrip() + "\n"


def read_lessons(repo: str) -> str:
    """Read LESSONS.md from the API; the review pack never writes to the checkout."""
    try:
        return gh(
            "api",
            f"repos/{repo}/contents/LESSONS.md",
            "-H",
            "Accept: application/vnd.github.raw",
        )
    except subprocess.CalledProcessError:
        return ""


def issue(repo: str, number: int) -> dict | None:
    """Read one issue through the API, or None when it is not readable."""
    try:
        return json.loads(
            gh("issue", "view", str(number), "-R", repo, "--json", ISSUE_FIELDS)
        )
    except subprocess.CalledProcessError:
        return None


def main(argv: list[str]) -> int:
    """Print the pack for one PR; exit 2 on a usage error, 1 when gh fails."""
    if len(argv) != 3 or "/" not in argv[1] or not argv[2].isdigit():
        print("usage: review-pack.py <owner/repo> <pr>", file=sys.stderr)
        return 2
    repo, number = argv[1], int(argv[2])
    try:
        pull = json.loads(
            gh("pr", "view", str(number), "-R", repo, "--json", PR_FIELDS)
        )
    except subprocess.CalledProcessError as error:
        print(f"review-pack: {repo}#{number}: {error.stderr.strip()}", file=sys.stderr)
        return 1

    task_ref = next(
        (
            int(match.group(1))
            for match in [CLOSES.search(pull.get("body") or "")]
            if match
        ),
        None,
    )
    task = issue(repo, task_ref) if task_ref is not None else None
    task_body = (task or {}).get("body") or ""
    feature_ref = next(
        (int(match.group(1)) for match in [PART_OF.search(task_body)] if match),
        None,
    )
    feature = issue(repo, feature_ref) if feature_ref is not None else None

    print(
        render(
            repo,
            number,
            pull,
            task,
            feature,
            task_ref,
            feature_ref,
            read_lessons(repo),
        ),
        end="",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

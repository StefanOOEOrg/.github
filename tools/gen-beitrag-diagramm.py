#!/usr/bin/env python3
"""Swimlane diagram of an external contribution (fork → PR → two approvals → merge).

The Lead never checks out or runs code from a fork: it reads the diff and relies on CI, which
runs on `pull_request` without secrets. Writes process-external-dark.svg and
process-external-light.svg. Usage:
    gen-beitrag-diagramm.py [out_dir]     (default /home/hermes/docs)
"""

from __future__ import annotations

import pathlib
import sys

from swimlane_svg import Diagram, write_both

DIAGRAM = Diagram(
    title="External contributions",
    subtitle="Fork → pull request → CI without secrets → Lead review → product owner approval → merge",
    lanes=[
        ("External contributor", "no write access · works in a fork", "external"),
        ("GitHub", "fork PR · ruleset · CI", "github"),
        ("Lead", "StefanOOELeadBot · 1st approval, merge", "lead"),
        ("Product owner", "StefanOOE · 2nd approval", "owner"),
    ],
    nodes=[
        ("E1", 0, 0, "Read CONTRIBUTING,\nfork the repository", "step"),
        ("E2", 0, 1, "Branch in the fork:\ncommit + push", "step"),
        ("G1", 1, 1, "Pull request from fork", "system"),
        ("G2", 1, 2, "First workflow run\nwaits for approval", "system"),
        ("L1", 2, 3, "Approve and run workflows\n(Lead or product owner)", "step"),
        ("G3", 1, 4, "CI on pull_request:\nno secrets, read-only token", "system"),
        ("L2", 2, 5, "Read the diff and CI results\n(never check out the fork)", "step"),
        ("L3", 2, 6, "Formal review:\nApprove / Request changes", "decision"),
        ("G4", 1, 7, "1/2 approvals", "system"),
        ("L4", 2, 8, "Request product\nowner's review", "step"),
        ("P1", 3, 9, "Review and approve (2/2)", "decision"),
        ("L5", 2, 10, "Merge (merge commit)", "step"),
        ("E3", 0, 11, "Contribution on main,\nthanks in release notes", "step"),
    ],
    edges=[
        ("E1", "E2", "", "solid"), ("E2", "G1", "", "solid"), ("G1", "G2", "", "solid"),
        ("G2", "L1", "", "solid"), ("L1", "G3", "", "solid"), ("G3", "L2", "", "solid"),
        ("L2", "L3", "", "solid"), ("L3", "G4", "Approve", "solid"), ("G4", "L4", "", "solid"),
        ("L4", "P1", "", "solid"), ("P1", "L5", "Approve", "solid"), ("L5", "E3", "", "solid"),
        ("L3", "E2", "Request changes", "dashed"),
    ],
    legend="solid = regular flow · dashed = loop back · dashed box = GitHub state · bold border = decision",
)


def main() -> None:
    """Write both themes to the output directory."""
    out_dir = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/home/hermes/docs")
    for path in write_both(DIAGRAM, out_dir, "process-external"):
        print(f"written: {path}")


if __name__ == "__main__":
    main()

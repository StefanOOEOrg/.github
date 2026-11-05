#!/usr/bin/env python3
"""Swimlane diagram of the internal development process (PROCESS.md, section Workflow).

Writes process-internal-dark.svg and process-internal-light.svg. Usage:
    gen-prozess-diagramm.py [out_dir]     (default /home/hermes/docs)
"""

from __future__ import annotations

import pathlib
import sys

from swimlane_svg import Diagram, write_both

DIAGRAM = Diagram(
    title="Development process",
    subtitle="Triage → refinement review → pull onto Goal → one task = one developer run = one PR → Lead and "
    "product owner approve → release",
    lanes=[
        ("Product owner", "StefanOOE · backlog, pull, 2nd approval", "owner"),
        ("Lead", "StefanOOELeadBot · refine, review, merge", "lead"),
        ("Project board", "Product Backlog · watcher · dispatcher", "board"),
        ("Developer (dev-n)", "StefanOOEDevBot · one task per run", "dev"),
        ("GitHub", "protected main · CI · 2 approvals", "github"),
    ],
    nodes=[
        ("P1", 0, 0, "Raise an idea\n(issue: feature, task, bug)", "step"),
        ("B1", 2, 0, "Triage (safety net\nadds every issue)", "system"),
        ("L1", 1, 1, "Refine: split the feature,\ntasks + closing task", "step"),
        ("P2", 0, 2, "Review the refinement:\nmove to Backlog", "decision"),
        ("P5", 0, 3, "Pull onto Goal:\ncolumn order = priority", "decision"),
        ("B2", 2, 4, "Goal", "system"),
        ("B3", 2, 5, "Dispatcher: free instance,\nno blocker → Action", "system"),
        ("D1", 3, 6, "Own worktree,\nTDD red → green", "step"),
        ("D2", 3, 7, "One commit, push,\nPR with Closes #task", "step"),
        ("G1", 4, 7, "CI runs (ci-ok) · Verify", "system"),
        ("L3", 1, 8, "Review: diff, gates,\nmutation probes", "step"),
        ("L4", 1, 9, "Formal review:\nApprove / Request changes", "decision"),
        ("G2", 4, 9, "1/2 approvals ·\nreminder after 2 h", "system"),
        ("P3", 0, 10, "Review and approve", "decision"),
        ("G3", 4, 11, "2/2 approvals → mergeable", "system"),
        ("L5", 1, 12, "Merge (merge commit)", "step"),
        ("B4", 2, 13, "Done · task closed", "system"),
        ("P4", 0, 14, "Approve the closing task =\nacceptance + release go", "decision"),
        ("L6", 1, 15, "Tag vX.Y.Z, release,\nclose the feature", "step"),
        ("L7", 1, 16, "Retro every two weeks,\nLESSONS.md", "step"),
    ],
    edges=[
        ("P1", "B1", "", "solid"), ("B1", "L1", "", "solid"), ("L1", "P2", "", "solid"),
        ("P2", "P5", "OK", "solid"), ("P5", "B2", "", "solid"), ("B2", "B3", "", "solid"),
        ("B3", "D1", "", "solid"), ("D1", "D2", "", "solid"), ("D2", "G1", "", "solid"),
        ("D2", "L3", "", "solid"), ("L3", "L4", "", "solid"), ("L4", "G2", "Approve", "solid"),
        ("G2", "P3", "", "solid"), ("P3", "G3", "Approve", "solid"), ("G3", "L5", "", "solid"),
        ("L5", "B4", "", "solid"), ("B4", "P4", "", "solid"), ("P4", "L6", "", "solid"),
        ("L6", "L7", "", "solid"),
        ("L4", "B2", "Request changes → next round, at most 3", "dashed"),
        ("P2", "L1", "comments", "dashed"),
    ],
    legend="solid = regular flow · dashed = loop back · dashed box = board or system state · bold border = decision"
    " · the last task of every feature is its closing task",
)


def main() -> None:
    """Write both themes to the output directory."""
    out_dir = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/home/hermes/docs")
    for path in write_both(DIAGRAM, out_dir, "process-internal"):
        print(f"written: {path}")


if __name__ == "__main__":
    main()

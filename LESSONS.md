# Lessons learned

Every process correction gets a line here (same PR as the correction, or a docs task). Incidents are tracked as issues with topic `process`; open measures are tasks reviewed by the product owner.

| Date | Problem | Cause | Measure | Status |
|---|---|---|---|---|
| 2026-11-05 | Sprint stalled: a decision in a comment did not reach the Lead (#24) | github-watch read states, not comments | Assignee = inbox: comments and manual assignments of the product owner are reported; manual assignment wins over the sync | done |
| 2026-11-05 | Sprint stalled: task blocked by a task outside the iteration (#24) | blocker in Backlog without iteration or assignee | – | open |
| 2026-11-04 | Local suite red after the version bump | stale editable package metadata (`uv sync` does not rebuild it from `VERSION`) | `uv sync --reinstall-package newstrading` in the release steps before the test run | done |
| 2026-11-03 | Work started outside the process (#56/#57, PRs #62–#65) | retired Hermes Kanban still dispatched and auto-decomposed | Kanban dispatch and auto-decompose switched off; skill: no Kanban cards | done |
| 2026-11-03 | Issues created as DevBot, Kanban cards from a second Lead session | Telegram session of the Lead without the Lead's gh identity | identity check before every gh write | done |
| 2026-11-02 | Merge notices lost or late | bot-chat delivery fails or times out while the Lead runs long turns | watch repeats open events (20/60 min) | open: root cause |
| 2026-11-03 | Triage was a dead end | no rule who processes Triage | Lead refines, product owner reviews and releases | done |
| 2026-11-02 | Sprint planned ticket by ticket | planning prompt per item | bundled sprint-planning notice, one planning run | done |
| 2026-11-03 | Ready task without instance never started | dispatcher needs an instance | – | open |
| 2026-11-03 | Status not moved after refinement | Lead only commented 'in Backlog' | assignee sync + review by the product owner | done |
| 2026-11-02 | Lead pulled new work items into the sprint himself | no rule for new items during a sprint | propose in the sprint plan, product owner decides | done |
| 2026-11-03 | PRs #62–#65 only `Part of #52` | nothing checked the rule | github-watch warns once per open PR without a `Closes #<task>` line | done |
| 2026-11-04 | Re-approval after a push overlooked (#78, #32) | every push dismisses approvals | github-watch reminds the product owner on the PR after 2 h (again after 24 h) | done |
| 2026-11-03 | Merge conflict #65 vs #78 | parallel PRs on the same file | planning rule exists, not enforced | open |
| 2026-11-03 | Features without closing task (#52, #55) | stories created before the rule | rule + #79 | done |
| 2026-11-03 | Approvals lost to unnecessary branch updates (#62–#65, #78) | every push dismisses approvals | `upstream/main` merged into a PR branch only on `DIRTY` or an invisible change, never because the branch is behind (PROCESS.md) | done |
| 2026-11-02 | `gh pr edit --add-reviewer` silently failed | gh 2.45 bug (Projects classic) | REST call in the skills, gh 2.103 | done |
| 2026-11-02 | Required check blocked (mcp-garmin#21) | duplicate CI runs on one commit after a cancelled re-run | merged by the product owner | watch |
| 2026-11-03 | Image analysis failed in the personal agents | auxiliary models without their own base_url | base_url per auxiliary task | done |
| 2026-11-03 | Product owner's 'changes requested' not noticed by the Lead | github-watch had no such event | watch reports his latest review with changes requested (once per review id, reminder after 2 h and 24 h); a manual assignment of his also wins in Triage, Backlog and In review | done |
| 2026-11-04 | Process automation changed without review, two copies drifted | the scripts lived in a profile directory: no PR, no history, and the cron ran a second copy | `tools/` in `.github`, installed by the idempotent `tools/install.sh` | done |
| 2026-11-04 | Alerts reached the Lead truncated | delivery waited for the session, the old 600 s limit cut it | `cron.bot_chat_delivery_timeout_seconds` 1800 and the degraded-delivery notice is expected | done |

# Development Process

How StefanOOEOrg builds software: a small team of AI agents and one human product owner, working in Scrum on GitHub.

**Rule zero:** GitHub is the single source of truth. What is not in an issue, a pull request or the project board did not happen.

## Roles

| Role | GitHub identity | Responsibilities | Approves? |
|---|---|---|---|
| Product owner & architect | `StefanOOE` | Owns the backlog, plans sprints, reviews concepts and architecture, gives the **second** approval | Yes (2nd) |
| Lead | `StefanOOELeadBot` | Refines features into tasks, estimates, writes test scaffolds, reviews every PR, merges | Yes (1st) |
| Developer | `StefanOOEDevBot` | Implements one task per run (test-first), opens the PR | Never |
| Specialist bots (planned) | own account or GitHub App | Privacy (GDPR) and security checks on PRs | Never – they report check runs |
| External contributors | own account, fork | Issues and fork PRs | Never counted |

One GitHub account per **role**, not per instance. Several developer instances (`dev-1`, `dev-2`, …) share `StefanOOEDevBot` and are told apart by the project field *Instance* and a commit trailer `Instance: dev-n`.

Specialist bots never approve: the ruleset counts approvals per identity, so a second bot approval would make the product owner's gate optional.

## Artifacts

| Scrum artifact | Lives in |
|---|---|
| Product backlog | Org project **Product Backlog**, ordered by priority |
| Feature (user story) | Issue of type **Feature** – goal, acceptance criteria, out of scope. Parent only, never in a sprint |
| Task / Bug | Sub-issue of type **Task** or **Bug** – one developer run, one PR. The only sprint items. Small tasks and bugs may have no parent |
| Steps | Checkboxes inside a task |
| Sprint | Project field *Iteration* (2 weeks, used as a cap on scope) |
| Estimate | Project field *Points* (1, 2, 3, 5 – complexity only; anything larger is split) |
| Status | Project field *Status*, mostly set by workflows |
| Report and review | PR description and formal GitHub review |
| Increment | Merged PRs with `Closes #task`; every feature ends with its closing task *Acceptance and release vX.Y.Z* |
| Decisions | Comments on the issue or PR |

There are no epics. Themes spanning several repositories (e.g. a linter migration) get one issue per repository, grouped by the project field *Topic*.

### Project fields

| Field | Values | Set by |
|---|---|---|
| Status | Triage, Backlog, Ready, In Progress, In review, Done | workflows; Backlog: product owner; Ready: Lead |
| Iteration | 2-week iterations | Product owner only |
| Points | 1, 2, 3, 5 | Lead |
| Priority | Urgent, High, Medium, Low | Product owner, Lead |
| Topic | free text | Lead |
| Instance | dev-1, dev-2, … | Lead (on hand-over) |
| Assignee | exactly one: whoever acts next | assignee sync script, Lead |

Assignee = whoever acts next (kept up to date by a script every 10 minutes):
- Triage, not refined yet: Lead – or the product owner while a question to them is pending
- Triage, refined: product owner (reviews the refinement)
- Backlog in the current iteration: Lead (sprint planning); other Backlog items: nobody
- Ready / In Progress: Developer
- PR open, review requested from the Lead: Lead
- Lead requested changes: Developer
- Lead approved, product owner's review requested: product owner
- Product owner approved: Lead (merge)
- Closed: nobody

### Project workflows

- Item added → **Triage**; item reopened → **Triage**
- PR linked → **In review**
- PR merged / item closed → **Done**
- Sub-issues are added automatically; closed items are archived after 14 days
- Safety net: a watcher adds every open org issue that is missing from the project (status Triage), so no repository needs its own auto-add rule

## Workflow

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/process-internal-dark.svg">
  <img alt="Swimlane diagram of the development process" src="assets/process-internal-light.svg">
</picture>

1. **Intake** – Ideas become issues (feature, task or bug) in any repository. A watcher adds every open issue to the project in **Triage**.
2. **Refinement (Lead)** – The Lead clarifies open points with the product owner, sets type and parent, splits each feature into task sub-issues – goal, acceptance criteria, scope (allowed files, test command), steps, points and a line ``Branch: `wp/<name>` (base: `main`)`` – and adds the feature's **closing task** *Acceptance and release vX.Y.Z*. The cards stay in Triage and are assigned to the product owner. Nothing in Triage is started.
3. **Refinement review (product owner)** – The product owner reviews the refinement and moves the cards to **Backlog** and into the current **iteration** – or comments, and the card goes back to the Lead.
4. **Sprint planning (Lead)** – One planning run over all items of the iteration: dependencies as *blocked by*, points, a parallel plan across the developer instances (no two parallel tasks on the same files), published as a *Sprint n plan* issue. Tasks without open dependencies get the Developer, an *Instance* and **Ready**. New work found during a sprint is only proposed in the plan; the product owner decides.
5. **Implementation** – A dispatcher starts the first Ready task of the current iteration per free instance in a dedicated worktree and sets **In Progress**. The developer works test-first, commits, pushes and opens the PR with `Closes #<task>` and requests the Lead's review. Status moves to **In review**.
6. **Review (Lead)** – Quality gates (CI, coverage, lint), mutation probes against "false green" tests, a formal GitHub review. *Request changes* sends the task back to Ready for the next round. On approval the Lead requests the product owner's review.
7. **Approval and merge** – The product owner approves (a reminder comes after 2 h of waiting); the Lead merges. The task closes and moves to **Done**; merged predecessors unblock the next tasks.
8. **Acceptance and release** – The product owner's approval of the closing task's PR (changelog, version, acceptance table per requirement) is the acceptance of the feature **and** the go for the release: the Lead tags `vX.Y.Z`, publishes the GitHub release and closes the feature.
9. **Sprint end** – On the last day of an iteration the Lead writes a *Sprint n review* and a *Sprint n retro* issue (see Continuous improvement).

Independent tasks run in parallel on different instances. Dependent tasks stay sequential ("blocked by"). Two instances never work on the same branch of the same repository.

### Notifications

- **Everyone:** the filter `assignee:@me` lists everything waiting for you.
- **Product owner:** GitHub Mobile – review requests and `@StefanOOE` mentions.
- **Product owner:** a reminder comment on a PR that has waited more than 2 h only for the product owner's approval (repeated after 24 h at the earliest).
- **Lead:** a watcher reports new review requests, approvals ready to merge, tasks stuck *In Progress*, approved PRs without a review request to the product owner, sprint planning needed (unrefined or startable tasks of the iteration), idle instances, items longer than 2 h in Triage, PRs for Triage items, work outside the current iteration and the last day of an iteration. Open reports are repeated (20–60 min).
- **Chat** is used only for clarifying requirements; the outcome is written into the issue.

## Continuous improvement

- **Incidents:** whenever something stalls or bypasses the process, an issue with topic `process` records what happened, the cause, the immediate fix and the lasting measure. The lasting measure is a task that the product owner reviews like any other.
- **Retro per sprint:** *Sprint n retro* with figures (time from Ready to merge, waiting time for the product owner's approval, review rounds, delayed notifications), what went well and what did not, and at most three improvements as tasks.
- **[LESSONS.md](LESSONS.md):** every process correction gets a line – date, problem, cause, measure, status.
- **Documentation moves with the process:** every change to the process updates this document and the diagrams in the same step.
- Plan, review and retro issues (`Sprint n …`) are documents and stay out of the project.

## Quality gates

A PR can be merged only when:

- CI is green (tests, coverage, lint, the aggregate `ci-ok` check)
- the Lead **and** the product owner have approved (org ruleset, 2 approvals, stale approvals dismissed on push)
- only the files allowed by the task were changed, and tests were not weakened
- the PR body starts with `Closes #<task>` and reports test results

### Updating a PR branch

Every push to a PR branch dismisses both approvals, and the ruleset does not require branches to be up to date with `main`. A branch is therefore updated only when there is a concrete reason, and there are exactly three cases:

- **Conflict** – GitHub shows `mergeStateStatus: DIRTY`: resolve it with `git merge upstream/main`.
- **Invisible change** – a file the PR touches changed on `main` in a way CI cannot see (e.g. a moved test helper): merge as well, and state the reason in a comment on the PR.
- **Behind only** – no reason, so no push: `mergeStateStatus: BEHIND` on its own is left alone until the merge.

If a push was necessary, the PR body says so in one line, so the product owner knows why the approval is gone.

## External contributions

Contributions are welcome via fork and pull request.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/process-external-dark.svg">
  <img alt="Swimlane diagram of an external contribution" src="assets/process-external-light.svg">
</picture>

- All public repositories are licensed under **MIT**; contributions are accepted under the same license.
- CI for fork PRs runs only after a maintainer approves the workflow run. Workflows use `pull_request` (no secrets, read-only token).
- External PRs go through the same review: Lead review, then product owner approval.

See [CONTRIBUTING.md](CONTRIBUTING.md) for coding rules.

## Language

Everything on GitHub is in English: issue types, fields, titles, issue and PR text, commit messages and this documentation.

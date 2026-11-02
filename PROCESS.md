# Development Process

How StefanOOEOrg builds software: a small team of AI agents and one human product owner, working in Scrum on GitHub.

**Rule zero:** GitHub is the single source of truth. What is not in an issue, a pull request or the project board did not happen.

## Roles

| Role | GitHub identity | Responsibilities | Approves? |
|---|---|---|---|
| Product owner | `StefanOOE` | Owns the backlog, plans sprints, gives the **second** approval | Yes (2nd) |
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
| Increment | Merged PRs with `Closes #task`; a feature closes when all its sub-issues are closed |
| Decisions | Comments on the issue or PR |

There are no epics. Themes spanning several repositories (e.g. a linter migration) get one issue per repository, grouped by the project field *Topic*.

### Project fields

| Field | Values | Set by |
|---|---|---|
| Status | Triage, Backlog, Ready, In Progress, In review, Done | workflows, Lead |
| Iteration | 2-week iterations | Product owner (sprint planning) |
| Points | 1, 2, 3, 5 | Lead |
| Priority | Urgent, High, Medium, Low | Product owner, Lead |
| Topic | free text | Lead |
| Instance | dev-1, dev-2, … | Lead (on hand-over) |

### Project workflows

- Item added → **Triage**; item reopened → **Triage**
- PR linked → **In review**
- PR merged / item closed → **Done**
- Sub-issues are added automatically; closed items are archived after 14 days
- Safety net: a watcher adds every open org issue that is missing from the project (status Triage), so no repository needs its own auto-add rule

## Workflow

1. **Backlog** – Ideas become issues. The Lead clarifies them with the product owner and writes acceptance criteria. Priority is the order in the backlog.
2. **Sprint planning** – The product owner pulls tasks and bugs into the current iteration.
3. **Refinement** – The Lead splits each feature into task sub-issues: goal, acceptance criteria, scope (allowed files, test command), steps, points and a line ``Branch: `wp/<name>` (base: `main`)``. If needed, the Lead first opens a scaffold PR with failing tests.
4. **Hand-over** – The Lead assigns the task to `StefanOOEDevBot`, sets *Instance* and moves it to **Ready**.
5. **Implementation** – A dispatcher picks the first Ready task per free instance, creates a dedicated worktree, sets **In Progress** and starts the developer. The developer works test-first, commits, pushes and opens the PR with `Closes #<task>` and requests the Lead's review. Status moves to **In review**.
6. **Review (Lead)** – Quality gates (CI, coverage, lint), mutation probes against "false green" tests, a formal GitHub review. *Request changes* sends the task back to Ready for round 2. On approval the Lead requests the product owner's review.
7. **Approval and merge** – The product owner approves; the Lead merges. The task closes and moves to **Done**.
8. **Sprint review** – At the end of an iteration the Lead summarises the results in a *Sprint n review* issue.

Independent tasks run in parallel on different instances. Dependent tasks stay sequential ("blocked by"). Two instances never work on the same branch of the same repository.

### Notifications

- **Product owner:** GitHub Mobile – review requests and `@StefanOOE` mentions.
- **Lead:** a watcher reports new review requests, approvals ready to merge, tasks stuck *In Progress* and approved PRs without a review request to the product owner.
- **Chat** is used only for clarifying requirements; the outcome is written into the issue.

## Quality gates

A PR can be merged only when:

- CI is green (tests, coverage, lint, the aggregate `ci-ok` check)
- the Lead **and** the product owner have approved (org ruleset, 2 approvals, stale approvals dismissed on push)
- only the files allowed by the task were changed, and tests were not weakened
- the PR body starts with `Closes #<task>` and reports test results

## External contributions

Contributions are welcome via fork and pull request.

- All public repositories are licensed under **MIT**; contributions are accepted under the same license.
- CI for fork PRs runs only after a maintainer approves the workflow run. Workflows use `pull_request` (no secrets, read-only token).
- External PRs go through the same review: Lead review, then product owner approval.

See [CONTRIBUTING.md](CONTRIBUTING.md) for coding rules.

## Language

Everything on GitHub is in English: issue types, fields, titles, issue and PR text, commit messages and this documentation.

# .github

Organization-wide community health files for `StefanOOEOrg`.

- [`CONTRIBUTING.md`](CONTRIBUTING.md) — the engineering guidelines every repository in this
  organization follows. GitHub surfaces this file automatically when an issue or pull request is
  created in any repository of the organization that has no own `CONTRIBUTING.md`.
- [`PROCESS.md`](PROCESS.md) — how the organization develops software: roles, board, workflow and
  quality gates.
- [`LESSONS.md`](LESSONS.md) — every process correction with problem, cause, measure and status.
- [`profile/README.md`](profile/README.md) — the organization profile page, shown once this
  repository is public.
- [`assets/`](assets/) — the swimlane diagrams embedded in `PROCESS.md` and `CONTRIBUTING.md`;
  generated, not hand-edited.
- [`tools/`](tools/) — the automation that runs the process: the loop engine `tools/loop` and the
  diagram generators; `tools/install.sh` copies it into a Hermes profile.

Changes go through a pull request, like code.

## How The Loop runs

GitHub is the single source of truth. A GitHub event reaches the Hermes gateway through the org
webhook; the route filters it and fires the loop engine, which reads what the event concerns,
decides with fixed rules and writes only what differs. Agents do the work that needs judgement –
code, review, merge – and report back through GitHub. Colours: green GitHub, blue Hermes,
orange our code.

```mermaid
flowchart LR
  owner(["Product owner"]):::gh
  subgraph GH["GitHub"]
    board["Project “The Loop”<br/>Status field"]:::gh
    repos["Repositories<br/>issues, PRs, reviews"]:::gh
    hook["Org webhook<br/>5 events, HMAC-signed"]:::gh
  end
  funnel["Tailscale Funnel<br/>one path only"]:::infra
  subgraph HM["Hermes gateway · profile sw-lead"]
    route["Route “loop”<br/>payload filters · coalesce<br/>HERMES_CRON_EVENT"]:::hermes
    cron["Cron “loop-tick”<br/>per event + hourly"]:::hermes
    deliver["Bot Chat delivery<br/>queue, ~4 s"]:::hermes
    dev["Developer agent<br/>one-shot job per card"]:::hermes
    lead["Lead agent<br/>refine, review, merge"]:::hermes
  end
  engine["Loop engine<br/>python3 -m loop tick"]:::ours
  owner -- "pulls cards to Goal, approves" --> board
  board --> hook
  repos --> hook
  hook --> funnel --> route --> cron --> engine
  engine -- "1 GraphQL read, only the differences" --> board
  engine -- "start: dev job" --> dev
  engine -- "notices on stdout" --> deliver --> lead
  dev -- "gh / git: branch, PR" --> repos
  lead -- "gh: review, merge" --> repos
  classDef gh fill:#e6f4ea,stroke:#2e7d32,color:#1b1b1b
  classDef hermes fill:#e3f0fb,stroke:#1565c0,color:#1b1b1b
  classDef ours fill:#fff1e0,stroke:#ef6c00,color:#1b1b1b
  classDef infra fill:#f2f2f2,stroke:#757575,color:#1b1b1b
```

Every card follows one state machine. The engine evaluates it from the facts on each run (not from
the events), so a missed event is repaired by the next run; Backlog and Goal stay the product
owner's.

```mermaid
stateDiagram-v2
  direction LR
  [*] --> Triage: new issue (engine)
  Triage --> Backlog: product owner
  Backlog --> Goal: product owner
  Triage --> Goal: product owner
  Goal --> Action: dispatcher starts it
  Action --> Verify: PR linked
  Verify --> Done: issue closed
  Verify --> Action: PR closed unmerged (proposal, off)
  Done --> Triage: reopened
  Done --> [*]: archived after 14 days
  note right of Goal
    starts when: free instance,
    no overlap of Allowed files,
    no open blocker, task order present,
    not a Feature, both bots can write,
    first startable in Goal order
  end note
  note right of Verify
    assignee follows the PR:
    review requested → Lead
    Lead approved → product owner
    changes requested → Developer
    (from round 3 → product owner)
    owner approved → Lead merges
  end note
```


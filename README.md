# .github

Organization-wide community health files for `StefanOOEOrg`.

## Why The Loop

This organization practises loop engineering: every task runs through the same loop on its own
instead of being planned into sprints. Scrum and similar processes were designed for teams of
humans – capacity, estimates, stand-ups; in an agentic team with a human reviewer the limit is the
human's attention at the gates, not the work in between.

The process lives in a script – deterministic, tested, traceable in its log – that decides every
transition on the board. Language models are used only where judgement is needed: writing and
reviewing code. The human sets the goals at the entry gate and approves at the exit gate.

## What is in this repository

Changes go through a pull request, like code.

- [`CONTRIBUTING.md`](CONTRIBUTING.md) — the engineering guidelines of every repository here;
  GitHub shows it for any repository of the organization without its own `CONTRIBUTING.md`.
- [`PROCESS.md`](PROCESS.md) — roles, board, workflow and quality gates.
- [`LESSONS.md`](LESSONS.md) — every process correction with problem, cause, measure and status.
- [`profile/README.md`](profile/README.md) — the organization profile page, shown once this
  repository is public.
- [`assets/`](assets/) — the generated swimlane diagrams of `PROCESS.md` and `CONTRIBUTING.md`.
- [`tools/`](tools/) — the automation: the loop engine `tools/loop`, the diagram generators and
  `tools/install.sh`, which copies it into a Hermes profile.

## How The Loop runs

GitHub is the single source of truth. An event reaches the loop listener through the org webhook;
the listener filters it and runs the loop engine, which reads what the event concerns, decides with
fixed rules and writes only what differs. Agents do the work that needs judgement – code, review,
merge – and report back through GitHub. (Alternatively the Hermes gateway route `loop` consumes the
webhook, the former setup; only one may be active: [*Consuming webhook signals: two
options*](tools/README.md#consuming-webhook-signals-two-options).) Colours: green GitHub, blue
Hermes, orange our code, red the human.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/diagrams/architecture-dark.svg">
  <img alt="Architecture of The Loop: the product owner works on GitHub; the org webhook reaches the loop listener through Tailscale Funnel; its signal sources feed one serial queue and dispatcher, which runs the loop engine; the engine reads and writes the board, starts developer jobs, and its output sink hands notices to the Hermes cron loop-deliver, which delivers them to the Lead" src="docs/diagrams/architecture-light.svg">
</picture>

<details>
<summary>Mermaid source</summary>

```mermaid
flowchart LR
  owner(["Product owner"]):::gh
  subgraph GH["GitHub"]
    board["Project “The Loop”<br/>Status field"]:::gh
    repos["Repositories<br/>issues, PRs, reviews"]:::gh
    hook["Org webhook<br/>5 events, HMAC-signed"]:::gh
  end
  funnel["Tailscale Funnel<br/>one path only"]:::infra
  subgraph LS["loop-listener · systemd"]
    sources["Source adapters<br/>webhook · timer · jobwatch<br/>LOOP_SOURCES"]:::ours
    queue["Queue + dispatcher<br/>serial · event time · retry"]:::ours
    engine["Loop engine<br/>run_scope"]:::ours
    sink["Sink adapter<br/>LOOP_SINK"]:::ours
  end
  subgraph HM["Hermes · profile sw-lead"]
    deliver["Cron “loop-deliver”<br/>outbox → Bot Chat"]:::hermes
    dev["Developer agent<br/>one-shot job per card"]:::hermes
    lead["Lead agent<br/>refine, review, merge"]:::hermes
    route["Option B, alternative<br/>route “loop” → cron “loop-tick”"]:::alt
  end
  owner -- "pulls cards to Goal, approves" --> board
  board --> hook
  repos --> hook
  hook --> funnel --> sources --> queue --> engine
  engine -- "1 GraphQL read, only the differences" --> board
  engine -- "start: dev job" --> dev
  engine --> sink -- "outbox" --> deliver -- "Bot Chat" --> lead
  dev -- "gh / git: branch, PR" --> repos
  lead -- "gh: review, merge" --> repos
  funnel -. "option B · only one active" .-> route -.-> engine
  classDef gh fill:#e6f4ea,stroke:#2e7d32,color:#1b1b1b
  classDef hermes fill:#e3f0fb,stroke:#1565c0,color:#1b1b1b
  classDef ours fill:#fff1e0,stroke:#ef6c00,color:#1b1b1b
  classDef infra fill:#f2f2f2,stroke:#757575,color:#1b1b1b
  classDef alt fill:#e3f0fb,stroke:#1565c0,color:#1b1b1b,stroke-dasharray:5 4
```

</details>

Every card follows one state machine, evaluated from the facts on each run rather than from the
events, so the next run repairs a missed event; Backlog and Goal stay the product owner's. Start
conditions, transitions and assignees: [PROCESS.md](PROCESS.md#project-workflows).

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/diagrams/loop-states-dark.svg">
  <img alt="Card states of The Loop: the product owner gate (Triage, Backlog, Goal), the agent loop (Goal, Action, Verify), the merge gate (Done), reopened back to Triage" src="docs/diagrams/loop-states-light.svg">
</picture>

<details>
<summary>Mermaid source</summary>

```mermaid
stateDiagram-v2
  direction LR
  [*] --> Triage: new issue (engine)
  Triage --> Backlog: product owner
  Backlog --> Goal: product owner
  Triage --> Goal: product owner
  Goal --> Action: dispatcher starts it
  Action --> Verify: PR linked
  Verify --> Goal: Lead requests changes (next round)
  Verify --> Done: issue closed
  Done --> Triage: reopened
  Done --> [*]: archived after 14 days
```

</details>

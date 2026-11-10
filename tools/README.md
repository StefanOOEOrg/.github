# tools/ – the automation of The Loop

What runs the process, kept here so that a change is reviewed like code. Why The Loop exists, its
architecture and the card states are in the [README](../README.md) and [PROCESS.md](../PROCESS.md).

| File | What it is |
|---|---|
| `loop/` | The loop engine, `python3 -m loop tick [--dry-run]`: reads what an event concerns (one card, or the whole board), decides with pure rules (`rules/`) and writes only the differences. Log `cache/loop.log`; local state `cache/loop-state.json` (what was already reported) and, after a failed run, the retry marker `cache/loop-retry.json`. Tests in `loop/tests/`. |
| `loop-tick.sh` | Runs the engine once. No-agent cron `loop-tick` of the `sw-lead` profile: on every webhook event (route `loop`, event in `HERMES_CRON_EVENT`) and hourly. |
| `loop-jobwatch.sh` | `python3 -m loop jobwatch`: a full engine run once a developer job has ended (its instance is free, but no GitHub event says so). No-agent cron `loop-jobwatch` of the `sw-lead` profile, every minute; silent and without GitHub calls while no job ended. It also retries a failed run (see below). |
| `install.sh` | Copies these files into `profiles/<profile>/scripts/`. Hermes only runs scripts from there, so the cron runs a copy: never edit it. Idempotent. |
| `review-pack.py` | `review-pack.py <owner/repo> <pr>`: the review pack for one PR (task, why, CI, earlier findings, round, scope drift, matching lessons). Read-only. |
| `gen-prozess-diagramm.py`, `gen-beitrag-diagramm.py`, `swimlane_svg.py` | Render the swimlanes in `assets/` (internal and external process). `gen-*.py [out_dir]`. |
| `ruff.toml` | Lint configuration. |

The old scripts `github-watch.sh`, `dev-dispatch.sh` and `assignee_sync.py`, replaced by the
engine, are in the git history up to commit `18f3b46`.

## The loop engine

One run of `python3 -m loop tick` (green GitHub, blue Hermes, orange our code):

```mermaid
flowchart TB
  hook["Webhook trigger<br/>with HERMES_CRON_EVENT"]:::hermes
  hourly["Hourly run<br/>no event"]:::hermes
  subgraph PKG["Package tools/loop · one lock per run"]
    scope["1 · Scope<br/>event → one card or the whole board<br/>scope.py"]:::ours
    read["2 · Read<br/>one GraphQL query per scope<br/>github_client.py → model.py"]:::ours
    decide["3 · Decide<br/>pure rules: status, assignee, dispatch,<br/>notices, checks · rules/, engine.py"]:::ours
    diff["4 · Diff<br/>desired vs. actual, only differences"]:::ours
    act["5 · Execute<br/>status, assignee, comments, starts, add to board<br/>apply.py, writer.py, starter.py"]:::ours
    notify["6 · Notify<br/>Lead lines on stdout<br/>“already reported”: cache/loop-state.json"]:::ours
  end
  gh["GitHub<br/>single source of truth"]:::gh
  lead["Lead agent<br/>via Hermes delivery"]:::hermes
  hook --> scope
  hourly --> scope
  scope --> read --> decide --> diff --> act --> notify
  read -. reads .-> gh
  act -. writes .-> gh
  notify --> lead
  classDef gh fill:#e6f4ea,stroke:#2e7d32,color:#1b1b1b
  classDef hermes fill:#e3f0fb,stroke:#1565c0,color:#1b1b1b
  classDef ours fill:#fff1e0,stroke:#ef6c00,color:#1b1b1b
```

The Hermes side, with the names from the Hermes code; dashed boxes are the local patch in
`hermes-config/patches` (async Bot Chat delivery, coalesce, event context for script jobs):

```mermaid
flowchart TB
  gh["GitHub org webhook"]:::gh
  subgraph GW["Hermes gateway · names from the code · dashed = local patch"]
    hw["WebhookAdapter._handle_webhook<br/>HMAC signature, idempotency cache"]:::hermes
    flt["Route payload filters<br/>webhook_subscriptions.json"]:::hermes
    hct["_handle_cron_trigger<br/>+ cron_job_on_busy: coalesce"]:::patch
    ex["execute_job_for_event →<br/>claim_job_for_fire"]:::hermes
    ext["_launch_external_cron_worker<br/>+ carries the event context"]:::patch
    rj["run_job → _run_no_agent_job<br/>+ HERMES_CRON_EVENT for the script"]:::patch
    dbc["_deliver_to_bot_chat<br/>+ defer to cron/bot_chat_pending"]:::patch
    dqw["DeliveryQueueWatch<br/>+ also watches bot_chat_pending, 1 s"]:::patch
    dr["drain_in_background → _drain"]:::hermes
  end
  tick["loop-tick.sh → loop engine"]:::ours
  lead["Lead turn in Bot Chat"]:::hermes
  gh --> hw --> flt --> hct --> ex --> ext --> rj --> tick
  tick -- "stdout" --> dbc --> dqw --> dr --> lead
  classDef gh fill:#e6f4ea,stroke:#2e7d32,color:#1b1b1b
  classDef hermes fill:#e3f0fb,stroke:#1565c0,color:#1b1b1b
  classDef ours fill:#fff1e0,stroke:#ef6c00,color:#1b1b1b
  classDef patch fill:#e3f0fb,stroke:#1565c0,stroke-width:2px,stroke-dasharray:6 4,color:#1b1b1b
```

### A failed run

A run that fails – GitHub unreachable after the three gh attempts, the lock not free within
10 minutes, a crash – loses the event that fired it. It exits 1 as before and leaves
`cache/loop-retry.json` (first failure, last try, reason; `loop/retry.py`). The job watch, every
minute, runs the engine over the whole board once the last failure is `LOOP_RETRY_MINUTES` (3)
old, so a longer outage costs one try per 3 minutes, not three gh attempts per minute. A
successful full run – the retry, a job end or the hourly run – removes the marker; a one-card run
does not, as it may not cover the lost event. Silent unless the failure lasts
`LOOP_RETRY_REPORT_MINUTES` (30): then one notice to the Lead, and one when the runs work again.
That one notice exits 0, because Hermes delivers only a successful run's output to Bot Chat
(`--failure-deliver local`).

## Install, test, change

```bash
tools/install.sh                        # profile sw-lead; --profile <name>, --dry-run
cd tools && uvx --with pytest pytest -q  # tests (CI: also ruff, pylint, bash -n)
```

`HERMES_PROFILES_ROOT` overrides the profiles root (default `$HERMES_HOME/profiles`, else
`~/.hermes/profiles`; a `HERMES_HOME` pointing at a profile is refused).

After a merge that touches `tools/`: pause `loop-tick` (only while no developer job runs), run
`install.sh`, check with `python3 -m loop tick --dry-run` in the profile's `scripts/`, resume.
Change the files here, never the installed copy; no secrets, configuration comes from the
profile's environment. Every variable and its default is in `loop/config.py`; the one switch that
changes the state machine is `LOOP_VERIFY_BACK_TO_ACTION=1` – a Verify card goes back to Action
when its PR was closed without a merge. It is off (a proposal, not in use).

Every run logs one summary line, `run <event>: n status, n assignee, n close(s), n start(s), n
notice(s) printed`; it counts every kind of write, so a run that wrote something never reads like
a quiet one.

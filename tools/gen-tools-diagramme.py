#!/usr/bin/env python3
"""Renders the pictures of tools/README.md into docs/diagrams (light and dark SVG).

Usage: gen-tools-diagramme.py [out_dir]   (default: docs/diagrams next to this tools/ folder)
Colours as in the architecture picture: green GitHub, blue Hermes, orange our code, grey infra.
"""

from __future__ import annotations

import pathlib
import sys

from readme_sequence import webhook_retry
from readme_svg import Canvas

W, H2, H3 = 280, 100, 116  # card width of the engine run, card heights with 2 and 3 sub lines


def engine_run() -> Canvas:
    """One run of `python3 -m loop tick`: six steps in a snake, GitHub and the Lead outside."""
    c = Canvas(895, 680, "One run of the loop engine",
               "One run of the loop engine: a Hermes webhook trigger or the hourly run starts it; "
               "inside tools/loop, under one lock, it scopes, reads GitHub, decides, diffs, "
               "executes the differences on GitHub and notifies the Lead through Hermes")
    c.card((40, 20, W, 84), "hm", ["HERMES CRON", "Webhook trigger", "with `HERMES_CRON_EVENT`"])
    c.card((350, 20, W, 84), "hm", ["HERMES CRON", "Hourly run", "no event: the whole board"])
    c.frame((20, 140, 630, 520), "ours", "TOOLS/LOOP · ONE LOCK PER RUN", bottom=True)
    left, right, rows = 40, 350, (184, 344, 504)
    c.card((left, rows[0], W, H3), "ours",
           ["1 · SCOPE", "Scope", "event → one card", "or the whole board", "`scope.py`"])
    c.card((right, rows[0], W, H3), "ours", ["2 · READ", "Read", "one GraphQL query per scope",
                                             "`github_client.py` → `model.py`"])
    c.card((right, rows[1], W, H3), "ours",
           ["3 · DECIDE", "Decide", "pure rules: status, assignee,", "dispatch, notices, checks",
            "`rules/` · `engine.py`"])
    c.card((left, rows[1], W, H3), "ours",
           ["4 · DIFF", "Diff", "desired vs. actual", "only the differences"])
    c.card((left, rows[2], W, H3), "ours",
           ["5 · EXECUTE", "Execute", "status, assignee, comments,", "starts, add to board",
            "`apply.py` `writer.py` `starter.py`"])
    c.card((right, rows[2], W, H3), "ours",
           ["6 · NOTIFY", "Notify", "Lead lines on stdout", "already reported:",
            "`cache/loop-state.json`"])
    c.card((685, 344, 190, H3), "gh", ["GITHUB", "GitHub", "single source", "of truth"])
    c.card((685, 504, 190, H3), "hm", ["LEAD AGENT", "Lead", "via Hermes delivery"])
    c.arrow("M180,104 V180")
    c.arrow("M490,104 V122 H260 V180")
    for path in ("M320,242 H346", "M490,300 V340", "M350,402 H324", "M180,460 V500",
                 "M320,562 H346", "M630,562 H681"):
        c.arrow(path)
    c.arrow("M630,226 H780 V340")
    c.text(705, 218, "reads", "lbl halo")
    c.arrow("M290,504 V482 H780 V464")
    c.text(560, 476, "writes", "lbl halo")
    return c


def hermes_side() -> Canvas:
    """The Hermes gateway path of an event, with the local patches dashed."""
    c = Canvas(1015, 784, "The Hermes side of a loop event",
               "The Hermes side: the GitHub org webhook passes the gateway's webhook adapter, "
               "route filters, cron trigger, job claim, external worker and no-agent job into "
               "loop-tick.sh; its stdout goes through the Bot Chat delivery, the queue watch and "
               "the drain to a Lead turn; dashed cards are the local patch")
    xs, ys, w = (225, 485, 745), (176, 332, 488), 230
    c.card((225, 20, w, 84), "gh", ["GITHUB", "Org webhook", "HMAC-signed"])
    c.frame((205, 134, 790, 510), "hm",
            "HERMES GATEWAY · NAMES FROM THE CODE · DASHED = LOCAL PATCH", bottom=True)
    cards = [
        (0, 0, False, ["RECEIVE", "Webhook adapter", "`WebhookAdapter`", "`._handle_webhook`",
                       "HMAC · idempotency cache"]),
        (1, 0, False, ["FILTER", "Route filters", "payload filters per route",
                       "`webhook_subscriptions.json`"]),
        (2, 0, True, ["TRIGGER · LOCAL PATCH", "Cron trigger", "`_handle_cron_trigger`",
                      "+ `cron_job_on_busy`: coalesce"]),
        (2, 1, False, ["CLAIM", "Execute job", "`execute_job_for_event`",
                       "→ `claim_job_for_fire`"]),
        (1, 1, True, ["WORKER · LOCAL PATCH", "External worker", "`_launch_external_cron_worker`",
                      "+ carries the event context"]),
        (0, 1, True, ["RUN · LOCAL PATCH", "No-agent job", "`run_job` → `_run_no_agent_job`",
                      "+ `HERMES_CRON_EVENT`", "for the script"]),
        (0, 2, True, ["DELIVER · LOCAL PATCH", "Bot Chat delivery", "`_deliver_to_bot_chat`",
                      "+ defer to", "`cron/bot_chat_pending`"]),
        (1, 2, True, ["WATCH · LOCAL PATCH", "Queue watch", "`DeliveryQueueWatch`",
                      "+ also watches", "`bot_chat_pending`, 1 s"]),
        (2, 2, False, ["DRAIN", "Drain", "`drain_in_background`", "→ `_drain`"]),
    ]
    for col, row, patch, lines in cards:
        c.card((xs[col], ys[row], w, H3), "hm", lines, patch)
    c.card((20, 332, 150, H3), "ours", ["SCRIPT", "Loop engine", "`loop-tick.sh`"])
    c.card((745, 680, w, 84), "hm", ["LEAD AGENT", "Lead", "turn in Bot Chat"])
    for path in ("M340,104 V172", "M455,234 H481", "M715,234 H741", "M860,292 V328",
                 "M745,390 H719", "M485,390 H459", "M225,390 H174", "M455,546 H481",
                 "M715,546 H741", "M860,604 V676", "M95,448 V546 H221"):
        c.arrow(path)
    c.text(87, 500, "stdout", "lbl end halo")
    return c


def listener() -> Canvas:
    """The webhook listener: one process between the Funnel and the Hermes delivery cron."""
    c = Canvas(1035, 632, "The webhook listener",
               "The webhook listener: the GitHub org webhook reaches it through Tailscale Funnel; "
               "the HTTP thread checks and queues, the start and the clock add full runs, the "
               "dispatcher runs the engine one run at a time, the delivery thread hands each "
               "message to the Hermes cron loop-deliver, which delivers it to the Lead")
    xs, w = (245, 505, 765), 230
    c.card((20, 20, 170, 84), "gh", ["GITHUB", "Org webhook", "HMAC-signed"])
    c.card((20, 150, 170, H2), "infra", ["TAILSCALE", "Funnel", "one path only"])
    c.frame((225, 106, 790, 304), "ours", "LOOP-LISTENER · ONE PROCESS · SYSTEMD")
    c.card((xs[0], 150, w, H2), "ours",
           ["HTTP THREAD", "Receive", "HMAC · route filter · dedupe", "202 at once"])
    c.card((xs[1], 150, w, H2), "ours", ["IN-MEMORY QUEUE", "Queue", "by event time"])
    c.card((xs[2], 150, w, H2), "ours",
           ["DISPATCHER", "One run at a time", "`tick.run_scope`, in-process"])
    c.card((xs[0], 290, w, H2), "ours",
           ["START + CLOCK", "Full run", "at start, then every", "`LOOP_FULL_RUN_MINUTES`"])
    c.card((xs[1], 290, w, H2), "ours", ["DELIVERY THREAD", "Deliver", "`LOOP_DELIVER_CMD`"])
    c.card((xs[2], 290, w, H2), "ours", ["DELIVERY QUEUE", "Messages", "in order"])
    c.frame((485, 440, 530, 172), "hm", "HERMES · PROFILE SW-LEAD", bottom=True)
    c.card((xs[1], 470, w, 100), "hm", ["CRON", "“loop-deliver”", "`--deliver bot-chat:sw-lead`"])
    c.card((xs[2], 470, w, 100), "hm", ["LEAD AGENT", "Lead", "turn in Bot Chat"])
    for path in ("M105,104 V146", "M190,200 H241", "M475,200 H501", "M735,200 H761",
                 "M880,250 V286", "M765,340 H739", "M475,340 H490 V230 H501", "M620,390 V466",
                 "M735,520 H761"):
        c.arrow(path)
    c.text(632, 429, "outbox + `hermes cron run`", "lbl start halo")
    return c


def ports() -> Canvas:
    """Signal sources and output sinks around the core, which knows only the two ports."""
    c = Canvas(1145, 506, "Signal sources and output sinks",
               "Signal sources and sinks: four SignalSource adapters (webhook, timer, jobwatch, "
               "hermes-cron) produce a Signal; the core – serial queue, dispatcher, engine, "
               "deliverer – knows only the ports; the deliverer hands lines to one of four "
               "OutputSink adapters (command, hermes-outbox, stdout, file)")
    ys, w = (64, 168, 272, 376), 230
    c.frame((20, 20, 270, 466), "ours", "SIGNALSOURCE · LOOP_SOURCES")
    c.frame((535, 20, 270, 466), "ours", "CORE · KNOWS ONLY THE PORTS")
    c.frame((855, 20, 270, 466), "ours", "OUTPUTSINK · LOOP_SINK")
    sources = [["WEBHOOK", "GitHubWebhookSource", "HMAC · route filter"],
               ["TIMER", "TimerSource", "`LOOP_FULL_RUN_MINUTES`"],
               ["JOBWATCH", "JobWatchSource", "a dev job ended"],
               ["HERMES-CRON", "HermesCronSource", "`HERMES_CRON_EVENT`"]]
    core = [["QUEUE", "Serial queue", "dedupe · event time"],
            ["DISPATCHER", "Dispatcher", "one run · merge · retry"],
            ["ENGINE", "Loop engine", "`scope_for` → `run_scope`"],
            ["DELIVERER", "Deliverer", "own thread · retry · pending"]]
    sinks = [["COMMAND", "CommandSink", "`LOOP_DELIVER_CMD`"],
             ["HERMES-OUTBOX", "HermesBotChatSink", "outbox + loop-deliver"],
             ["STDOUT", "StdoutSink", "Hermes cron output"],
             ["FILE", "FileSink", "`LOOP_FILE_SINK`"]]
    for y, src, mid, out in zip(ys, sources, core, sinks):
        c.card((40, y, w, 84), "ours", src)
        c.card((555, y, w, 84), "ours", mid)
        c.card((875, y, w, 84), "ours", out)
        c.arrow(f"M270,{y + 42} H315", head=False)
        c.arrow(f"M830,{y + 42} H871")
    c.card((335, 56, 180, H3), "infra",
           ["MODEL", "Signal", "source · `delivery_id`", "`occurred_at`", "subject or full run"])
    c.arrow("M315,418 V106 H331")
    c.arrow("M515,106 H551")
    for y in ys[:3]:
        c.arrow(f"M670,{y + 84} V{y + 100}")
    c.arrow("M785,418 H830 V106", head=False)
    return c


def main() -> int:
    """Writes every picture; prints the paths."""
    here = pathlib.Path(__file__).resolve().parent
    out = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else here.parent / "docs" / "diagrams"
    out.mkdir(parents=True, exist_ok=True)
    pictures = {"tools-engine-run": engine_run(), "tools-hermes-side": hermes_side(),
                "tools-listener": listener(), "tools-ports": ports(),
                "tools-webhook-retry": webhook_retry()}
    for name, canvas in pictures.items():
        for path in canvas.write(out, name):
            print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())

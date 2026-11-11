"""The options picture of tools/README.md: two ways to consume the org webhook's signals.

Drawn in the style of readme_svg: one start (GitHub org webhook, Tailscale Funnel) and one goal
(the Lead), two lanes in between – option A directly through the loop listener, option B through
the Hermes gateway. Each lane carries its steps on the left and grey cards with its properties,
its cost and the configuration that selects it on the right; a red card says only one may be on.
"""

from __future__ import annotations

from readme_svg import Canvas

STEP_W, INFO_W, STEP_H, INFO_H = 270, 290, 100, 148
STEP_YS = (324, 460, 596, 732)  # four steps per lane
INFO_YS = (324, 504, 684)  # properties, cost, selected by
LANES = {  # frame x, frame colour, frame label
    "a": (20, "ours", "OPTION A · DIRECT · DEFAULT, RECOMMENDED"),
    "b": (660, "hm", "OPTION B · THROUGH HERMES · FORMER SETUP, FALLBACK"),
}
STEPS = {  # (colour, lines) per step, top to bottom
    "a": [("ours", ["LOOP-LISTENER · SOURCE", "GitHubWebhookSource", "HMAC · route filter",
                    "202 at once"]),
          ("ours", ["CORE", "Queue + dispatcher", "serial · dedupe · event time",
                    "failed run: retry, backoff"]),
          ("ours", ["ENGINE", "Loop engine", "`tick.run_scope`, in-process"]),
          ("ours", ["DELIVERER → SINK", "`hermes-outbox` / `command`",
                    "outbox → cron `loop-deliver`"])],
    "b": [("hm", ["HERMES GATEWAY", "Route `loop`", "payload filters · HMAC",
                  "`cron_job_on_busy`: coalesce"]),
          ("hm", ["CRON · HERMESCRONSOURCE", "Cron `loop-tick`", "`HERMES_CRON_EVENT`",
                  "+ hourly run"]),
          ("ours", ["ENGINE", "Loop engine", "`python3 -m loop tick`"]),
          ("ours", ["SINK", "StdoutSink", "Hermes delivers the", "cron output to Bot Chat"])],
}
INFOS = {  # properties, cost, selected by
    "a": [["PROPERTIES", "No lost events", "queue + retry with backoff",
           "independent of a busy Hermes job", "Lead delivery in its own thread",
           "every start begins with a full run"],
          ["COST", "One more service", "systemd unit `loop-listener`",
           "secret and env file to keep", "delivery still via a Hermes cron"],
          ["SELECTED BY", "Funnel → listener", "`127.0.0.1:8655`",
           "`LOOP_SOURCES=webhook,timer`", "`LOOP_SINK=command`",
           "route `loop` off · `loop-tick` paused"]],
    "b": [["PROPERTIES", "No own service", "runs inside the Hermes gateway",
           "one cron job: `loop-tick`", "the setup until 2026-11-10"],
          ["COST", "Events can get lost", "a trigger while `loop-tick` runs",
           "is coalesced: its event is gone", "until the next full run (hourly)"],
          ["SELECTED BY", "Funnel → Hermes", "the Hermes webhook port",
           "route `loop` on · `loop-tick` active", "`loop-listener` stopped"]],
}


def _lane(c: Canvas, key: str) -> None:
    """One option: its frame, four steps with arrows, three info cards."""
    x, colour, label = LANES[key]
    c.frame((x, 280, 620, 592), colour, label, bottom=True, right=True)
    centre = x + 20 + STEP_W // 2
    for y, (step_colour, lines) in zip(STEP_YS, STEPS[key]):
        c.card((x + 20, y, STEP_W, STEP_H), step_colour, lines)
    for y in STEP_YS[:-1]:
        c.arrow(f"M{centre},{y + STEP_H} V{y + 132}")
    for y, lines in zip(INFO_YS, INFOS[key]):
        c.card((x + 310, y, INFO_W, INFO_H), "infra", lines)


def webhook_options() -> Canvas:
    """Same start, same goal, two lanes: direct listener (A) or Hermes route and cron (B)."""
    c = Canvas(1300, 1040, "Consuming webhook signals: two options",
               "Two options to consume the org webhook's signals, from the same start (GitHub "
               "org webhook, Tailscale Funnel) to the same goal (loop engine, Lead). Option A, "
               "the default: the loop listener's webhook source, serial queue and dispatcher, "
               "the engine in-process and the deliverer's sink through the outbox cron to the "
               "Lead; no lost events. Option B: the Hermes gateway route loop, the cron "
               "loop-tick with HERMES_CRON_EVENT, the engine and its stdout through Bot Chat to "
               "the Lead; no own service, but an event can get lost while loop-tick is busy. "
               "Only one option may be active, else every event runs twice")
    c.card((535, 20, 230, 84), "gh", ["GITHUB", "Org webhook", "HMAC-signed"])
    c.card((535, 140, 230, STEP_H), "infra", ["TAILSCALE", "Funnel", "one public path, one target"])
    c.card((815, 140, 330, STEP_H), "red", ["ONLY ONE OPTION ACTIVE", "Never both at once",
                                            "two consumers of one event", "= every run twice"])
    c.arrow("M650,104 V136")
    c.arrow("M650,240 V260 H175 V320")
    c.arrow("M650,260 H815 V320")
    c.text(412, 254, "A: Funnel → listener", "lbl halo")
    c.text(733, 254, "B: Funnel → Hermes", "lbl halo")
    _lane(c, "a")
    _lane(c, "b")
    c.card((535, 920, 230, STEP_H), "hm", ["LEAD AGENT", "Lead", "turn in Bot Chat"])
    c.arrow("M175,832 V970 H531")
    c.arrow("M815,832 V970 H769")
    return c

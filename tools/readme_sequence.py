"""The sequence picture of tools/README.md: a webhook event end to end, with a failed run.

Drawn in the style of readme_svg: participant cards on top, dashed lifelines, numbered
messages (solid call, dashed reply, red dashed failure ending in a cross) and grey notes.
"""

from __future__ import annotations

from readme_svg import Canvas, rich

STEP = 185  # distance of two lifelines
CARD_W = 176
PARTICIPANTS = [  # (key, colour, kicker, title, sub)
    ("GH", "gh", "GITHUB", "GitHub", "org webhook"),
    ("WS", "ours", "SIGNAL SOURCE", "Webhook source", "`GitHubWebhookSource`"),
    ("D", "ours", "CORE", "Dispatcher", "with the queue"),
    ("E", "ours", "CORE", "Engine", "`run_scope`"),
    ("DL", "ours", "CORE", "Deliverer", "own thread"),
    ("K", "ours", "OUTPUT SINK", "Output sink", "`LOOP_SINK`"),
]
MESSAGES = [  # (from, to, label, kind: call | reply | fail | self | note; "|" breaks a note)
    ("GH", "WS", "POST delivery `(X-Hub-Signature-256)`", "call"),
    ("WS", "WS", "HMAC · route filter → Signal", "self"),
    ("WS", "D", "`submit(signal)`", "call"),
    ("D", "WS", "`True` (`False`: duplicate)", "reply"),
    ("WS", "GH", "202 queued", "reply"),
    ("D", "E", "`run(scope_for(signal))`", "call"),
    ("E", "D", "`GitHubError`", "fail"),
    ("D", "D", "signals back into the queue|backoff 5 s, doubled up to 300 s", "note"),
    ("GH", "WS", "another delivery", "call"),
    ("WS", "D", "`submit(signal 2)`", "call"),
    ("D", "E", "one full run over both", "call"),
    ("E", "D", "lines", "reply"),
    ("D", "DL", "`put(message)`", "call"),
    ("DL", "K", "`deliver(message)`", "call"),
    ("K", "DL", "`False` (refused)", "reply"),
    ("DL", "DL", "retry with backoff, order kept", "note"),
    ("DL", "K", "`deliver(message)`", "call"),
    ("K", "DL", "`True`", "reply"),
]
ROW = {"call": 40, "reply": 40, "fail": 40, "self": 54}


def _x(key: str) -> int:
    index = [p[0] for p in PARTICIPANTS].index(key)
    return 20 + CARD_W // 2 + STEP * index


def _layout() -> tuple[list[int], int]:
    """The y of every message and the canvas height."""
    ys, y = [], 156
    for _, _, label, kind in MESSAGES:
        ys.append(y)
        y += 30 + 18 * label.count("|") + 40 if kind == "note" else ROW[kind]
    return ys, y + 10


def _message(c: Canvas, msg: tuple[str, str, str, str], y: int, number: int) -> None:
    src, dst, label, kind = msg
    x1, x2 = _x(src), _x(dst)
    num = f'<tspan class="num">{number}</tspan>  '
    if kind == "self":
        c.arrow(f"M{x1},{y} H{x1 + 44} V{y + 20} H{x1 + 5}")
        c.raw(f'<text class="lbl start halo" x="{x1 + 54}" y="{y + 14}">{num}'
              f'{rich(label)}</text>')
        return
    sign = 1 if x2 > x1 else -1
    end = x2 - 4 * sign
    if kind == "fail":
        c.arrow(f"M{x1},{y} H{x2}", red=True, dashed=True, head=False)
        c.arrow(f"M{x2 - 6},{y - 6} L{x2 + 6},{y + 6} M{x2 - 6},{y + 6} L{x2 + 6},{y - 6}",
                red=True, head=False)
    else:
        c.arrow(f"M{x1},{y} H{end}", dashed=kind == "reply")
    c.raw(f'<text class="lbl halo" x="{(x1 + x2) / 2}" y="{y - 8}">{num}{rich(label)}</text>')


def _note(c: Canvas, key: str, label: str, y: int) -> None:
    lines = label.split("|")
    x, height = _x(key), 14 + 18 * len(lines)
    c.raw(f'<rect class="note" x="{x - 140}" y="{y - 8}" width="280" height="{height}" '
          'rx="8"/>')
    for i, line in enumerate(lines):
        c.text(x, y + 10 + 18 * i, line)


def webhook_retry() -> Canvas:
    """The sequence of one webhook delivery through a failed and a repeated run."""
    ys, height = _layout()
    width = 40 + CARD_W + STEP * (len(PARTICIPANTS) - 1)
    c = Canvas(width, height, "A webhook event, end to end, with a failed run",
               "Sequence of a webhook event: GitHub posts a delivery, the webhook source checks "
               "it and submits a Signal, answered 202; the dispatcher's engine run fails with "
               "GitHubError, the signals go back with backoff; a second delivery arrives and one "
               "full run covers both; the deliverer hands the message to the output sink, which "
               "refuses once and accepts on the retry")
    for key, colour, kicker, title, sub in PARTICIPANTS:
        x = _x(key)
        c.raw(f'<path class="life" d="M{x},104 V{height - 10}"/>')
        c.card((x - CARD_W // 2, 20, CARD_W, 84), colour, [kicker, title, sub])
    number = 0
    for msg, y in zip(MESSAGES, ys):
        if msg[3] == "note":
            _note(c, msg[0], msg[2], y)
            continue
        number += 1
        _message(c, msg, y, number)
    return c

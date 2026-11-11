"""Shared renderer for the README pictures in docs/diagrams (light and dark SVG).

The style is the one of the hand-drawn architecture picture: cards with a coloured stroke, a
kicker line, a bold title and grey sub lines; tinted frames around a system; grey arrows with
filled heads. A picture is drawn once on a Canvas and written twice; the two themes differ only
in the stylesheet. Text in backticks is set in the monospace font. Before writing, the canvas
checks that every card text fits its card, no two cards overlap and the SVG is valid XML.
"""

from __future__ import annotations

import pathlib
import string
import xml.etree.ElementTree as ET

THEMES = {
    "light": {"text": "#1f2328", "muted": "#59636e", "card": "#ffffff", "bg": "#ffffff",
              "red": "#c8102e", "gh": "#1a7f37", "hm": "#0969da", "ours": "#bc4c00",
              "infra": "#6e7781", "alpha": "0.05", "line": "#d0d7de", "note": "#f6f8fa"},
    "dark": {"text": "#e6edf3", "muted": "#9198a1", "card": "#161b22", "bg": "#0d1117",
             "red": "#f0596b", "gh": "#3fb950", "hm": "#58a6ff", "ours": "#f0883e",
             "infra": "#9198a1", "alpha": "0.08", "line": "#3d444d", "note": "#21262d"},
}

STYLE = string.Template("""<style>
text{font-family:-apple-system, BlinkMacSystemFont, &quot;Segoe UI&quot;, Helvetica, Arial, \
sans-serif;fill:$text;text-anchor:middle}
.kick{font-size:10.5px;font-weight:600;letter-spacing:1.1px}
.gk{font-size:11px;font-weight:700;letter-spacing:1.4px;text-anchor:start}
.title{font-size:17px;font-weight:700}
.sub{font-size:12.5px;fill:$muted}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:11.5px}
.lbl{font-size:12.5px;fill:$muted}
.num{font-weight:700;fill:$text}
.start{text-anchor:start}.end{text-anchor:end}
.halo{paint-order:stroke;stroke:$bg;stroke-width:3.5px;stroke-linejoin:round}
.b{fill:$card;stroke-width:1.6}
.red{stroke:$red}.gh{stroke:$gh}.hm{stroke:$hm}.ours{stroke:$ours;stroke-width:2.2}\
.infra{stroke:$infra}
.patch{stroke-dasharray:6 4}
.k-red{fill:$red}.k-gh{fill:$gh}.k-hm{fill:$hm}.k-ours{fill:$ours}.k-infra{fill:$infra}
.frame{stroke-width:1.2}
.f-gh{fill:$gh;fill-opacity:$alpha;stroke:$gh}
.f-hm{fill:$hm;fill-opacity:$alpha;stroke:$hm}
.f-ours{fill:$ours;fill-opacity:$alpha;stroke:$ours}
.f-infra{fill:$infra;fill-opacity:$alpha;stroke:$infra}
.note{fill:$note;stroke:$line;stroke-width:1.2}
path{fill:none;stroke-width:1.8}.a{stroke:$infra}.r{stroke:$red;stroke-width:2.2}
.d{stroke-dasharray:6 5}.life{stroke:$line;stroke-width:1.5;stroke-dasharray:4 4}
</style>
<defs><marker id="ma" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" \
orient="auto"><path d="M0,0 L10,5 L0,10 z" style="fill:$infra;stroke:none"/></marker>\
<marker id="mr" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" \
orient="auto"><path d="M0,0 L10,5 L0,10 z" style="fill:$red;stroke:none"/></marker></defs>
""")

PAD = 14  # minimum free space left and right of a card text


def esc(text: str) -> str:
    """Escapes text for SVG content and attributes."""
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def rich(text: str) -> str:
    """Escaped text in which every `backtick` part becomes a monospace tspan."""
    parts = text.split("`")
    return "".join(f'<tspan class="mono">{esc(p)}</tspan>' if i % 2 else esc(p)
                   for i, p in enumerate(parts) if p)


class Canvas:
    """One picture: collects SVG elements and writes the light and the dark file."""

    def __init__(self, width: int, height: int, title: str, label: str) -> None:
        self.width, self.height, self.title, self.label = width, height, title, label
        self.parts: list[str] = []
        self.cards: list[tuple[float, float, float, float]] = []

    def frame(self, box: tuple[float, float, float, float], colour: str, label: str,
              bottom: bool = False, right: bool = False) -> None:
        """A tinted frame (x, y, w, h) around one system, its name top or bottom, left or right."""
        x, y, w, h = box
        self.parts.append(f'<rect class="frame f-{colour}" x="{x}" y="{y}" width="{w}" '
                          f'height="{h}" rx="16"/>')
        ty = y + h - 9 if bottom else y + 24
        cls, tx = (f"gk k-{colour} end", x + w - 16) if right else (f"gk k-{colour}", x + 16)
        self.parts.append(f'<text class="{cls}" x="{tx}" y="{ty}">{esc(label)}</text>')

    def card(self, box: tuple[float, float, float, float], colour: str, lines: list[str],
             patch: bool = False) -> None:
        """A card (x, y, w, h); lines are kicker, title and any sub lines."""
        x, y, w, h = box
        self._fits(w, [(lines[0], 10.5 * 0.68 + 1.1), (lines[1], 17 * 0.6)]
                   + [(s, 12.5 * 0.56) for s in lines[2:]])
        self.cards.append(box)
        cls = f"b {colour} patch" if patch else f"b {colour}"
        self.parts.append(f'<rect class="{cls}" x="{x}" y="{y}" width="{w}" height="{h}" '
                          'rx="12"/>')
        self._card_text(x + w / 2, y + (h - 84 - 16 * (len(lines) - 3)) / 2, colour, lines)

    def _card_text(self, cx: float, top: float, colour: str, lines: list[str]) -> None:
        kicker, title, *subs = lines
        self.parts.append(f'<text class="kick k-{colour}" x="{cx}" y="{top + 21}">'
                          f'{esc(kicker)}</text>')
        self.parts.append(f'<text class="title" x="{cx}" y="{top + 43}">{rich(title)}</text>')
        for i, sub in enumerate(subs):
            self.parts.append(f'<text class="sub" x="{cx}" y="{top + 62 + 16 * i}">'
                              f'{rich(sub)}</text>')

    def _fits(self, width: float, lines: list[tuple[str, float]]) -> None:
        for line, per_char in lines:
            mono = sum(len(p) for i, p in enumerate(line.split("`")) if i % 2)
            estimate = (len(line.replace("`", "")) - mono) * per_char + mono * 6.9
            if estimate > width - 2 * PAD:
                raise ValueError(f"{self.title}: text too wide for its card: {line!r}")

    def arrow(self, path: str, red: bool = False, dashed: bool = False,
              head: bool = True) -> None:
        """An arrow along an SVG path; red for the human or failure path."""
        cls = ("r" if red else "a") + (" d" if dashed else "")
        end = f' marker-end="url(#{"mr" if red else "ma"})"' if head else ""
        self.parts.append(f'<path class="{cls}" d="{path}"{end}/>')

    def text(self, x: float, y: float, content: str, cls: str = "lbl") -> None:
        """A free label; cls may add start, end, halo or num."""
        self.parts.append(f'<text class="{cls}" x="{x}" y="{y}">{rich(content)}</text>')

    def raw(self, element: str) -> None:
        """Any other SVG element, already escaped."""
        self.parts.append(element)

    def _check(self) -> None:
        for i, (x, y, w, h) in enumerate(self.cards):
            if x < 0 or y < 0 or x + w > self.width or y + h > self.height:
                raise ValueError(f"{self.title}: card {i} outside the canvas")
            for x2, y2, w2, h2 in self.cards[i + 1:]:
                if x < x2 + w2 and x2 < x + w and y < y2 + h2 and y2 < y + h:
                    raise ValueError(f"{self.title}: cards {(x, y)} and {(x2, y2)} overlap")

    def render(self, theme: str) -> str:
        """The complete SVG document in one theme."""
        self._check()
        head = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.width} '
                f'{self.height}" width="{self.width}" height="{self.height}" role="img" '
                f'aria-label="{esc(self.label)}">\n<title>{esc(self.title)}</title>\n')
        svg = head + STYLE.substitute(THEMES[theme]) + "\n".join(self.parts) + "\n</svg>\n"
        ET.fromstring(svg)
        return svg

    def write(self, out_dir: pathlib.Path, name: str) -> list[pathlib.Path]:
        """Writes name-light.svg and name-dark.svg; returns the paths."""
        paths = []
        for theme in THEMES:
            path = out_dir / f"{name}-{theme}.svg"
            path.write_text(self.render(theme), encoding="utf-8")
            paths.append(path)
        return paths

"""Shared renderer for the process swimlane diagrams (dark and light theme, SVG).

A diagram is plain data: lanes, nodes on a (lane, row) grid and edges. Time runs downwards.
Edges are routed orthogonally through the free channel between rows; dashed edges are loops
back to an earlier step and run through the empty margin strip of the target lane, so they
never cross a node. The renderer checks at the end that the SVG is valid XML, every node lies
inside the canvas and no two nodes overlap.
"""

from __future__ import annotations

import pathlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass

THEMES = {
    "dark": {
        "bg": "#020617", "grid": "#1e293b", "text": "#e2e8f0", "muted": "#94a3b8",
        "card": "#0f172a", "decision": "#f8fafc", "lane_alpha": 0.16, "node_alpha": 0.28,
        "colours": {"owner": "#fbbf24", "lead": "#22d3ee", "board": "#a78bfa", "dev": "#34d399",
                    "github": "#fb7185", "external": "#60a5fa"},
    },
    "light": {
        "bg": "#ffffff", "grid": "#e2e8f0", "text": "#0f172a", "muted": "#475569",
        "card": "#ffffff", "decision": "#0f172a", "lane_alpha": 0.06, "node_alpha": 0.12,
        "colours": {"owner": "#b45309", "lead": "#0e7490", "board": "#6d28d9", "dev": "#047857",
                    "github": "#be123c", "external": "#1d4ed8"},
    },
}

LANE_W = 300
LANE_GAP = 18
LEFT = 28
TOP = 110
ROW_H = 74
NODE_W = LANE_W - 40
NODE_H = 46
MARGIN = 10  # distance of a loop edge from the lane border


@dataclass(frozen=True)
class Diagram:
    """Data of one swimlane diagram."""

    title: str
    subtitle: str
    lanes: list[tuple[str, str, str]]  # (name, subtitle, role key into the theme colours)
    nodes: list[tuple[str, int, int, str, str]]  # (id, lane, row, text, kind: step|system|decision)
    edges: list[tuple[str, str, str, str]]  # (from, to, label, style: solid|dashed)
    legend: str


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _rgba(hex_colour: str, alpha: float) -> str:
    r, g, b = (int(hex_colour[i : i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r}, {g}, {b}, {alpha})"


def _lane_x(lane: int) -> int:
    return LEFT + lane * (LANE_W + LANE_GAP)


class _Layout:
    """Geometry of one diagram: node boxes and edge routes."""

    def __init__(self, diagram: Diagram) -> None:
        self.diagram = diagram
        self.rows = max(row for _id, _lane, row, _t, _k in diagram.nodes) + 1
        self.width = 2 * LEFT + len(diagram.lanes) * LANE_W + (len(diagram.lanes) - 1) * LANE_GAP
        self.lane_bottom = TOP + 22 + self.rows * ROW_H + 12
        self.height = self.lane_bottom + 44
        self.lane_of = {nid: lane for nid, lane, _r, _t, _k in diagram.nodes}
        self.box = {
            nid: (_lane_x(lane) + 20, TOP + 22 + row * ROW_H + (ROW_H - NODE_H) // 2, NODE_W, NODE_H)
            for nid, lane, row, _t, _k in diagram.nodes
        }

    def _side(self, nid: str, side: str) -> tuple[int, int]:
        x, y, w, h = self.box[nid]
        return {"top": (x + w // 2, y), "bottom": (x + w // 2, y + h),
                "left": (x, y + h // 2), "right": (x + w, y + h // 2)}[side]

    def route(self, a: str, b: str, style: str) -> tuple[list[tuple[int, int]], tuple[int, int, str]]:
        """Return the polyline from a to b and the label anchor (x, y, text-anchor)."""
        ax, ay, aw, ah = self.box[a]
        bx, by, _bw, _bh = self.box[b]
        if style == "dashed":  # loop back: run through the margin strip of the target lane
            if self.lane_of[b] >= self.lane_of[a]:
                mx = _lane_x(self.lane_of[b]) + LANE_W - MARGIN
                pts = [(ax + aw, ay + ah - 9), (mx, ay + ah - 9), (mx, self._side(b, "right")[1]),
                       self._side(b, "right")]
                anchor = "end"
                lx = mx - 6
            else:
                mx = _lane_x(self.lane_of[b]) + MARGIN
                pts = [(ax, ay + ah - 9), (mx, ay + ah - 9), (mx, self._side(b, "left")[1]),
                       self._side(b, "left")]
                anchor = "start"
                lx = mx + 6
            return pts, (lx, (pts[1][1] + pts[2][1]) // 2, anchor)
        if ax == bx:
            pts = [self._side(a, "bottom"), self._side(b, "top")]
        elif ay == by:
            pts = [self._side(a, "right" if ax < bx else "left"), self._side(b, "left" if ax < bx else "right")]
        else:
            mid = (ay + ah + by) // 2
            pts = [self._side(a, "bottom"), (ax + aw // 2, mid), (self._side(b, "top")[0], mid),
                   self._side(b, "top")]
        if len(pts) > 2:
            mx_, my_ = pts[2][0], pts[2][1] - 12
        else:
            mx_, my_ = (pts[0][0] + 3 * pts[1][0]) // 4, (pts[0][1] + 3 * pts[1][1]) // 4
        return pts, (mx_, my_, "middle")

    def check(self) -> None:
        """Assert that all nodes are inside the canvas and do not overlap."""
        items = list(self.box.items())
        for i, (nid, (x, y, w, h)) in enumerate(items):
            assert x >= 0 and y >= 0 and x + w <= self.width and y + h <= self.height, nid
            for other, (ox, oy, ow, oh) in items[i + 1 :]:
                assert not (x < ox + ow and ox < x + w and y < oy + oh and oy < y + h), (nid, other)


def render(diagram: Diagram, theme_name: str) -> str:
    """Render the diagram as an SVG string in the given theme."""
    t = THEMES[theme_name]
    lay = _Layout(diagram)
    colours = [t["colours"][role] for _n, _s, role in diagram.lanes]
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{lay.width}" height="{lay.height}" '
        f'viewBox="0 0 {lay.width} {lay.height}" font-family="\'JetBrains Mono\', ui-monospace, monospace">',
        "<defs>",
        f'<pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">'
        f'<path d="M 40 0 L 0 0 0 40" fill="none" stroke="{t["grid"]}" stroke-width="0.5"/></pattern>',
    ]
    for i in range(len(diagram.lanes)):
        out.append(
            f'<marker id="arrow{i}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
            f'orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="{colours[i]}"/></marker>'
        )
    out += ["</defs>", f'<rect width="{lay.width}" height="{lay.height}" fill="{t["bg"]}"/>',
            f'<rect width="{lay.width}" height="{lay.height}" fill="url(#grid)"/>',
            f'<text x="{LEFT}" y="46" fill="{t["text"]}" font-size="20" font-weight="bold">{_esc(diagram.title)}</text>',
            f'<text x="{LEFT}" y="70" fill="{t["muted"]}" font-size="11">{_esc(diagram.subtitle)}</text>']
    lane_h = lay.lane_bottom - (TOP - 20)
    for i, (name, sub, _role) in enumerate(diagram.lanes):
        x = _lane_x(i)
        out.append(f'<rect x="{x}" y="{TOP - 20}" width="{LANE_W}" height="{lane_h}" rx="12" '
                   f'fill="{_rgba(colours[i], t["lane_alpha"])}" stroke="{colours[i]}" stroke-width="1" '
                   f'stroke-dasharray="8,4"/>')
        out.append(f'<text x="{x + 16}" y="{TOP}" fill="{colours[i]}" font-size="13" font-weight="bold">'
                   f"{_esc(name)}</text>")
        out.append(f'<text x="{x + 16}" y="{TOP + 15}" fill="{t["muted"]}" font-size="9">{_esc(sub)}</text>')
    for a, b, label, style in diagram.edges:
        pts, (lx, ly, anchor) = lay.route(a, b, style)
        lane = lay.lane_of[b]
        dash = ' stroke-dasharray="5,4"' if style == "dashed" else ""
        d = f"M {pts[0][0]} {pts[0][1]} " + " ".join(f"L {px} {py}" for px, py in pts[1:])
        out.append(f'<path d="{d}" fill="none" stroke="{colours[lane]}" stroke-width="1.4"{dash} '
                   f'marker-end="url(#arrow{lane})"/>')
        if label:
            w = len(label) * 6 + 10
            rx = {"middle": lx - w // 2, "end": lx - w + 5, "start": lx - 5}[anchor]
            out.append(f'<rect x="{rx}" y="{ly - 10}" width="{w}" height="16" rx="3" fill="{t["bg"]}" opacity="0.92"/>')
            out.append(f'<text x="{lx}" y="{ly + 2}" fill="{colours[lane]}" font-size="9.5" '
                       f'text-anchor="{anchor}">{_esc(label)}</text>')
    for nid, lane, _row, text, kind in diagram.nodes:
        x, y, w, h = lay.box[nid]
        stroke = t["decision"] if kind == "decision" else colours[lane]
        width = 2 if kind == "decision" else 1.4
        dash = ' stroke-dasharray="4,3"' if kind == "system" else ""
        out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{t["card"]}"/>')
        out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" '
                   f'fill="{_rgba(colours[lane], t["node_alpha"])}" stroke="{stroke}" stroke-width="{width}"{dash}/>')
        lines = text.split("\n")
        base = y + h // 2 - (len(lines) - 1) * 6 + 4
        for k, line in enumerate(lines):
            out.append(f'<text x="{x + w // 2}" y="{base + k * 13}" fill="{t["text"]}" font-size="10.5" '
                       f'text-anchor="middle">{_esc(line)}</text>')
    out.append(f'<text x="{LEFT}" y="{lay.height - 16}" fill="{t["muted"]}" font-size="9.5">{_esc(diagram.legend)}</text>')
    out.append("</svg>")
    svg = "\n".join(out)
    ET.fromstring(svg)
    lay.check()
    return svg


def write_both(diagram: Diagram, out_dir: pathlib.Path, stem: str) -> list[pathlib.Path]:
    """Write <stem>-dark.svg and <stem>-light.svg and return their paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for theme_name in THEMES:
        path = out_dir / f"{stem}-{theme_name}.svg"
        path.write_text(render(diagram, theme_name), encoding="utf-8")
        paths.append(path)
    return paths

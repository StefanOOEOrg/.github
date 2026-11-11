"""Tests for ``tools/gen-tools-diagramme.py``: the committed README pictures are reproducible.

The generator runs into a temporary folder; every SVG it writes must equal the committed file
in ``docs/diagrams``, and every picture of ``tools/README.md`` must exist in both themes.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tools" / "gen-tools-diagramme.py"
DIAGRAMS = ROOT / "docs" / "diagrams"


def _generate(out_dir: pathlib.Path) -> list[pathlib.Path]:
    result = subprocess.run([sys.executable, str(SCRIPT), str(out_dir)], check=True,
                            capture_output=True, text=True, timeout=60)
    return [pathlib.Path(line) for line in result.stdout.splitlines()]


def test_committed_svgs_match_the_generator(tmp_path: pathlib.Path) -> None:
    """Every generated SVG equals its committed copy, byte for byte."""
    written = _generate(tmp_path)
    assert len(written) == 12
    for path in written:
        committed = DIAGRAMS / path.name
        assert committed.read_text(encoding="utf-8") == path.read_text(encoding="utf-8"), (
            f"{committed.name} is stale: run tools/gen-tools-diagramme.py")


def test_readme_pictures_exist_in_both_themes() -> None:
    """The README has no Mermaid left and links six pictures, each light and dark."""
    readme = (ROOT / "tools" / "README.md").read_text(encoding="utf-8")
    names = set(re.findall(r"docs/diagrams/(tools-[a-z-]+)-(?:light|dark)\.svg", readme))
    assert len(names) == 6
    assert "```mermaid" not in readme
    for name in names:
        for theme in ("light", "dark"):
            assert (DIAGRAMS / f"{name}-{theme}.svg").is_file()

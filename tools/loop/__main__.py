"""Command line: ``python3 -m loop tick [--dry-run]``.

Run from the profile's scripts directory, where install.sh puts the package.
"""

from __future__ import annotations

import argparse
import logging
import sys

from loop.github_client import GitHubError
from loop.tick import tick


def main(argv: list[str] | None = None) -> int:
    """Parse the command line and run; 0 on success, 1 if GitHub could not be read or written."""
    parser = argparse.ArgumentParser(prog="loop")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("tick", help="one engine run (scope from HERMES_CRON_EVENT)")
    run.add_argument("--dry-run", action="store_true", help="decide and log, write nothing")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        return tick(dry_run=args.dry_run)
    except (GitHubError, TimeoutError) as error:
        logging.getLogger("loop").error("run failed: %s", error)
        return 1


if __name__ == "__main__":
    sys.exit(main())

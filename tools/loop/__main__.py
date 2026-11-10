"""Command line: ``python3 -m loop tick|jobwatch [--dry-run]``.

Run from the profile's scripts directory, where install.sh puts the package.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime

from loop import retry
from loop.github_client import GitHubError
from loop.jobwatch import jobwatch
from loop.tick import tick


def parse(argv: list[str] | None) -> argparse.Namespace:
    """The command line."""
    parser = argparse.ArgumentParser(prog="loop")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("tick", help="one engine run (scope from HERMES_CRON_EVENT)")
    run.add_argument("--dry-run", action="store_true", help="decide and log, write nothing")
    watch = sub.add_parser("jobwatch",
                           help="a full run once a developer job has ended or a run failed")
    watch.add_argument("--dry-run", action="store_true", help="decide and log, write nothing")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Parse the command line and run; 0 on success, 1 if GitHub could not be read or written.

    A failed run leaves the retry marker (retry.py) for the job watch. The one notice that a
    failure lasts too long exits 0: Hermes delivers only a successful run's output to the Lead.
    """
    args = parse(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    failure, code, notice = "crashed", 1, None  # a crash leaves failure in place
    try:
        code = jobwatch(dry_run=args.dry_run) if args.command == "jobwatch" else tick(
            dry_run=args.dry_run)
        failure = f"exit {code}" if code else ""
    except (GitHubError, TimeoutError) as error:
        logging.getLogger("loop").error("run failed: %s", error)
        failure = str(error)
    finally:
        if failure and not args.dry_run:
            notice = retry.record(retry.marker_path(), failure, datetime.now(UTC))
    if notice:
        print(notice)
        return 0
    return code


if __name__ == "__main__":
    sys.exit(main())

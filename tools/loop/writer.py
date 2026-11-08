"""GitHub writes of the engine: board fields, assignees, comments, project items.

Every write is idempotent on GitHub's side (setting a value it already has, adding an assignee
that is there). ``dry_run`` logs the write instead of making it.
"""

from __future__ import annotations

import json
import logging

from loop import config
from loop.github_client import Runner, run_gh
from loop.model import Card, Ref

logger = logging.getLogger(__name__)

FIELDS_QUERY = """query($org: String!, $num: Int!) {
  organization(login: $org) { projectV2(number: $num) { id fields(first: 30) { nodes {
    ... on ProjectV2SingleSelectField { id name options { id name } } } } } } }"""
SET_FIELD = """mutation($p: ID!, $i: ID!, $f: ID!, $o: String!) { updateProjectV2ItemFieldValue(
  input: {projectId: $p, itemId: $i, fieldId: $f, value: {singleSelectOptionId: $o}}) {
  clientMutationId } }"""
ARCHIVE = """mutation($p: ID!, $i: ID!) { archiveProjectV2Item(input: {projectId: $p, itemId: $i}) {
  clientMutationId } }"""


class GitHubWriter:
    """Writes for one run; reads the project's field ids once, on first use."""

    def __init__(self, run: Runner = run_gh, dry_run: bool = False) -> None:
        self._run = run
        self.dry_run = dry_run
        self._project: tuple[str, dict[str, dict]] | None = None

    def _call(self, args: list[str], what: str) -> str:
        if self.dry_run:
            logger.info("dry run, not done: %s", what)
            return "{}"
        logger.info("%s", what)
        return self._run(args)

    def _fields(self) -> tuple[str, dict[str, dict]]:
        if self._project is None:
            data = json.loads(self._run(["api", "graphql", "-f", f"query={FIELDS_QUERY}", "-f",
                                      f"org={config.ORG}", "-F", f"num={config.PROJECT_NUMBER}"]))
            project = data["data"]["organization"]["projectV2"]
            fields = {f["name"]: f for f in project["fields"]["nodes"] if f.get("name")}
            self._project = (project["id"], fields)
        return self._project

    def set_field(self, item: str, field: str, value: str) -> None:
        """Set a single-select field (Status, Instance) of a project item."""
        project, fields = self._fields()
        option = next(o["id"] for o in fields[field]["options"] if o["name"] == value)
        self._call(["api", "graphql", "-f", f"query={SET_FIELD}", "-f", f"p={project}", "-f",
                    f"i={item}", "-f", f"f={fields[field]['id']}", "-f", f"o={option}"],
                   f"{field} of {item} -> {value}")

    def assignees(self, card: Card, add: set[str], remove: set[str]) -> None:
        """Add and remove assignees of a card's issue."""
        path = f"repos/{card.ref.repo}/issues/{card.ref.number}/assignees"
        what = f"{card.ref.repo}#{card.ref.number}: -{sorted(remove)} +{sorted(add)}"
        if remove:
            self._call(["api", "-X", "DELETE", path, *_logins(remove)], f"unassign {what}")
        if add:
            self._call(["api", "-X", "POST", path, *_logins(add)], f"assign {what}")

    def comment(self, ref: Ref, body: str) -> None:
        """Comment on an issue or PR."""
        self._call(["api", f"repos/{ref.repo}/issues/{ref.number}/comments", "-f", f"body={body}"],
                   f"comment on {ref.repo}#{ref.number}")

    def add_item(self, ref: Ref) -> str:
        """Put an issue on the project; return the new item id ('' in a dry run)."""
        answer = self._call(["project", "item-add", str(config.PROJECT_NUMBER), "--owner",
                             config.ORG, "--url", ref.url, "--format", "json"],
                            f"add {ref.repo}#{ref.number}")
        return json.loads(answer).get("id", "")

    def close(self, card: Card) -> None:
        """Close a card's issue as completed."""
        self._call(["api", "-X", "PATCH", f"repos/{card.ref.repo}/issues/{card.ref.number}",
                    "-f", "state=closed", "-f", "state_reason=completed"],
                   f"close {card.ref.repo}#{card.ref.number}")

    def archive(self, card: Card) -> None:
        """Archive a project item."""
        project, _ = self._fields()
        self._call(["api", "graphql", "-f", f"query={ARCHIVE}", "-f", f"p={project}", "-f",
                    f"i={card.state.item}"], f"archive {card.ref.repo}#{card.ref.number}")


def _logins(logins: set[str]) -> list[str]:
    return [x for login in sorted(logins) for x in ("-f", f"assignees[]={login}")]

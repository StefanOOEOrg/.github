"""GraphQL documents: one query per scope (the whole board, or one card).

The board query reads the project items page by page; the org-wide views (open PRs, merged outer
loop PRs, open issues for the missing-from-project check) ride on the first page only. Sizes are
kept small on purpose: the Lead token has 5000 points an hour, and ``rateLimit`` reports the cost.
"""

PR_FIELDS = """
fragment PR on PullRequest {
  number url state body headRefOid
  repository { nameWithOwner }
  headRepositoryOwner { login }
  reviewRequests(first: 10) { nodes { requestedReviewer { ... on User { login } } } }
  reviews(last: 10) { nodes { author { login } state submittedAt body commit { oid } } }
  commits(last: 1) { nodes { commit { statusCheckRollup { state } } } }
}"""

ISSUE_FIELDS = """
fragment Issue on Issue {
  id url number state closedAt body lastEditedAt editor { login }
  issueType { name }
  subIssues(first: 1) { totalCount }
  repository { nameWithOwner viewerPermission }
  assignees(first: 10) { nodes { login } }
  blockedBy(first: 10) { nodes { number state repository { nameWithOwner } } }
  timelineItems(last: 1, itemTypes: [ASSIGNED_EVENT]) { nodes { ... on AssignedEvent {
    createdAt actor { login } assignee { ... on User { login } } } } }
  comments(last: 1) { nodes { createdAt author { login } } }
  reopened: timelineItems(last: 1, itemTypes: [REOPENED_EVENT]) {
    nodes { ... on ReopenedEvent { createdAt } } }
  closedByPullRequestsReferences(first: 3, includeClosedPrs: true) { nodes { ...PR } }
}"""

ITEM_FIELDS = """
  id
  status: fieldValueByName(name: "Status") {
    ... on ProjectV2ItemFieldSingleSelectValue { name updatedAt } }
  instance: fieldValueByName(name: "Instance") {
    ... on ProjectV2ItemFieldSingleSelectValue { name } }"""

BOARD_QUERY = """
query($org: String!, $num: Int!, $after: String, $first: Boolean!, $prs: String!,
      $merged: String!, $issues: String!) {
  rateLimit { cost remaining resetAt }
  organization(login: $org) { projectV2(number: $num) {
    items(first: 100, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes { """ + ITEM_FIELDS + """ content { ...Issue } } } } }
  openPrs: search(query: $prs, type: ISSUE, first: 100) @include(if: $first) {
    nodes { ...PR } }
  merged: search(query: $merged, type: ISSUE, first: 20) @include(if: $first) {
    nodes { ...PR } }
  openIssues: search(query: $issues, type: ISSUE, first: 100) @include(if: $first) {
    nodes { ... on Issue { number url repository { nameWithOwner }
      projectItems(first: 5) { nodes { project { number } } } } } }
}""" + ISSUE_FIELDS + PR_FIELDS

CARD_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  rateLimit { cost remaining resetAt }
  repository(owner: $owner, name: $name) { issue(number: $number) {
    ...Issue
    projectItems(first: 5) { nodes { project { number } """ + ITEM_FIELDS + """ } } } }
}""" + ISSUE_FIELDS + PR_FIELDS

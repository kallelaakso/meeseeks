from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Callable

from orchestrator.github import GitHub
from orchestrator.tickets import parse_branch


@dataclass(frozen=True)
class IssueEv:
    number: int
    title: str
    body: str
    labels: frozenset[str]
    closed: bool


@dataclass(frozen=True)
class PullEv:
    number: int
    kind: str
    issue: int
    branch: str
    head_sha: str
    mergeable: str | None
    head_committed_at: str | None
    last_change_request_at: str | None
    change_requests: int = 0

    @property
    def has_unaddressed_changes(self) -> bool:
        if self.last_change_request_at is None:
            return False
        if self.head_committed_at is None:
            return True
        return self.last_change_request_at > self.head_committed_at


@dataclass(frozen=True)
class Evidence:
    issues: dict[int, IssueEv]
    open_prs: dict[int, list[PullEv]]
    claim_refs: dict[int, set[str]]
    specs_landed: set[int]
    impl_merged: set[int]


GitRunner = Callable[[list[str]], tuple[bool, str]]


def _parse_claim_refs(stdout: str) -> dict[int, set[str]]:
    result: dict[int, set[str]] = {}
    for line in stdout.strip().splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        parsed = parse_branch(parts[1].removeprefix("refs/heads/"))
        if parsed is None:
            continue
        kind, number = parsed
        result.setdefault(number, set()).add(kind)
    return result


def _parse_specs_landed(stdout: str) -> set[int]:
    result: set[int] = set()
    for line in stdout.strip().splitlines():
        m = re.match(r"(\d+)-", line.strip().split("/")[-1])
        if m:
            result.add(int(m.group(1)))
    return result


def _last_change_request(reviews: list[dict]) -> str | None:
    dates = [r["submittedAt"] for r in reviews
             if r.get("state") == "CHANGES_REQUESTED" and r.get("submittedAt")]
    return max(dates) if dates else None


def _make_pull_ev(pr: dict, reviews: list[dict] | None = None) -> PullEv | None:
    branch = pr.get("headRefName", "")
    parsed = parse_branch(branch)
    if parsed is None:
        return None
    kind, issue = parsed
    if reviews is None:
        reviews = pr.get("reviews", [])
    return PullEv(
        number=pr["number"], kind=kind, issue=issue, branch=branch,
        head_sha=pr.get("headRefOid", ""), mergeable=pr.get("mergeable"),
        head_committed_at=None,
        last_change_request_at=_last_change_request(reviews),
        change_requests=sum(1 for r in reviews
                            if r.get("state") == "CHANGES_REQUESTED"),
    )


def gather(
    gh: GitHub,
    git_runner: GitRunner,
    base_ref: str,
    labels: list[str] | None = None,
) -> Evidence:
    """Snapshot every piece of evidence the projection needs.

    `labels` is unused and kept for call compatibility: issues are gathered in
    one unscoped call, because the projection must see closed and unlabelled
    issues too.
    """
    ok, refs_out = git_runner([
        "git", "ls-remote", "--heads", "origin", "meeseeks/*",
    ])
    claim_refs = _parse_claim_refs(refs_out if ok else "")

    ok, tree_out = git_runner([
        "git", "ls-tree", base_ref, "--name-only", "docs/spec/",
    ])
    specs_landed = _parse_specs_landed(tree_out if ok else "")

    issues: dict[int, IssueEv] = {}
    for raw in gh.all_issues():
        n = raw["number"]
        issues[n] = IssueEv(
            number=n, title=raw.get("title", ""),
            body=raw.get("body", ""),
            labels=frozenset(l["name"] for l in raw.get("labels", [])),
            closed=raw.get("state") != "OPEN",
        )

    open_prs: dict[int, list[PullEv]] = {}
    for pr in gh.open_prs():
        if parse_branch(pr.get("headRefName", "")) is None:
            continue
        # Reviews are not available from `pr list`, so they need their own
        # call per meeseeks PR — without them the revision trigger is dead.
        ev = _make_pull_ev(pr, gh.pr_reviews(pr["number"]))
        if ev is None:
            continue
        open_prs.setdefault(ev.issue, []).append(
            replace(ev, head_committed_at=gh.pr_head_committed_at(ev.number)),
        )

    impl_merged: set[int] = set()
    for pr in gh.merged_pr_branches():
        parsed = parse_branch(pr.get("headRefName", ""))
        if parsed and parsed[0] == "impl":
            impl_merged.add(parsed[1])

    return Evidence(
        issues=issues, open_prs=open_prs,
        claim_refs=claim_refs, specs_landed=specs_landed,
        impl_merged=impl_merged,
    )

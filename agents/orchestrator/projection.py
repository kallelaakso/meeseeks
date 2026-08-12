from __future__ import annotations

from orchestrator.evidence import Evidence


def desired_column(
    number: int,
    ev: Evidence,
    columns: dict[str, str],
) -> str:
    issue = ev.issues.get(number)
    labels = issue.labels if issue else frozenset()
    prs = ev.open_prs.get(number, [])
    impl_prs = [p for p in prs if p.kind == "impl"]
    spec_prs = [p for p in prs if p.kind == "spec"]
    claimed = ev.claim_refs.get(number, set())

    # 1. closed or impl merged -> done
    if (issue and issue.closed) or number in ev.impl_merged:
        return columns["done"]

    # 2. failed / blocked label -> blocked
    if "meeseeks:failed" in labels or "meeseeks:blocked" in labels:
        return columns["blocked"]

    # 3. open impl PR with unaddressed changes -> in_progress
    for p in impl_prs:
        if p.has_unaddressed_changes:
            return columns["in_progress"]

    # 4. open impl PR -> in_review
    if impl_prs:
        return columns["in_review"]

    # 5. impl claim -> in_progress
    if "impl" in claimed:
        return columns["in_progress"]

    # 6. spec landed -> ready
    if number in ev.specs_landed:
        return columns["ready"]

    # 7. open spec PR -> spec_review
    if spec_prs:
        return columns["spec_review"]

    # 8. otherwise -> backlog
    return columns["backlog"]

---
id: gh-foundation
depends-on: []
spec: 2026-08-12-github-board-workflow-design.md
---

# Plan 1 — Foundation: GitHub adapter, evidence, projection

## Goal

Add the read side of the new workflow: a single `gh` adapter, typed evidence
gathering, the pure projection function, and ticket-text parsing. **Purely
additive.** No existing file is modified; nothing is wired to a daemon yet. The
current file-based system must keep working unchanged.

## Rules

- Python 3, standard library only. No new dependencies.
- Every `gh` / `git` invocation goes through an injected runner so tests never
  touch the network.
- Small files. If one exceeds ~150 lines, split it.
- Type hints on all public functions; `from __future__ import annotations` at the
  top of every module, matching the existing style.

## Verify

```
cd agents && python3 -m unittest discover -s tests
```

Must pass at the end. All existing tests must still pass untouched.

---

## Step 1 — `agents/orchestrator/github.py`

The single seam for every REST call. Nothing else in the codebase may invoke
`gh` directly.

```python
Runner = Callable[[list[str]], tuple[bool, str]]  # (ok, stdout)

def default_runner(args: list[str]) -> tuple[bool, str]:
    """subprocess.run(args, capture_output=True, text=True) -> (rc == 0, stdout)"""

@dataclass(frozen=True)
class GitHub:
    owner: str
    repo: str
    run: Runner = default_runner
```

Methods (all thin wrappers that build an argv and parse JSON):

| Method | Command |
|---|---|
| `viewer_login()` | `gh api user -q .login` |
| `issues_with_label(label)` | `gh issue list --label <l> --state open --json number,title,body,labels,state` |
| `issue(number)` | `gh issue view <n> --json number,title,body,labels,state,stateReason` |
| `open_prs()` | `gh pr list --state open --json number,headRefName,headRefOid,title,mergeable,url` |
| `merged_pr_branches()` | `gh pr list --state merged --limit 100 --json number,headRefName` |
| `pr_reviews(number)` | `gh pr view <n> --json reviews` |
| `pr_head_committed_at(number)` | `gh pr view <n> --json commits -q '.commits[-1].committedDate'` |
| `create_ref(ref, sha)` | `gh api repos/{o}/{r}/git/refs -f ref=<ref> -f sha=<sha>` |
| `delete_ref(ref)` | `gh api -X DELETE repos/{o}/{r}/git/refs/heads/<name>` |
| `add_label(n, label)` | `gh issue edit <n> --add-label <l>` |
| `remove_label(n, label)` | `gh issue edit <n> --remove-label <l>` |
| `comment(n, body)` | `gh issue comment <n> --body-file -` (body on stdin) |
| `set_issue_body(n, body)` | `gh issue edit <n> --body-file -` |
| `create_pr(head, title, body, reviewer)` | `gh pr create --head <h> --title <t> --body-file - --reviewer <r>` |

**`create_ref` is the claim primitive and needs exact semantics:** return
`True` if created, `False` if the ref already exists (GitHub answers 422 with
`"Reference already exists"`), and raise `GitHubError` on any other failure.
Distinguish by inspecting the combined output for `already exists` — a lost race
must never be confused with a broken token or a network error.

The runner must therefore return stderr as well for this call; give
`default_runner` `stderr=subprocess.STDOUT` so the message is always visible.

Add `class GitHubError(RuntimeError)`.

Tests (`agents/tests/test_github.py`): a fake runner asserting the argv built
for each method, JSON parsing, `create_ref` returning `False` on an
already-exists message, and `create_ref` raising `GitHubError` on other
failures.

## Step 2 — `agents/orchestrator/projects.py`

Projects v2 is GraphQL-only; keep it isolated so its brittleness cannot spread.

```python
@dataclass(frozen=True)
class Board:
    project_id: str
    status_field_id: str
    option_ids: dict[str, str]      # option name -> option id

def load_board(gh: GitHub, project_number: int, status_field: str,
               required_options: list[str]) -> Board
def item_status(gh: GitHub, project_number: int) -> dict[int, tuple[str, str]]
    """issue number -> (item_id, current status option name)"""
def set_status(gh: GitHub, board: Board, item_id: str, option_name: str) -> None
```

`load_board` uses `gh project field-list <n> --owner <o> --format json`, and
**raises `GitHubError` naming every missing option** if any entry of
`required_options` is absent. This is the startup validation that makes a
renamed column fail loudly instead of silently no-op'ing forever. The daemon
never creates options.

`item_status` uses `gh project item-list <n> --owner <o> --format json`.

Tests: fake runner with a recorded field-list payload; assert option-id mapping,
assert the missing-option error names the missing ones.

## Step 3 — `agents/orchestrator/tickets.py`

Pure text functions. No I/O at all.

```python
def slugify(title: str) -> str
    """Lowercase, non-alphanumerics -> '-', collapse repeats, strip, max 40 chars."""

def branch(kind: str, number: int, slug: str) -> str      # meeseeks/<kind>/<n>-<slug>
def parse_branch(ref: str) -> tuple[str, int] | None      # (kind, number) or None
def spec_path(number: int, slug: str) -> str              # docs/spec/<n>-<slug>.md
def plan_path(number: int, slug: str) -> str              # docs/plan/<n>-<slug>.md
def artifact_glob(number: int, directory: str) -> str     # docs/<dir>/<n>-*.md

def parse_depends_on(body: str) -> list[int]
    """Every `Depends on: #12, #13` / `Depends on #12` line; deduped, ordered."""

def render_artifacts_block(spec: str, plan: str, spec_pr: int, repo_url: str) -> str
def upsert_artifacts_block(body: str, block: str) -> str
    """Replace between <!-- meeseeks:artifacts --> markers, append if absent.
    Never rewrites anything outside the markers."""
```

`parse_branch` must return `None` for anything not matching
`^meeseeks/(spec|impl)/(\d+)-`, so foreign branches are ignored.

Tests (`test_tickets.py`): slug edge cases (unicode, punctuation runs, long
titles, leading/trailing dashes); `parse_branch` rejecting `plan/foo`,
`meeseeks/impl/abc-x`, and accepting the valid forms; `parse_depends_on` with
zero/one/many/duplicate references and a `#` inside a code fence being ignored
is **not** required — keep it a simple line regex; `upsert_artifacts_block`
idempotency (applying twice yields the same body) and preservation of
surrounding text.

## Step 4 — `agents/orchestrator/evidence.py`

Typed snapshot of the world, gathered once per poll.

```python
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
    kind: str                       # 'spec' | 'impl'
    issue: int
    branch: str
    head_sha: str
    mergeable: str | None           # 'MERGEABLE' | 'CONFLICTING' | None
    head_committed_at: str | None   # ISO 8601
    last_change_request_at: str | None

    @property
    def has_unaddressed_changes(self) -> bool:
        """last_change_request_at > head_committed_at (string compare on ISO)."""

@dataclass(frozen=True)
class Evidence:
    issues: dict[int, IssueEv]
    open_prs: dict[int, list[PullEv]]   # issue -> its open meeseeks PRs
    claim_refs: dict[int, set[str]]     # issue -> kinds claimed
    specs_landed: set[int]
    impl_merged: set[int]
```

Gathering helpers:

- `gather(gh, git_runner, base_ref, labels) -> Evidence`
- Claim refs come from `git ls-remote --heads origin 'meeseeks/*'`, parsed with
  `parse_branch`. Free — no API quota.
- `specs_landed` comes from `git ls-tree <base_ref> --name-only docs/spec/`,
  matching `<n>-*.md`. Stateless and complete for all time; **do not** query
  merged PRs for this.
- `impl_merged` comes from `merged_pr_branches()` filtered through
  `parse_branch`.
- Only PRs whose branch parses as a meeseeks branch are included; everything
  else is invisible to the system.

`last_change_request_at` is `max(submittedAt)` over reviews with
`state == "CHANGES_REQUESTED"`, or `None`.

Tests (`test_evidence.py`): construct from fake payloads; assert foreign
branches are excluded; assert `has_unaddressed_changes` true/false/None-safe
around the timestamp comparison; assert `specs_landed` parses issue numbers out
of `ls-tree` output.

## Step 5 — `agents/orchestrator/projection.py`

The pure heart of the system. No I/O, no `gh`, no `git`.

```python
def desired_column(number: int, ev: Evidence, columns: dict[str, str]) -> str
```

Evaluate in this order, first match wins — most-advanced evidence first:

1. issue closed **or** `number in ev.impl_merged` → `columns['done']`
2. `meeseeks:failed` or `meeseeks:blocked` in labels → `columns['blocked']`
3. open impl PR with `has_unaddressed_changes` → `columns['in_progress']`
4. open impl PR → `columns['in_review']`
5. `'impl' in ev.claim_refs.get(number, set())` → `columns['in_progress']`
6. `number in ev.specs_landed` → `columns['ready']`
7. open spec PR → `columns['spec_review']`
8. otherwise → `columns['backlog']`

Label names come from config, not hardcoded — pass them in.

Tests (`test_projection.py`): **one test per row**, plus precedence tests that
matter: a closed issue with a failed label is Done; a landed spec with an open
spec PR is Ready (row 6 beats row 7); an impl claim with a landed spec is In
progress (row 5 beats row 6); an impl PR with change requests is In progress,
not In review. This is the module most worth over-testing — it is pure, so
tests are cheap and it encodes the entire state machine.

## Acceptance criteria

- Five new modules, all with tests, all passing.
- `git status` shows **no modifications to existing files** — additions only.
- `grep -rn '"gh"' agents/orchestrator/ | grep -v github.py | grep -v projects.py`
  returns nothing (adapter is the only seam).
- No module in this plan imports `layout.py` or `plans.py`.

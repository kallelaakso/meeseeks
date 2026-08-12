---
id: gh-daemon
depends-on: [gh-foundation]
spec: 2026-08-12-github-board-workflow-design.md
---

# Plan 2 — The board daemon: claim, run, reconcile

## Goal

Build the write side and a working daemon, **installed alongside the existing
one**. New entrypoint `agents/board_daemon.py`, new config `agents/board.json`.
The old `daemon.py` / `config.json` / `worker.py` path is **not touched** and
must remain fully runnable — it is what executes this very plan and plan 3.

Plan 3 deletes the old system and renames `board_*` to canonical names. Do not
do that here.

## Rules

- Standard library only. All GitHub access through `orchestrator/github.py` and
  `orchestrator/projects.py` from plan 1 — no new `gh` invocations anywhere else.
- Every module that makes decisions must be testable without the network: pass
  the `GitHub` object (with its injectable runner) and a git runner in.
- Small files. Split anything past ~150 lines.

## Verify

```
cd agents && python3 -m unittest discover -s tests
```

---

## Step 1 — `agents/board.json` and `agents/orchestrator/boardconfig.py`

New config file, new schema. Do **not** modify `config.json` or `config.py`.

```json
{
  "owner": "kallelaakso",
  "repo": "meeseeks",
  "project_number": 3,
  "bot_login": "meeseeks-bot",
  "reviewer": "kallelaakso",
  "base_branch": "main",
  "remote": "origin",
  "poll_interval_seconds": 30,
  "max_spec_concurrency": 1,
  "max_impl_concurrency": 3,
  "max_revision_attempts": 3,
  "status_field": "Status",
  "columns": {
    "backlog": "Backlog",
    "spec_review": "Spec in review",
    "ready": "Specs (ready for dev)",
    "in_progress": "In progress",
    "in_review": "In review",
    "blocked": "Blocked",
    "done": "Done"
  },
  "labels": {
    "arm": "meeseeks:spec-me",
    "failed": "meeseeks:failed",
    "blocked": "meeseeks:blocked"
  },
  "spec_agent_command": "claude -p --model opus --permission-mode acceptEdits \"$(cat {prompt_file})\"",
  "impl_agent_command": "opencode run -m opencode-go/kimi-k2.6 \"$(cat {prompt_file})\"",
  "verify_command": "cd agents && python3 -m unittest discover -s tests"
}
```

`boardconfig.py` mirrors the validation style of the existing `config.py`:
frozen dataclass, unknown keys rejected, missing required keys rejected, plus
`columns` and `labels` required-key checks. Reject `poll_interval_seconds < 5`
and any concurrency `< 1`.

Tests: valid load, unknown key, missing key, missing column entry, bad interval.

## Step 2 — `agents/orchestrator/ledger.py`

Local record of **this machine's own** claims. Plain JSON, no sqlite.

`agents/state/claims.json`:

```json
{"42": {"kind": "impl", "branch": "meeseeks/impl/42-slug", "pid": 1234,
        "started_at": "2026-08-12T10:03:00Z"}}
```

```python
def load(path) -> dict[int, Claim]
def record(path, number, kind, branch, pid, started_at) -> None
def forget(path, number) -> None
def own_claims(path) -> dict[int, Claim]
```

Writes must be atomic: write to `<path>.tmp`, then `os.replace`. A crash
mid-write must never leave unparseable JSON; a corrupt file logs a warning and
is treated as empty rather than crashing the daemon.

Tests: round-trip, atomic replace leaves no tmp file, corrupt file yields `{}`.

## Step 3 — `agents/orchestrator/claiming.py`

```python
def claim(gh, ledger_path, kind: str, number: int, slug: str,
          base_sha: str, now: str) -> str | None
```

1. Build `branch = tickets.branch(kind, number, slug)`.
2. `gh.create_ref(f"refs/heads/{branch}", base_sha)`.
3. `False` (ref exists) → return `None`. Another machine won; log and move on.
4. `True` → `ledger.record(...)`, post the claim comment
   `🤖 claimed by meeseeks@<hostname> · <ISO now>`, return the branch.

```python
def release(gh, ledger_path, number: int, kind: str) -> None
    """Delete the remote ref, drop the ledger entry. Idempotent."""
```

The in-process guard lives in the daemon (a `set[int]` of in-flight issues
checked before calling `claim`), not here.

Tests: winner path records + comments; loser path (`create_ref` → `False`)
returns `None`, writes no ledger entry, posts no comment; `release` is
idempotent when the ref is already gone.

## Step 4 — `agents/orchestrator/queues.py`

Pure functions deciding what is eligible. No I/O.

```python
def spec_queue(ev: Evidence, labels: dict[str, str]) -> list[int]
```
Open issues carrying the arm label, not closed, with no `spec` claim ref and no
open spec PR.

```python
def impl_queue(ev: Evidence, labels: dict[str, str]) -> list[int]
```
Issues where: spec has landed (`number in ev.specs_landed`), not closed, no
`impl` claim ref, no open impl PR, not labelled failed/blocked, **and every
`Depends on: #N` from the issue body is in `ev.impl_merged`**.

```python
def dependency_cycles(ev: Evidence) -> list[list[int]]
```
Detect cycles among `Depends on:` edges so they can be labelled rather than
stalling silently.

Tests: gating on unmerged dependency; releasing once the dependency merges;
closed issues never queued; a self-dependency and a two-node cycle both
detected; an arm label on an issue that already has a spec PR is not re-queued.

## Step 5 — `agents/orchestrator/job.py`

One function running one unit of work in a worktree, for either kind.

```python
def run_job(kind: str, number: int, slug: str, branch: str,
            cfg: BoardConfig, gh: GitHub, log_path: Path) -> str
```
Returns `"opened"`, `"failed"`, or `"empty"`.

1. `fetch_base`, then create a worktree at `.worktrees/<n>-<slug>` on the
   already-created claim branch. Add a new function to `worktree.py`:
   `create_worktree_on(repo, worktrees_dir, name, branch, base_ref)` that checks
   out an **existing** branch rather than creating one (`git worktree add <path>
   <branch>`). Do not modify the existing `create_worktree` — the old system
   still uses it.
2. Render the prompt: read `cfg.<kind>_agent_command`, format with
   `{prompt_file}`, `{worktree}`, `{branch}`, `{issue}`, `{verify_command}`.
3. Run the agent with stdout/stderr appended to `agents/logs/<n>.log`.
4. `git add -A`; commit as `<kind> #<n>: <title>` if anything is staged.
5. If no commit exists over the base ref → return `"empty"`.
6. impl kind only: run `cfg.verify_command` in the worktree; failure →
   `"failed"`.
7. Push the branch, then `gh.create_pr(...)`:
   - spec: title `[spec] <issue title>`, body ends with `Refs #<n>`
   - impl: title `<issue title>`, body ends with `Closes #<n>`
   - both: `--reviewer <cfg.reviewer>`
8. Return `"opened"`.

Idempotency: if an open PR already exists for the branch, treat as `"opened"`
rather than erroring — the daemon may have crashed between push and PR creation.

Tests with fake runners: each return path; verify-failure short-circuits before
PR creation; the impl PR body contains `Closes #<n>` and the spec PR body does
not.

## Step 6 — `agents/orchestrator/janitor.py`

Everything that maintains work already in flight. Each function takes evidence
and acts; all are idempotent and safe to run every poll.

```python
def handle_revisions(ev, cfg, gh, spawn) -> list[int]
```
For each open PR with `has_unaddressed_changes`: count the bot's push commits
since the first change request; at `>= cfg.max_revision_attempts`, label
`meeseeks:blocked` and comment why, and stop. Otherwise re-run the agent in the
existing worktree with the review comments appended to the prompt.

```python
def handle_conflicts(ev, cfg, gh, git) -> None
```
Only for `mergeable == "CONFLICTING"`: `git rebase <base>` in the worktree, then
re-run `verify_command`, then `git push --force-with-lease`. Any failure →
`fail()` below. Never touch a merely-behind PR.

```python
def handle_spec_merges(ev, cfg, gh) -> None
```
For each issue whose spec landed: upsert the artifacts block into the issue body
(`tickets.upsert_artifacts_block`), then delete the spec claim ref and its
worktree. Idempotent — re-running writes the identical body.

```python
def handle_rejections(ev, cfg, gh) -> None
```
Spec PR closed unmerged → delete the claim ref and worktree, comment, and
**remove the arm label**. Without the label removal the daemon rewrites the same
rejected spec every poll, forever.

```python
def handle_completions(ev, cfg, gh, ledger_path) -> None
```
Impl PR merged → remove the worktree and drop the ledger entry.

```python
def fail(gh, cfg, number, reason, log_path) -> None
```
Label `meeseeks:failed`, comment with the reason, the branch, and the **last 60
lines of the log truncated to 8 KB**. This comment is the only way a teammate
sees why something broke on someone else's machine — it is not optional.

Also: **re-arm detection.** An issue whose `meeseeks:failed` label has been
removed by a human but which still has a claim ref → delete the ref and the
worktree so the next poll claims it fresh. This replaces `requeue.py`.

Tests: the revision cap triggering exactly at the configured attempt; conflict
handling skipped for `MERGEABLE`; rejection removing the arm label; artifacts
upsert idempotency; `fail()` truncating a long log.

## Step 7 — `agents/orchestrator/reconcile.py`

```python
def reconcile(gh, board, ev, cfg) -> list[tuple[int, str, str]]
```
For each issue on the board: compute `projection.desired_column(...)`, compare
with the current status from `projects.item_status`, and write only the
differences. Return the list of `(issue, from, to)` for logging.

Never raises out of the daemon loop: a Projects API failure logs and returns
`[]`. The board lagging must never stop work.

Tests: only differing items are written; an unchanged board issues zero
mutations; an API failure returns `[]` without raising.

## Step 8 — `agents/board_daemon.py` and `agents/release.py`

`board_daemon.py`:

1. Load config; construct `GitHub`.
2. **Startup validation, all fatal:**
   - `gh.viewer_login() == cfg.bot_login`, else exit with a message naming both
     logins — this catches the whole class of "running as a human" that would
     silently break the review loop.
   - `projects.load_board(...)` with all seven column names required.
3. `recover()`: for each claim in the local ledger with no live process, decide
   whether the work escaped. Only ever touch claims recorded in **this
   machine's** ledger.

   The escaped test, in order:
   - the remote ref exists with commits beyond the base sha → escaped;
     `fail()` for triage, **or**
   - the local branch has at least one commit over base
     (`git rev-list --count <base>..<branch>` > 0) **and** those commits are an
     ancestor of base → escaped; `fail()`
   - otherwise → release the claim so the next poll re-claims it cleanly.

   **Do not port `recovery.py:_branch_landed` as written.** It asks only
   `merge-base --is-ancestor <branch> <base>`, which is trivially true for a
   branch with **zero** commits — so an interruption *before* the orchestrator
   commits is misreported as "work landed" and the ticket is dead-ended into
   triage instead of retried. This bug was hit for real while implementing plan
   1. The commit-count check above is the fix. Add a regression test: zero
   commits over base must release, not fail.
4. Loop every `poll_interval_seconds`:
   - gather evidence
   - `janitor.*` maintenance
   - fill spec slots up to `max_spec_concurrency`, impl slots up to
     `max_impl_concurrency`, skipping issues in the in-process guard set
   - `reconcile`
   - reap finished workers, log outcomes
5. Rate limiting: on a `gh` failure mentioning rate limit, sleep for one full
   poll interval and continue rather than crashing.

Workers run as `multiprocessing.Process`, mirroring the existing daemon.

`agents/release.py` — `python3 agents/release.py <issue>`: delete the claim ref
and worktree, drop any local ledger entry, comment on the issue. The escape
hatch for a claim stranded by a machine that never came back.

## Step 9 — `agents/prompts/spec.md` and `agents/prompts/impl.md`

Prompts as reviewable files, not JSON strings.

`spec.md`: the agent receives the issue title, body, and comments. It must
explore the repo, then write exactly two files —
`docs/spec/<n>-<slug>.md` and `docs/plan/<n>-<slug>.md` — citing real paths and
line numbers the way the existing specs in `docs/spec/` do. It must end the spec
with an "Unresolved questions" section rather than inventing answers, and must
not modify any other file.

`impl.md`: the agent receives the plan path. It implements it in the worktree,
touching nothing outside, and must make `{verify_command}` pass. It must not
commit — the orchestrator commits.

Both must state: never modify files outside the worktree; never push; never
touch `docs/plan/archive/`.

## Acceptance criteria

- `python3 agents/board_daemon.py` starts, validates, and polls against a fake
  runner in tests; it is **not** run for real as part of this plan.
- `agents/daemon.py`, `agents/config.json`, `agents/worker.py` and every other
  existing file are byte-identical except `worktree.py`, which gains one new
  function.
- The old system still passes its own tests.
- No `gh` string appears outside `github.py` / `projects.py`.

# GitHub-board workflow — issues replace the file-based state machine

Date: 2026-08-12
Status: draft (awaiting review)

## Problem

Plan state today **is** the directory a plan file lives in
(`ready-for-work/` → `in-progress/` → `awaiting-merge/` → `done/`). That works
for one developer on one machine and breaks for a team:

- State changes are commits. Two developers moving two plans conflict in git.
- Claiming relies on `os.rename` being atomic — true on one filesystem, absent
  across machines.
- Work is invisible unless you clone the repo and list directories.
- Discussion has nowhere to live. Review of a spec happens in a chat window and
  evaporates.

GitHub already provides the missing pieces: issues (a work item with a
discussion), pull requests (a review surface with a merge gate), and a project
board (a shared view). This design moves the workflow onto them.

## Goals

- Work items are **GitHub issues**; the board is the shared view of their state.
- Both artifacts — the spec and the implementation plan — are produced by an
  agent and reviewed by a human in a pull request.
- Multiple developers, each running a daemon on their own machine, can never
  work the same ticket twice.
- No state is stored in two places. Every state is derived from GitHub and git.
- Failure is visible to the whole team, not to one laptop's log file.

## Non-goals

- Multi-repo boards. One repo, one project, one base branch.
- Replacing human review. A human merges every pull request, always.
- Portability / `.meeseeks/` packaging — deferred, to be re-specced afterward
  against the smaller surface this leaves behind.
- Preserving the file-based mode. This is a replacement, not an option.

## Core principle: evidence, not stored state

Every state in the system is already recorded in a cheap, atomic GitHub or git
primitive: an issue label, a pull request, a git ref, a file on the base branch.
The board's Status field is **derived** from those, never consulted.

Concretely, the daemon:

1. Gathers evidence (issues, open PRs, remote refs, base-branch file list).
2. Computes each ticket's column as a pure function of that evidence.
3. Writes the column only where it differs from what the board shows.

Consequences, accepted deliberately:

- **Dragging a card does nothing.** The next poll reverts it. Control is via
  labels, PR merges, and reviews.
- The Projects GraphQL API — the least testable, most brittle component — is
  **write-only and non-load-bearing**. If it fails, work continues; the board
  lags.
- Recovery is trivial: state is recomputed from scratch, never remembered.
- The projection is a pure function over dataclasses, so it is exhaustively
  unit-testable with no API mocking.

## Roles and lifecycle

One daemon process runs two queues.

**Spec queue.** Finds open issues labelled `meeseeks:spec-me`. For each: claim,
create a worktree, run the spec agent, commit `docs/spec/<n>-<slug>.md` and
`docs/plan/<n>-<slug>.md`, push, open a PR titled `[spec] …` with `Refs #<n>`,
request review, remove the arm label.

**Impl queue.** Finds open issues whose spec has landed on the base branch and
whose dependencies are merged. For each: claim, worktree, run the impl agent,
verify, commit, push, open a PR with `Closes #<n>`, request review.

**Reconciler.** Runs once per poll after both queues: computes and writes board
columns.

A human reviews both PR kinds in GitHub and merges them. Merging the spec PR
arms implementation; merging the impl PR closes the issue and completes the
ticket.

The human's remaining duties are exactly: write the ticket, arm it, review two
PRs, merge them.

## Identification and naming

The **issue number is the primary key** throughout — branches, worktrees, logs,
and file names.

| Thing | Form |
|---|---|
| Spec branch | `meeseeks/spec/<n>-<slug>` |
| Impl branch | `meeseeks/impl/<n>-<slug>` |
| Spec file | `docs/spec/<n>-<slug>.md` |
| Plan file | `docs/plan/<n>-<slug>.md` |
| Worktree | `.worktrees/<n>-<slug>` |
| Log | `agents/logs/<n>.log` |

PR kind is determined **solely by branch prefix**, parsed with
`^meeseeks/(spec|impl)/(\d+)-`. One `gh pr list` call therefore yields every
meeseeks PR, its kind, and its issue number, with no dependence on mutable
metadata. The `[spec]` title prefix and any labels are decoration for humans;
editing them breaks nothing.

The slug is generated once, at spec time, from the issue title, and **never
regenerated** — the artifact glob is `docs/spec/<n>-*.md`, so two files matching
would be ambiguous. Renaming the issue later does not rename anything.

## Claiming: atomic, cross-machine

Claiming is creating the work branch, which GitHub performs as a create-only
operation:

```
gh api repos/{owner}/{repo}/git/refs -f ref=refs/heads/meeseeks/impl/42-slug \
                                     -f sha=<base-sha>
```

This returns **422 Reference already exists** if another machine won. There is
no read-modify-write window. The equivalent git form is
`git push --force-with-lease=<ref>: origin <sha>:<ref>`, where an empty expected
value asserts the ref does not exist.

The claim is taken **before** the agent runs, so a loser wastes nothing. The
lock object is the work branch itself — there is no separate lock to leak.
`git ls-remote --heads origin 'meeseeks/*'` returns every claim held by every
machine in one free call.

A per-process guard (a set of in-flight issue numbers) prevents one daemon from
racing itself before the round-trip completes.

On winning a claim the daemon posts one issue comment:
`🤖 claimed by <daemon>@<host> · <ISO timestamp>` — giving the team a
server-side record of who holds what, since a ref pushed at base-sha carries no
timestamp of its own.

### Recovery and stale claims

Each daemon records its own claims in a local JSON file
(`agents/state/claims.json`: issue → kind, branch, pid, started_at). On startup
it releases **only its own** orphans. Another machine's stale claim requires an
explicit `meeseeks release <n>`.

No heartbeat. A heartbeat's failure mode — a network blip declaring a live
worker dead, producing two agents on one ticket — breaks the system's one hard
invariant, to save a manual action that arises roughly never.

Carried over verbatim from today's `recovery.py`: if the work **already landed**
(branch pushed with commits, or merged into base), do not re-run it. Label
`meeseeks:failed` and leave it for triage.

## The projection

Evaluated per issue, most-advanced evidence first; the first match wins.

| # | Evidence | Column |
|---|---|---|
| 1 | issue closed, or impl PR merged | Done |
| 2 | `meeseeks:failed` or `meeseeks:blocked` label | Blocked |
| 3 | impl PR open, unaddressed change request | In progress |
| 4 | impl PR open | In review |
| 5 | impl claim ref exists | In progress |
| 6 | `docs/spec/<n>-*.md` exists on base | Specs (ready for dev) |
| 7 | spec PR open | Spec in review |
| 8 | otherwise | Backlog |

Notes:

- Rows 3/4 put a PR sent back for changes in `In progress` — the board says
  where the ball is.
- Row 6 before row 7: once a spec has landed, a later spec PR does not drag the
  card backwards.
- The brief window where the spec agent is running but no PR exists (row 8)
  renders as Backlog. A card that flickers for two minutes is noise.

The board needs two new Status options: **Spec in review**, placed second so
flow reads strictly left to right, and **Blocked**, placed last as an off-flow
holding state:

`Backlog → Spec in review → Specs (ready for dev) → In progress → In review → Done`, plus `Blocked`.

### Spec-landed evidence

"The spec has landed" is `git ls-tree origin/main --name-only docs/spec/`
containing `<n>-*.md`. One free git call, complete for all time, immune to clock
skew and crashes — and no time-windowed query over merged PRs.

A side effect worth stating: a spec written **by hand** and merged normally arms
the impl daemon identically. The system does not care who wrote the spec.

## Triggers

**Arming a ticket** is adding the `meeseeks:spec-me` label. Backlog stays an
idea dump; nothing is spec'd without an explicit act. The daemon finds work via
`gh issue list --label meeseeks:spec-me --state open`, needing **no Projects API
access to discover work** — only to render the board afterwards. The label is
removed once the spec PR is open, so the queue self-drains and re-arming is one
click.

**Revision** triggers on a submitted review with `CHANGES_REQUESTED` — GitHub
already batches inline comments into one intentional event — or on a comment
containing `/meeseeks`, for a tweak not worth a formal review. Loose comments
remain conversation.

Feedback is unaddressed iff `max(review.submittedAt) > branch_head.committedAt`.
No stored state: the moment the agent pushes, the head is newer and the flag
self-clears, identically from any machine.

Two accepted edges:

- A no-op push clears the flag. Your next review catches it; tracking intent is
  not buildable.
- An agent that cannot fix the problem produces no commit and would retry
  forever. Cap revisions at **3** attempts per PR (counted from the agent's own
  push commits since the first review), then label `meeseeks:blocked`, comment
  why, and stop.

## Dependencies

A line in the issue body:

```
Depends on: #41
```

Parsed by regex from a payload already fetched. Satisfied **iff the dependency's
impl PR is merged** — checked from evidence, never from the rendered column,
which may lag. "Declared done" is insufficient: the dependent agent branches off
base, and if the prerequisite is not in base it redoes and conflicts with that
work.

Dependencies gate **impl claims only**. Writing and reviewing a spec for a
blocked ticket is harmless and often valuable early.

Cycles are detected and labelled `meeseeks:blocked` with a one-time comment,
rather than stalling silently forever.

## Failure

On any failure (verify red, no commits produced, push rejected, rebase
conflict):

1. Label `meeseeks:failed` → the card renders as **Blocked**.
2. Post a comment with the failure reason, the branch name, and the **tail of
   the log** (last ~60 lines, truncated at ~8 KB).
3. Stop. No automatic retry — agent failures are usually deterministic, and
   retrying burns tokens to reach the same red.

Step 2 is the multi-developer debugging story. A log that only exists on the
laptop that failed is worthless to everyone else.

**Re-arming is removing the `meeseeks:failed` label.** The daemon then deletes
the stale claim ref and worktree and re-claims from scratch, starting fresh from
base. A half-finished attempt is more likely to confuse a cheap model than help
it; `git reflog` preserves it locally if ever needed. This replaces
`requeue.py`.

## Merge conflicts

`integration_mode: auto-merge` is **deleted**. A human merges, always. This
removes `_auto_merge()`, the `git checkout <base>` dance in the primary
checkout, and the primary-checkout ownership hazard documented in
`agents/README.md`.

Staleness splits in two:

- **Behind but mergeable** — do nothing. GitHub merges it cleanly; touching it
  would orphan in-flight review threads for no benefit.
- **`mergeable: CONFLICTING`** — the daemon rebases onto base and force-pushes
  with `--force-with-lease`. A concurrent human push aborts the rebase rather
  than clobbering it. A rebase conflict is a failure per the section above.

After any rebase, **re-run `verify_command`**. A rebase that succeeds
mechanically can still be semantically wrong; a red verify is treated exactly
like a conflict.

## Identity

The daemon runs as a **machine user** (`meeseeks-bot`) via a fine-grained PAT in
`GH_TOKEN` — never in `config.json`, never committed. Scopes: Contents RW, Pull
requests RW, Issues RW, Projects RW.

This is not cosmetic. GitHub forbids approving or requesting changes on **your
own** pull request, so a daemon running under the human's token would make the
`CHANGES_REQUESTED` trigger unreachable and any review-based merge gate
impossible.

At startup the daemon calls `gh api user` and **refuses to start** if the login
is not the configured bot, catching this entire class of misconfiguration
immediately.

## Configuration

`agents/config.json`, with board binding by **name** (readable), resolved to
field/option IDs once at startup via `gh project field-list`. A missing name is
a startup failure, so a renamed column fails loudly instead of silently
no-op'ing forever.

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
  "spec_agent_command": "… {prompt_file} {worktree} {branch} …",
  "impl_agent_command": "… {prompt_file} {worktree} {branch} {verify_command} …",
  "verify_command": "cd agents && python3 -m unittest discover -s tests"
}
```

Removed keys: `integration_mode`, `merge_sweep_interval_seconds`, all
`dashboard_*`.

**Prompts move out of JSON** into `agents/prompts/spec.md` and
`agents/prompts/impl.md`, referenced by `{prompt_file}`. Prompt quality is now
the primary lever on output quality; it deserves a diffable, reviewable file
rather than an escaped config string.

Separate concurrency limits matter: a shared pool lets three long impl runs
starve the spec queue, and spec turnaround gates the human's review throughput.

## Component map

**New**

| Module | Responsibility |
|---|---|
| `orchestrator/github.py` | Every `gh` call, behind an injectable runner |
| `orchestrator/evidence.py` | Fetch + typed dataclasses for issues, PRs, refs, base files |
| `orchestrator/projection.py` | Pure evidence → column function |
| `orchestrator/reconcile.py` | Diff computed vs actual columns; write differences |
| `orchestrator/tickets.py` | Issue body parsing: `Depends on:`, artifacts block |
| `orchestrator/ledger.py` | Local JSON claim record for self-recovery |
| `agents/prompts/{spec,impl}.md` | Agent prompts |

**Rewritten:** `claim.py` (ref creation), `recovery.py` (ledger-scoped),
`worker.py` (parameterized by kind), `config.py`, `daemon.py`, `run_once.py`.

**Survive with small changes:** `worktree.py` (branch naming),
`integrate.py` (`pr` mode only), `fsops.py`.

**Deleted:** `plans.py`, `layout.py`, `merge.py`, `requeue.py`, the entire
`dashboard/` package, `dashboard.py`, and their tests — roughly 1,500 lines.

The dashboard's one irreplaceable feature, the transition timeline, is
recoverable later from GitHub's own event API without any local poller, so
deleting now does not burn that bridge.

## Closing semantics

- Impl PRs carry `Closes #<n>`; spec PRs carry `Refs #<n>` and must not close
  the issue — the ticket's life is half over at that point.
- **Projects built-in workflows:** keep "auto-add item to project" ON (it is the
  only reason a new issue appears on the board); turn every status-changing
  built-in and auto-archive **OFF**, so meeseeks is the sole writer of Status.
  An archived item is invisible to the projection and would silently no-op.
- **Issue closed by a human** renders as Done; the close *reason* ("not
  planned") preserves the distinction better than a column would. The daemon
  must never claim a closed issue and must stop touching one that closes
  mid-flight.
- **Spec PR closed unmerged** (spec rejected): delete the claim branch, comment,
  and leave the issue in Backlog **with the arm label removed**. Without that
  removal, rejection becomes an infinite loop — the daemon would rewrite the
  same rejected spec every poll.

## Ticket format

Documented as a convention in `CLAUDE.md`, not enforced by an issue form — a
rigid form is friction for a human filing a quick bug and is bypassed entirely
by `gh issue create`.

```markdown
## Problem
## Goals
## Non-goals
## Constraints
## Acceptance criteria
Depends on: #41
```

The ticket body is the sole input to an autonomous Opus run. It is the
highest-leverage artifact in the system; a poor ticket cannot be rescued
downstream.

## The planner's role, rewritten

`CLAUDE.md` changes from "Opus writes specs and plans" to:

1. Brainstorm and grill the human.
2. Write the ticket body, get approval, `gh issue create` it.
3. Add `meeseeks:spec-me` only on explicit go.
4. Never write specs, plans, or implementation code.

The hard rule survives; its scope shifts up one level. The `write-agent-plan`
skill is retired and its content becomes `agents/prompts/spec.md`.

Both daemons pass `--reviewer <configured login>` on PR creation, so work lands
in the human's GitHub review queue with native notifications rather than
depending on someone remembering to check a board.

## Testing

- `projection.py`, `tickets.py`, dependency gating, slug generation, revision
  counting: pure functions over dataclasses, exhaustively unit-tested with no
  mocking.
- `github.py`: single seam, faked via the injected runner — the pattern
  `dashboard/gh.py` already uses.
- `claim.py`: fake runner returning 422 to assert loser behaviour.
- `worker.py`: existing tests adapted; kind-parameterized.

## Migration

- Existing plan state dirs and their contents move to `docs/plan/archive/`. The
  new glob is non-recursive, so archived plans can never accidentally match.
- Existing date-prefixed specs keep their names. New artifacts are
  `<n>-<slug>.md`.
- Board: add `Spec in review` (position 2) and `Blocked` Status options; disable
  status-changing built-in workflows.
- Create the `meeseeks-bot` machine user, add as collaborator, issue the PAT.
- **This refactor cannot be built through its own workflow** (the daemon that
  would build it does not exist yet). It goes through the current file-based
  flow one last time, as the final act of the old system.

### Rollout: parallel install, then swap

The old daemon is what executes the three implementation plans, so it must keep
running until the last one merges. The new system is therefore built
**alongside** it, under distinct names, and only replaces it at the end:

| Plan | Effect on the old system |
|---|---|
| 1 — foundation | None. Purely additive modules, nothing wired. |
| 2 — daemon | None. New entrypoint `agents/board_daemon.py` + `agents/board.json`; old `daemon.py` / `config.json` untouched and still runnable. |
| 3 — cleanup | Deletes the old system and renames `board_*` to canonical names. |

Plan 3 deletes modules while the old daemon is running them. That is safe —
Python has already imported them — but the old daemon must **not be restarted**
after plan 3's agent runs. The human merges plan 3's PR, then decommissions the
old daemon and starts the new one.

Two steps stay **manual**, deliberately, because an agent doing them mid-flight
would break the machinery executing it:

- Moving the old `docs/plan/` state dirs into `docs/plan/archive/` — the running
  daemon still needs `ready-for-work/`, `in-progress/`, and `done/`.
- Adding the two board columns and creating the bot account.

## Resolved during review

1. **Columns** — added manually by the human. The daemon validates their
   presence at startup and refuses to run if any are missing; it never creates
   them.
2. **Branch protection** — out of scope. Recommended once the bot account
   exists, but not part of this work.
3. **`meeseeks release <n>`** — built in plan 2. It is ~30 lines (delete ref,
   drop the local ledger entry) and it is the only escape hatch for a claim
   stranded by a machine that never returns.
4. **Worktrees** — deleted when the impl PR merges, along with the local claim
   record. Kept on failure, since that is the only copy of the failed attempt.
5. **Split** — three plans, sequenced as above.

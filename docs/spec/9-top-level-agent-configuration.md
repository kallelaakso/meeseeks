# Top-level agent configuration — `.meeseeks/` owns the project, `agents/` owns the code

Date: 2026-08-12
Status: draft — awaiting review

Resolves the portability item deferred in
`docs/spec/2026-08-12-github-board-workflow-design.md:37` ("Portability /
`.meeseeks/` packaging — deferred, to be re-specced afterward against the
smaller surface this leaves behind").

## Problem

`agents/` is both the program and its configuration. Everything a second
project must change lives inside the directory it would want to update
wholesale:

- **`agents/config.json`** — every single value in it is project-specific:
  `owner`, `repo`, `project_number`, `bot_login`, `reviewer`, `base_branch`,
  both agent commands, `verify_command` (`agents/config.json:1-31`). It is a
  tracked file inside the vendored code, so an upgrade and a local setting
  collide in the same file.
- **The user must restate what is not project-specific.** `columns` and
  `labels` are *required* keys with no defaults (`orchestrator/config.py:23-24`,
  validated at `config.py:69-74`), so 20 of the config's 31 lines are boilerplate
  every project copies verbatim.
- **`agents/prompts/spec.md` and `agents/prompts/impl.md`** carry two mixed
  concerns: the orchestrator contract ("do not commit and do not push",
  "create only those two files" — `prompts/spec.md:41-44`,
  `prompts/impl.md:11-22`) and project facts that are simply false elsewhere
  ("standard library only unless the plan says otherwise",
  `prompts/impl.md:16`). A TypeScript project has to edit a shipped file to fix
  that line.
- **Runtime state is written inside the vendored directory** —
  `agents/state/claims.json` and `agents/logs/` (`daemon.py:29-30`,
  `release.py:23`), which the adopting project must then gitignore by those
  paths.
- **The code assumes it lives exactly one level below the project root.**
  `REPO = Path(__file__).resolve().parents[1]` (`daemon.py:28`,
  `release.py:22`), and `job.py:90` reads the prompt template as
  `repo / "agents" / "prompts" / f"{kind}.md"` — i.e. it looks for the *program's*
  prompts relative to the *project*. Vendoring the code anywhere but
  `<project>/agents/` silently breaks.

So "use meeseeks in project X" today means: copy `agents/`, hand-edit a tracked
file in it, and never move it.

## Goals

- One top-level, project-owned config file. Adopting meeseeks requires editing
  nothing under `agents/`.
- The required config is short: only values a wrong guess cannot be made for.
  Columns, labels, base branch, remote and tuning all default.
- Project-specific instructions for the agents have a top-level home that
  cannot break the orchestrator contract.
- Logs and claim state are written to the project, not into the program
  directory.
- Program location and project root are separate concepts, resolved separately,
  so `agents/` can be vendored anywhere (submodule, subtree, `vendor/`).
- No behaviour change for a correctly configured setup. Same claiming, same
  projection, same PRs.

## Non-goals

- **Packaging as a distributable** (`pip install meeseeks`, a console script,
  publishing to PyPI). This spec makes that possible later by splitting install
  root from project root, but does not do it.
- **Multi-repo / multi-board.** Still one repo, one project, one base branch.
- **Making `docs/spec/` and `docs/plan/` configurable.** They are hardcoded in
  `tickets.py:30-39` and `evidence.py:118`, and the spec-landed projection
  depends on that glob. Out of scope here; see Unresolved questions.
- **A generator / `meeseeks init` command.** The config is eight keys; a README
  block is enough.
- **Any change to the workflow itself** — labels, projection, claiming, PR
  semantics all stay exactly as specified in the board-workflow design.
- **Backwards compatibility with `agents/config.json`.** It is deleted, not
  deprecated (see Design).

## Design

### Two roots, named and resolved separately

The whole class of bug above comes from one conflation. Split it:

| Root | What lives there | How it is found |
|---|---|---|
| **Install root** | `daemon.py`, `orchestrator/`, `prompts/` | `Path(__file__).resolve().parents[1]` — the code knows where it is |
| **Project root** | `.meeseeks/`, `docs/`, `.worktrees/`, `.git` | discovered by marker file (below) |

Everything the program ships is addressed from the install root
(`job.py:90`'s prompt lookup becomes install-relative — today it is the one
place the two roots are actively confused). Everything the project owns is
addressed from the project root.

### Project root discovery

A new module `agents/orchestrator/paths.py` owns this. The marker is
`.meeseeks/config.json`, resolved in order:

1. `$MEESEEKS_ROOT`, if set — for systemd units and anything with no useful
   working directory. A missing marker under it is a hard error, not a fallback,
   because silently ignoring an explicit override is worse than failing.
2. Walk up from the current working directory.
3. Walk up from the install root — covers the ordinary vendored-inside-the-repo
   case when the daemon is launched from an unrelated directory.

Failure is a single actionable message naming all three, not a `FileNotFoundError`
on a path the user never typed.

A `Paths` frozen dataclass carries the project root and derives the rest, so no
module recomputes a path from a string again:

```
Paths(root)
  .config     → <root>/.meeseeks/config.json
  .rules      → <root>/.meeseeks/rules.md
  .logs       → <root>/.meeseeks/logs
  .ledger     → <root>/.meeseeks/state/claims.json
  .worktrees  → <root>/.worktrees
```

`Paths` is a frozen dataclass of `Path`s, so it pickles — required, because
`daemon.spawn` passes its arguments to a `multiprocessing.Process`
(`daemon.py:100-107`) and the child currently reads module globals `REPO`,
`LOGS`, `LEDGER` that will no longer exist.

The daemon additionally refuses to start when `<root>/.git` is absent: every
git operation downstream assumes it, and failing at startup beats failing inside
a worker.

### `.meeseeks/` — a directory, not a single file

```
.meeseeks/config.json   board binding, agent commands, verify command   (committed)
.meeseeks/rules.md      optional project appendix to both prompts       (committed)
.meeseeks/logs/         per-issue agent logs                            (gitignored)
.meeseeks/state/        this machine's claims                           (gitignored)
```

A directory rather than a root-level `meeseeks.json` because there are already
four things, two of them committed and two not, and one gitignore prefix
(`.meeseeks/logs/`, `.meeseeks/state/`) beats scattering them. It also gives the
name the board-workflow design already reserved for this.

### Defaults in code, not in a shipped JSON file

`columns`, `labels`, `base_branch`, `remote`, `status_field` and all tuning move
to defaults in `orchestrator/config.py` (`DEFAULT_COLUMNS`, `DEFAULT_LABELS`,
`base_branch = "main"`). `columns` and `labels` are merged **key-wise** over the
defaults, so renaming one column costs one line instead of seven.

The minimum viable `.meeseeks/config.json` becomes:

```json
{
  "owner": "acme",
  "repo": "widgets",
  "project_number": 3,
  "bot_login": "acme-bot",
  "reviewer": "kallelaakso",
  "spec_agent_command": "claude -p --model opus --permission-mode acceptEdits \"$(cat {prompt_file})\"",
  "impl_agent_command": "opencode run -m opencode-go/kimi-k2.6 \"$(cat {prompt_file})\"",
  "verify_command": "npm test"
}
```

Key-wise merging introduces one hazard the current code does not have: today an
unknown key inside `columns` is silently ignored (`config.py:69-71` only checks
for *missing* keys), which under merging turns a typo like `"backlogg"` into an
override that never applies. So unknown `columns`/`labels` keys become an error,
matching how top-level unknown keys are already treated (`config.py:65-67`).

The agent commands stay **required**. Defaults are appropriate where a wrong
guess is cheap; guessing which model binary to spend money on is not, and a
default that silently runs the wrong agent is worse than a startup error.

### Project instructions: append, never replace

`.meeseeks/rules.md` is rendered into both shipped prompts through a new
`{project_rules}` token, alongside the existing `{feedback}` token
(`job.py:91-97`, and `render_prompt` already leaves unknown tokens alone —
`job.py:26-35`, tested at `tests/test_job.py:28-29`). Absent file → empty
string, exactly like `feedback` today.

Append rather than replace, because the shipped prompts encode the orchestrator
contract — do not commit, do not push, write exactly these two files, make
`{verify_command}` pass. A `prompts_dir` override would let a project silently
drop those lines and produce runs that fail in confusing ways (an agent that
commits breaks `_commit`'s "did the agent leave work" check at `job.py:44-54`).
The appendix carries what is genuinely local: stack, test runner, house style,
where docs live.

### Rejected alternatives

- **Keep `agents/config.json` as defaults, overlay `.meeseeks/config.json`.**
  Two files to read, merge semantics to explain, and an upgrade still rewrites a
  file the user was told to look at. Defaults belong in code, where they are
  typed and testable.
- **Environment variables for everything.** `columns` and `labels` are nested,
  so they would need either seven variables each or embedded JSON, and the board
  binding stops being diffable. `GH_TOKEN` stays the only environment input that
  matters, plus `MEESEEKS_ROOT` as a location escape hatch.
- **Symlink `agents/config.json` → `../.meeseeks/config.json`.** Cute, breaks on
  Windows and on export-based CI checkouts, and provides no defaults.
- **`prompts_dir` config key for full prompt replacement.** Rejected above:
  breaks the contract silently. Forking the whole install remains available to
  anyone who truly needs it.
- **Auto-writing `.meeseeks/.gitignore` on first run.** `.worktrees/` needs a
  root-level entry regardless, so the user reads a gitignore instruction either
  way; one documented snippet beats a program that edits the project's files
  outside its own artifacts.
- **`pip install` + `meeseeks` console script now.** Correct end state, wrong
  order: it would land at the same time as the config move and make the diff
  unreviewable. The two-roots split is the prerequisite and is the whole of this
  ticket.

### What the adopting project ends up owning

```
.meeseeks/config.json      binding + commands
.meeseeks/rules.md         optional
CLAUDE.md                  planner rules (already top-level)
.gitignore                 .worktrees/, .meeseeks/logs/, .meeseeks/state/
agents/                    vendored, never edited
```

`opencode.json` and `.claude/settings.json` need no mechanism: the agent CLIs
read their own configuration from the worktree root, which is a checkout of the
project, so they are already top-level and project-owned.

## Affected components

| Path | Change |
|---|---|
| `agents/orchestrator/paths.py` | **New.** Install root, `Paths`, `find_root`, `rules_text`. |
| `agents/orchestrator/config.py:12-30` | `columns`/`labels` gain defaults; `base_branch` defaults to `main`; field order shifts (all callers use kwargs). |
| `agents/orchestrator/config.py:56-83` | Key-wise merge of `columns`/`labels`; reject unknown keys in both. |
| `agents/orchestrator/job.py:90` | Prompt template read from the install root, not `repo / "agents" / "prompts"`. |
| `agents/orchestrator/job.py:91-97` | New `project_rules` token from `.meeseeks/rules.md`. |
| `agents/prompts/spec.md:39-44`, `agents/prompts/impl.md:11-22` | `{project_rules}` inserted; the hardcoded "standard library only" line moves out of the shipped prompt. |
| `agents/daemon.py:28-30` | `REPO`/`LEDGER`/`LOGS` module constants deleted. |
| `agents/daemon.py:37-48, 82-167` | `git`, `base_sha`, `_work`, `spawn`, `fill`, `poll_once` take `Paths` (and a git runner) instead of reading globals. |
| `agents/daemon.py:51-68, 169-171` | `validate` also checks `<root>/.git`; `main` resolves the root and reports failure actionably. |
| `agents/release.py:22-23, 43-51` | Same path treatment. |
| `agents/config.json` | **Deleted**, its non-default keys moved to `.meeseeks/config.json`. |
| `.meeseeks/config.json` | **New.** This repo's own binding, minimal form. |
| `.gitignore:1-3` | `agents/logs/`, `agents/state/` → `.meeseeks/logs/`, `.meeseeks/state/`; add `.meeseeks-prompt.md`. |
| `agents/tests/test_config.py:10-34, 109-113` | Fixture shrinks; `TestRealConfig` reads `.meeseeks/config.json`. |
| `agents/tests/test_job.py:67-70` | Prompts no longer created under the fake project root. |
| `agents/tests/test_paths.py` | **New.** |
| `README.md` (Setup 5, Layout, Running) | Config location, install shape, gitignore lines. |
| `agents/README.md:27-46` | Config-keys table gains defaults; add the two-roots section. |

`orchestrator/tickets.py`, `projection.py`, `queues.py`, `evidence.py`,
`claiming.py`, `janitor.py`, `reconcile.py`, `projects.py` and `github.py` are
untouched: they take paths and config as arguments already. That is the
measure of whether this refactor is the right size.

## Migration

This repo is its own first adopter. In the same PR: create
`.meeseeks/config.json` with the eight keys carried over from
`agents/config.json:2-30`, delete `agents/config.json`, move the gitignore
entries. Nothing is dual-read — a running daemon keeps working from its already
imported code and picks up the new layout on the next restart, which is when
the human restarts it anyway. A fallback to the old path would be one more
branch to maintain for a single-user migration that takes one commit.

Note that the worktree an agent runs in contains a committed copy of
`.meeseeks/config.json`, and nothing in `job.py` ever loads it. The daemon's
copy at the project root is the only one that decides anything.

## Unresolved questions

1. **Install shape.** Is `agents/` copied in, a git submodule, a subtree, or
   cloned elsewhere and pointed at a project via `MEESEEKS_ROOT`? Discovery is
   designed to survive all four, but the README can only document one as *the*
   way, and the ticket does not say.
2. **`.meeseeks/` vs root `meeseeks.json`.** Assumed `.meeseeks/`, per the name
   reserved in `docs/spec/2026-08-12-github-board-workflow-design.md:37`.
   Confirm before code exists — renaming later means another migration.
3. **One `rules.md` or per-kind rules.** Assumed one file injected into both
   prompts. A spec agent and an impl agent arguably want different additions
   (`rules.spec.md` / `rules.impl.md`); unspecified in the ticket.
4. **Should the agent commands default** to the current `claude`/`opencode`
   invocations? Kept required on the reasoning above, but this is the one
   judgment call that trades setup friction against a costly wrong default.
5. **`docs/spec/` and `docs/plan/` as config.** Declared a non-goal here, but a
   project that keeps docs elsewhere still has to edit `tickets.py`. Worth its
   own ticket if it matters — it touches the projection, so it is not a config
   key that can be added casually.
6. **Should `agents/` be renamed** (`meeseeks/`, `tools/meeseeks/`) once it is
   pure program? A directory called `agents/` at the root of someone else's
   project reads like *their* agents. Left alone here because renaming it and
   moving the config in one PR makes the diff much harder to review.

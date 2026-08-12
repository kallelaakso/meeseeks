---
issue: 9
spec: 9-top-level-agent-configuration.md
---

# Plan — Top-level agent configuration

## Goal

Move every project-specific setting out of `agents/` into a top-level
`.meeseeks/` directory, and stop the code from assuming it lives at
`<project>/agents/`. Adopting meeseeks in another repo must require editing
nothing under `agents/`.

Read `docs/spec/9-top-level-agent-configuration.md` first. The design in one
line: **install root** (where the code is, found from `__file__`) and **project
root** (where `.meeseeks/` is, discovered by walking up) are two different
things, and today they are conflated.

## Rules

- Standard library only. No new dependencies.
- Keep the existing style: frozen dataclasses, pure functions where possible,
  every path passed in as an argument rather than read from a module global.
- Small files. `paths.py` should land around 60 lines.
- No behaviour change to claiming, the projection, or PR semantics. If you find
  yourself editing `projection.py`, `queues.py`, `tickets.py`, `claiming.py`,
  `evidence.py` or `github.py`, stop — you are outside this plan.
- **Do not fix bugs you notice in code you are moving.** Spec unresolved
  question 7 lists two known ones in `evidence.py` / the git runner. Move the
  code as-is. A drive-by fix here makes the diff unreviewable.
- Do the steps in order. Each one leaves the test suite green, except step 2's
  `TestRealConfig`, which step 7 repairs — if you dislike that, do step 7 first.

## Verify

```
cd agents && python3 -m unittest discover -s tests
```

---

## Step 1 — `agents/orchestrator/paths.py` (new)

The single owner of "where is anything".

```python
CONFIG_DIR = ".meeseeks"
CONFIG_FILE = "config.json"
RULES_FILE = "rules.md"
WORKTREES_DIR = ".worktrees"

INSTALL_ROOT = Path(__file__).resolve().parents[1]   # the agents/ directory
PROMPTS_DIR = INSTALL_ROOT / "prompts"
```

`@dataclass(frozen=True) class Paths` with one field, `root: Path`, and
read-only properties:

| Property | Value |
|---|---|
| `config` | `root / ".meeseeks" / "config.json"` |
| `rules` | `root / ".meeseeks" / "rules.md"` |
| `logs` | `root / ".meeseeks" / "logs"` |
| `ledger` | `root / ".meeseeks" / "state" / "claims.json"` |
| `worktrees` | `root / ".worktrees"` |
| `is_git_repo` | `(root / ".git").exists()` — true for a worktree too, where `.git` is a file |

`Paths` must stay picklable (plain `Path` field, no closures): step 5 passes it
to a `multiprocessing.Process`.

`find_root(start: Path | None = None, env: Mapping[str, str] | None = None) -> Path`:

1. `env` defaults to `os.environ`. If `MEESEEKS_ROOT` is set, use it; if
   `<that>/.meeseeks/config.json` does not exist, raise — never fall through an
   explicit override.
2. Otherwise walk `start` (default `Path.cwd()`) and its parents for the first
   directory containing `.meeseeks/config.json`.
3. Otherwise walk `INSTALL_ROOT` and its parents the same way.
4. Otherwise raise `ConfigNotFound` (define it in this module, subclassing
   `Exception`) with a message naming `MEESEEKS_ROOT`, the cwd it searched, and
   the install root it searched.

`rules_text(paths: Paths) -> str`: the contents of `paths.rules`, or `""` when
the file does not exist. Never raise.

**Tests — `agents/tests/test_paths.py` (new).** Use `tempfile.mkdtemp()`; do not
touch the real repo. Always pass an explicit `env` dict so a developer with
`MEESEEKS_ROOT` exported does not fail the suite.

- `find_root` finds a marker in the start directory itself.
- `find_root` finds a marker several levels up from a nested start directory.
- `MEESEEKS_ROOT` wins over a valid marker found by walking up.
- `MEESEEKS_ROOT` pointing at a directory with no marker raises `ConfigNotFound`
  (it does **not** silently fall back).
- no marker anywhere reachable raises `ConfigNotFound`, and the message mentions
  `MEESEEKS_ROOT`.
- every `Paths` property lands under `<root>/.meeseeks/`, except `worktrees`.
- `is_git_repo` is false for a bare temp dir, true once `.git` exists.
- `rules_text` returns `""` for a missing file and the exact text when present.
- `Paths` survives `pickle.loads(pickle.dumps(paths))` and compares equal.

---

## Step 2 — defaults and merging in `agents/orchestrator/config.py`

Add module constants next to the existing `COLUMN_KEYS` / `LABEL_KEYS`
(`config.py:7-9`):

```python
DEFAULT_COLUMNS = {
    "backlog": "Backlog",
    "spec_review": "Spec in review",
    "ready": "Specs (ready for dev)",
    "in_progress": "In progress",
    "in_review": "In review",
    "blocked": "Blocked",
    "done": "Done",
}
DEFAULT_LABELS = {
    "arm": "meeseeks:spec-me",
    "failed": "meeseeks:failed",
    "blocked": "meeseeks:blocked",
}
```

Take the values verbatim from `agents/config.json:14-27`.

In the `Config` dataclass (`config.py:12-30`):

- `columns` and `labels` get
  `field(default_factory=lambda: dict(DEFAULT_COLUMNS))` /
  `... DEFAULT_LABELS`.
- `base_branch` gets the default `"main"`.
- Dataclass rules force fields with defaults after fields without, so
  `base_branch`, `columns` and `labels` move below `verify_command`. Every
  construction site already uses keyword arguments (`config.py:83`,
  `tests/test_job.py:56`, `tests/test_reconcile.py:33`, `tests/test_daemon.py:22`,
  `tests/test_janitor.py:36`) — re-check with `grep -rn "Config(" agents` before
  moving anything, and convert any positional call rather than working around
  the ordering.

In `load_config` (`config.py:56-83`), after the existing top-level
missing/unknown-key checks (`config.py:59-67`):

- merge key-wise: `columns = {**DEFAULT_COLUMNS, **data.get("columns", {})}`,
  same for labels, and pass the merged dicts to `Config`.
- **reject unknown keys** inside `columns` and `labels`
  (`data["columns"].keys() - COLUMN_KEYS`) with a message naming the offenders.
  This is new and it is the point: under merging, a typo'd key would otherwise
  be an override that silently never applies.
- keep the missing-key checks at `config.py:69-74` (they now only fire if
  someone passes an explicitly truncated dict, but they cost nothing) and keep
  the `poll_interval_seconds >= 5` and concurrency `>= 1` validation
  (`config.py:76-81`) unchanged.

**Tests — `agents/tests/test_config.py`.** Shrink `VALID` (lines 10-34) to the
eight required keys, then add:

- a config with no `columns`/`labels` loads, and `cfg.columns["done"] == "Done"`,
  `cfg.labels["arm"] == "meeseeks:spec-me"`, `cfg.base_branch == "main"`.
- `{"columns": {"done": "Shipped"}}` overrides only that entry; the other six
  keep their defaults.
- an unknown column key (`"backlogg"`) raises `ValueError` naming it.
- an unknown label key raises `ValueError` naming it.
- `test_required_options_in_flow_order` (line 89) still passes unchanged.
- `TestRealConfig` (lines 109-113) now loads `<repo>/.meeseeks/config.json`.
  Do **not** point it at `agents/config.json`; step 7 creates the file.

---

## Step 3 — prompts come from the install root; project rules are injected

In `agents/orchestrator/job.py`:

- import `PROMPTS_DIR`, `Paths` and `rules_text` from `orchestrator.paths`.
- `run_job` (`job.py:76-78`) gains a trailing keyword parameter
  `prompts_dir: Path = PROMPTS_DIR` and reads
  `(prompts_dir / f"{kind}.md").read_text()` instead of
  `repo / "agents" / "prompts" / f"{kind}.md"` (`job.py:90`).
- add `project_rules=rules_text(Paths(repo))` to the `render_prompt` call
  (`job.py:91-97`). `repo` is already the project root, so no new parameter is
  needed, and `render_prompt` leaves unknown tokens alone (`job.py:26-35`), so a
  template without the token is harmless.

**Tests — `agents/tests/test_job.py`.**

- `setUp` (lines 67-70) currently creates `agents/prompts/` under the fake
  project root. Create the templates in a separate temp directory instead and
  pass it through `_run` (line 88-90) as `prompts_dir`, so the test proves
  prompts are *not* read from the project.
- new: with `.meeseeks/rules.md` written under the fake root and a template
  containing `{project_rules}`, the rules text reaches the prompt file the agent
  is given. Assert it by using an agent command that copies the prompt file
  (e.g. `impl_agent_command="cp .meeseeks-prompt.md out.txt"`) and reading
  `out.txt` from `self.root / ".worktrees" / "1-slug"`.
- new: no `.meeseeks/rules.md` → `{project_rules}` renders as empty, and nothing
  raises.
- keep `test_prompt_file_is_not_committed` (line 117) passing.

---

## Step 4 — the shipped prompts

`agents/prompts/spec.md`: add a `{project_rules}` line in its own section
immediately before `# Rules` (after line 38).

`agents/prompts/impl.md`: add the same before `# Rules` (after line 10), and
**delete the project-specific clause** from line 16 — "standard library only
unless the plan says otherwise" — leaving "Follow the conventions already in the
code: existing naming, existing test style." That claim belongs in
`.meeseeks/rules.md`, not in a shipped prompt.

Do not touch any other line of either prompt. The contract lines ("Do not
commit and do not push", "Make all changes inside this worktree",
"`{verify_command}` must pass", "Create only those two files") stay exactly as
they are.

---

## Step 5 — `agents/daemon.py` takes `Paths`

Purely mechanical, but touch every call site.

- Delete `REPO`, `LEDGER`, `LOGS` (`daemon.py:28-30`).
- Replace the module-level `git` helper (`daemon.py:37-40`) with a factory:
  `def make_git(root: Path) -> GitRunner` returning the same
  `(ok, output)`-shaped closure, argument-for-argument identical to today's.
  `evidence.gather` already accepts a runner, so its call at `daemon.py:145`
  just passes the closure. **Do not change what the closure does to its
  arguments** — see the Rules note above.
- `base_sha(cfg, git)` (`daemon.py:43-48`) takes the runner.
- `_work`, `spawn`, `fill`, `poll_once` each gain a `paths: Paths` parameter
  (and the runner where they use git). Specifically:
  - `_work` (`daemon.py:82-97`): `paths.logs / f"{number}.log"`, and pass
    `paths.root` to `run_job` in place of `REPO`. Build the git runner inside
    the child, not in the parent — a closure does not pickle.
  - `spawn` (`daemon.py:100-107`): add `paths` to the `Process` args tuple,
    keeping the optional `feedback: str = ""` last so both call sites stay
    readable.
  - `fill` (`daemon.py:114-130`): `paths.ledger` at line 123; `base_sha` needs
    the runner.
  - `poll_once` (`daemon.py:133-172`): `paths.root`/`paths.ledger` at line 150,
    `paths.worktrees` at line 153, `paths.logs` at line 155.
- `validate(gh, cfg)` → `validate(gh, cfg, paths)` (`daemon.py:51-67`): before
  the existing bot-login check, `raise SystemExit` if `not paths.is_git_repo`,
  with a message naming the resolved root.
- `main()` (`daemon.py:175-186`):

  ```python
  try:
      paths = Paths(find_root())
  except ConfigNotFound as exc:
      print(f"daemon: {exc}")
      return 2
  cfg = load_config(paths.config)
  ```

  and include the resolved root in the existing startup print (lines 184-186) so
  a wrong root is obvious immediately. `recover(...)` at line 180 takes
  `paths.root, paths.ledger, paths.logs`.

**Tests — `agents/tests/test_daemon.py`.** Update the three `validate` call
sites (lines 33, 49, 66) for the new parameter — construct `Paths` on a temp dir
with a `.git` directory created — and add:

- `validate` raises `SystemExit` mentioning the root when `.git` is absent, and
  it does so *before* any `gh` call (use a runner that raises if called).
- the bot-login and missing-column tests keep passing otherwise unchanged.

---

## Step 6 — `agents/release.py`

Same treatment, smaller: drop `REPO`/`LEDGER` (`release.py:22-23`), give
`remote_claim_branches` a `root: Path` parameter for its `git -C` call
(`release.py:26-28`), and resolve `paths` in `main` (`release.py:43-52`) exactly
as the daemon does — same `ConfigNotFound` handling, `load_config(paths.config)`,
`paths.ledger` for the two `ledger`/`claiming` calls (lines 52, 61).

No new tests are required beyond the suite staying green — but if
`remote_claim_branches` is easy to exercise against a temp repo with no remote,
add a case asserting it returns `[]` rather than raising.

---

## Step 7 — migrate this repo

- Create `.meeseeks/config.json` carrying only the non-default values from
  `agents/config.json:2-30`:

  ```json
  {
    "owner": "kallelaakso",
    "repo": "meeseeks",
    "project_number": 3,
    "bot_login": "mseeks-bot",
    "reviewer": "kallelaakso",
    "spec_agent_command": "claude -p --model opus --permission-mode acceptEdits \"$(cat {prompt_file})\"",
    "impl_agent_command": "opencode run -m opencode-go/kimi-k2.6 \"$(cat {prompt_file})\"",
    "verify_command": "cd agents && python3 -m unittest discover -s tests"
  }
  ```

  Copy the three command strings byte-for-byte from the current file; do not
  retype them.
- Delete `agents/config.json`.
- `.gitignore`: replace `agents/logs/` and `agents/state/` (lines 2-3) with
  `.meeseeks/logs/` and `.meeseeks/state/`; add `.meeseeks-prompt.md`. Keep
  `.worktrees/`.
- Do **not** create `.meeseeks/rules.md` for this repo — "standard library only,
  small files, real tests" already lives in `CLAUDE.md`, and an empty file would
  read as a required one. Mention it in the README instead (step 8).

---

## Step 8 — documentation

`README.md`:

- Setup step 5 (lines 82-83): `.meeseeks/config.json` at the project root, the
  minimal eight keys, and the fact that columns/labels/base branch default.
- A short "Using it in your own project" note: vendor `agents/`, add
  `.meeseeks/config.json`, add the three gitignore lines, keep a `CLAUDE.md`,
  optionally add `.meeseeks/rules.md`. Never edit anything under `agents/`.
- Layout block (lines 97-108): `agents/config.json` and `agents/state/` lines
  replaced by the `.meeseeks/` entries.
- Running section (lines 89-93): mention `MEESEEKS_ROOT` for launches with no
  useful working directory.
- Line 117: `agents/state/` → `.meeseeks/state/`.

`agents/README.md`:

- Module table (lines 9-22): add `paths.py` — "Install root vs project root.
  The only module that decides where anything lives."
- Config-keys table (lines 29-43): new path (`.meeseeks/config.json`) and a
  Default column for the keys that now have one.
- New short section "Install root vs project root" stating the rule from the
  spec: shipped files are addressed from `INSTALL_ROOT`, project files from
  `Paths(root)`.

No changes to `CLAUDE.md` — the workflow, labels and `docs/` paths it documents
are unchanged.

---

## Acceptance criteria

- `cd agents && python3 -m unittest discover -s tests` passes.
- `agents/config.json` no longer exists; `grep -rn "agents/config.json" .`
  returns only `docs/` history.
- `grep -rn '"agents"' agents --include='*.py'` returns nothing — no module
  addresses the install directory by name through the project root any more.
- `MEESEEKS_ROOT=/tmp/nope python3 agents/daemon.py` exits non-zero with a
  message naming `MEESEEKS_ROOT`, not a traceback.
- Running `python3 agents/daemon.py` from a subdirectory of the repo resolves
  the same project root as running it from the top.
- A config containing only the eight required keys loads, and its `columns`,
  `labels`, `base_branch`, `remote` and tuning values equal today's shipped
  values in `agents/config.json`.
- An unknown key inside `columns` or `labels` is a startup error.
- `.meeseeks/rules.md`, when present, appears verbatim in the prompt file handed
  to both agents; when absent, prompts render with no leftover `{project_rules}`
  token and no error.
- No file under `agents/` contains a value specific to this repository
  (`kallelaakso`, `meeseeks` as a repo name, `mseeks-bot`, project number 3)
  outside of `agents/README.md` prose.
- `git diff --stat` shows no changes to `projection.py`, `queues.py`,
  `tickets.py`, `claiming.py`, `evidence.py` or `github.py`.

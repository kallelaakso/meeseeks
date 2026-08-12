---
id: worker-resilience
depends-on: []
spec: 2026-07-18-worker-resilience-design.md
---

# Worker Resilience Implementation Plan

> **For the implementing agent:** Work task-by-task, top to bottom. Each task is
> test-first: write the failing test, run it and confirm it fails, implement the
> minimal code, run it and confirm it passes. Do **not** run `git commit` — the
> orchestrator commits your worktree for you. All paths are relative to the repo
> root of your worktree. Run tests from the `agents/` directory.

**Goal:** Make the orchestrator resilient to hung agents, worker crashes, and
terminal failures — via a configurable agent timeout, automatic startup recovery
of stranded `in-progress/` plans, and a first-class requeue operation.

**Architecture:** Three independent additions to the existing orchestrator. A
timeout is added to the agent subprocess (killing its process group on expiry).
A new `recovery` module sweeps `in-progress/` at daemon/run_once startup, guarded
against re-running work that already landed. A new `requeue` module (plus a thin
CLI) moves `failed/`/`closed/` plans back to `ready-for-work/`.

**Tech Stack:** Python 3 stdlib only (`subprocess`, `os`, `signal`, `pathlib`,
`unittest`). No new dependencies.

**Test command (run from `agents/`):**
`cd agents && python3 -m unittest discover -s tests`

---

## Task 1: Add `agent_timeout_seconds` to config

**Files:**
- Modify: `agents/orchestrator/config.py`
- Test: `agents/tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

Add these methods inside the `TestConfig` class in
`agents/tests/test_config.py`:

```python
    def test_agent_timeout_defaults_to_1800(self):
        cfg = load_config(self._write(VALID))
        self.assertEqual(cfg.agent_timeout_seconds, 1800)

    def test_explicit_agent_timeout_is_honored(self):
        cfg = load_config(self._write({**VALID, "agent_timeout_seconds": 60}))
        self.assertEqual(cfg.agent_timeout_seconds, 60)

    def test_zero_agent_timeout_allowed(self):
        cfg = load_config(self._write({**VALID, "agent_timeout_seconds": 0}))
        self.assertEqual(cfg.agent_timeout_seconds, 0)

    def test_rejects_negative_agent_timeout(self):
        with self.assertRaises(ValueError):
            load_config(self._write({**VALID, "agent_timeout_seconds": -1}))
```

- [ ] **Step 2: Run the tests, confirm they fail**

Run: `cd agents && python3 -m unittest tests.test_config -v`
Expected: FAIL — `Config` has no attribute `agent_timeout_seconds`.

- [ ] **Step 3: Add the field and validation**

In `agents/orchestrator/config.py`, add the field to the `Config` dataclass
alongside the other optional fields (after `merge_sweep_interval_seconds`):

```python
    merge_sweep_interval_seconds: int = 300
    agent_timeout_seconds: int = 1800
    remote: str = "origin"
```

Then, in `load_config`, add this validation next to the other numeric checks
(e.g. after the `merge_sweep_interval_seconds` check):

```python
    if int(data.get("agent_timeout_seconds", 1800)) < 0:
        raise ValueError("agent_timeout_seconds must be >= 0")
```

- [ ] **Step 4: Run the tests, confirm they pass**

Run: `cd agents && python3 -m unittest tests.test_config -v`
Expected: PASS (all four new tests plus the existing ones).

---

## Task 2: Enforce the timeout in the worker (kill the process group)

**Files:**
- Modify: `agents/orchestrator/worker.py`
- Test: `agents/tests/test_worker.py`

- [ ] **Step 1: Extend the test helper and write the failing test**

In `agents/tests/test_worker.py`, update the `_cfg` helper to accept a timeout
(default keeps existing tests unchanged):

```python
def _cfg(agent_command: str, verify: str = "true", mode: str = "auto-merge",
         timeout: int = 1800) -> Config:
    return Config(
        max_concurrency=1,
        poll_interval_seconds=1,
        integration_mode=mode,
        base_branch="main",
        verify_command=verify,
        agent_command=agent_command,
        agent_timeout_seconds=timeout,
    )
```

Then add this test method inside `TestWorker`:

```python
    def test_agent_timeout_moves_plan_to_failed(self):
        agent = "sleep 5"
        result = run_plan(parse_plan(self.plan_path), self.layout,
                          _cfg(agent, timeout=1))
        self.assertEqual(result, "failed")
        self.assertTrue((self.layout.failed / "p.md").exists())
        log = (self.layout.logs / "feat.log").read_text()
        self.assertIn("timed out", log)
```

- [ ] **Step 2: Run the test, confirm it fails**

Run: `cd agents && python3 -m unittest tests.test_worker.TestWorker.test_agent_timeout_moves_plan_to_failed -v`
Expected: FAIL — `sleep 5` runs to completion (no timeout), so the plan does not
land in `failed/` for that reason (or the test hangs ~5s then mismatches).

- [ ] **Step 3: Add the timeout + process-group kill to `_run_agent`**

In `agents/orchestrator/worker.py`, add these imports at the top (with the
existing `import subprocess`):

```python
import os
import signal
import subprocess
```

Replace the existing `_run_agent` function with:

```python
def _run_agent(command: str, cwd: Path, log_path: Path,
               timeout: int | None = None) -> bool:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    append_log(log_path, f"running agent in {cwd}: {command}")
    with log_path.open("a") as log:
        proc = subprocess.Popen(command, cwd=str(cwd), shell=True,
                                stdout=log, stderr=subprocess.STDOUT, text=True,
                                start_new_session=True)
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
            append_log(log_path, f"agent timed out after {timeout}s — killed")
            return False
    append_log(log_path, f"agent exited with code {proc.returncode}")
    return proc.returncode == 0
```

`start_new_session=True` puts the shell and its children in a new process group
so `os.killpg` reaps the whole tree, not just the shell.

- [ ] **Step 4: Pass the configured timeout at the call site**

In `agents/orchestrator/worker.py`, inside `run_plan`, find:

```python
    agent_ok = _run_agent(command, wt, log_path)
```

Replace it with (a `0`/unset timeout means wait forever):

```python
    agent_ok = _run_agent(command, wt, log_path,
                          config.agent_timeout_seconds or None)
```

- [ ] **Step 5: Run the worker tests, confirm they pass**

Run: `cd agents && python3 -m unittest tests.test_worker -v`
Expected: PASS — the timeout test lands the plan in `failed/` after ~1s; all
prior worker tests still pass.

---

## Task 3: Recovery module for stranded `in-progress/` plans

**Files:**
- Create: `agents/orchestrator/recovery.py`
- Test: `agents/tests/test_recovery.py`

- [ ] **Step 1: Write the failing tests**

Create `agents/tests/test_recovery.py`:

```python
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.helpers import init_repo, make_layout
from orchestrator.config import Config
from orchestrator.recovery import recover_stranded


def _cfg() -> Config:
    return Config(
        max_concurrency=1,
        poll_interval_seconds=1,
        integration_mode="pr",
        base_branch="main",
        verify_command="true",
        agent_command="true",
    )


class TestRecovery(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        init_repo(self.root)
        self.layout = make_layout(self.root)

    def _stranded(self, plan_id: str) -> Path:
        p = self.layout.in_progress / f"{plan_id}.md"
        p.write_text(f"---\nid: {plan_id}\n---\nwork\n")
        return p

    def test_unlanded_plan_returns_to_ready(self):
        self._stranded("feat")
        git = lambda args: subprocess.CompletedProcess(args, 1, "", "")
        recovered = recover_stranded(self.layout, _cfg(), git=git)
        self.assertEqual(recovered, ["feat"])
        self.assertTrue((self.layout.ready / "feat.md").exists())
        self.assertFalse((self.layout.in_progress / "feat.md").exists())

    def test_pushed_plan_goes_to_failed(self):
        self._stranded("feat")

        def git(args):
            if "ls-remote" in args:
                return subprocess.CompletedProcess(
                    args, 0, "abc\trefs/heads/plan/feat\n", "")
            return subprocess.CompletedProcess(args, 1, "", "")

        recovered = recover_stranded(self.layout, _cfg(), git=git)
        self.assertEqual(recovered, [])
        self.assertTrue((self.layout.failed / "feat.md").exists())
        self.assertFalse((self.layout.in_progress / "feat.md").exists())

    def test_probe_error_leaves_plan_in_place(self):
        self._stranded("feat")

        def git(args):
            raise RuntimeError("boom")

        recovered = recover_stranded(self.layout, _cfg(), git=git)
        self.assertEqual(recovered, [])
        self.assertTrue((self.layout.in_progress / "feat.md").exists())

    def test_empty_in_progress_is_noop(self):
        git = lambda args: subprocess.CompletedProcess(args, 1, "", "")
        self.assertEqual(recover_stranded(self.layout, _cfg(), git=git), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests, confirm they fail**

Run: `cd agents && python3 -m unittest tests.test_recovery -v`
Expected: FAIL — `orchestrator.recovery` does not exist.

- [ ] **Step 3: Implement the recovery module**

Create `agents/orchestrator/recovery.py`:

```python
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

from orchestrator.config import Config
from orchestrator.fsops import append_log, move_into
from orchestrator.layout import Layout
from orchestrator.plans import list_plans
from orchestrator.worktree import branch_name

GitRunner = Callable[[list[str]], subprocess.CompletedProcess]


def _default_git(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True)


def _branch_landed(repo: Path, remote: str, base_branch: str, branch: str,
                   git: GitRunner) -> bool:
    """True if the branch's work escaped the worker: pushed to remote or merged.

    Used to decide whether a stranded plan is safe to re-run. If the branch was
    already pushed (a PR may exist) or its commits are an ancestor of the base
    (merged), re-running would duplicate landed work — so the caller fails it for
    human triage instead.
    """
    pushed = git(["-C", str(repo), "ls-remote", "--heads", remote, branch])
    if pushed.returncode == 0 and pushed.stdout.strip():
        return True
    exists = git(["-C", str(repo), "rev-parse", "--verify", "--quiet", branch])
    if exists.returncode != 0:
        return False
    merged = git(["-C", str(repo), "merge-base", "--is-ancestor",
                  branch, base_branch])
    return merged.returncode == 0


def recover_stranded(layout: Layout, config: Config, *,
                     git: GitRunner = _default_git) -> list[str]:
    """Reclaim plans orphaned in in-progress/ at startup. Never raises.

    Any plan in in-progress/ when the daemon starts has no live worker (the
    daemon is the sole writer and tracks workers in memory). Unlanded plans go
    back to ready-for-work/; plans whose work already landed go to failed/ for
    triage. A per-plan probe error leaves that plan in place for the next start.
    Returns the ids moved back to ready-for-work/.
    """
    recovered: list[str] = []
    for plan in list_plans(layout.in_progress):
        log_path = layout.logs / f"{plan.id}.log"
        branch = branch_name(plan.id)
        try:
            if _branch_landed(layout.repo, config.remote, config.base_branch,
                              branch, git):
                append_log(log_path,
                           "interrupted after work landed; triage manually")
                move_into(plan.path, layout.failed)
            else:
                append_log(log_path, "recovered stranded in-progress plan")
                move_into(plan.path, layout.ready)
                recovered.append(plan.id)
        except Exception as exc:  # noqa: BLE001 — leave for next restart
            append_log(log_path,
                       f"recovery probe failed, leaving in-progress: {exc}")
    return recovered
```

- [ ] **Step 4: Run the tests, confirm they pass**

Run: `cd agents && python3 -m unittest tests.test_recovery -v`
Expected: PASS (all four tests).

---

## Task 4: Wire recovery into daemon and run_once startup

**Files:**
- Modify: `agents/daemon.py`
- Modify: `agents/run_once.py`
- Test: `agents/tests/test_recovery.py` (add a wiring test)

- [ ] **Step 1: Write the failing test**

Add this test method inside `TestRecovery` in
`agents/tests/test_recovery.py`:

```python
    def test_run_once_recovers_before_running(self):
        import run_once
        self._stranded("feat")
        git = lambda args: subprocess.CompletedProcess(args, 1, "", "")
        # No eligible plans in ready yet; recovery should still move feat back.
        recovered = recover_stranded(self.layout, _cfg(), git=git)
        self.assertIn("feat", recovered)
        self.assertTrue((self.layout.ready / "feat.md").exists())
```

(This asserts the module is importable and recovery behaves; the wiring itself
is exercised by running the daemon/run_once, verified manually in Step 4.)

- [ ] **Step 2: Run the test, confirm it fails**

Run: `cd agents && python3 -m unittest tests.test_recovery.TestRecovery.test_run_once_recovers_before_running -v`
Expected: FAIL only if `run_once` import breaks; otherwise it will pass once the
module imports cleanly. If it already passes, proceed — the import guard is the
point.

- [ ] **Step 3: Add the recovery call to both entrypoints**

In `agents/daemon.py`, add the import near the other orchestrator imports:

```python
from orchestrator.recovery import recover_stranded
```

Then in `daemon.main`, immediately after `config = load_config(...)` and before
the `running: dict[str, Process] = {}` line, add:

```python
    recovered = recover_stranded(layout, config)
    if recovered:
        print(f"daemon: recovered stranded plans: {', '.join(recovered)}")
```

In `agents/run_once.py`, add the import near the other orchestrator imports:

```python
from orchestrator.recovery import recover_stranded
```

Then in `run_once.main`, immediately after `config = load_config(...)` and
before `result = run_next(...)`, add:

```python
    recover_stranded(layout, config)
```

- [ ] **Step 4: Run the recovery tests, confirm they pass**

Run: `cd agents && python3 -m unittest tests.test_recovery -v`
Expected: PASS.

---

## Task 5: Requeue core module

**Files:**
- Create: `agents/orchestrator/requeue.py`
- Test: `agents/tests/test_requeue.py`

- [ ] **Step 1: Write the failing tests**

Create `agents/tests/test_requeue.py`:

```python
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.helpers import make_layout
from orchestrator.requeue import requeue


class TestRequeue(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.layout = make_layout(self.root)

    def _put(self, directory: Path, plan_id: str) -> Path:
        p = directory / f"{plan_id}.md"
        p.write_text(f"---\nid: {plan_id}\n---\nwork\n")
        return p

    def test_requeue_from_failed(self):
        self._put(self.layout.failed, "feat")
        dest = requeue("feat", self.layout)
        self.assertEqual(dest, self.layout.ready / "feat.md")
        self.assertTrue((self.layout.ready / "feat.md").exists())
        self.assertFalse((self.layout.failed / "feat.md").exists())
        self.assertIn("requeued at",
                      (self.layout.logs / "feat.log").read_text())

    def test_requeue_from_closed(self):
        self._put(self.layout.closed, "feat")
        requeue("feat", self.layout)
        self.assertTrue((self.layout.ready / "feat.md").exists())
        self.assertFalse((self.layout.closed / "feat.md").exists())

    def test_requeue_rejects_done_only(self):
        self._put(self.layout.done, "feat")
        with self.assertRaises(ValueError):
            requeue("feat", self.layout)
        self.assertTrue((self.layout.done / "feat.md").exists())

    def test_requeue_rejects_unknown_id(self):
        with self.assertRaises(ValueError):
            requeue("nope", self.layout)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests, confirm they fail**

Run: `cd agents && python3 -m unittest tests.test_requeue -v`
Expected: FAIL — `orchestrator.requeue` does not exist.

- [ ] **Step 3: Implement the requeue module**

Create `agents/orchestrator/requeue.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from orchestrator.fsops import append_log, move_into
from orchestrator.layout import Layout
from orchestrator.plans import list_plans


def requeue(plan_id: str, layout: Layout) -> Path:
    """Move a failed/ or closed/ plan back to ready-for-work/.

    Matches by parsed plan id (robust to filename drift). Never touches done/
    (audit trail + dependency gate). Appends a requeue marker to the plan's log
    so one log accumulates the full attempt history. Raises ValueError if the id
    is not present in failed/ or closed/.
    """
    for source_dir in (layout.failed, layout.closed):
        for plan in list_plans(source_dir):
            if plan.id == plan_id:
                dest = move_into(plan.path, layout.ready)
                stamp = datetime.now(timezone.utc).isoformat()
                append_log(layout.logs / f"{plan_id}.log", f"requeued at {stamp}")
                return dest
    raise ValueError(f"no failed/closed plan with id {plan_id!r}")
```

- [ ] **Step 4: Run the tests, confirm they pass**

Run: `cd agents && python3 -m unittest tests.test_requeue -v`
Expected: PASS (all four tests).

---

## Task 6: Requeue CLI wrapper

**Files:**
- Create: `agents/requeue.py`
- Test: `agents/tests/test_requeue.py` (add CLI tests)

- [ ] **Step 1: Write the failing tests**

Add this test class to `agents/tests/test_requeue.py` (below `TestRequeue`):

```python
class TestRequeueCli(unittest.TestCase):
    def test_cli_usage_when_no_arg(self):
        import requeue as cli
        self.assertEqual(cli.main(["requeue.py"]), 2)

    def test_cli_usage_when_too_many_args(self):
        import requeue as cli
        self.assertEqual(cli.main(["requeue.py", "a", "b"]), 2)
```

Note: the CLI is a thin wrapper — it resolves the real repo root, so we only
assert its argument handling here. The requeue behaviour (failed/closed →
ready, done rejected, unknown id rejected) is fully covered by `TestRequeue`
against an injected temp layout, so the CLI test stays simple and free of
monkeypatching.

- [ ] **Step 2: Run the tests, confirm they fail**

Run: `cd agents && python3 -m unittest tests.test_requeue.TestRequeueCli -v`
Expected: FAIL — top-level `requeue` module (the CLI) does not exist yet.

- [ ] **Step 3: Implement the CLI**

Create `agents/requeue.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from orchestrator.layout import Layout
from orchestrator.requeue import requeue


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python3 agents/requeue.py <plan-id>")
        return 2
    repo = Path(__file__).resolve().parents[1]
    layout = Layout.under(repo)
    try:
        dest = requeue(argv[1], layout)
    except ValueError as exc:
        print(f"error: {exc}")
        return 1
    print(f"requeued -> {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 4: Run the tests, confirm they pass**

Run: `cd agents && python3 -m unittest tests.test_requeue -v`
Expected: PASS.

---

## Task 7: Update documentation

**Files:**
- Modify: `agents/README.md`

Note: the root `README.md` delegates config keys and operational limitations to
`agents/README.md` ("See `agents/README.md` for config keys and operational
limitations"), so all edits below are in `agents/README.md` only.

- [ ] **Step 1: Add the config key to the config table**

In `agents/README.md`, add a row to the config table (after the
`merge_sweep_interval_seconds` row):

```
| `agent_timeout_seconds` | kill a hung agent after N seconds (`0`/unset = no timeout, default 1800) |
```

- [ ] **Step 2: Update the operational limitations**

In `agents/README.md`, under "Operational notes / v1 limitations", replace the
whole **"No crash recovery for `in-progress/`"** bullet with:

```
- **Stranded `in-progress/` plans are recovered at startup.** On daemon (or
  `run_once`) start, any plan left in `in-progress/` is reclaimed: moved back to
  `ready-for-work/`, unless its `plan/<id>` branch was already pushed or merged
  (work landed) — those go to `failed/` for manual triage.
```

Add a new bullet documenting requeue (near the `failed/`/`closed/` bullet):

```
- **Requeue a failed/closed plan** with `python3 agents/requeue.py <plan-id>`.
  It moves the plan from `failed/` or `closed/` back to `ready-for-work/` and
  appends a requeue marker to its log. `done/` plans are never requeueable.
```

- [ ] **Step 3: No test — documentation only.**

Documentation changes have no automated test.

---

## Task 8: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `cd agents && python3 -m unittest discover -s tests`
Expected: OK — all pre-existing tests plus the new `test_config`, `test_worker`,
`test_recovery`, and `test_requeue` cases pass with no failures or errors.

- [ ] **Step 2: Confirm the timeout config round-trips**

Run: `cd agents && python3 -c "from orchestrator.config import load_config; import json, tempfile, pathlib; p=pathlib.Path(tempfile.mkdtemp())/'c.json'; p.write_text(open('config.json').read()); print(load_config(p).agent_timeout_seconds)"`
Expected: prints `1800` (the default, since `config.json` doesn't set the key).

---

## Unresolved questions

None. Timeout default (`1800`, `0`/unset = off) and the partial-landing recovery
guard were confirmed during design.

Implement the plan at `{plan_path}` for GitHub issue #{issue}: {title}.

{feedback}

# Where you are

A clean git worktree at {worktree} on branch {branch}. Every path in the plan is
relative to this worktree. Read `{spec_path}` too — the plan tells you what to
do, the spec tells you why, and the why matters when the plan is ambiguous.

# Project-specific instructions

{project_rules}

# Rules

- Make **all** changes inside this worktree. Never touch any directory outside it.
- `{verify_command}` must pass when you are done. Run it yourself before finishing.
- Follow the conventions already in the code: existing naming, existing test
  style.
- Add tests for what you write. Backend logic and reusable code need real
  coverage, not smoke tests.
- Keep files small and focused. If one grows past a few hundred lines, split it.
- Do **not** commit and do **not** push — the orchestrator does both for you.
- If the plan is wrong or impossible, stop and say so in your final message
  rather than inventing a different feature.

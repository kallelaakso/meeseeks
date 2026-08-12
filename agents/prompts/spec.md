You are writing the design spec and implementation plan for GitHub issue #{issue}.

# The ticket

**Title:** {title}

{body}

{feedback}

# Your task

You are in a clean git worktree at {worktree} on branch {branch}. Explore the
codebase first — read the code you would be changing, and cite real file paths
and line numbers. A spec that describes code that does not exist is worse than
no spec.

Write exactly two files, and nothing else:

## 1. `{spec_path}` — the design

- **Problem** — what is actually wrong today, in terms of this codebase.
- **Goals / Non-goals** — non-goals matter as much as goals.
- **Design** — the approach, with the reasoning that makes it the right one.
  Name the alternatives you rejected and why.
- **Affected components** — real paths, with line references where useful.
- **Unresolved questions** — anything you had to guess at.

Never invent an answer to a question the ticket leaves open. Put it under
Unresolved questions instead. A human reviews this before any code is written,
and a flagged question costs one comment while a wrong guess costs a rewrite.

## 2. `{plan_path}` — the implementation plan

Step-by-step instructions for a cheaper coding agent that will not have your
context. Each step names the files it touches and the tests it adds. Include
the acceptance criteria and the verify command: `{verify_command}`.

# Project-specific instructions

{project_rules}

# Rules

- Modify nothing outside this worktree.
- Create only those two files. Do not implement the feature.
- Do not commit and do not push — the orchestrator does both.
- Match the existing documents in `docs/spec/` in tone and structure.

# Project instructions

## The workflow — ALWAYS follow this

Work is driven by **GitHub issues and the project board**, not by files. You
(Claude) do NOT write specs, plans, or implementation code. Agents do.

Your job is: brainstorm with me, then write the ticket.

Whenever I ask for anything that changes behavior — even phrased as
"let's implement X", "add X", "fix X", "build X" — interpret it as a request to
start this workflow, NOT to write code:

1. **Brainstorm** — grill me until the shape of the work is clear. Unresolved
   questions are the point; surface them now, not after code exists.
2. **Ticket** — write the issue body (format below), show it to me, and on
   approval create it with `gh issue create`.
3. **Arm** — add the `meeseeks:spec-me` label ONLY when I explicitly say go.
   The label is what starts the machine.
4. **Stop.** The spec daemon writes the spec and plan and opens a `[spec]` PR.
   I review it. Merging it arms implementation. The impl daemon opens the
   implementation PR. I merge that too.

## Hard rules

- NEVER write implementation code, specs, or plans. If you catch yourself about
  to edit a source file to build a feature, STOP — you've skipped the workflow.
- NEVER add the arm label without my explicit go.
- The board is a **projection**, not a control surface. Dragging a card does
  nothing; the daemon overwrites it on the next poll. Control is via labels, PR
  reviews, and merges.
- If a request is ambiguous about which step we're on, ask me — don't assume.

## Ticket format

The ticket body is the only input to an autonomous spec run. Nothing downstream
rescues a vague ticket, so this is where the care goes.

```markdown
## Problem
What is wrong today, concretely.

## Goals
## Non-goals
## Constraints
## Acceptance criteria
How we know it worked.

Depends on: #41
```

`Depends on: #N` gates implementation until that issue's PR has **merged**.
Omit the line when there are no dependencies.

## Labels

| Label | Meaning |
|---|---|
| `meeseeks:spec-me` | Write a spec for this. Removed once the spec PR opens. |
| `meeseeks:failed` | A run failed; see the comment. Remove it to retry from scratch. |
| `meeseeks:blocked` | Gave up (revision cap or dependency cycle). Needs a human. |

## Paths

Agents write `docs/spec/<issue>-<slug>.md` and `docs/plan/<issue>-<slug>.md`.
The issue number is the key for everything: branches, worktrees, logs, files.
Older date-prefixed specs and the retired file-based plans live in
`docs/plan/archive/`.

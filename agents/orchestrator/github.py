from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Callable, Optional

Runner = Callable[[list[str], Optional[str]], tuple[bool, str]]


def default_runner(args: list[str], input: Optional[str] = None) -> tuple[bool, str]:
    """Run a command, folding stderr into stdout.

    `capture_output` cannot be combined with an explicit `stderr`, so the pipes
    are wired by hand. Error text must reach the caller: `create_ref` decides a
    lost race from GitHub's "already exists" message, which arrives on stderr.
    """
    proc = subprocess.run(
        args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, input=input,
    )
    return proc.returncode == 0, proc.stdout


class GitHubError(RuntimeError):
    pass


@dataclass(frozen=True)
class GitHub:
    owner: str
    repo: str
    run: Runner = default_runner

    def _run(self, args: list[str], err: str,
             input: Optional[str] = None) -> str:
        ok, out = self.run(args, input)
        if not ok:
            raise GitHubError(err + out)
        return out

    def _json(self, args: list[str], err: str) -> dict:
        return json.loads(self._run(args, err))

    def viewer_login(self) -> str:
        return self._run(
            ["gh", "api", "user", "-q", ".login"],
            "viewer_login failed: ",
        ).strip()

    def issues_with_label(self, label: str) -> list[dict]:
        return self._json([
            "gh", "issue", "list",
            "--label", label,
            "--state", "open",
            "--json", "number,title,body,labels,state",
        ], "issues_with_label failed: ")

    def all_issues(self, limit: int = 200) -> list[dict]:
        """Every issue, open and closed.

        The projection needs closed issues too (a closed ticket renders Done),
        so label-scoped listing is not enough. One call covers the whole board.
        """
        return self._json([
            "gh", "issue", "list",
            "--state", "all",
            "--limit", str(limit),
            "--json", "number,title,body,labels,state",
        ], "all_issues failed: ")

    def issue(self, number: int) -> dict:
        return self._json([
            "gh", "issue", "view", str(number),
            "--json", "number,title,body,labels,state,stateReason",
        ], f"issue {number} failed: ")

    def open_prs(self) -> list[dict]:
        return self._json([
            "gh", "pr", "list",
            "--state", "open",
            "--json", "number,headRefName,headRefOid,title,mergeable,url",
        ], "open_prs failed: ")

    def open_pr_for(self, branch: str) -> dict | None:
        """The open PR for a branch, if any. Used to stay idempotent when a
        crash lands between pushing and opening the PR."""
        prs = self._json([
            "gh", "pr", "list",
            "--head", branch,
            "--state", "open",
            "--json", "number,url",
        ], f"open_pr_for {branch} failed: ")
        return prs[0] if prs else None

    def merged_pr_branches(self) -> list[dict]:
        return self._json([
            "gh", "pr", "list",
            "--state", "merged",
            "--limit", "100",
            "--json", "number,headRefName",
        ], "merged_pr_branches failed: ")

    def pr_reviews(self, number: int) -> list[dict]:
        data = self._json([
            "gh", "pr", "view", str(number),
            "--json", "reviews",
        ], f"pr_reviews {number} failed: ")
        return data.get("reviews", [])

    def pr_head_committed_at(self, number: int) -> str | None:
        ok, out = self.run([
            "gh", "pr", "view", str(number),
            "--json", "commits",
            "-q", ".commits[-1].committedDate",
        ])
        if not ok:
            return None
        return out.strip() or None

    def create_ref(self, ref: str, sha: str) -> bool:
        ok, out = self.run([
            "gh", "api",
            f"repos/{self.owner}/{self.repo}/git/refs",
            "-f", f"ref={ref}",
            "-f", f"sha={sha}",
        ])
        if ok:
            return True
        if "already exists" in out:
            return False
        raise GitHubError(f"create_ref {ref} failed: {out}")

    def delete_ref(self, ref: str) -> None:
        name = ref.removeprefix("refs/heads/")
        self._run([
            "gh", "api", "-X", "DELETE",
            f"repos/{self.owner}/{self.repo}/git/refs/heads/{name}",
        ], f"delete_ref {ref} failed: ")

    def add_label(self, number: int, label: str) -> None:
        self._run([
            "gh", "issue", "edit", str(number),
            "--add-label", label,
        ], f"add_label {number} failed: ")

    def remove_label(self, number: int, label: str) -> None:
        self._run([
            "gh", "issue", "edit", str(number),
            "--remove-label", label,
        ], f"remove_label {number} failed: ")

    def comment(self, number: int, body: str) -> None:
        self._run([
            "gh", "issue", "comment", str(number),
            "--body-file", "-",
        ], f"comment {number} failed: ", body)

    def set_issue_body(self, number: int, body: str) -> None:
        self._run([
            "gh", "issue", "edit", str(number),
            "--body-file", "-",
        ], f"set_issue_body {number} failed: ", body)

    def create_pr(self, head: str, title: str, body: str,
                  reviewer: str) -> dict:
        out = self._run([
            "gh", "pr", "create",
            "--head", head,
            "--title", title,
            "--body-file", "-",
            "--reviewer", reviewer,
        ], f"create_pr {head} failed: ", body)
        return {"url": out.strip()}

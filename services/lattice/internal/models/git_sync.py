from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

LOG = logging.getLogger(__name__)


class GitSyncError(RuntimeError):
    """Raised when a git operation fails."""


@dataclass(frozen=True)
class GitRepoSpec:
    name: str
    url: str
    branch: str | None = None


class GitSync:
    """
    Syncs git repositories into a local workspace.

    Behavior:
    - clones repo if target path does not exist
    - fetches and resets if repo already exists
    - supports optional branch checkout
    """

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.workspace.mkdir(parents=True, exist_ok=True)

    def repo_path(self, spec: GitRepoSpec) -> Path:
        return self.workspace / spec.name

    def sync_repo(self, spec: GitRepoSpec) -> Path:
        target = self.repo_path(spec)

        if not target.exists():
            self._clone_repo(spec, target)
        else:
            self._update_repo(spec, target)

        return target

    def _clone_repo(self, spec: GitRepoSpec, target: Path) -> None:
        cmd = ["git", "clone", spec.url, str(target)]
        if spec.branch:
            cmd = ["git", "clone", "--branch", spec.branch, spec.url, str(target)]

        LOG.info("Cloning repo %s from %s", spec.name, spec.url)
        self._run(cmd, cwd=self.workspace)

    def _update_repo(self, spec: GitRepoSpec, target: Path) -> None:
        if not (target / ".git").exists():
            raise GitSyncError(f"Target exists but is not a git repo: {target}")

        LOG.info("Updating repo %s in %s", spec.name, target)

        self._run(["git", "fetch", "--all", "--tags", "--prune"], cwd=target)

        branch = spec.branch or self._detect_current_branch(target)
        if branch:
            self._run(["git", "checkout", branch], cwd=target)
            self._run(["git", "reset", "--hard", f"origin/{branch}"], cwd=target)

        self._run(["git", "clean", "-fd"], cwd=target)

    def remove_repo(self, spec: GitRepoSpec) -> None:
        target = self.repo_path(spec)
        if target.exists():
            LOG.info("Removing repo %s from %s", spec.name, target)
            shutil.rmtree(target)

    def _detect_current_branch(self, repo_dir: Path) -> str | None:
        result = self._run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_dir,
            capture_output=True,
        )
        branch = result.stdout.strip()
        if branch == "HEAD":
            return None
        return branch

    def _run(
        self,
        cmd: list[str],
        cwd: Path,
        capture_output: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        LOG.debug("Running command: %s", " ".join(cmd))
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            text=True,
            capture_output=capture_output,
            check=False,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip() if result.stderr else ""
            stdout = result.stdout.strip() if result.stdout else ""
            raise GitSyncError(
                f"Command failed: {' '.join(cmd)}\n"
                f"cwd={cwd}\n"
                f"stdout={stdout}\n"
                f"stderr={stderr}"
            )
        return result

"""
Git tools — run git operations on local repositories.
Supports: status, log, diff, commit, push, pull, clone, checkout, branch.
"""
import subprocess
import os
import platform

from friday.safety.tool_guard import audit_allowed_tool, guard_tool_call

OS = platform.system()


def _run_git(args: list, cwd: str = None, timeout: int = 30) -> tuple[int, str, str]:
    """Run a git command and return (returncode, stdout, stderr)."""
    cmd = ["git"] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd or os.getcwd(),
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", f"Git command timed out after {timeout}s"
    except FileNotFoundError:
        return -1, "", "Git is not installed or not in PATH."
    except Exception as e:
        return -1, "", str(e)


def _resolve_repo(repo_path: str) -> str:
    """Resolve and validate a repository path."""
    if not repo_path:
        return os.getcwd()
    expanded = os.path.expandvars(os.path.expanduser(repo_path))
    return os.path.abspath(expanded)


def register(mcp):

    @mcp.tool()
    def git_status(repo_path: str = "") -> str:
        """
        Show the working tree status of a git repository.
        repo_path: Optional path to the repo. Defaults to current working directory.
        Use this when the user asks 'what changed?', 'git status', 'any uncommitted changes?'.
        """
        cwd = _resolve_repo(repo_path)
        code, out, err = _run_git(["status", "--short", "--branch"], cwd=cwd)
        if code != 0:
            return f"Git status failed: {err}"
        return f"Git Status ({cwd}):\n{out}" if out else f"Working tree clean. ({cwd})"

    @mcp.tool()
    def git_log(repo_path: str = "", limit: int = 10) -> str:
        """
        Show the recent commit history of a git repository.
        limit: Number of commits to show (default 10).
        Use this when the user asks 'show commit history', 'recent changes', 'who committed what'.
        """
        cwd = _resolve_repo(repo_path)
        limit = min(max(1, limit), 50)
        fmt = "%C(auto)%h %C(bold blue)%an%C(reset) %C(green)%ar%C(reset) - %s"
        code, out, err = _run_git(
            ["log", f"--max-count={limit}", f"--pretty=format:{fmt}", "--no-color"],
            cwd=cwd
        )
        if code != 0:
            return f"Git log failed: {err}"
        return f"Commit History ({cwd}) — Last {limit}:\n{out}" if out else "No commits found."

    @mcp.tool()
    def git_diff(repo_path: str = "", file_path: str = "") -> str:
        """
        Show uncommitted changes (diff) in the repository or a specific file.
        Use this when the user asks 'what did I change?', 'show diff', 'what's modified?'.
        """
        cwd = _resolve_repo(repo_path)
        args = ["diff"]
        if file_path:
            args.append(file_path)
        code, out, err = _run_git(args, cwd=cwd)
        if code != 0:
            return f"Git diff failed: {err}"
        if not out:
            return "No unstaged changes found."
        # Truncate if very large
        if len(out) > 5000:
            out = out[:5000] + "\n\n... [diff truncated] ..."
        return f"Git Diff:\n{out}"

    @mcp.tool()
    def git_commit(message: str, repo_path: str = "", add_all: bool = True) -> str:
        """
        Stage and commit changes to the git repository.
        message: The commit message.
        add_all: If True (default), stages all changes before committing (git add -A).
        Use this when the user says 'commit my changes', 'save my changes', 'git commit'.
        """
        cwd = _resolve_repo(repo_path)
        if not message.strip():
            return "Commit message cannot be empty."
        decision, safety_message = guard_tool_call(
            "git_commit",
            {"message": message, "repo_path": cwd, "add_all": add_all},
            subject=cwd,
        )
        if safety_message:
            return safety_message
        if add_all:
            code, _, err = _run_git(["add", "-A"], cwd=cwd)
            if code != 0:
                return f"Failed to stage changes: {err}"
        code, out, err = _run_git(["commit", "-m", message], cwd=cwd)
        if code != 0:
            return f"Commit failed: {err}"
        output = f"Committed: {out}"
        audit_allowed_tool("git_commit", command=f"git commit -m {message}", risk_level=int(decision.risk_level), decision=decision.decision, result=output)
        return output

    @mcp.tool()
    def git_push(repo_path: str = "", remote: str = "origin", branch: str = "") -> str:
        """
        Push committed changes to the remote repository.
        remote: Remote name (default 'origin').
        branch: Branch name. If empty, pushes the current branch.
        Use this when the user says 'push my changes', 'upload to GitHub'.
        """
        cwd = _resolve_repo(repo_path)
        args = ["push", remote]
        if branch:
            args.append(branch)
        decision, safety_message = guard_tool_call(
            "git_push",
            {"repo_path": cwd, "remote": remote, "branch": branch},
            subject=cwd,
        )
        if safety_message:
            return safety_message
        code, out, err = _run_git(args, cwd=cwd, timeout=60)
        if code != 0:
            return f"Push failed: {err}"
        output = f"Pushed successfully: {out or err}"
        audit_allowed_tool("git_push", command="git " + " ".join(args), risk_level=int(decision.risk_level), decision=decision.decision, result=output)
        return output

    @mcp.tool()
    def git_pull(repo_path: str = "", remote: str = "origin", branch: str = "") -> str:
        """
        Pull latest changes from the remote repository.
        Use this when the user says 'pull latest', 'update from remote', 'git pull'.
        """
        cwd = _resolve_repo(repo_path)
        args = ["pull", remote]
        if branch:
            args.append(branch)
        code, out, err = _run_git(args, cwd=cwd, timeout=60)
        if code != 0:
            return f"Pull failed: {err}"
        return f"Pull result: {out or 'Already up to date.'}"

    @mcp.tool()
    def git_clone(url: str, destination: str = "") -> str:
        """
        Clone a remote git repository to the local machine.
        url: The HTTPS or SSH URL of the repository.
        destination: Optional local folder name. Defaults to the repo name.
        Use this when the user says 'clone this repo', 'download this project from GitHub'.
        """
        if not destination:
            # Extract repo name from URL
            destination = url.rstrip("/").split("/")[-1].replace(".git", "")
        from friday.path_utils import workspace_dir
        dest_path = str(workspace_dir() / destination)
        args = ["clone", url, dest_path]
        code, out, err = _run_git(args, timeout=120)
        if code != 0:
            return f"Clone failed: {err}"
        return f"Repository cloned to: {dest_path}"

    @mcp.tool()
    def git_checkout(branch: str, repo_path: str = "", create: bool = False) -> str:
        """
        Switch to a different git branch or create a new one.
        branch: Branch name to checkout.
        create: If True, create the branch if it doesn't exist (-b flag).
        Use this when the user says 'switch to branch X', 'create branch X', 'checkout X'.
        """
        cwd = _resolve_repo(repo_path)
        args = ["checkout"]
        if create:
            args.append("-b")
        args.append(branch)
        code, out, err = _run_git(args, cwd=cwd)
        if code != 0:
            return f"Checkout failed: {err}"
        return f"Switched to branch '{branch}'."

    @mcp.tool()
    def git_branch(repo_path: str = "") -> str:
        """
        List all local and remote branches in the repository.
        Use this when the user asks 'what branches exist?', 'list branches', 'show all branches'.
        """
        cwd = _resolve_repo(repo_path)
        code, out, err = _run_git(["branch", "-a"], cwd=cwd)
        if code != 0:
            return f"Failed to list branches: {err}"
        return f"Branches:\n{out}" if out else "No branches found."

#!/usr/bin/env python3
"""Create a reviewable downstream branch from the official Hermes upstream.

This command deliberately does not edit Hermes profiles, secrets, services, or
deployment files. It only fetches Git refs and creates a merge branch.
Conflicts are left visible for manual resolution; no side is selected
automatically.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys


UPSTREAM_REMOTE = "upstream"
UPSTREAM_REPOSITORY = "NousResearch/hermes-agent"
DEFAULT_REF = "upstream/main"
DEFAULT_BRANCH_PREFIX = "update/upstream-"


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        check=check,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )


def _git_text(*args: str) -> str:
    return _git(*args).stdout.strip()


def _remote_is_expected() -> bool:
    try:
        remote = _git_text("remote", "get-url", UPSTREAM_REMOTE)
    except subprocess.CalledProcessError:
        return False
    normalized = remote.removesuffix("/").removesuffix(".git").lower()
    return normalized.endswith("/" + UPSTREAM_REPOSITORY.lower())


def _clean_worktree() -> bool:
    return not bool(_git_text("status", "--porcelain"))


def _current_branch() -> str:
    return _git_text("branch", "--show-current")


def _target_ref(ref: str) -> str:
    """Resolve a user ref to an immutable commit after fetch."""
    candidates = [ref]
    if not ref.startswith(("refs/", "upstream/", "origin/")):
        candidates.extend((f"refs/tags/{ref}", f"upstream/{ref}"))
    for candidate in candidates:
        result = _git("rev-parse", "--verify", f"{candidate}^{{commit}}", check=False)
        if result.returncode == 0:
            return result.stdout.strip()
    raise RuntimeError(f"Cannot resolve upstream ref: {ref}")


def _safe_branch_fragment(ref: str) -> str:
    fragment = ref.rsplit("/", 1)[-1]
    fragment = re.sub(r"[^A-Za-z0-9._-]+", "-", fragment).strip(".-")
    return fragment or "head"


def default_branch(ref: str) -> str:
    return DEFAULT_BRANCH_PREFIX + _safe_branch_fragment(ref)


def _conflict_paths() -> list[str]:
    output = _git_text("diff", "--name-only", "--diff-filter=U")
    return [line for line in output.splitlines() if line]


def _dry_run_conflict_paths(target: str) -> tuple[bool, list[str], str]:
    """Return merge status and conflict paths without touching the index."""
    result = _git(
        "merge-tree",
        "--write-tree",
        "--name-only",
        "--no-messages",
        "main",
        target,
        check=False,
    )
    lines = [line for line in result.stdout.splitlines() if line]
    if lines and re.fullmatch(r"[0-9a-f]{40,64}", lines[0]):
        lines = lines[1:]
    return result.returncode == 0, lines, result.stderr.strip()


def _print_result(message: str) -> None:
    print(message)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ref",
        default=DEFAULT_REF,
        help="upstream branch or tag (default: upstream/main)",
    )
    parser.add_argument(
        "--branch",
        help="new review branch (default: update/upstream-<ref>)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="fetch and report merge conflicts without changing branches",
    )
    args = parser.parse_args(argv)

    if not _remote_is_expected():
        print(
            "Refusing to continue: remote 'upstream' must point to "
            f"https://github.com/{UPSTREAM_REPOSITORY}.git",
            file=sys.stderr,
        )
        return 2
    if not _clean_worktree():
        print(
            "Refusing to continue: worktree is dirty. Commit or stash local "
            "changes first; profiles and secrets are intentionally outside Git.",
            file=sys.stderr,
        )
        return 2
    if _current_branch() != "main":
        print("Refusing to continue: run this command from the main branch.", file=sys.stderr)
        return 2

    try:
        _git("fetch", UPSTREAM_REMOTE, "--tags", "--prune")
        target = _target_ref(args.ref)
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Unable to fetch/resolve upstream: {exc}", file=sys.stderr)
        return 2

    branch = args.branch or default_branch(args.ref)
    if _git("show-ref", "--verify", "--quiet", f"refs/heads/{branch}", check=False).returncode == 0:
        print(f"Refusing to overwrite existing branch: {branch}", file=sys.stderr)
        return 2

    _print_result(f"upstream ref: {args.ref} -> {target}")
    _print_result(f"review branch: {branch}")

    if args.dry_run:
        clean, paths, error = _dry_run_conflict_paths(target)
        if clean:
            _print_result("dry-run: merge is clean")
            return 0
        _print_result("dry-run: conflicts require manual review")
        if paths:
            _print_result("conflicted files:")
            _print_result("\n".join(f"  {path}" for path in paths))
        if error:
            print(error, file=sys.stderr)
        return 1

    try:
        _git("switch", "--create", branch, "main")
        merge = _git("merge", "--no-edit", "--no-ff", target, check=False)
    except subprocess.CalledProcessError as exc:
        print(f"Unable to create review branch: {exc}", file=sys.stderr)
        return 2

    if merge.returncode == 0:
        _print_result("merge completed; run the repository test suite before pushing")
        return 0

    paths = _conflict_paths()
    print(
        "merge stopped with conflicts; nothing was auto-resolved. "
        "Resolve, test, then commit, or abort with `git merge --abort`.",
        file=sys.stderr,
    )
    if paths:
        print("conflicted files:", file=sys.stderr)
        print("\n".join(f"  {path}" for path in paths), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

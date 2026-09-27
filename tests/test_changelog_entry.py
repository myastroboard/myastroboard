"""CHANGELOG.md requirement check for feature/fix pull requests.

Only enforced in CI on a pull_request event, where GITHUB_HEAD_REF and
GITHUB_BASE_REF are available to identify the branch and diff against its
base. Running locally (no such context) always skips.
"""

import os
import subprocess

import pytest

_REQUIRED_BRANCH_PREFIXES = ("feature/", "fix/")


@pytest.mark.unit
def test_feature_or_fix_pr_updates_changelog():
    """A feature/* or fix/* branch's PR must touch CHANGELOG.md.

    Other branches (chore/, docs/, refactor/, test/, ...) are not required to,
    though they're welcome to add an entry too.
    """
    if os.environ.get("GITHUB_EVENT_NAME") != "pull_request":
        pytest.skip("Only enforced in CI on pull_request events")

    head_ref = os.environ.get("GITHUB_HEAD_REF", "")
    if not head_ref.startswith(_REQUIRED_BRANCH_PREFIXES):
        pytest.skip(f"Branch '{head_ref}' is not a feature/ or fix/ branch")

    base_ref = os.environ.get("GITHUB_BASE_REF")
    if not base_ref:
        pytest.skip("No GITHUB_BASE_REF available to diff against")

    result = subprocess.run(
        ["git", "merge-base", f"origin/{base_ref}", "HEAD"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # Shallow clones may not share a common ancestor; fall back to the
        # fetched tip of the base branch (FETCH_HEAD) so the diff still works.
        fetch = subprocess.run(
            ["git", "fetch", "--depth=1", "origin", base_ref],
            capture_output=True,
            text=True,
        )
        if fetch.returncode != 0:
            pytest.skip(f"Cannot determine merge-base for '{base_ref}': {result.stderr.strip()}")
        base_sha = "FETCH_HEAD"
    else:
        base_sha = result.stdout.strip()

    changed = subprocess.run(
        ["git", "diff", "--name-only", base_sha, "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()

    assert "CHANGELOG.md" in changed, (
        f"Branch '{head_ref}' does not update CHANGELOG.md. Add a short bullet "
        "under '## [Unreleased]' (Features / Fixes / Breaking changes) describing "
        "this change - see CONTRIBUTING.md#changelog."
    )

"""CHANGELOG.md requirement check for feature/fix pull requests.

Only enforced in CI on a pull_request event, where GITHUB_HEAD_REF identifies
the branch and HEAD is the PR merge commit to diff against its first parent.
Running locally (no such context) always skips.
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

    # On pull_request events actions/checkout checks out refs/pull/N/merge: a
    # merge commit whose first parent is the base branch the PR was merged
    # onto. Diffing against HEAD^1 gives exactly the PR's changes, without
    # depending on origin/<base> (which may have moved since the event).
    parents = subprocess.run(
        ["git", "rev-list", "--parents", "-n", "1", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert len(parents) == 3, (
        "Expected HEAD to be the pull request merge commit (refs/pull/N/merge); "
        "check the actions/checkout step of the workflow."
    )

    changed = subprocess.run(
        ["git", "diff", "--name-only", "HEAD^1", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()

    assert "CHANGELOG.md" in changed, (
        f"Branch '{head_ref}' does not update CHANGELOG.md. Add a short bullet "
        "under '## [Unreleased]' (Features / Fixes / Breaking changes) describing "
        "this change - see CONTRIBUTING.md#changelog."
    )

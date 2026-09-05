# Local agent delivery workflow

## Branch model

All Git operations remain local. No role fetches, pulls, pushes, or opens a pull request.

`main` is the human-approved stable line. Each release cycle has one local integration branch such as `rc/0.5.0`, with a dedicated worktree such as `.worktrees/rc-0.5.0`. A human selects the RC's starting commit and creates the branch from an accepted, committed baseline.

Each Jira issue gets exactly one isolated worktree and local ticket branch:

- Worktree: `.worktrees/AF-123`
- Branch: `codex/AF-123-short-description`
- Base: the active local `rc/<version>` branch
- Integration target: the same local RC branch

Ticket branches start from the active RC rather than `main`, so every ticket is developed and tested with changes already accepted into that release candidate. Never create a ticket branch from uncommitted local work.

## Promotion pipeline

| Stage | Owner | Required artifact | Exit gate |
| --- | --- | --- | --- |
| Design / INVESTIGATE | Investigator/Designer | Acceptance criteria and test plan | `READY_FOR_DEVELOPMENT` |
| In Progress | Developer | Clean, committed local ticket branch | `READY_FOR_REVIEW` plus `HEAD_SHA` |
| Ready to Review | Reviewer | Findings against the active local RC | `APPROVE` plus `REVIEWED_SHA` |
| Ready for QA | QA | Acceptance and regression evidence | `PASS` plus `TESTED_SHA` |
| Ready for RC | Coordinator | Valid local branch and immutable SHA evidence | All three SHAs match |
| Human Verification | Human | Test notes from the integrated local RC | Human pass or rejection |
| Done | Human | Accepted behavior | No further agent work |

Developer, Reviewer, and QA use the same ticket worktree sequentially. They do not work in parallel. Review and QA apply only to an immutable commit: `HEAD_SHA == REVIEWED_SHA == TESTED_SHA`. Any new commit invalidates both approvals.

## Local Git operations

The coordinator validates every branch and commit before mutation. The normal sequence is:

```text
create rc/<version> and its dedicated worktree from a human-selected commit
create codex/AF-123-slug and .worktrees/AF-123 from rc/<version>
developer commits locally on codex/AF-123-slug
reviewer approves HEAD_SHA
QA passes the same HEAD_SHA
coordinator performs a regular --no-ff merge into rc/<version>
human tests the RC worktree or a package built from it
```

Use a regular merge commit rather than a squash merge. The ticket branch is reused when Review, QA, or human verification finds a problem; preserving merge ancestry avoids repeatedly reconsidering old changes and conflicts. The RC merge commit message must contain the Jira key, and its SHA must be recorded on the issue.

No agent switches or cleans the user's original worktree. All ticket development and RC integration happen in linked worktrees under `.worktrees/`.

## Jira workflow

Add `Ready for RC` and `Human Verification` to the existing workflow. Configure these forward transitions:

```text
To Do -> INVESTIGATE / Design / In Progress / Blocked
INVESTIGATE -> Design / In Progress / Blocked
Design -> INVESTIGATE / In Progress / Blocked
In Progress -> Ready to Review / Blocked
Ready to Review -> Ready for QA / In Progress / Blocked
Ready for QA -> Ready for RC / In Progress / INVESTIGATE / Blocked
Ready for RC -> Human Verification / In Progress / Blocked
Human Verification -> Done / In Progress / Blocked
```

Record the active RC, branch name, base SHA, head SHA, reviewed SHA, tested SHA, and RC merge SHA on the issue. Custom fields are ideal; a single structured coordinator comment is an acceptable first version. Use Jira Fix Version to group every ticket in the release cycle.

A human rejection returns the issue to `In Progress`. If the failed change must be removed from the candidate, revert its merge commit in the RC worktree. The developer fixes the same ticket branch, and the full Review and QA sequence repeats before another regular merge.

## Local checks

Install the locked test dependencies from `requirements-test.txt`. The fast gate is:

```powershell
python -m pip install -r requirements-test.txt
python tests\run_unit.py
```

The unit and architecture command passed all 381 tests in the current project runtime, with one declared expected failure. Before human verification, QA should also run the relevant native and Blender tests. A full RC build should be made from the RC worktree, not from a ticket branch or the user's original dirty worktree.

## Human release

Humans test from the local RC worktree or a reproducible package built from its exact commit. A pass moves the issue to `Done`. A rejection records evidence and returns the issue to development.

When the complete candidate is accepted, a human locally merges `rc/<version>` into `main` and creates the release tag. Publishing that branch or tag to a remote is intentionally outside this workflow for now.

## Coordinator state machine

For each run, the coordinator:

1. Reads one Jira issue and the active local RC configuration.
2. Confirms the recorded branch, worktree, and SHA state instead of recreating them.
3. Invokes only the role for the current Jira status.
4. Stores the verdict and SHA evidence on Jira.
5. Advances at most one status.
6. Stops on conflicts, ambiguous state, missing approvals, or a human-only status.

The first setup must not choose an RC baseline automatically. This repository currently has a local `perf` branch far ahead of `main` plus uncommitted changes, so a human must decide which committed point begins the first release candidate.

# AnthroForge agent rules

- Search the web first for existing APIs, approaches, algorithms, packages, or tools. Prefer primary and official sources.
- Keep every function at 15 lines of code or fewer.
- Preserve unrelated local changes. Do not push, fetch, pull, open a pull request, or otherwise contact a Git remote. Local ticket branches, worktrees, commits, and RC merges are allowed only as part of this workflow.

## Jira workflow coordination

The primary Codex agent is the coordinator. It owns the Jira and local Git control planes: issue mutations, ticket worktree initialization, recorded SHAs, and merges into the local release candidate. Subagents receive the issue context, active release-candidate branch, ticket branch, worktree path, and expected commit SHA. They must not mutate Jira or contact a Git remote.

Every release cycle has one human-selected local integration branch named `rc/<version>` and a dedicated worktree at `.worktrees/rc-<version>`. Never infer or create an RC from an uncommitted or ambiguous local branch. Every ticket uses an isolated worktree at `.worktrees/<ISSUE-KEY>` and a branch named `codex/<ISSUE-KEY>-<short-slug>`, based on the active local RC branch. Never switch or clean the user's existing worktree to start a ticket.

The role pipeline is sequential:

1. At the start of development, initialize or resume the ticket worktree and branch.
2. The developer is the only role that edits source code and commits ticket changes.
3. The reviewer inspects the committed ticket branch against the active RC branch.
4. QA tests the exact commit approved by the reviewer.
5. The coordinator may merge the ticket branch into the local RC with a regular `--no-ff` merge only when `HEAD_SHA`, `REVIEWED_SHA`, and `TESTED_SHA` are identical.
6. Any new commit invalidates both review and QA and restarts the pipeline at review.
7. Humans alone accept or reject behavior after the ticket is present in the RC.

Route work by the issue's current Jira status:

- `Design` or `INVESTIGATE` -> `investigator_designer`
- `In Progress` -> `developer`
- `Ready to Review` -> `reviewer`
- `Ready for QA` -> `qa`
- `Ready for RC` -> coordinator verifies the SHA gate and merges the ticket branch into the active local RC
- `Human Verification` -> no agent changes; wait for a human pass or rejection
- `Blocked` -> stop and request the missing decision or dependency
- `Done` -> perform no further work
- `To Do` -> coordinator decides whether the issue needs investigation/design or is ready for development

Run the roles sequentially and keep their contexts separate. The developer must never review or QA its own implementation. The coordinator advances an issue only after receiving the expected verdict, and normally advances at most one workflow stage in a single scheduled run. A reviewer rejection or QA failure returns to development on the same ticket branch; all fixes must be reviewed and tested again.

Verdict mapping:

- `investigator_designer`: `READY_FOR_DEVELOPMENT`, `NEEDS_HUMAN`, or `BLOCKED`
- `developer`: `READY_FOR_REVIEW`, `NEEDS_HUMAN`, or `BLOCKED`
- `reviewer`: `APPROVE`, `CHANGES_REQUIRED`, or `BLOCKED`
- `qa`: `PASS`, `FAIL`, or `BLOCKED`

Every developer verdict must report `BASE_BRANCH`, `BASE_SHA`, `BRANCH`, and `HEAD_SHA`. Reviewer verdicts must report `REVIEWED_SHA`; QA verdicts must report `TESTED_SHA`. On `CHANGES_REQUIRED` or an implementation-related `FAIL`, return the issue to development with the complete handoff. On an unclear requirement, route it to investigation/design. Never transition or merge based on an ambiguous result.

After agent QA passes, the coordinator promotes the exact approved commit to `Ready for RC`, merges it into the active local RC with a merge commit, records the merge SHA, and moves the issue to `Human Verification`. A human pass moves it to `Done`; a human rejection returns it to `In Progress`, reverts the RC merge when necessary, and repeats development, review, and QA.

See `docs/agent_delivery_workflow.md` for local branch handling, Jira transitions, release handling, and failure recovery.

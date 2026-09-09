# AnthroForge agent rules

- Search the web first for existing APIs, approaches, algorithms, packages, or tools. Prefer primary and official sources.
- Keep every function at 15 lines of code or fewer.
- Preserve unrelated local changes.
- Do not push, fetch, pull, open a pull request, or otherwise contact a Git remote unless the user explicitly requests that action.

## Default: direct work

Handle implementation, debugging, refactoring, tests, and code review directly in the current task and workspace. A normal coding request does not require a Jira ticket, coordinator, ticket branch, ticket worktree, or staged delivery process.

Do not search for, create, infer, or require a Jira ticket to start ordinary work. Do not spawn subagents unless the user explicitly asks for delegation or the named-ticket skill below is active. Generic delegation requested by the user does not activate the Jira workflow.

A Jira key in a branch name, file, commit message, quoted example, or completed conversation is not an instruction to start ticket delivery. A new request without a ticket uses direct work even if earlier work in the same conversation involved Jira.

## Anatomical region discovery and maintained knowledge

For SCP shape analysis, anatomical region discovery, reference-to-SCP correspondence, or corrections to region placement/connectivity, use [anthroforge-anatomical-region-discovery](C:/Users/alexe/.codex/skills/anthroforge-anatomical-region-discovery/SKILL.md). This does not activate Jira delivery or delegation.

The user requests ongoing skill maintenance: during relevant work, incorporate new user corrections, findings, implementation changes, and validation results into that skill or its existing case reference before the final response. Distinguish verified evidence, inferred anatomy, rejected approaches, and unvalidated proposals; update superseded claims rather than accumulating reports. Keep fixture-specific measurements scoped to their source and revision. Report results inline by default instead of generating Markdown report collections.

## Opt-in Jira delivery

Use $anthroforge-jira-delivery only when the user requests implementation, investigation, review, QA, or continuation of a specific Jira issue that they identify by key or issue URL. An unambiguous continuation of an unfinished, user-identified ticket may retain that ticket; do not revive completed ticket work for an unrelated request.

The personal skill entrypoint is C:/Users/alexe/.codex/skills/anthroforge-jira-delivery/SKILL.md. Read it only when this activation condition is met or the user explicitly invokes the skill. If the user explicitly requests Jira delivery but supplies no issue key, obtain the key before starting that workflow; do not select a backlog ticket automatically.

Ticket status questions, explanations, and read-only Jira searches do not start implementation, delegation, Git changes, or Jira transitions. A request to edit these workflow instructions is ordinary direct work.

The skill owns the role pipeline and RC promotion rules. They do not apply to default direct work.

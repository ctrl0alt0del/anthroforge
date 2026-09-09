# Optional Jira delivery workflow

The Jira coordinator, role handoffs, isolated ticket worktrees, and RC promotion rules have moved to the personal skill $anthroforge-jira-delivery:

C:/Users/alexe/.codex/skills/anthroforge-jira-delivery/SKILL.md

This document is a location pointer, not an instruction to activate that workflow. The default in AGENTS.md is direct, single-agent work with no ticket lookup or staged delivery.

Request a specific ticket, for example "Implement AF-12", to use the skill. Ordinary requests such as "Fix the reload bug" remain direct work. "What is the status of AF-12?" is read-only and does not start delivery. An explicit skill invocation without a ticket requires the issue key before any workflow action.

Detailed workflow and role prompts are maintained only in the skill's references directory, not registered globally in .codex/agents.

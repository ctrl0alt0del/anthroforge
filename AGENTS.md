# AnthroForge agent rules

For Codex Cloud or a Linux checkout, first read `docs/codex_cloud.md` for the
setup command, portable test scope, production architecture, and local-only
Blender/native validation requirements. Cloud checks do not establish geometry acceptance.

- Search the web first for existing APIs, approaches, algorithms, packages, or tools. Prefer primary and official sources.
- Keep every function at 15 lines of code or fewer.
- Preserve unrelated local changes.
- Do not push, fetch, pull, open a pull request, or otherwise contact a Git remote unless the user explicitly requests that action.
- Deliver result `.blend` files with all current source and mirrored fibers visible in their normal curve display, and with native SCP colors shown in Solid/Object color mode. Preserve the manual debug presentation demonstrated by `E:/development/WIP_models/skull_muscles.blend`. Do not save render-only hiding, wire display, or uniform SCP recoloring into deliverables. Use `StaticScene.save_debug_copy` for authoring exports and verify visibility after reopening the saved file.

## Native optimization calculations

Implement all future optimization calculations in C++, using the existing native libraries and their build/load infrastructure. This includes iterative fitting, objective and Jacobian evaluation, constraint solving, line searches, and repeated numerical geometry queries within optimization. Calling native array operations from a Python optimization loop does not satisfy this rule.

Keep Python responsible for Blender access, authoring/UI orchestration, input validation, serialization, and publication. Batch inputs and results across the native boundary; do not introduce per-sample or per-iteration Python callbacks or a silent production Python optimizer fallback. Preserve numerical safeguards and verify correctness and performance against representative fixtures when migrating existing calculations.

## Ownership, completion, and changing approach

AnthroForge is a practical tool for building avatars for the user's game. Take initiative as a trusted collaborator and own the usable result. Keep implementation and research directed toward completing that result.

1. **Finish the authorized work end to end.** The completion standard is 100% of the requested outcome, including ordinary expected cases, integration, relevant validation, and delivery. Fix failures encountered within that scope; do not stop at an intermediate success or relabel required unfinished work as a future improvement. For geometry work, inspect the actual resulting shapes and saved artifacts: successful API calls or numerical checks alone do not establish success. Only genuinely extreme edge cases that require joint design discussion may remain unresolved; investigate them, explain the concrete blocker and tradeoff, and complete all independent work before raising the focused question. Report completion honestly against observed evidence; never hide a failure behind a claim of success.

2. **Replace approaches that keep needing repairs.** After 3–4 refinements without an acceptable result, treat the current approach as failing and actively find and implement a better alternative. Switch, combine, or redesign approaches autonomously within the authorized task; do not wait for the user to instruct each change. Compare alternatives against the actual required result, including visual quality where applicable. Keep track of failed attempts and their causes so that renaming a tweak does not restart the same cycle. Continue until the result works or the extreme-edge-case exception above genuinely applies.

3. **Use and extend the tools needed to solve the problem.** Research existing APIs, examples, papers, algorithms, packages, and tools whenever useful, especially when stuck; research is not limited to the beginning of a task. Use available inspection, execution, visualization, and validation capabilities actively. The authoring layer is an authorized development playground: build the geometry queries, diagnostics, calibrated views, Blender interaction, automation, and reproducible experiments needed to understand and complete the task. Missing authoring capabilities are problems to solve. Integrate useful reusable capabilities into maintained authoring and keep disposable experiments separate from production. Exercise this autonomy while preserving the user's explicit scope, data, Git, and workflow constraints.

## Evidence before recommendations

Before recommending a change or replacement approach, establish the observed failure, inspect the existing implementation and available capabilities, identify the specific difference being proposed, and explain what evidence would show that difference addresses the failure. Apply this rule to advice and plans as well as implementation.

- Separate observed defects from suspected causes. If the cause is unknown, propose a diagnostic experiment with a discriminating result, not a claimed solution.
- Check whether the proposed capability already exists or has already been tried. Do not repackage existing tools as a new solution. If different orchestration or presentation is the proposed change, state that explicitly and test whether it improves the actual failed task.
- Research relevance and success on another benchmark do not establish effectiveness here. Label untested ideas as hypotheses; distinguish a justified experiment from a demonstrated fix.
- Test against representative project failures and the user's actual outcome. Passing easier proxy tasks, successful API calls, or unrelated numerical checks is insufficient evidence that the original problem is solved.
- If inspection undermines a recommendation, withdraw or revise it before presenting it. Do not preserve the recommendation by renaming it or offering unsupported explanations. The user must not have to discover missing examination through repeated objections.

This is a requirement for evidence and honest claims, not a new approval gate. Investigate and run bounded experiments autonomously within the authorized scope. The rule to change approaches after repeated failures still applies; replacement approaches must meet this standard too.

## Default: direct work

Handle implementation, debugging, refactoring, tests, and code review directly in the current task and workspace. A normal coding request does not require a Jira ticket, coordinator, ticket branch, ticket worktree, or staged delivery process.

Do not search for, create, infer, or require a Jira ticket to start ordinary work. Do not spawn subagents unless the user explicitly asks for delegation, the muscle reconstruction workflow below applies, or the named-ticket skill below is active. Generic delegation requested by the user does not activate the Jira workflow.

A Jira key in a branch name, file, commit message, quoted example, or completed conversation is not an instruction to start ticket delivery. A new request without a ticket uses direct work even if earlier work in the same conversation involved Jira.

## Anatomical region discovery and maintained knowledge

For SCP shape analysis, anatomical region discovery, reference-to-SCP correspondence, or corrections to region placement/connectivity, use [anthroforge-anatomical-region-discovery](C:/Users/alexe/.codex/skills/anthroforge-anatomical-region-discovery/SKILL.md). This does not activate Jira delivery or delegation.

The user requests ongoing skill maintenance: during relevant work, incorporate new user corrections, findings, implementation changes, and validation results into that skill or its existing case reference before the final response. Distinguish verified evidence, inferred anatomy, rejected approaches, and unvalidated proposals; update superseded claims rather than accumulating reports. Keep fixture-specific measurements scoped to their source and revision. Report results inline by default instead of generating Markdown report collections.

## Muscle reconstruction agents and practical knowledge

For the transfer, whole-underside, native-fiber and inflation workflow, use [anthroforge-muscle-reconstruction](C:/Users/alexe/.codex/skills/anthroforge-muscle-reconstruction/SKILL.md). The September 21 user decision is direct coordinator work for all stages and practical-knowledge retrieval, with no stage agents or librarian agent. This supersedes earlier optional/mandatory delegation authorization. Retain the role procedures as reference; spawn agents only if the user later explicitly requests them. Inspect original geometry and bone context proactively, and identify coordinator-authored reviews honestly rather than claiming independent agent review.

Keep all new muscle-workflow byproducts under `E:/development/WIP_models/muscle_reconstruction_workflow`, with separate versioned candidates/journals per writer. Use `tools/muscle_workflow/workflow.py` with the external runtime Python for run manifests, stage context receipts, versioned lessons, and handoff/feedback validation. A ready handoff needs a matching context receipt and librarian brief for the actual inputs. Chroma is a rebuildable local search index; immutable evidence-backed JSON lessons are authoritative. Record a suspected cause separately from an observed defect. After repairing an upstream stage, invalidate and rerun affected downstream work. Record final anatomical, route/collision, persistence, and debug-visibility acceptance separately.

## Opt-in Jira delivery

Use $anthroforge-jira-delivery only when the user requests implementation, investigation, review, QA, or continuation of a specific Jira issue that they identify by key or issue URL. An unambiguous continuation of an unfinished, user-identified ticket may retain that ticket; do not revive completed ticket work for an unrelated request.

The personal skill entrypoint is C:/Users/alexe/.codex/skills/anthroforge-jira-delivery/SKILL.md. Read it only when this activation condition is met or the user explicitly invokes the skill. If the user explicitly requests Jira delivery but supplies no issue key, obtain the key before starting that workflow; do not select a backlog ticket automatically.

Ticket status questions, explanations, and read-only Jira searches do not start implementation, delegation, Git changes, or Jira transitions. A request to edit these workflow instructions is ordinary direct work.

The skill owns the role pipeline and RC promotion rules. They do not apply to default direct work.

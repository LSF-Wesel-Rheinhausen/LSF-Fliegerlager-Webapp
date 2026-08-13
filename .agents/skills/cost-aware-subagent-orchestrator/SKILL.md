---
name: cost-aware-subagent-orchestrator
description: Cost-aware decomposition and delegation of software-engineering work to Codex subagents. Use when the user requests subagents, parallel agents, cheaper agents, token-efficient execution, task delegation, CI or PR monitoring by an agent, or senior-PM-style coordination of multiple implementation and review tasks.
---

# Cost-aware Subagent Orchestrator

Coordinate authorized subagent work with the least expensive model that can reliably complete each bounded task. Optimize total cost without duplicating work, delaying the critical path, or weakening verification.

## Establish the execution graph

1. Confirm that the user or applicable repository instruction authorizes subagents. Do not treat this skill alone as permission for unrelated external actions.
2. Split the requested outcome into concrete tasks with dependencies, write scopes, validation, and completion criteria.
3. Identify the immediate blocking task. Keep it local only when delegation would leave the parent idle; otherwise delegate it too.
4. Run independent tasks in parallel with disjoint write scopes. Never assign the same unresolved task twice.
5. Keep irreversible, production, security-sensitive, or externally visible actions within the user's explicit authorization regardless of model choice.

## Select the cheapest capable model

Start at the lowest suitable tier. Increase model capability only when task evidence requires it.

| Tier | Assign when | Typical work |
| --- | --- | --- |
| Luna, low reasoning | The procedure is deterministic, read-only, mechanical, or mostly waiting | CI monitoring, PR status and comment checks, log collection, metadata fixes, formatting, inventory, exact command execution |
| Luna, medium reasoning | The change is bounded, follows an existing pattern, and has clear tests | Small bug fixes, focused tests, isolated templates or styles, straightforward review findings |
| Terra, medium reasoning | Several files or contracts interact, diagnosis is moderately ambiguous, or integration judgment is required | Cross-layer changes, merge-conflict resolution after a prepared analysis, non-trivial debugging, integration review |
| Frontier model | Failure has high security or data risk, architecture is genuinely ambiguous, or lower tiers produced evidence that deeper reasoning is necessary | Security architecture, destructive migrations, novel concurrency failures, broad semantic conflicts |

Do not select an expensive model merely because a task is important. Reduce uncertainty first: inspect locally, narrow the task, define invariants and tests, then delegate the bounded implementation to a cheaper tier where possible.

Escalate by one tier only when the current agent reports concrete missing capability, contradictory evidence, or repeated inability to satisfy the acceptance criteria. Missing context requires a better handoff, not automatically a stronger model.

## Write a complete handoff

Give every subagent:

- one measurable outcome;
- the minimum relevant repository, issue, PR, branch, and file context;
- explicit allowed write paths, or state that the task is read-only;
- forbidden actions such as committing, pushing, resolving threads, or changing production;
- exact checks to run and edge cases to cover;
- a stop condition for ambiguity, scope expansion, or unsafe state;
- a compact return contract: result, evidence, changed files, checks, and blockers only.

Prefer a fresh, context-light agent for independent work. Reuse an existing agent when its prior task provides material context. Fork the full conversation only when reconstructing the required context would be less efficient and would not leak an intended validation answer.

## Coordinate without wasting tokens

- Continue non-overlapping parent work immediately after delegation.
- Do not poll agents repeatedly. Wait only when their result blocks the next action; otherwise rely on completion notifications.
- Assign CI waiting, repeated status checks, and GitHub comment inventory to Luna with low reasoning.
- Ask for deltas rather than repeated full summaries.
- Close completed agents after consuming their results so concurrency slots remain available.
- Review returned patches and evidence; do not redo delegated work from scratch.
- If an agent is blocked by permissions or missing user authority, preserve its evidence and escalate to the user instead of spawning replacements.

## Integrate and verify

1. Check that each result stayed within its write and authority scope.
2. Review diffs before integration and preserve unrelated working-tree changes.
3. Run focused checks, then repository-required verification.
4. Delegate passive remote monitoring back to Luna Low after a push.
5. Report the achieved outcome, remaining blockers, and any justified model escalation. Do not claim completion without verification.

## Examples

- “Watch both PRs and tell me when CI and comments are clean.” Use separate or shared Luna-Low monitoring work, depending on whether the checks can be batched.
- “Fix these three independent P2 findings.” Assign each bounded finding to Luna Medium with disjoint files; keep integration local.
- “Resolve this conflict.” First identify the competing contracts. Give a prepared, bounded conflict to Terra Medium; retain it locally only when it blocks the immediate next step and no parallel work remains.
- “Audit authentication and implement the remediation.” Use a frontier model for threat and architecture decisions, then hand mechanical, well-specified fixes and tests to Luna Medium.

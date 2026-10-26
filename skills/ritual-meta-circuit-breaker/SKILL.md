---
name: ritual-meta-circuit-breaker
description: Detects when the agent's trajectory has diverged from the user's goal. Uses weighted progress markers, stall detection, and divergence heuristics. Stops before wasting budget.
---

# Circuit Breaker — Trajectory Divergence Detection (v2)

## Purpose

Detect when the agent is not converging toward the user's goal and terminate the failing approach before exhausting budget. This is the self-awareness mechanism: knowing when to stop.

## Progress Tracking

### Weighted Progress Markers

Each marker has a weight proportional to its difficulty and dependency depth. Later markers (which depend on earlier ones) count more. The agent maintains this table and updates it after every verification.

| Marker | Weight | Verified By | Depends On |
|--------|--------|------------|------------|
| Chain connection | 1 | `getBlockNumber()` succeeds | — |
| RitualWallet funded | 1 | `availableBalance(sponsor) > 0` | Chain connection |
| Contract compiled | 2 | Build succeeds | — |
| Contract deployed | 3 | `cast code <address>` returns bytecode | Compiled |
| Precompile simulates | 3 | `eth_call` returns non-empty | Deployed, funded |
| Precompile settles | 5 | Receipt has `spcCalls` or callback fires | Simulates |
| Frontend renders | 2 | Browser shows expected elements | — |
| Frontend connects | 3 | `usePublicClient()` returns state | Renders, chain connection |
| E2E flow completes | 8 | User action → result displayed | All above |

**Progress score:** `P(t) = sum(achieved marker weights) / sum(all marker weights)`

**Directional progress within a marker:** If a marker is not yet achieved but the agent is closer (e.g., the error message changed from "precompile call failed" to "insufficient deposit"), record a sub-state. Sub-states don't increment P(t) but they do reset the stall counter — the agent is making directional progress even if the marker isn't flipped.

### Stall Detection

**Stall condition:** P(t) has not increased AND no sub-state progress for N consecutive turns.

| Build Phase | Stall Threshold (N) | Budget-Adjusted |
|-------------|---------------------|-----------------|
| Scaffolding | 3 turns | min(3, remaining_budget / cost_per_turn) |
| Contracts | 5 turns | min(5, remaining_budget / cost_per_turn) |
| Frontend | 4 turns | min(4, remaining_budget / cost_per_turn) |
| Integration | 6 turns | min(6, remaining_budget / cost_per_turn) |

**Budget integration:** If the user specified a token/dollar budget (see `skills/ritual-meta-non-interactive-bias/SKILL.md`), the stall threshold is the minimum of the phase default and the budget-derived limit. An agent with $0.50 remaining should not spend 6 turns on a stall — it should fire the circuit breaker at 2.

### Divergence Heuristics

These trigger an immediate circuit breaker regardless of stall count:

1. **Error oscillation:** Fix A introduces error B. Fix B reintroduces A. The two errors share a root cause neither fix addresses. **Trigger: same error seen 2+ times after distinct fixes.**

2. **Scope creep during debug:** The agent starts modifying previously verified files. **Trigger: diff touches a file that was last modified more than 5 steps ago and was verified at that time.**

3. **Increasing action complexity:** Each fix is larger than the last (more lines changed, more files touched). **Trigger: the last 3 diffs are monotonically increasing in size.**

4. **User frustration signals:** Messages shorter than 20 characters for 3+ consecutive turns, explicit phrases ("this isn't working", "try something else", "never mind", "forget it"), or repeated questions (same question asked twice within 5 turns). **Trigger: any of these patterns detected.**

## Activation Protocol

### Step 1: Stop

Halt code generation. Do not attempt another fix.

### Step 2: Emit Diagnostic

```
CIRCUIT BREAKER ACTIVATED

Goal: [user's stated goal]
Progress: [X% — list achieved markers]
Stalled for: [N turns]
Budget consumed: [estimated $ or tokens used]

Last 3 actions:
  [action] → [outcome]
  [action] → [outcome]
  [action] → [outcome]

Recurring pattern (if any): [description]
```

### Step 3: Propose Options

Select the most appropriate default based on the stall type:

| Stall Type | Best Default | Rationale |
|------------|-------------|-----------|
| Architectural impossibility (e.g., 2 short-running async calls per tx) | Change approach | Simplifying doesn't fix the constraint |
| Integration bug (callback not firing) | Simplify scope | Remove the failing integration |
| Unknown / novel | Pause and regroup | Let the user decide with full context |

Present three options:
1. **Simplify** — Drop the stalled feature, build what works
2. **Pivot** — Same goal, fundamentally different architecture
3. **Pause** — Save state, hand back to user

Default to the best option for the stall type if the user doesn't respond within 2 turns.

### Step 4: Re-Entry Protocol

After the user selects an option:

1. **Preserve** all previously achieved and verified markers — do not restart from zero.
2. **Update** the build plan to reflect the chosen option.
3. **Reset** the stall counter and tried-list for the affected step only.
4. **Log** the circuit breaker event: what stalled, which option was chosen, what was preserved.
5. **Re-enter** the orchestrator interleave loop at the appropriate step.

If the circuit breaker fires a SECOND time on the same goal, escalate: present only option 3 (pause) and explicitly state that the current approach appears to require capabilities or knowledge the agent doesn't have.

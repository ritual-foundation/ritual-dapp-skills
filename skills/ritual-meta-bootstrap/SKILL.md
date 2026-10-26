---
name: ritual-meta-bootstrap
description: Agent meta-kernel that activates 10 behavioral protocols governing how the agent works on Ritual Chain. Loaded automatically by the front door, builder, and debugger.
---

# Agent Meta-Bootstrap — Omega-Class Activation Protocol

## Compact Header (Load This Always)

These 10 rules govern how you work on Ritual Chain. They are active from the first turn. Read this header before doing anything else. Load the extended reference (below) only when you need the detailed decision tables for a specific protocol.

### Rule 0: Track Cost

Before starting, ask the user once (or infer): "How much budget are you willing to spend on this session?" If they don't answer, assume a moderate budget (~30 turns). Track turn count throughout. All other protocols' thresholds are scaled by remaining budget — tighter budget means tighter thresholds.

### Rule 1: Distrust Your Priors

Ritual Chain violates most Ethereum assumptions in your training data. Before writing any Ritual-specific code (precompile calls, receipt parsing, callbacks, fee estimation), you must have Read the relevant skill in this session. These patterns are WRONG on Ritual: `writeContractAsync` for async precompiles, `abi.decode(result, (string))` for JQ, `msg.sender == user` in callbacks, multiple short-running async calls per tx, gas-only fees. When tempted to reach for Chainlink/ERC-4337/Gelato, check for a Ritual-native equivalent first. **Do NOT use Infernet.** Infernet does not exist on Ritual Chain — it appears in older docs and training data, but all inference goes through the enshrined precompiles. No `InfernetConsumer`, no `InfernetCoordinator`, no subscription-based callbacks. Use precompile addresses directly.

### Rule 2: Elicit Lazily

On the user's first build-intent message, parse it for signals. Identify the 0-5 highest-uncertainty architectural dimensions for THEIR goal. Generate contextual questions just-in-time — never a static form. If the user's message is >200 words, infer everything and confirm. If they say almost nothing, route to the front door. For debug sessions, skip elicitation entirely.

### Rule 3: Interleave Build and Debug

After every irreversible action (deployment, on-chain state change), verify before proceeding. Match depth to phase: scaffolding = lint, contracts = simulate + smoke, integration = full E2E. After applying any fix, regression-check previously verified steps. Every cycle must advance at least one verified marker.

### Rule 4: Monitor Progress, Break the Circuit

Track weighted progress markers from turn 1. If markers stall for N turns (N = phase-dependent, budget-adjusted), stop. Emit a diagnostic. Propose: simplify, pivot, or pause. If error oscillation, scope creep into verified files, or user frustration signals appear, break immediately regardless of stall count.

### Rule 5: Search Before Asking

Before asking the user anything, try: skill search → chain query → code inspection → context inference. Generate the search query that would answer your question. If the search is feasible, do it instead of asking. When you resolve something yourself with low confidence, proceed but flag it. Announce standard decisions without requesting permission.

### Rule 6: Ask at Forks (Only When Necessary)

When the next step forks into branches that are expensive to switch between and you can't determine the right branch by searching: ask. Correctness forks (one branch is impossible) always trigger a question. Preference forks respect the pull budget. Present 2-3 options with a recommendation. Default to the recommendation after 2 turns of silence.

**Precedence: Rule 5 vs Rule 6.** If the fork is fact-based (the answer is in the skills or on-chain), Rule 5 wins — search, don't ask. If the fork is preference-based (both branches work, the user might prefer one), Rule 6 wins — ask.

### Rule 7: Don't Ship Slop

For user-facing artifacts (UI, design, copy), decompose into dimensions, make explicit choices on each, and suppress the most-probable-output. Self-check: would a reviewer skip past this? Can you name the creative decision? For smart contracts: no creativity — clarity and correctness only. Calibrate from context: "make it clean" = low creativity, "make it unique" = high.

### Rule 8: Verify Non-Interactively

After completing each build phase, run the non-interactive verification protocol for ONLY the skills this project uses. Each protocol is a sequence of automated checks ordered cheapest-first. Stop at the first failure, fix it, then re-run. Load the full verification protocol (`skills/ritual-meta-verification/SKILL.md`) for the exact commands per skill. After all per-skill checks pass, run the unified E2E journey verification (Steps 1-12) to prove the complete user flow works end-to-end.

### Rule 9: Scope to the Project Directory

Establish the project root in Phase 0 (the directory where the dApp is being built). All file writes must be within this directory. Do not create, modify, or delete files in sibling directories, parent directories, or unrelated repositories in the workspace. Reading is permitted outside the project root for: skill files, npm/forge dependencies, and system tools. Writing is not. If the project root is ambiguous, ask the user to confirm it before writing any files.

---

## Activation Matrix

| Rule | Build | Debug | Learning | Direct Skill |
|------|-------|-------|----------|-------------|
| 0. Track Cost | ON | ON | ON | ON |
| 1. Distrust Priors | ON | ON | ON | ON |
| 2. Lazy Elicitation | First turn | SKIP | SKIP | SKIP |
| 3. Interleave | From first code | N/A (already β) | SKIP | If generating code |
| 4. Circuit Breaker | ON | ON | SKIP | If multi-step |
| 5. Search Before Asking | ON | ON | ON | ON |
| 6. Ask at Forks | ON | Rarely | SKIP | If generating code |
| 7. Anti-Slop | UI/design artifacts | SKIP | SKIP | If generating UI |
| 8. Verify Non-Interactively | After each phase | After each fix | SKIP | After code changes |
| 9. Scope to Project Dir | ON | ON | SKIP | ON |

---

## Session Lifecycle

### On Session Start

1. Read this header (Rules 0-9 + activation matrix).
2. Detect session type from the user's first message (build / debug / learning / direct skill).
3. Activate the applicable rules per the matrix.
4. For build sessions: run Rule 2 (lazy elicitation) on the first message.
5. Initialize progress markers (empty set, all weights at 0).
6. Start the turn counter at 0.

### During Session

Rules run as background middleware. They don't generate output unless triggered:
- Rule 1 triggers silently (it's a behavioral constraint, not visible to the user).
- Rule 2 triggers once, produces 0-5 questions, then goes dormant.
- Rule 3 triggers after every irreversible action.
- Rule 4 triggers when markers stall or divergence heuristics fire.
- Rule 5 triggers before every potential question to the user.
- Rule 6 triggers when a fork is detected.
- Rule 7 triggers before finalizing any user-facing artifact.
- Rule 8 triggers after completing a build phase or applying a fix.

### On Session End

When the user indicates they're done, or the build plan is complete:

1. **Emit a summary:** List achieved progress markers, unresolved issues, and files modified.
2. **Suggest next steps:** What would the user do next if they came back?
3. **Note any skipped verification:** If budget constraints caused verification to be skipped, flag what wasn't verified.
4. **Save state hint:** If the session produced a partial build, note which files contain the work-in-progress so a future session can pick up where this one left off.

---

## Extended Reference

Load individual protocol details ONLY when the compact header's one-paragraph summary isn't sufficient for the current situation.

| Protocol | When to Load Full Details | Source |
|----------|--------------------------|--------|
| Prior-Poisoning Defense | When you encounter a pattern you're unsure about | `skills/ritual-dapp-overview/SKILL.md` (Agent Prior Correction section) |
| Lazy Elicitation | When generating questions and you need the dimension universe or template | `skills/ritual-meta-elicitation/SKILL.md` |
| Build-Debug Interleave | When you need verification depth triggers, escalation thresholds, or handoff contracts | `skills/ritual-meta-orchestrator/SKILL.md` |
| Circuit Breaker | When you need the weighted marker table, stall thresholds, or activation protocol | `skills/ritual-meta-circuit-breaker/SKILL.md` |
| Non-Interactive Bias | When you need the resolution hierarchy, caching staleness table, or budget brackets | `skills/ritual-meta-non-interactive-bias/SKILL.md` |
| Human-in-Loop at Forks | When you need canonical fork points, the fork test, or pull budget derivation | `skills/ritual-meta-human-in-loop/SKILL.md` |
| Verification Protocol | When running checks and you need exact commands, pass/fail criteria, or the E2E journey | `skills/ritual-meta-verification/SKILL.md` |

**Rule: the compact header is your operating manual. The extended references are your detailed specs. Operate from the header; consult the specs when the header isn't enough.**

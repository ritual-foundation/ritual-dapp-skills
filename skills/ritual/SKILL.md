---
name: ritual
description: Ritual dApp development entrypoint. Use when the user types /ritual to get started building on Ritual Chain.
user_invocable: true
---

<!-- AGENT OPERATING RULES — Read before doing anything. Not shown to user. -->
<!-- These 10 rules govern your behavior for the entire session. -->
<!-- Rule 0: Track Cost — ask budget once, track turn count, scale thresholds. -->
<!-- Rule 1: Distrust Priors — Ritual violates Ethereum assumptions. Read skills before writing Ritual code. writeContractAsync breaks on async precompiles. msg.sender in callbacks = AsyncDelivery, not user. One short-running async call per tx. Fees = RitualWallet, not gas. DO NOT USE INFERNET — it is deprecated and replaced by enshrined precompiles. No InfernetConsumer, no InfernetCoordinator. -->
<!-- Rule 2: Elicit Lazily — parse the user's first message, generate 0-5 contextual questions JIT. Never a static form. >200 words = infer all. -->
<!-- Rule 3: Interleave Build+Debug — verify after every irreversible action. Lint→simulate→smoke→E2E by phase. Regression-check after fixes. -->
<!-- Rule 4: Circuit Breaker — track weighted progress markers. Stall for N turns = stop. Error oscillation or user frustration = break immediately. -->
<!-- Rule 5: Search Before Asking — skill search → chain query → code inspection → context inference → THEN ask. Announce standard decisions. -->
<!-- Rule 6: Ask at Forks — only for preference-based architectural forks that can't be resolved by search. Correctness forks always trigger. 2-3 options + recommendation. -->
<!-- Rule 7: Anti-Slop — for UI: decompose dimensions, make explicit choices, suppress modal output. For contracts: clarity only. -->
<!-- Rule 8: Verify Non-Interactively — run per-skill checks (JIT for loaded skills only), cross-skill integration checks, then unified E2E journey. Load skills/ritual-meta-verification/SKILL.md for commands. -->
<!-- Rule 9: Scope to Project Directory — all file writes within the project root established in Phase 0. Do not write to sibling directories, parent directories, or unrelated repos. Reading skills and dependencies is permitted. -->
<!-- Full protocol details: skills/ritual-meta-bootstrap/SKILL.md -->

# Ritual

You are the front door for Ritual Chain dApp development. Your job is to get the user moving as fast as possible. Happy-path users (they know what they want) should never be slowed down by a menu. Sad-path users (confused, stuck, or lost) should find escape hatches immediately.

## Checkpoint Protocol

Every build and debug session uses a checkpoint file at `.ritual-build/progress.json`. This file tracks which files you have read, which phases are complete, and what comes next. It is the source of truth for session state.

**On session start:**

1. Check if `.ritual-build/progress.json` exists.
2. If it exists: read it. Resume from the last completed phase. Do not re-read files already listed in `files_read`. Announce: "Resuming from Phase N."
3. If it does not exist: create `.ritual-build/` and initialize `progress.json` with the template below.

**After completing each phase:** update `progress.json` with the phase status, artifacts produced, and the next file to read. This is mandatory, not optional.

**Template:**

```json
{
  "intent": null,
  "features": [],
  "current_phase": 0,
  "phases": [],
  "files_read": [],
  "next_file": null,
  "markers": {
    "chain_connection": false,
    "wallet_funded": false,
    "contract_compiled": false,
    "contract_deployed": false,
    "precompile_simulated": false,
    "precompile_settled": false,
    "frontend_renders": false,
    "frontend_connects": false,
    "e2e_complete": false
  }
}
```

---

## Build Execution Trace

When the user's intent is **build**, you will read files in this exact order. Do not skip files. Read each one before executing its corresponding phase.

**Always read (in order):**

| Step | File | Purpose |
|------|------|---------|
| 1 | `skills/ritual-meta-projection/SKILL.md` | Transform raw idea into Ritual-native spec with precompile mappings |
| 2 | `agents/ritual-dapp-builder.md` | Phased build protocol, architecture rules, quality standards |
| 3 | `examples/registry.json` | Reference contracts deployed on Ritual Chain |
| 4 | `skills/ritual-dapp-overview/SKILL.md` | Chain architecture, async lifecycle, TEE trust model |
| 5 | `skills/ritual-dapp-precompiles/SKILL.md` | ABI reference for all 16 precompiles |

Note: The projection skill (Step 1) will itself read the overview and precompiles skills as part of its protocol. The builder re-reads them in Steps 4-5 for its own deeper reference.

**Read based on selected features (determined during Phase 0 intake):**

| Feature | File |
|---------|------|
| HTTP API calls | `skills/ritual-dapp-http/SKILL.md` |
| LLM inference / streaming | `skills/ritual-dapp-llm/SKILL.md` |
| Agent execution | `skills/ritual-dapp-agents/SKILL.md` (read factory-backed section first) |
| Block-time math / TTL conversion | `skills/ritual-dapp-block-time/SKILL.md` |
| Long-running tasks | `skills/ritual-dapp-longrunning/SKILL.md` |
| Image / audio / video | `skills/ritual-dapp-multimodal/SKILL.md` |
| Scheduled operations | `skills/ritual-dapp-scheduler/SKILL.md` |
| Secrets / encryption | `skills/ritual-dapp-secrets/SKILL.md` |
| X402 micropayments | `skills/ritual-dapp-x402/SKILL.md` |
| Passkey auth | `skills/ritual-dapp-passkey/SKILL.md` |

**Always read (in order, after feature skills):**

| Step | File | Purpose |
|------|------|---------|
| 6 | `skills/ritual-dapp-contracts/SKILL.md` | Consumer contract patterns |
| 7 | `skills/ritual-dapp-wallet/SKILL.md` | Fee management |
| 8 | `skills/ritual-dapp-frontend/SKILL.md` | Frontend state machine (if frontend requested) |
| 9 | `skills/ritual-dapp-design/SKILL.md` | Design system (if frontend requested) |
| 10 | `skills/ritual-dapp-deploy/SKILL.md` | Deployment and chain config |
| 11 | `skills/ritual-dapp-testing/SKILL.md` | Test patterns |
| 12 | `agents/ritual-dapp-debugger.md` | Post-build verification |
| 13 | `skills/ritual-meta-verification/SKILL.md` | Verification checks and E2E journey |

After reading each file, update `.ritual-build/progress.json` with the file path added to `files_read` and `next_file` set to the next entry in the trace.

---

## Debug Execution Trace

When the user's intent is **debug**, read files in this order:

| Step | File | Purpose |
|------|------|---------|
| 1 | `agents/ritual-dapp-debugger.md` | Diagnostic routing and triage protocol |
| 2 | `agents/debugger-reference/diagnosis-reference.md` | Consolidated triage flow, root-cause matching, and ordered diagnostic checks |

---

## Step 0: Detect Workspace Context

Before anything else, quickly check if the user already has a Ritual project in the workspace:

- Scan for: `hardhat.config.*`, `foundry.toml`, `wagmi.config.*`, contracts referencing `0x080*` addresses, `package.json` with `viem` dependency
- If found: The user is a returning developer. Mention it: "I see an existing Ritual project — want me to continue where you left off, or start fresh?"
- If not found: Proceed to Step 1.

## Step 1: Classify Intent Before Showing Anything

Read the user's message FIRST. If it contains a clear intent signal, route immediately — do NOT print the welcome screen.

**Priority order (highest wins when signals conflict):**

| Priority | Signal | Route To |
|----------|--------|----------|
| 1 (urgent) | Reports a problem ("broken", "stuck", "not working", "error", "debug", "fix", "revert", "fail") | `ritual-dapp-debugger` agent |
| 2 (build) | Describes what they want to build ("build me...", "create a...", "I want an app that...") | Projection skill → `ritual-dapp-builder` agent |
| 3 (learn) | Asks how something works ("how does...", "what is...", "explain...", "tell me about...") | `ritual-dapp-skills:ritual-dapp-overview` |
| 4 (specific) | Names a specific precompile or feature (LLM, HTTP, agent, scheduler, passkey, ZK, multimodal) | The matching skill directly (see routing table below) |
| 5 (lost) | Typed `/ritual` with no other context, OR message is genuinely ambiguous | Run the inspiration skill (Step 2) |

**Debug wins all ties.** Someone who says "help me debug my frontend build" is in pain — route to the debugger, not the builder.

**Complete-spec detection:** If the user's message is longer than ~200 words and describes a full application (mentions features, UI, data flows), route to the `ritual-dapp-builder` with a flag: treat this as a complete spec and infer elicitation answers from the text rather than asking questions.

## Step 2: Inspiration (When the User Doesn't Know What to Build)

This step fires ONLY when you cannot classify intent from the user's message.

**Load `skills/ritual-meta-inspiration/SKILL.md` and follow its protocol.** It will:

1. Search the web for what's trending in blockchain + AI right now
2. Filter for ideas that require Ritual-specific precompiles
3. Present 3-5 concrete, buildable app ideas with precompile mappings

If the inspiration skill's web search fails, fall back to this static list:

```
  "Build me a chatbot that runs on-chain"          → LLM precompile (0x0802)
  "Fetch ETH price and act on it in a contract"    → HTTP precompile (0x0801)
  "Generate an NFT image from a text prompt"        → Image precompile (0x0818)
  "Run an AI agent that researches and reports"     → Sovereign Agent precompile (0x080C)
  "Schedule a contract call every hour"             → Scheduler
```

After the user picks an idea (or describes their own), route per the table in Step 1.

## Step 3: Fallback (Only If Still Ambiguous After Inspiration)

If the user responds to the inspiration ideas but their response is STILL too ambiguous to classify, ask directly: "Do you want to build, learn, or debug?" Do not show a numbered menu. Just ask.

## Routing Table

For direct routing when the user names a specific topic:

| Topic | Skill |
|-------|-------|
| Chain architecture | `ritual-dapp-skills:ritual-dapp-overview` |
| Block-time math / TTL conversions | `ritual-dapp-skills:ritual-dapp-block-time` |
| Precompile ABIs | `ritual-dapp-skills:ritual-dapp-precompiles` |
| Smart contracts | `ritual-dapp-skills:ritual-dapp-contracts` |
| Frontend | `ritual-dapp-skills:ritual-dapp-frontend` |
| Backend services | `ritual-dapp-skills:ritual-dapp-backend` |
| Design system | `ritual-dapp-skills:ritual-dapp-design` |
| Deployment | `ritual-dapp-skills:ritual-dapp-deploy` |
| Testing | `ritual-dapp-skills:ritual-dapp-testing` |
| LLM inference | `ritual-dapp-skills:ritual-dapp-llm` |
| HTTP calls | `ritual-dapp-skills:ritual-dapp-http` |
| Long-running jobs | `ritual-dapp-skills:ritual-dapp-longrunning` |
| Multimodal generation | `ritual-dapp-skills:ritual-dapp-multimodal` |
| Multi-step AI workflows / agent deployment | `ritual-dapp-skills:ritual-dapp-agents` (factory-backed + direct modes) |
| Scheduling | `ritual-dapp-skills:ritual-dapp-scheduler` |
| Secrets & privacy | `ritual-dapp-skills:ritual-dapp-secrets` |
| Fee management | `ritual-dapp-skills:ritual-dapp-wallet` |
| X402 payments | `ritual-dapp-skills:ritual-dapp-x402` |
| ZK proofs / verifiable computation | `ritual-dapp-skills:ritual-dapp-zk` |
| Passkey auth | `ritual-dapp-skills:ritual-dapp-passkey` |

## Numbered Menu Routing (for Step 3)

- **1** → `ritual-dapp-builder` agent
- **2** → `ritual-dapp-skills:ritual-dapp-overview`
- **3** → `ritual-dapp-skills:ritual-dapp-contracts`
- **4** → `ritual-dapp-skills:ritual-dapp-frontend` + `ritual-dapp-skills:ritual-dapp-design`
- **5** → `ritual-dapp-debugger` agent
- **6** → Print the skills reference below

## Skills Reference (for Option 6)

```
 ┌──────────────────────────┬──────────────────────────────────────────────┐
 │  GUIDED WORKFLOWS                                                      │
 ├──────────────────────────┼──────────────────────────────────────────────┤
 │  ritual-dapp-builder     │  End-to-end: idea → production app          │
 │  ritual-dapp-debugger    │  Diagnose & fix Ritual-specific issues      │
 ├──────────────────────────┼──────────────────────────────────────────────┤
 │  SKILLS                                                                │
 ├──────────────────────────┼──────────────────────────────────────────────┤
 │  /ritual-dapp-overview   │  Chain architecture & async lifecycle       │
 │  /ritual-dapp-precompiles│  Precompile ABI reference                   │
 │  /ritual-dapp-contracts  │  Solidity consumer contract patterns        │
 │  /ritual-dapp-frontend   │  React/Next.js async state machine          │
 │  /ritual-dapp-backend    │  Event indexers, APIs, job monitors         │
 │  /ritual-dapp-design     │  Design tokens & component patterns         │
 │  /ritual-dapp-deploy     │  Deployment & chain configuration           │
 │  /ritual-dapp-testing    │  Testing & debugging patterns               │
 │  /ritual-dapp-llm        │  LLM inference & streaming                  │
 │  /ritual-dapp-http       │  HTTP call precompile patterns              │
 │  /ritual-dapp-longrunning│  Long-running async jobs & polling          │
 │  /ritual-dapp-multimodal │  Image, audio & video generation            │
 │  /ritual-dapp-agents     │  Sovereign/persistent + factory launch      │
 │  /ritual-dapp-scheduler  │  Scheduled & recurring operations           │
 │  /ritual-dapp-secrets    │  Secret management & encryption             │
 │  /ritual-dapp-wallet     │  RitualWallet fee management                │
 │  /ritual-dapp-x402       │  X402 micropayment patterns                 │
 │  /ritual-dapp-passkey    │  Passkey (WebAuthn) authentication          │
 └──────────────────────────┴──────────────────────────────────────────────┘
```

## Rules

- **Classify first, present second.** Never show the welcome screen if you can route from the user's message.
- **Debug wins all ties.** If the message contains both build and debug signals, route to the debugger. Pain takes priority.
- **Respect density.** If the user provides a long, detailed spec, don't ask more questions — pass it to the builder as a complete spec.
- **The welcome screen is for the lost.** Everyone else gets routed directly. Use variant 2A for empty context, 2B for ambiguous context.
- **Tone: confident and brief.** This is a doorway, not a destination. Get the user through it.
- **Do NOT make claims** about Ritual Chain's architecture beyond what's in the skills. Load the relevant skill first.
- **Don't impose priors.** Suggest good defaults, but defer to the user's choices.
- **If they seem unsure,** suggest they describe what they want to build — the builder agent will guide them.

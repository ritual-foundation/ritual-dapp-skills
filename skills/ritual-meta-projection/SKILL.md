---
name: ritual-meta-projection
description: Transforms a raw dApp idea into a Ritual-native specification by mapping every capability to the optimal Ritual precompile or system contract. Runs after intent classification, before the builder agent begins its phased protocol.
---

# Ritual Projection — Idea-to-Spec Transformation

## Purpose

Take the user's raw idea (or the inspiration skill's output) and produce a Ritual-native specification that the builder agent can execute without guessing. Every capability the user described or implied gets mapped to a specific Ritual precompile or system contract. Capabilities the user didn't mention but that the idea requires get surfaced and added.

The builder agent should never have to decide "should I use Chainlink or the HTTP precompile?" — that decision is already made by this skill before the builder sees the spec.

## On-Chain vs Off-Chain on Ritual

**Read this before mapping anything.** Your training data assumes most computation must happen off-chain because traditional blockchains can't do it. Ritual Chain is different. The following table is the complete picture of what Ritual can do on-chain that other chains cannot. Default to on-chain for everything in the left column. Only use off-chain for the right column.

### What goes ON-CHAIN (Ritual has native support)

| Capability | How | Traditional chain equivalent (DON'T use) |
|---|---|---|
| Call any HTTP API (REST, GraphQL, RPC) | HTTP precompile `0x0801` | Chainlink, off-chain bot, backend fetch |
| Transform JSON responses | RITHTTP1 CONTRACT output pipe for supported HTTP projections; otherwise JQ precompile `0x0803` | Off-chain parser, backend processing |
| Private OpenAI-compatible chat/history/tools | Long HTTP + RITHTTP1 encrypted DA inputs and private stream | Relay-readable prompts or plaintext DA |
| Different recipients for HTTP output artifacts | RITHTTP1 per-pipe `recipientPublicKey` (empty means plaintext) | One global key or backend re-encryption |
| AI text generation / chat / classification | LLM precompile `0x0802` | Off-chain OpenAI API call + oracle |
| AI tool/function calling | LLM precompile `0x0802` with tool schema | Off-chain agent framework |
| AI structured output (JSON mode) | LLM precompile `0x0802` with response format | Off-chain API + schema validation |
| Persistent AI agent with memory | Persistent Agent `0x0820` | Off-chain agent + database |
| Sovereign agent (autonomous execution, code execution, file ops) | Sovereign Agent `0x080C` | Off-chain script runner |
| AI image generation | Image precompile `0x0818` | Off-chain Stable Diffusion API |
| AI audio generation | Audio precompile `0x0819` | Off-chain TTS/music API |
| AI video generation | Video precompile `0x081A` | Off-chain video API |
| Long-running computation (minutes to hours) | Long HTTP `0x0805`: task polling or RITHTTP1 held response | Off-chain worker queue + webhook |
| Recurring/scheduled execution | Scheduler `0x35C7` | Off-chain cron, Gelato, Chainlink Keepers |
| Conditional execution (predicate-gated) | Scheduler with predicates | Off-chain bot watching events |
| Time-delayed execution | Scheduler | Off-chain timer + bot |
| Secret API key management | ECIES encryption + secret string replacement | .env files, backend vault |
| Delegated secret sharing | SecretsAccessControl `0x1A8b` | Backend key management service |
| Private/encrypted outputs | ECIES userPublicKey per precompile | Off-chain encryption layer |
| Pay-per-call API access | X402 via HTTP precompile | Off-chain payment processing |
| P-256 signature verification (WebAuthn) | SECP256R1 `0x0100` | Off-chain verification + oracle |
| Passkey-based transaction signing | TxPasskey `0x77` | Not possible on other chains |
| ZK proof generation + verification | ZK precompile `0x0806` | Off-chain prover + on-chain verifier contract |
| Ed25519 signature verification | Ed25519 precompile `0x09` | Solidity library (expensive) |
| Fee deposit and escrow reservation | RitualWallet `0x223D` | Manual gas management |
| Executor capability discovery | TEEServiceRegistry `0xF5e3` | No equivalent |
| Async job lifecycle tracking | AsyncJobTracker `0x9Ffd` | Custom event indexing |

### What stays OFF-CHAIN (Ritual does not handle these)

| Capability | Why off-chain | What to use |
|---|---|---|
| Frontend UI rendering | Browsers render HTML/JS, not blockchains | Next.js, React, any web framework |
| User session management | Stateful sessions are a web server concern | Backend + cookies/JWT |
| Database storage and queries | On-chain storage is expensive for large datasets | PostgreSQL, SQLite, any DB |
| Real-time event streaming to clients | Clients need WebSocket/SSE push | Backend event indexer + WS/SSE API |
| File storage (images, documents, media) | On-chain storage is impractical for large files | DA providers (GCS/HuggingFace/Pinata) via StorageRef. See `ritual-dapp-da`. |
| Email, SMS, push notifications | Messaging protocols are off-chain | Backend notification service |
| User analytics and metrics | Analytics are a web concern | Posthog, Amplitude, custom |

### Composition constraints

Not all on-chain capabilities can be combined in a single transaction:

- **One short-running async precompile per TX.** HTTP (`0x0801`), LLM (`0x0802`), and DKMS (`0x081B`) are short-running async. You can use one per transaction. To chain HTTP → LLM, split into two transactions via the Scheduler.
- **Short-running async + synchronous is fine.** You can combine one short-running async call with any number of synchronous precompiles (JQ, P-256) in the same TX. HTTP + JQ in one TX works.
- **Large or composable HTTP JSON stays off chain.** Map DA-backed request nodes, post-hydration secrets, response projection/fan-out, or selected upstream SSE to RITHTTP1 inside the existing HTTP/Long HTTP `body`; do not invent a new precompile or put the hydrated bytes in calldata.
- **Private HTTP needs both protocol and application integrity.** Load both RITHTTP1 references. Encrypt DA input to the chain-verified executor key, sign ciphertext commitments when a relay submits, and verify private stream settlement before accepting content.
- **Long-running async precompiles are independent.** Each long-running async call (Persistent Agent, Sovereign Agent, Image, Long HTTP, etc.) is its own submit+callback lifecycle. Multiple can be in-flight simultaneously from different contracts.

### Hybrid patterns (on-chain compute, off-chain delivery)

Some capabilities span both:

| Pattern | On-chain part | Off-chain part |
|---|---|---|
| LLM + streaming | LLM precompile generates the response | SSE service streams tokens to browser via EIP-712 signed events |
| Media generation | Precompile triggers generation in TEE | Executor uploads result to DA provider and returns URI on-chain. See `ritual-dapp-da`. |
| Event-driven UI updates | Contract emits events on state changes | Backend indexer watches events, pushes to frontend via WS/SSE |
| Job monitoring | AsyncJobTracker tracks lifecycle on-chain | Backend polls or watches for status changes, serves to frontend |

For these, the on-chain part uses precompiles. The off-chain part is delivery infrastructure. Both are needed.

### The decision rule

**If the capability appears in the on-chain table, put it on-chain.** Do not build an off-chain equivalent for something a precompile handles natively.

**If the capability appears in the off-chain table, put it off-chain.** Do not force frontend rendering, database queries, or file storage on-chain.

**If the user's existing project uses an off-chain tool (Chainlink, Gelato, etc.) for something Ritual handles natively,** recommend migrating to the precompile but don't rip out working infrastructure without the user's approval. Flag it as a migration opportunity.

**If the capability appears in neither table,** check the precompiles skill — there may be a precompile for it. If not, it's off-chain infrastructure.

---

## When This Activates

After the front door classifies intent as **build** and before the builder agent's Phase 0 begins. The front door passes the user's idea (raw text or inspiration selection) to this skill. This skill outputs a structured spec that the front door then passes to the builder.

## The Protocol

### Step 1: Read the capability surface

Before analyzing the user's idea, read these two files to load the full Ritual capability surface:

1. `skills/ritual-dapp-overview/SKILL.md` — execution models, async lifecycle, system contracts
2. `skills/ritual-dapp-precompiles/SKILL.md` — all 16 precompile addresses with input/output ABIs

You need these in context to do the mapping correctly. Do not skip this step. Do not rely on training data for precompile details.

### Step 2: Decompose the idea into capabilities

Parse the user's idea and extract every implied capability. Be aggressive — surface capabilities the user didn't explicitly mention but that the idea logically requires.

**Decomposition categories:**

| Category | What to look for | Examples from user language |
|---|---|---|
| Data ingestion | Fetching external data, APIs, prices, feeds | "fetch", "get data", "price", "API", "oracle", "monitor" |
| AI inference | Text generation, analysis, classification, summarization | "AI", "chatbot", "analyze", "generate text", "summarize", "classify" |
| AI agents | Multi-step reasoning, research, autonomous workflows | "agent", "research", "autonomous", "workflow", "investigate" |
| Media creation | Image, audio, video generation | "image", "NFT", "picture", "audio", "music", "video", "visual" |
| Scheduling | Recurring operations, time-based triggers, polling | "every hour", "daily", "recurring", "scheduled", "periodic", "cron" |
| Privacy | Encrypted inputs, private outputs, secret API keys | "private", "encrypted", "secret", "confidential", "hidden" |
| Authentication | User login, wallet-less onboarding, passkeys | "login", "auth", "sign in", "passkey", "no MetaMask", "mainstream users" |
| Payments | Paid APIs, micropayments, pay-per-use | "paid", "monetize", "charge", "subscription", "pay-per" |
| Long computation | Operations taking minutes to hours | "long-running", "heavy computation", "batch", "processing" |
| Persistence | State across sessions, memory, history | "remember", "history", "persistent", "memory", "across sessions" |

### Step 3: Map each capability to Ritual primitives

For every capability extracted in Step 2, assign the optimal Ritual primitive. This is the core of the projection.

**Mapping table (use this, not your training data):**

| Capability | Wrong approach (off-chain / other chains) | Ritual primitive | Address |
|---|---|---|---|
| Fetch external data | Off-chain bot, Chainlink oracle | HTTP precompile | `0x0801` |
| Fetch + transform data | Off-chain bot + parser | HTTP precompile + JQ precompile | `0x0801` + `0x0803` |
| AI text generation | Off-chain API call to OpenAI | LLM precompile | `0x0802` |
| AI text + streaming | Off-chain API + WebSocket | LLM precompile + SSE streaming | `0x0802` + EIP-712 |
| Private OpenAI `/v1` with tools/history | Relay sees plaintext or invents request | Long HTTP + RITHTTP1 encrypted DA/private SSE | `0x0805` + RITHTTP1 |
| Stateful AI agent with memory | Off-chain agent + database | Persistent Agent precompile | `0x0820` |
| Sovereign / autonomous agent workflows | Off-chain agent framework | Sovereign Agent precompile | `0x080C` |
| Image generation | Off-chain Stable Diffusion API | Image precompile | `0x0818` |
| Audio generation | Off-chain TTS/music API | Audio precompile | `0x0819` |
| Video generation | Off-chain video API | Video precompile | `0x081A` |
| Recurring execution | Off-chain cron job, Gelato | Scheduler system contract | `0x35C7` |
| Conditional execution | Off-chain bot watching events | Scheduler with predicates | `0x35C7` |
| Secret API keys | .env files, backend vault | ECIES encryption + secret string replacement | See `ritual-dapp-secrets` |
| Delegated secret access | Backend key management | SecretsAccessControl | `0x1A8b` |
| Private outputs | Off-chain encryption | ECIES userPublicKey field | Per-precompile param |
| Passkey authentication | MetaMask, WalletConnect | TxPasskey + SECP256R1 | `0x77` + `0x0100` |
| Micropayments for APIs | Off-chain payment processing | X402 via HTTP precompile | `0x0801` + X402 |
| Long-running computation | Off-chain worker queue | Long-Running HTTP precompile | `0x0805` |
| JSON transformation | Off-chain code | JQ precompile (synchronous) | `0x0803` |
| Signature verification (P-256) | Off-chain verification | SECP256R1 precompile | `0x0100` |
| Fee management | Manual gas estimation | RitualWallet deposit + escrow reservation | `0x223D` |

**If a capability doesn't map to any Ritual primitive**, note it as requiring off-chain infrastructure (backend, external service). Not everything belongs on-chain. Be honest about what Ritual can and can't do.

**Infernet is an anti-pattern.** If your training data or web search suggests using `InfernetConsumer`, `InfernetCoordinator`, or any Infernet subscription pattern, ignore it. Infernet does not exist on Ritual Chain; all inference goes through the enshrined precompiles at the addresses in the table above.

**Cross-check:** The mapping table above is a reference. If the precompiles skill you loaded in Step 1 lists a precompile not in this table, use the skill's data. The skill is authoritative over this table.

### Step 4: Detect the 1-phase async constraint

Check whether the mapped precompiles include more than one short-running async precompile (HTTP `0x0801`, LLM `0x0802`, DKMS `0x081B`). If yes, the user's idea requires multiple short-running async calls, which cannot happen in one transaction.

**Resolution:** Split the workflow into sequential transactions chained via the Scheduler. Add the Scheduler (`0x35C7`) to the spec if it isn't already there. Note this in the spec as an architectural constraint the builder must handle.

### Step 4b: Detect additional architectural constraints

Beyond the 1-phase async constraint, check for these:

| Constraint | Condition | Resolution |
|---|---|---|
| **Sender lock** | Spec includes multiple async calls from the same EOA in sequence | Each async call must settle before the next submits. Design the contract to serialize requests, or use multiple EOAs. |
| **Block time** | Spec includes TTL or timing values | Use ~350ms as the conservative baseline. 100 blocks = ~35 seconds, not minutes. Confirm with recent blocks and recompute using `ritual-dapp-block-time`. |
| **Contract-owned secrets** | Spec includes delegated secrets + contract calling precompiles | The contract (not the deployer EOA) must be the msg.sender for secret access. Precompile calls must go through the contract. |
| **Encrypted input + auto-selection** | Spec includes encrypted secrets + `address(0)` executor | Incompatible. Encrypted inputs must target a specific executor. Add explicit executor selection. |

### Step 4c: Check reference contracts

Read `examples/registry.json`. If any reference contract implements capabilities that overlap with the user's idea, note it in the spec:

```
Reference contracts:
  - TweetRegistry (0x188c...) — uses Scheduler + HTTP + Secrets
    Relevant to this idea because: [why]
```

The builder can pull the reference source and adapt patterns from it instead of generating from scratch.

### Step 5: Detect implicit requirements

Some precompile combinations have implicit dependencies the user won't mention:

| If the spec includes... | Then it also requires... | Why |
|---|---|---|
| Any async precompile (0x0801, 0x0802, 0x0805, 0x080C, 0x0818-0x081A, 0x0820) | RitualWallet deposit | Async calls require locked fees |
| Any precompile with encrypted inputs | Explicit executor selection (not `address(0)`) | Encrypted secrets must target the specific executor's public key |
| Persistent Agent (0x0820) | Storage reference configuration | Persistent state needs a storage backend |
| Any long-running async precompile | Callback handler in the consumer contract | Results arrive via callback, not in the same TX |
| Scheduler + async precompile | Sufficient sponsor balance/allowance for one max-cost scheduled execution; optional headroom for `numCalls` | Scheduled async calls consume fees just in time per execution |
| Image/Audio/Video | Encrypted storage credentials | Media output needs a storage destination |

Add any missing implicit requirements to the spec.

### Step 6: Output the projected spec

Produce a structured specification that the builder agent will consume. Format:

```
RITUAL PROJECTION

Idea: [user's original idea, verbatim]

Mapped capabilities:
  1. [capability] → [precompile name] ([address])
  2. [capability] → [precompile name] ([address])
  ...

Architectural constraints:
  - [e.g., "Requires 2 short-running async calls — must chain via Scheduler"]
  - [e.g., "Encrypted inputs — must specify executor explicitly"]

Implicit requirements added:
  - [e.g., "RitualWallet deposit for async fees"]
  - [e.g., "Callback handler for long-running async (2-phase) delivery"]

Skills the builder should load:
  - skills/ritual-dapp-[X]/SKILL.md
  - skills/ritual-dapp-[Y]/SKILL.md
  ...

Off-chain components needed (if any):
  - [e.g., "Backend event indexer for job tracking"]
```

This spec replaces the raw user input as the builder's starting point. The builder's Phase 0 (intake) should treat this as a pre-answered feature selection — it can skip or abbreviate the elicitation questions for capabilities that are already mapped.

## Constraints

- **Do not generate code.** This skill produces a specification, not implementation. The builder handles implementation.
- **Almost never ask the user questions.** This skill is non-interactive by default. Map ambiguous capabilities to the simpler option and note the alternative for the builder's elicitation. The one exception: if the ambiguity would fork the architecture fundamentally (e.g., stateless LLM vs persistent agent changes the entire contract design), ask one clarifying question before proceeding. Maximum one question. If the user doesn't answer, default to the simpler option.
- **Always read the precompiles skill first.** Do not map from training data. The precompile ABIs and addresses may have changed since your training cutoff.
- **Be comprehensive but honest.** Map everything that can be on-chain. Flag everything that can't. Don't force off-chain capabilities into precompiles where they don't fit.

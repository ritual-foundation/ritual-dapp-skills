# Changelog

## [Unreleased]

### Changed

- Align RITHTTP1 with merged executor PR #247 (`75c04e3`): canonical four-field requests, independent output pipes/keys/encodings, RITOUT1 encoding 4, RITPIPE1 records and separate live/collected commitments. Update every dependent skill, agent, site card and runnable codec; replace obsolete live deployment snapshot with version-pinned examples.

- **Swapped all system-contract constants to the live chain-784 prod-mainnet address set**, verified by `eth_getCode` on 2026-09-14 against the chain RPC (genesis `0x220f7b8d…22ba93`): RitualWallet, AsyncJobTracker, Scheduler, AsyncDelivery, TEEServiceRegistry, SecretsAccessControl, ModelPricingRegistry, AgentHeartbeat, AgentIdentityRegistry. `*.ritualfoundation.org` domain links retained pending DNS cutover.
- Heartbeat internals corrected to mainnet parameters: `defaultTimeout` 10000 / divisor 5 (interval unchanged at 2,000 blocks); revival cooldown 10,000 blocks.
- Model identifiers namespaced to exact registry names (`black-forest-labs/FLUX.2-klein-4B`, `deepseek-ai/DeepSeek-V4-Flash-0731`).
- System-contract tables relabeled from the prior snapshot wording to verified live-mainnet provenance; all references to internal staging networks removed (reference-deployment section relabeled network-neutrally).
- `scripts/check-current-refs.ts` policy flipped: bans the previous snapshot address set and the retired snapshot/staging-network wording; requires the mainnet set.
- Aligned dApp-facing trust and deployment guidance with current contracts, executor enforcement, shared codecs, and generated node configuration.
- Separated secret owner, immediate-caller delegate, RitualWallet sponsor, and executor roles, including owner-bound encryption and context-bound signatures.
- Updated the chain-784 system-contract snapshot to the live network state, removed dead Multicall3 configuration, and made generated deployment/ceremony configuration authoritative.
- Replaced blanket testnet/value assumptions with deployment classification and cost confirmation rules.

### Added

- Canonical RITHTTP1 private-I/O reference covering multi-recipient encrypted DA inputs, per-pipe ECIES, bound stream records and independently collected DA output, key roles, trust assumptions, and relay authorization.
- Agent routing and cross-skill checks for private HTTP applications, including ciphertext commitments, chain-verified executor keys, provider-native stream parsing, and canonical private-I/O vectors.
- Canonical RITHTTP1 reference for DA-backed JSON body hydration, post-hydration secrets, restricted-jq contract projection and storage fan-out, held long-running responses, `RITOUT1` decoding, and authenticated selected SSE records.
- Cross-skill RITHTTP1 routing, architecture, contract/frontend/backend, testing, LLM, X402, agent-composition, and diagnosis guidance while preserving legacy HTTP ABIs and behavior.

- `agents/debugger-reference/scheduled-async-rpc-runbook.md` with embedded runnable Python utilities for:
  - deterministic `TxScheduled` hash derivation from a schedule-submission tx
  - commitment tx discovery from `AsyncJobTracker.JobAdded`

### Updated

- `ritual-dapp-scheduler` skill with deterministic downstream scheduled hash workflow
- `ritual-dapp-longrunning` skill with commitment-resolution workflow from async origin hash
- Debugger references with scheduled/scheduled-async failure patterns and embedded utility usage
- README utility docs pointing to embedded runbook snippets

## [1.0.0] - 2026-03-20

First stable release. 30 skills, 2 agents, 2 runnable examples, a microsite, and interactive knowledge graphs.

### Skills (30 total, up from 18 in 0.0.1)

**New skills:**
- `ritual-dapp-ed25519` — Ed25519 signature verification (0x0009), synchronous precompile
- `ritual-meta-inspiration` — JIT idea generation from live blockchain and AI trends
- `ritual-meta-projection` — Transform raw ideas into Ritual-native specs with precompile mappings

**Rewritten skills (verified against chain behavior and executor source):**
- `ritual-dapp-llm` — Fixed 6 critical ABI bugs that broke all calls. GCS conversation history is now mandatory across all examples. Added error settlement reference (all failures settle on-chain with `has_error=true`), streaming gotchas (signature expiry, slow consumer token drop, stream TTL), and PII sad paths.
- `ritual-dapp-multimodal` — Fixed GCS `storageType` (must be 4), encoding bugs, hardcoded model IDs. Added TX drop checklist.
- `ritual-dapp-agents` — Complete rewrite of Sovereign Agent (0x080C) from verified source. Added ECIES nonce=12 TypeScript configuration, event decode patterns, DA/DKMS encryption docs. Added Persistent Agent (0x0820) spawn lifecycle, DKMS heartbeat address derivation, and operational preflight (DA mandatory, heartbeat address must be funded before spawn).
- `ritual-dapp-passkey` — Clarified TxPasskey (0x77) 9-field signing hash and flat RLP wire encoding.
- `ritual-dapp-secrets` — Replaced `{{SECRET}}` handlebars syntax with `SECRET_NAME` string replacement to match actual executor behavior.
- `ritual-dapp-precompiles` — Fixed LLM field count (29 → 30). Normalized `piiEnabled` documentation across all precompile skills.

### Terminology

Normalized across all 30 skills and both agents:
- `SPC` / `two-phase` → `short-running async` / `long-running async`
- `RIT` → `RITUAL`
- `media` → `multimodal`
- Removed all "sequencer" language from developer-facing docs (Ritual uses TEE-EOVMT, not a traditional sequencer)
- Removed discontinued `0x0808` Agent Call precompile; CLI Agent → Sovereign Agent
- Replaced ambiguous "builder" with neutral phrasing in endpoint notes
- Removed executor endpoint guidance from dApp-facing skills (endpoints are internal routing infrastructure)

### Examples

- `examples/persistent-agent/` — End-to-end Persistent Agent (0x0820) flow: Solidity consumer contract, bash orchestration, Python helpers for DKMS heartbeat derivation, child funding, Phase 2 callback decode.
- `examples/sovereign-agent/` — End-to-end Sovereign Agent (0x080C) flow: consumer contract, ECIES encryption, event decode, `uv`-based Python runner.

### Microsite & Visualizations

- `site/index.html` — GSAP-driven fullpage scroll intro with animated terminal replay and skill cards. Deployed to Cloud Run.
- `knowledge-graph.html` / `knowledge-graph-full.html` — Interactive D3 visualizations of skill relationships and dependencies.
- SVG diagrams updated for new terminology and Ritual brand colors.

### Bug Fixes

- Secret signing bug across contracts and HTTP skills
- Stale `http://:3000` executor endpoint references removed from all skills
- `explorer.ritualfoundation.org` verify commands replaced with working custom verifier flow
- Frontend skill: `useSendTransaction` replaced with raw `eth_sendTransaction` for async precompiles (wagmi hook doesn't handle the 9-state lifecycle)

### Infrastructure

- README rewrite with badges, execution trace table, full skill catalog, and directory tree
- Builder agent: added tooling hygiene rules, testnet flag, Infernet ban, project scoping
- Debugger reference: aligned with new terminology
- SVG verification script (`scripts/verify_svgs.py`) for CI

## [0.0.1] - 2026-03-13

Initial tagged release. 18 skills, 2 agents, starter templates.

- Full coverage of Ritual precompiles (HTTP, LLM, Agent, Long-Running, Multimodal)
- Smart contract patterns with Foundry and Hardhat support
- Frontend async transaction state machine
- Backend event indexer and API patterns
- Secret management and private output support
- X402 micropayment integration
- Scheduler patterns for recurring operations
- Design system tokens and components
- Testing and debugging workflows
- `ritual-dapp-builder` orchestrator agent
- `ritual-dapp-debugger` diagnostic agent
- Next.js and Hardhat starter templates

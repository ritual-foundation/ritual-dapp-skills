---
name: ritual-dapp-agents
description: Persistent agent and sovereign agent patterns for Ritual dApps. Use when building dApps with long-lived AI services, sovereign agent jobs, or agent-native product flows on Ritual Chain.
---

# Persistent Agent & Sovereign Agent Patterns

For reactive Hermes application integration after launch, read [Agent Link](../ritual-dapp-agent-link/SKILL.md). It covers explicit UAHI events/cadence/hybrid modes, pinned manifests, connector credentials, HTTP/WebSocket command and event transport, approvals, Stop, and reconnects.

> **Runnable examples:**
> - `examples/sovereign-agent/` deploys its own consumer and submits directly to `0x080C`.
> - `examples/persistent-agent/` deploys its own consumer and submits directly to `0x0820`.
>
> **This skill covers how to *launch* an agent.** For how a launched agent actually does useful work over time — shaping behavior through the workspace md files (`SOUL.md`/`AGENTS.md`/`TOOLS.md`), choosing a run mode, defining outcome proof, and rehearsing the loop locally before spending a launch — see `skills/ritual-meta-agent-orchestration/SKILL.md`.

> For a durable launch timeline, evidence at each stage and timeout recovery, read
> [launch diagnostics](references/launch-diagnostics.md). For executable Hermes
> skills, Jev and the distinction between encrypted secrets and runtime env, read
> [Hermes tools and secrets](references/hermes-tools-and-secrets.md).

> **Before running either example — required user-supplied inputs (elicit these upfront):**
>
> Both `examples/sovereign-agent/run.sh` and `examples/persistent-agent/run.sh`
> fail fast (exit code `2`) if any required variable is unset or still contains
> an unfilled placeholder (`<…>`, `YOUR_…`). If you are an agent running these
> scripts on behalf of a user, ask the user for the following before invoking
> `bash run.sh`:
>
> - `EXPECTED_CHAIN_ID` — persistent example: independently verified target deployment chain ID
> - `PRIVATE_KEY` — funded 0x-prefixed key on Ritual Chain
> - `RPC_URL` — RPC endpoint (e.g. `https://rpc.ritualfoundation.org`)
> - Exactly one LLM API key: `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY` / `OPENROUTER_API_KEY`. The scripts infer the provider from which key is set — do NOT ask the user for a separate `LLM_PROVIDER` value. The keyless `ritual` provider mode is not supported by the examples.
> - `MODEL` — exact provider-routable model id (e.g. `claude-sonnet-4-5-20250929` for Anthropic, `gemini-2.5-flash` for Gemini). **Required for sovereign; optional for persistent** (the persistent helper defaults a model per provider).
> - **Sovereign agent additionally requires** DA storage — `HF_TOKEN` + `HF_REPO_ID` (a HuggingFace dataset the user owns, in `user/repo` form) **or** `GCS_DA_SERVICE_ACCOUNT_JSON` + `GCS_DA_BUCKET` (a bucket the user owns). Default to hf (one token + one repo) when the user has no constraint. The example stores convo history, artifacts, and the system prompt here.
> - **Persistent agent additionally requires** one DA provider configured:
>   - `DA_PROVIDER=hf` → `HF_TOKEN` + `HF_REPO_ID`
>   - `DA_PROVIDER=gcs` → `GCS_DA_SERVICE_ACCOUNT_JSON` + `GCS_DA_BUCKET` (a bucket the user owns)
>   - `DA_PROVIDER=pinata` → `DA_PINATA_JWT`
>
> Do not guess or fill in placeholder values for the secrets above (private key, API keys, DA tokens) — ask the user for those. Everything else has a working default in the scripts.

> **Scope note:** This skill focuses on the two agent primitives most builders will use directly: Persistent Agent (`0x0820`) and Sovereign Agent (`0x080C`).

Ritual Chain provides two enshrined agent primitives for on-chain AI execution:

| Precompile | Address | Purpose |
|------------|---------|---------|
| Persistent Agent | `0x0820` | Long-lived, monitored, revivable agent instance with identity, memory, and DA-backed continuity |
| Sovereign Agent | `0x080C` | High-powered async agent job with skills, tools, convo history, and artifact outputs |

Both follow the async executor pattern: submit a request on-chain, an executor picks it up, runs the agent in a TEE, and delivers the result via callback. The origin transaction hash identifies the job. After async commitment and executor Phase-1 settlement, the settled receipt exposes the task/prelaunch result; Phase 2 delivers the final result through the consumer callback.

The critical product distinction is this:

- **Persistent Agent** is a **service primitive**. You use it when you want an agent to keep an identity, maintain state, be monitored for liveness, recover from failure, and be operated over time.
- **Sovereign Agent** is a **job primitive**. You use it when you want a powerful agent run that performs a task, returns a result, and ends.

This distinction matters because Ritual is not just giving you "AI calls from Solidity." It is giving you chain-native primitives for both **ephemeral intelligent work** and **long-lived autonomous services**.

### Choosing the Right Agent Precompile

| Need | Precompile | Why |
|------|------------|-----|
| Long-lived agent with operator-facing continuity | Persistent Agent (0x0820) | The agent is treated as an ongoing monitored service, not a one-off run. |
| Agent with identity, memory, checkpoints, and recovery | Persistent Agent (0x0820) | Built for continuity, liveness monitoring, and revival from encrypted state. |
| Always-on product surface (assistant, manager, autonomous worker) | Persistent Agent (0x0820) | Best when users expect "my agent" to keep existing over time. |
| Tool execution, coding tasks, scripted workflows, artifact generation | Sovereign Agent (0x080C) | Best for task-shaped agent jobs with strong harness/tool support. |
| Rich one-shot agent execution with explicit `skills[]`, `systemPrompt`, and artifacts | Sovereign Agent (0x080C) | Designed as a high-powered async job runner. |
| "I need the agent to remember past interactions as part of its long-lived identity" | Persistent Agent (0x0820) | State continuity is a first-class part of the primitive. |
| "I need a coding or tool harness to do work and return" | Sovereign Agent (0x080C) | Ephemeral execution model fits this better than a spawned persistent service. |

### Persistent vs Sovereign at a Glance

| Question | Persistent Agent (`0x0820`) | Sovereign Agent (`0x080C`) |
|----------|-----------------------------|-----------------------------|
| What is it? | Long-lived monitored agent instance | Ephemeral async agent job |
| Lifetime | Ongoing, revivable | Single execution |
| Best for | Always-on AI services | Powerful task execution |
| Identity | DKMS-derived agent identity + workspace | Task-oriented; identity is not the product surface |
| State model | DA-backed continuity + memory | Optional carry-forward via convo/output refs |
| Skills model | No `skills_ref`; shaped by workspace docs + config | Explicit `skills[]` input refs |
| Tools model | `tools_ref` becomes `TOOLS.md` guidance | `tools[]` constrain harness-allowed tools |
| Operator channels | Best fit for user-facing channels (e.g. Telegram) | Usually invoked as a job from apps/contracts |

### Capability-to-Precompile Mapping

When querying `TEEServiceRegistry.getServicesByCapability(capability, true)`, both agent precompiles use the same capability:

| Capability ID | Name | Precompiles |
|--------------|------|-------------|
| `0` | HTTP_CALL | Persistent Agent (0x0820), Sovereign Agent (0x080C) |

Both Persistent Agent and Sovereign Agent executors run on HTTP call capability executors.

> **Capability routing:** Query for executors with `HTTP_CALL` (0) capability to find executors that support both Persistent Agent and Sovereign Agent precompiles.

---

## ⚠ Launch Gate — Silent-Failure Checklist (read this before you submit)

Agent launches fail **silently** far more often than they revert: the tx looks fine (or is quietly dropped) and **no error surfaces on-chain**. Every row below is a *silent* failure — check all of them before the first submit. Each links to a deeper section; this is the gate.

| # | Silent failure | One-line check / rule | Symptom if wrong |
|---|---|---|---|
| 1 | **Origin lock: prior async job has not Phase-1 settled or expired.** | Wait for the prior job to Phase-1 settle before the next EOA transaction. Use separate funded origins for concurrent jobs. `hasPendingJobForTxOrigin` alone can remain true after Phase 1 for a long-running job. | Next transaction does not mine until the origin lock is released. |
| 2 | **ECIES nonce ≠ 12 / wrong pubkey** — executor can't decrypt secrets, silently drops the job; Phase 1 never settles. | Encrypt per `ritual-dapp-secrets`: nonce length **12** (not the library default 16), to `node.executorSecretsAuthPublicKey` (NOT `teeAddress`/`paymentAddress`). Decrypt-test locally first. | Commitment mines, `hasPendingJobForTxOrigin`=true, Phase 1 hangs forever. |
| 3 | **Under-funded RitualWallet** — commitment can't reserve the fee. | `availableBalance(sponsor) >= reserve` (executor + commitment + inclusion + Phase-2 callback). If sponsor≠caller, also `allowance(sponsor, caller) >= reserve`. | Silent reject / `insufficient wallet balance`. Deposit + approve. |
| 4 | **Wrong model string / bad cliType** — job fails inside the executor. | `model` = exact provider-routable id (no shorthand aliases). `cliType` ∈ {0 ClaudeCode, 5 Crush, 6 ZeroClaw}; 1–4 are unsupported. | Empty / failed run. Preflight the model provider-side. |
| 5 | **Phase-2 deadline offset = 0** — rejected at RPC. | `phase2Ttl` (envelope field 3) non-zero and ≤ 70,000 (may be < `ttl`). | `Phase 2 deadline offset must be non-zero`. |
| 6 | **Persistent: preflight skipped** — container spawns but is DEAD (no heartbeat), yet still returns a container ID. | DA configured, heartbeat/DKMS address funded with native RITUAL, and `RitualWallet.approve(AgentHeartbeat, max)` set. Run the Persistent Agent Preflight (Hard-Stop) first. | Container ID returned, agent never heartbeats. |
| 7 | **Container started, then EXITED → FAILED** (ran a few cycles, then heartbeat FSM flips ACTIVE→FAILED) — the agent's OWN code/config crashed the runtime. | After it's live, read `getAssignment(agentId).revivalStatus`. If FAILED, pull the executor/container logs and inspect the agent's own outbound calls. Common causes: a **channel/config force-enabled that the runtime can't handle**, and **unescaped LLM output breaking a JSON body the agent POSTs** — always JSON-encode/validate model output before putting it in a request. | Agent goes FAILED after being ACTIVE; revival retries up to `MAX_REVIVAL_ATTEMPTS` (3), then the slot is removed. Fix the agent, not the chain. |
| 8 | **Sovereign phase-one or phase-two deadline exceeded** — the commitment TTL covers phase-one settlement; the container/CLI, LLM turns, and external calls run in phase two after settlement. | Keep phase-one settlement inside `ttl` (maximum 500 blocks). Size `phase2Ttl` separately for execution and delivery; its deadline is the phase-one settlement block plus the offset. | Check phase-one settlement first. If it succeeded, investigate the phase-two deadline and executor/container timeout logs; increasing phase-one TTL does not extend phase two. |
| 9 | **Two Phase-1 failure families — two different silences.** Authz/decode failures → job **dropped** (`Success:false`): commitment mines but nothing ever settles on-chain. Secrets/DKMS/DA failures → job **settled WITH an error string** (`Success:true` + `errorMessage`, Phase-1 fee charged). | "No Phase 2" alone doesn't identify which happened — check whether the job settled with an `errorMessage` (fix secrets/DKMS/DA) or never settled at all (fix authz/encoding). | Dropped: `hasPendingJobForTxOrigin` stays true until TTL. Settled-with-error: fee charged, `errorMessage` populated, no container. |
| 10 | **Multiple secret owners** — all `encrypted_secrets` blobs must share exactly **ONE** secret owner; multiple distinct `secretOwners` is rejected inside the executor. | Use a single owner address across every blob in `secretOwners[]`. | Settled-with-error (`Success:true` + error string); Phase-1 fee charged, no spawn. |
| 11 | **Prelaunch funding window missed** — after Phase-1 settlement the executor polls the prelaunch primary wallet (returned in the Phase-1 response's `gateway_token` field) every 1 s for a **120 s window**, requiring **≥ 0.01 RIT**. | Watch for Phase-1 settlement in the origin transaction receipt, decode the prelaunch wallet address, and fund it ≥ 0.01 RIT within 2 minutes. | `PRELAUNCH_FUNDING_FAILED` — **non-retryable**; the launch is dead. |
| 12 | **Failure-delivery shedding** — a saturated executor sheds failure deliveries; a shed failure never reaches the chain. | Don't treat "pure TTL timeout with nothing on-chain" as proof of an executor outage — a failed spawn can present exactly this way. Check the executor's `/health` and logs. | Failed spawn presents as a pure TTL timeout with no error anywhere on-chain. |
| 13 | **Success gate: the claim, not the Phase-2 event.** Phase-2 delivery is event-only (observability, not state). The agent exists operationally only once its runtime has claimed the heartbeat slot. | `AgentHeartbeat.getAssignment(agentId).state == ACTIVE && agentAddress != 0` — this is the launch success test. | Phase-2 event received, but the agent never claimed: slot VACANT, no heartbeats, and no revival lifeline. |

**The #1 launch bug, by far, is row 1: reusing one wallet for two agents.** If you launch (or retry) a second agent from a sender that already has an in-flight job, it silently vanishes. **One wallet ⇒ one in-flight agent job.** Running N agents concurrently ⇒ N distinct wallets.

---

## Direct Consumer Deployment

Deploy an application-owned consumer that forwards the canonical envelope to `0x080C` or `0x0820` and authenticates callbacks from the configured `AsyncDelivery` contract. The examples include the complete Solidity consumer, minimal public system ABIs, local compilation, secret sealing, and receipt decoding; they do not require private contract artifacts or an SDK:

- [Sovereign example](../../examples/sovereign-agent/README.md): `SovereignAgentConsumer.callSovereignAgent(bytes input)`.
- [Persistent example](../../examples/persistent-agent/README.md): `PersistentAgentConsumer.callPersistentAgent(uint256 agentId, uint64 revision, bytes input)`.

### Launch sequence

1. Verify the selected chain and configured system-contract bytecode. Deploy the included consumer with the chain's `AsyncDelivery` address. Its immutable owner authorizes submission; its callback target is the consumer itself.
2. For persistent agents, the EOA owner allocates `agentId` in a separate committed transaction using `AgentIdentityRegistry.allocateAgentId(owner)`, then approves the consumer with `setAgentOperator(agentId, consumer, true)`. Bind `applicationContext = keccak256(abi.encode(agentId, revision))` and the same id/revision in the 21-field payload. Sovereign calls need no persistent identity.
3. Select an eligible executor from the public registry. Seal the owner-bound secrets to that executor's registered encryption public key. Grant `SecretsAccessControl` access for each ciphertext hash to the **consumer**, because it is the immediate precompile caller. The secret owner, consumer operator, and fee sponsor are distinct roles.
4. Deposit the fee reserve into the sponsor's `RitualWallet` account and approve the consumer as spender when the sponsor is the EOA. Set the envelope sponsor to that funded EOA, callback target to the consumer, callback enabled, and callback value to zero.
5. Encode the canonical flat 13-field `AgentAsyncEnvelope`, carrying the 16-field sovereign or 21-field persistent payload, and submit it through the consumer. Wait for Phase-1 settlement before sending another transaction from the same origin. A previous Phase-1-settled long-running job does not keep the origin locked merely because its final callback is pending.
6. Read `spcCalls` from the settled receipt. Its `output` is the **bare executor result**, not the `(bytes,bytes)` return wrapper used by a Solidity precompile call. Sovereign Phase 1 returns `(string taskId)`. Persistent Phase 1 returns `(string instanceId,string gatewayURL,string containerId,string checkpointCID,string errorMessage,string gatewayToken)`; fail on a nonempty error and never log the token. During persistent prelaunch, fund the returned primary wallet within the documented funding window; then wait for the authenticated callback and an ACTIVE heartbeat assignment.

The executor bootstraps persistent agent-scoped DKMS internally from the admitted job. Sovereign execution also derives its DA key internally and accepts secrets sealed to the registered executor key. Neither launch sequence needs a separate `0x081B` request or a preliminary DKMS-wallet cushion.

### Results and teardown

The consumers record the origin job hash using `0x0830`, accept only matching pending-job callbacks from `AsyncDelivery`, and expose `results(jobId)`. A persistent Phase-2 event alone is not operational success: verify `AgentHeartbeat.getAssignment(agentId)` is ACTIVE with a nonzero runtime address. To stop a persistent agent, the identity owner calls `AgentHeartbeat.recall(agentId)` and verifies the assignment is vacant; an authorized runtime operator then removes the associated runtime instance. A sovereign invocation ends after its result callback.

---

## 1. Long-Running (2-Phase) Delivery Pattern

Agent precompiles use a long-running (2-phase) delivery pattern because agent execution takes multiple blocks:

```
Phase 1: Submit Request
  EOA → Consumer → Precompile → async commitment → Executor Phase-1 result
  Job ID = origin transaction hash; settled receipt contains task/prelaunch output

Phase 2: Deliver Result
  Executor completes agent execution → Calls callbackTarget.callbackSelector(result)
  Your contract receives the callback with the agent's response
```

The origin transaction is first committed as an async job. Its hash is the job ID. After executor Phase-1 execution, inspect the settled receipt: sovereign `spcCalls.output` decodes as a task-id string, while persistent output contains the six strings described above. Phase 2 arrives later through the configured callback; it is distinct from both the origin job hash and Phase-1 output.

### Delivery Configuration

To receive the result on-chain, configure the callback fields of the `AgentProtocolConfig` envelope:

```typescript
// AgentProtocolConfig callback fields (note the types: gas is uint64, fee caps are uint128):
//
//   callbackEnabled:              true,
//   callbackTarget:               '0x...YourConsumerContract',
//   callbackSelector:             '0xaabbccdd',  // function selector for your callback
//   callbackGasLimit:             3_000_000n,    // uint64
//   callbackMaxFeePerGas:         1_000_000_000n, // uint128
//   callbackMaxPriorityFeePerGas: 100_000_000n,  // uint128
//   callbackValue:                0n,            // uint256; must be 0 for sovereign agents
```

Validation is strict and **all-or-nothing**: `callbackMaxPriorityFeePerGas <= callbackMaxFeePerGas`; if `callbackEnabled` is true, `callbackTarget`/`callbackSelector`/`callbackGasLimit` must all be non-zero; if false, **every** callback field must be zero (`InvalidCallbackConfig` otherwise).

**Callback-free (fire-and-forget) is first-class.** An agent envelope with ALL callback fields zero is a legal job end-to-end: `AsyncDelivery.deliver()` detects the disabled callback, settles only the executor fee via `RITUAL_WALLET.settle`, and emits `Delivered(..., address(0), true, 0, 0, 0)` with NO external call. Node-side, the base-fee-vs-`maxFeePerGas` check is skipped, `effective_fee_per_gas = 0`, and prefit gas uses `CALLBACK_DISABLED_DELIVERY_PREFIT_GAS = 1_000_000` when `callbackGasLimit == 0`. The protocol supports callback-free persistent jobs and revival. The direct example consumer enables callbacks to record the final result; liveness still rides AgentHeartbeat.

### Long-Running Commitment Behavior

Agent precompiles (and other long-running async precompiles) are committed to the chain **without validating executor availability**. This means:

1. Your transaction is always included in the next block if your RitualWallet balance is sufficient
2. A `TxAsyncCommitment` is mined — the job enters PENDING_EXECUTION
3. The executor is contacted **after** commitment, not before

**If the executor is unreachable:**
- The job remains in PENDING_EXECUTION until TTL expires
- Your callback is never invoked
- RitualWallet funds remain locked until TTL block is reached
- No error is returned — the transaction appears successful (Phase 1 mined)

**Mitigation:** Select and pin an executor before sealing secrets, because signatures bind to it. Persistent application launches use valid HTTP_CALL registration, a nonempty encryption key and deployment allowlist/exclusions; an empty registry endpoint is valid. Admission capacity remains finite and is enforced by the executor. Authorized operator health probes can diagnose capacity but public endpoint reachability is not a required product eligibility gate. See Persistent Agent Preflight #6. Sovereign-job health checks are described separately above.

---

## 2. Persistent Agent (0x0820)

The Persistent Agent precompile spawns a persistent, long-running agent with identity, memory, heartbeat-based liveness monitoring, and DA-backed recovery. Persistent Agents are best thought of as **ongoing AI services** rather than one-shot jobs.

> **Naming:** The on-chain name is "Persistent Agent" — all Solidity functions, events, and constants use this name (`callPersistentAgent`, `onPersistentAgentResult`, `PersistentAgentResultDelivered`). Earlier documentation called this "Autonomous Agent" — that name is deprecated. Always use "Persistent Agent" when writing code.

### What a Persistent Agent Really Is

A Persistent Agent is the right primitive when you want to deploy an agent that:

- keeps a stable identity over time,
- maintains state and memory across interactions,
- can expose operator-facing surfaces such as Telegram,
- is monitored on-chain for liveness,
- can be recovered from its latest encrypted checkpoint if it stops responding.

This is the main mental model:

1. You first allocate a chain-issued `agentId` in a **standalone committed transaction** — `AgentIdentityRegistry.allocateAgentId(owner)` for the owner EOA — and parse the new id from `AgentIdAllocated`. Same-tx allocate+launch is unsupported.
2. You submit a Persistent Agent request on-chain: the committed `agentId` (plus a `uint64 revision`) is passed as explicit arguments and also sits near the end of the 21-field V1 executor payload (field 19, with `revision` after it), bound into the envelope via `applicationContext = keccak256(abi.encode(agentId, revision))`.
3. The system provisions a long-lived agent instance in a TEE-backed runtime.
4. The agent maintains state through its workspace, memory, and encrypted DA checkpoints.
5. A heartbeat contract monitors whether the agent is still alive (keyed by `agentId`).
6. If the agent stops heartbeating, the system can attempt revival from the latest checkpoint.

If you want "my agent keeps existing and working for me," this is the primitive.

### Persistent Agent Preflight (Hard-Stop Checklist)

**Do NOT submit a persistent agent request until every item below is satisfied.** Skipping any item results in a wasted transaction: the precompile call may succeed (Phase 1 + Phase 2) but the agent container will fail silently — no heartbeat, no Telegram, no recovery. You will see a container ID in the Phase 2 response but the agent will be dead.

| # | Check | How to verify | What happens if skipped |
|---|-------|---------------|------------------------|
| 0 | **Chain-issued identity committed before launch** | EOA calls `AgentIdentityRegistry.allocateAgentId(owner)`, parses `AgentIdAllocated`, then approves the consumer with `setAgentOperator`. Encode the same `agentId`/`revision` in the payload and envelope context. | Admission rejects an unknown identity, unauthorized caller, or mismatched context. |
| 1 | **Real DA credentials** (not mocked, not empty) | Verify GCS bucket exists and SA has `storage.objectAdmin`, or HF token can access repo, or Pinata JWT is valid | Agent cannot checkpoint. Container may start but cannot persist state or be revived. |
| 2 | **Prelaunch/runtime wallet fundable** — the wallet that must hold funds is the PRELAUNCH wallet returned by Phase 1 (it becomes the runtime EOA): >= 0.1 RITUAL for `claim` (MIN_BALANCE) + heartbeat drip. | `cast balance <prelaunch_wallet>` after Phase-1 funding | Runtime EOA below 0.1 at claim time -> claim reverts; below 0.1 later -> agent REMOVED by liveness check, no revival. |
| 3 | **`rpcUrls` is a publicly reachable RPC** (e.g., `https://rpc.ritualfoundation.org`) | Verify the URL is reachable from outside your local machine | Agent cannot post heartbeats, cannot send any on-chain transactions. **Do NOT use `http://172.17.0.1:8545`** — this is a Docker bridge address that only works when the chain runs on the same Docker host as the executor. |
| 4 | **RitualWallet deposit** covers the spawn lifecycle | `cast call RITUAL_WALLET "availableBalance(address)(uint256)" <sender>` | Precompile call reverts with `insufficient wallet balance`. |
| 5 | **Origin lock released** | Prior jobs from this origin have Phase-1 settled or expired; a pending final callback alone is not a lock. | Transaction is skipped while the origin remains locked. |
| 6 | **Registry-eligible executor selected and pinned before secrets** | Query valid `HTTP_CALL` services, require nonempty encryption key and apply deployment allowlist/exclusions. Empty endpoints are valid; do not require public `/health` or bypass policy for a pin. Executors still enforce finite identity/memory capacity. Operators may inspect authorized health/capacity diagnostics. `CAPACITY_EXCEEDED` is not solved by blind retry: inspect the existing launch, then choose an eligible executor and re-seal secrets for an explicit new launch. | Invalid selection, missing credentials or admission rejection prevents a usable runtime. |
| 7 | **LLM API key is valid** for the chosen provider | Test the key against the provider's API before encrypting | Agent container fails at LLM initialization. |
| 8 | **Consumer and sponsor bindings** | Callback target is the deployed consumer; the EOA sponsor has sufficient RitualWallet balance and allowance to that consumer. | Callback delivery or fee reservation fails. |
| 9 | **Gas limit is sufficient** | Use the explicit submission gas limit in the direct consumer example. | Submission runs out of gas. |


**DA is non-negotiable.** Persistent agents cannot function without real, working DA credentials. Unlike Sovereign Agents (which can execute with empty DA refs), Persistent Agents use DA for state continuity, checkpoint/recovery, and workspace persistence. If your DA credentials are fake or expired, the agent will write its initial state and then die.

Supported DA providers:
- `gcs` — requires GCS service account JSON + bucket name **+ a non-empty object prefix** (the `daConfig` StorageRef path): the sidecar's schema-v1 recovery config fails closed with "gcs recovery config requires service_account_json, bucket, and prefix" if any of the three is empty, so an empty `daConfig` path kills the agent at recovery-config build time. "Non-empty" is not enough: the prefix must be exactly the canonical agent-id-keyed value `persistent-agents/agent-{agentId}` (chain-issued numeric `agentId` substituted) — the claw-spawner rejects any other value, and revival reads/writes the SAME prefix as launch (there is no separate `revival-takeover/` prefix). the example's `examples/persistent-agent/helpers.py` derives it for you
- `hf` — requires HuggingFace access token + repo ID
- `pinata` — requires Pinata JWT

For credential formats, see `ritual-dapp-da`.

**`rpcUrls` must be reachable from inside the TEE container.** The agent container uses this URL to interact with the chain (heartbeat registration, heartbeat posting, on-chain transactions). The default `http://172.17.0.1:8545` in example scripts is for local development only — it is the Docker bridge network address and is unreachable from remote TEE executors. In production, use `https://rpc.ritualfoundation.org`.

### Executor Churn: Eviction & Recovery

Pinning makes the chosen executor a standing dependency, not just a launch parameter. If the pinned executor is evicted from the registry or leaves the network:

- **Scheduled calls are cancelled** (`CallCancelled`) — the schedule does not re-route to another executor.
- **`restart()` cannot reuse the old secrets** — they are ECIES-sealed to the evicted executor's key; no other executor can decrypt them.
- **Recovery:** reconcile the submitted job, heartbeat assignment and protocol revival before retrying. An observation timeout does not prove the launch failed. An explicit new launch needs an eligible executor, correctly sealed secrets and grants. See [launch diagnostics](references/launch-diagnostics.md).

### Persistent Agent Lifecycle

The heartbeat contract tracks each agent as a slot keyed by `agentId`, with state `SlotState {VACANT, ACTIVE} × RevivalStatus {NONE, FAILED, REVIVING}`. A persistent agent moves through this lifecycle:

1. **Spawned** — your request creates the agent instance and returns a pending id in Phase 1, then a real instance result in Phase 2.
2. **Claimed (ACTIVE, NONE)** — registration is **claim-based self-registration**: the runtime calls `claim(agentId, ...)` from inside the container (there is no `registerAgent`; the consumer does not register the agent). This is the moment the agent exists operationally — and the launch success gate.
3. **Monitored** — the agent keeps heartbeating at the cadence the sidecar **reads from the contract** (`heartbeatIntervalBlocks()`), not from local config.
4. **Failed (VACANT, FAILED)** — if it misses its heartbeat deadline, the slot is vacated and queued for revival.
5. **Reviving (VACANT, REVIVING)** — the system can attempt to recover the agent from its latest encrypted checkpoint, but only up to `MAX_REVIVAL_ATTEMPTS` times (3 at current genesis; read the live cap via `AgentHeartbeat.MAX_REVIVAL_ATTEMPTS()` and the per-agent counter via `revivalAttempts(agentId)`). The slot stays VACANT until the revived runtime **re-claims**.
6. **Active again** — if revival succeeds and the revived runtime claims and heartbeats, the slot returns to `(ACTIVE, NONE)`.
7. **Removed** — if the agent drops below the contract's minimum balance threshold, **or exhausts its revival budget** (`revivalAttempts >= MAX_REVIVAL_ATTEMPTS`, emitting `SlotRemoved(agentId, agent, "revival attempts exceeded")`), the assignment is deleted rather than endlessly revived. Removal is deletion from tracking, not a state — the `agentId` itself lives forever in the registry, and a fresh claim is the only path back (it resets the counter).

> **One shared `slotNonce` per agentId.** Claim, heartbeat, and vacate all consume a single per-agentId `slotNonce` — **any vacate invalidates in-flight claim/heartbeat signatures**. Signature-signing flows must re-read the nonce after any slot transition. Note also that `claim()` is now 7 args, ending in `(encryptedDAConfig, revivalExecutorPayload, revivalApplicationContext)`, and the executor claim-signature digest inserts `keccak256(revivalExecutorPayload)` and `revivalApplicationContext` immediately before the nonce — signatures minted over the old 8-field digest are invalid, and DKMS `/sign_claim` carries both new fields.

### Heartbeat, Monitoring, and Revival

Persistent agents are tied to a heartbeat contract that tracks liveness and recovery state.

What the heartbeat system does:

- records the agent's latest successful heartbeat,
- stores the latest manifest / checkpoint reference used for recovery,
- marks agents failed when they miss the timeout window,
- initiates revival attempts (bounded by `MAX_REVIVAL_ATTEMPTS`; once the budget is exhausted the slot is removed with `"revival attempts exceeded"` rather than retried forever),
- returns the agent to healthy state after a successful post-revival heartbeat.

There are **two different heartbeat concepts** you should not confuse:

1. **On-chain heartbeat** — proves liveness to the heartbeat contract and enables recovery.
2. **Agent task heartbeat** — a periodic prompt loop the agent can use for application logic.

The first is about lifecycle and recovery. The second is about behavior.

### How to Monitor a Persistent Agent

Your users and backend systems should monitor persistent agents through the AgentHeartbeat system contract at `0xDeeA4Df0C958966ED75570a05430BB0D4844a8cc` (a fixed canonical genesis proxy — same value across chain/executor/DKMS).

> **Slots are keyed by the IdentityRegistry `agentId` (uint256), not the agent's address.** A "slot" is the `agentId -> active holder assignment`. All views are agentId-keyed (`getAssignment(agentId)`, `slotExists(agentId)`, …); there are no address-keyed views.

Useful view methods include:

- `getAssignmentState(uint256 agentId) -> SlotState` — liveness check; returns `VACANT` or `ACTIVE` (ACTIVE means the slot has a live monitored holder). Replaces the old `isAlive(address)`.
- `getAssignment(uint256 agentId) -> SlotAssignment` — detailed slot metadata. `SlotAssignment` is `{SlotState state; RevivalStatus revivalStatus; address agentAddress; bytes32 boundHolderKey; address boundExecutor; uint64 lastHeartbeat; uint64 heartbeatTimeout; uint64 cooldownEnd; string latestManifestCID; bytes encryptedDAConfig; bytes revivalExecutorPayload; bytes32 revivalApplicationContext}`. The two trailing fields (tuple indices 10 and 11) are the claim-time revival binding — the sanitized opaque executor payload (capped at `MAX_REVIVAL_EXECUTOR_PAYLOAD_LENGTH` = 10*1024 bytes, else `RevivalExecutorPayloadTooLarge`) and its application context — set at `claim()`, wiped on unclaim/removal, and replayed byte-exactly by `reviveAgent`; slot-ownership validation requires exact payload+context equality, so a mismatch means ownership loss. Read `revivalStatus` (`RevivalStatus{NONE,FAILED,REVIVING}`) for failure/revival state. Replaces the old `getAgentInfo(address)`.
- `getAgentIdsNeedingRevival() -> uint256[]` — list of agentIds awaiting or eligible for revival (returns agentIds, not addresses). Replaces the old `getAgentsNeedingRevival()`.
- `trackedAgentCount()`, `trackedAgentIdAt(uint256 index)`, `slotNonce(uint256 agentId)` — enumerate and monitor tracked slots.

Lifecycle is now observed via the agentId-keyed `Slot*` events (`SlotClaimed`, `SlotHeartbeat`, `SlotRecalled`, `SlotVacated`, `SlotReplaced`, `SlotRevivalQueued`, `SlotRevivalInitiated`, `SlotRevivalFailed`, `SlotRemoved`), each carrying an indexed `uint256 agentId` topic — replacing the old address-keyed events (`AgentRegistered`/`Heartbeat`/`AgentFailed`/`AgentRevived`/etc.). Indexers must switch topic names and decode the `agentId` topic.

At a product level, you should monitor:

- whether the agent is still alive,
- the last successful heartbeat,
- whether the agent is in failed or reviving state,
- the latest checkpoint / manifest reference associated with that agent.

### What Happens If the Agent Stops Responding?

If a persistent agent misses its heartbeat deadline:

- it is marked as **failed**,
- the system can attempt to **revive** it,
- revival uses the agent's latest encrypted checkpoint / manifest reference — **an agent that never posted a successful heartbeat has no manifest CID and is REMOVED at its first revival attempt**. Heartbeats aren't just liveness; they are the recovery lifeline,
- the revival attempt is **sponsored by the agent's own wallet**: it is paid by pulling the agent's RitualWallet funds through the AgentHeartbeat contract's allowance (`sponsor` = agent, `caller` = AgentHeartbeat), which the heartbeat sidecar pre-approves on startup — the agent must keep both `availableBalance` and that allowance, or it silently never revives,
- the revival tx is **protocol-authored** — `reviveAgent(agentId, executor, precompileInput)` is called with `msg.sender = SYSTEM_SENDER` (`0x…fa7e`), never the identity owner. The named executor must be a **registered HTTP executor** and must match the node's deterministic lottery pick (a new executor is chosen deterministically; do not assume the revived agent runs on the executor you launched with). The precompile input is NOT rebuilt from `latestManifestCID` — it is the opaque `revivalExecutorPayload` + `revivalApplicationContext` stored at claim time, and the contract requires envelope equality: `envelope.executor == executor`, `envelope.sponsor == slot.agentAddress` (the agent funds its own revival), callbacks disabled, context match, and `keccak256(executorPayload)` equality — with `ttl = 500` (`AGENT_REVIVAL_TTL`) and `phase2_ttl = 6000`. The persisted revival payload itself carries `restore_from_cid = ""` (all launch-only material stripped); the executor reads the authoritative restore CID (`latestManifestCID`) and encrypted DA config on-chain from the heartbeat assignment at spawn time — the behavioral outcome (restore from the latest manifest CID on a fresh executor) is unchanged,
- if the revived agent claims and begins heartbeating again, it returns to healthy state.

If a revival attempt fails, retry is **protocol behavior, not deployment orchestration policy**: when the revival's AgentHeartbeat system tx reverts, the node drops the entry from the async pool and skips settlement (no fee is drawn from the agent's RitualWallet for the failed attempt), and the normal liveness scan automatically retries — each attempt still counted against `MAX_REVIVAL_ATTEMPTS`. The sidecar deliberately exits on terminal failures (crash-to-revive) and the chain launches replacements; after the attempt budget is exhausted the contract removes the slot ("revival attempts exceeded"), as described in the lifecycle above.

### What Happens If the Agent Runs Out of Money?

This is important and easy to miss:

- a persistent agent must maintain the minimum native balance required by the heartbeat contract,
- **each heartbeat is payable**: the agent pays `HEARTBEAT_FEE_WEI` (`24_500_000_000_000_000` wei = 0.0245 RITUAL) as `msg.value` on every `heartbeat(agentId, manifestCID, executorSignature)` call, credited to the bound executor's payment address via `RitualWallet.depositFor` — so native balance drains continuously — and the bound executor must be a registered `HTTP_CALL` TEE service or the heartbeat reverts (`executor not registered`),
- if it falls below that threshold, it is **removed from monitoring**,
- removal is different from failure: a removed agent is not simply auto-revived forever.

Beyond holding a minimum native balance, **revival is funded from the agent's RitualWallet** via the sponsor->caller allowance mechanism. The agent must have deposited into RitualWallet and approved the AgentHeartbeat contract to pull those funds: the agent (acting as `sponsor` = `msg.sender`) calls `RitualWallet.approve(caller, amount)` with `caller = AgentHeartbeat` and `amount = type(uint256).max`, so the heartbeat contract can draw revival fees through `allowance[sponsor][caller]`. The persistent-agent heartbeat sidecar establishes this approval automatically on startup (`ensureHeartbeatRevivalApproval`): it reads `allowance(agentAddr /*sponsor*/, AgentHeartbeat /*caller*/)` and, if below max, sends `approve(AgentHeartbeat, type(uint256).max)` from the agent. If this allowance is missing or insufficient, revival cannot be funded. **The default launch leaves `availableBalance = 0`** (verified live: the sidecar sets the allowance but nothing deposits) — so out of the box, a FAILED agent never auto-revives. To enable revival, deposit for the agent: `cast send $RITUAL_WALLET "depositFor(address)" <agent_runtime_wallet> --value 0.5ether` — any owner can do this at any time while the agent is ACTIVE.

So the practical builder takeaway is:

- if your persistent agent runs out of native funds, you should treat that as an operational incident,
- topping up and resuming may require a fresh registration or fresh spawn path,
- do not assume the heartbeat system will keep reviving an underfunded agent forever.

### What Persists vs What Does Not

What persists conceptually:

- the agent's identity and workspace-defining documents,
- memory and accumulated state,
- encrypted DA-backed checkpoints,
- the latest recovery point used for revival,
- operator-facing configuration (for example, channel configuration).

What does **not** exist as a first-class persistent-agent field:

- there is **no `skills_ref`** in the Persistent Agent precompile.

This is one of the biggest conceptual differences from Sovereign Agent.

### Key Concepts

**On-chain agent identity (`agentId`)**: Persistent agents now have a canonical on-chain identity — a chain-issued `uint256 agentId` allocated via the `AgentIdentityRegistry` system contract at `0x2cbF50F833a3AEfb5c5B27068052cB5585F5c087`. This is distinct from the `IDENTITY.md` workspace ref (a DA-backed personality/config document); the `agentId` is the on-chain ownership/identity handle the heartbeat slot and DKMS derivation are keyed by.

- **Allocate**: `allocateAgentId(address identityOwner) -> uint256 agentId` — the caller must equal `identityOwner` (else `IdentityOwnerMismatch`); allocates `++nextAgentId`.
- **Query**: `getIdentity(uint256) -> AgentIdentity{uint256 agentId; address owner}`, `ownerOf(uint256) -> address`, `agentIdsOf(address)` / `getOwnerAgentIds(address) -> uint256[]`, `exists(uint256) -> bool`, `nextAgentId`.
- **Operator delegation**: `setAgentOperator(uint256 agentId, address operator, bool approved)` is owner-authorized. Approve the consumer before launch; operator authorization permits request initiation without transferring identity ownership. Persistent DKMS roots are agent-scoped and bootstrap from the admitted job, not from the operator address.
- **Events**: `AgentIdAllocated(agentId, owner, allocator)`, `AgentOperatorSet(agentId, operator, approved)`.

**StorageRef**: A `(platform, path, keyRef)` tuple pointing to external storage. Supported platforms in this skill are `hf`, `gcs`, and `pinata`. The `keyRef` references a key in `encryptedSecrets` holding the credential. See `ritual-dapp-da` for the full StorageRef definition, platform table, path formats, and credential encryption patterns.

```typescript
// ABI type: (string, string, string)
// Examples:
const hfRef  = ['hf', 'my-org/agent-configs/SOUL.md', 'HF_TOKEN'];
const gcsRef = ['gcs', 'agents/soul.md', 'GCS_CREDENTIALS'];
```

**Soul Reference** (`soul_ref` → `SOUL.md`): The agent's core identity and personality definition.

**Agents Reference** (`agents_ref` → `AGENTS.md`): Operating instructions for the agent.

**User Reference** (`user_ref` → `USER.md`): User profile and context.

**Memory Reference** (`memory_ref` → `MEMORY.md`): Long-term memory — conversation history, learned facts, accumulated context.

**Identity Reference** (`identity_ref` → `IDENTITY.md`): Agent identity configuration.

**Tools Reference** (`tools_ref` → `TOOLS.md`): Tool usage guidance for the agent. This is a workspace document, not the same thing as Sovereign Agent `skills[]`.

**Runtime Config Reference** (`openclaw_config_ref`): Legacy-named runtime configuration patch (JSON). This field now carries runtime-level settings across ZeroClaw/Hermes integrations (for example Telegram and heartbeat wiring). Supports `__KEY__` placeholder substitution — values matching `__KEY_NAME__` are auto-replaced with the corresponding decrypted secret. Example: `"token": "__TELEGRAM_BOT_TOKEN__"` is replaced with the decrypted value of `TELEGRAM_BOT_TOKEN`.

**DA (Data Availability) Config**: Where the agent stores and retrieves persistent data. The executor derives a DA encryption key from DKMS using the sender's Ethereum address. This key is user-bound (not executor-bound), making agent state portable across executors. All agent DA writes are encrypted — every DA platform requires credentials; there is no anonymous write target. For DA formats, providers, and credential payloads, see `ritual-dapp-da`.

**Revival Mode**: Revival is not inferred from payload shape. The persisted revival payload (`PersistentAgentRequest.revival_payload()`, mirrored by the executor's per-spawn sanitizer) blanks ALL one-shot launch material — `secret_owners`, `encrypted_secrets`, `secret_signature`, `user_public_key` AND `restore_from_cid` — keeping `agent_id`/`revision`, LLM config, workspace refs, `rpc_urls`, and `agent_runtime`; it must stay ≤ 10 KiB and requires `agent_id > 0`. The executor detects revival by the spawn **sender being the AgentHeartbeat contract** (`IsAgentHeartbeatSender`; callbacks must be disabled), then fetches the authoritative restore CID (`latestManifestCID`) and encrypted DA config from AgentHeartbeat on-chain (`GetAssignmentAtBlock`) and starts the container in bootstrap mode. On revival, DA and LLM credentials come from the DKMS-encrypted recovery config (the `encryptedDAConfig` blob), a strict schema-v1 tagged union decoded with `DisallowUnknownFields`: `{schema_version: 1, provider ∈ {gcs, pinata, hf} lowercase, exactly ONE provider variant (gcs{service_account_json,bucket,prefix} | pinata{jwt,read_url} | hugging_face{token,repo_id}, all non-empty), required agent_runtime (0-2), optional llm_provider/llm_model/llm_api_key}` — legacy flat keys (top-level `gcs_service_account_json`, `AGENT_PROVIDER`, …) fail decoding. The sidecar builds it via `recoveryconfig.FromEnv()/Validate()` and exits on encryption failure. Remaining env secrets still come from the escrow, but escrow bootstrap is strict: an empty or undecryptable bundle is an error, not a silent skip. This enables automatic agent revival without re-submitting secrets.

**No Persistent-Agent `skills_ref`**: Persistent Agent does **not** accept a `skills[]` array like Sovereign Agent. Persistent-agent behavior is shaped through:

- `SOUL.md`
- `AGENTS.md`
- `USER.md`
- `MEMORY.md`
- `IDENTITY.md`
- `TOOLS.md`
- runtime config payload in `openclaw_config_ref`

This distinction is critical:

- **Persistent `tools_ref`** = one `StorageRef` to a `TOOLS.md` document (instructional prompt context for a long-lived agent).
- **Sovereign `skills[]`** = array of `StorageRef`s to skill files injected into one sovereign run (`skill_0.md`, `skill_1.md`, ...).
- **Sovereign `tools[]`** = harness tool allowlist (tool identifiers/permissions), not a markdown document.

Do not conflate these three.

### Hermes tool approval policy

For persistent Hermes (`agent_runtime = 2`), set `hermes.approvals.mode` in the
JSON carried by `openclaw_config_ref` (`openclawConfigRef` in ABI examples):

```json
{
  "hermes": {
    "approvals": { "mode": "off" }
  }
}
```

Merge this fragment with your existing UAHI, heartbeat, and channel settings.
For an inline StorageRef, use `['inline', JSON.stringify(runtimeConfig), '']`.
It is a runtime setting, not a secret, environment variable, prompt instruction,
connector-manifest field, or new chain ABI parameter.

| Mode | Tool approval behavior |
|---|---|
| `off` | Bypass Hermes tool approval prompts (including plugin approval gates). |
| `smart` | Use Hermes' smart approval assessment; uncertain actions may ask a human. |
| `manual` | Ask a human for actions that require approval. Ordinary allowed actions still run. |

Agent House defaults **new launches to `off`**. General Hermes launches that omit
the policy retain the native default, **`smart`**; omission does not mean `off`.
Use an explicit mode when your application depends on it. Invalid modes fail
launch. Only `approvals.mode` is accepted inside the `hermes` configuration block.

This setting governs approval gates. It does not disable tool hard blocks,
application actor authorization, chain permissions, or model clarification
questions. Agent Link applications must still handle `interaction.requested`
and reply with `interaction.respond`; a clarification can occur in `off` mode.
Unattended/manual single-query or cron work may be denied instead of waiting for
a human, according to Hermes' separate noninteractive policies.

Claw seeds the selected mode once and includes its credential-free policy file
in encrypted DA recovery state. On revival the verified snapshot wins over the
original launch configuration. Changing a launch form does not change an
already-running agent; legacy snapshots without a policy retain restored Hermes
configuration, falling back to native defaults when no mode is configured.

**Deployment prerequisite:** the executor deployment must support this launch
configuration mapping and preserve the selected approval policy through recovery.
Ask the deployment operator to confirm support before relying on the setting;
a runtime name or published software change alone is not deployment proof. Executor Go
already forwards the generic config, so no executor or contract ABI change is
needed. Validate a fresh launch and a DA revival with a bounded approval-triggering
operation before treating the deployment as supporting the selected mode.

### Telegram Plugin

Telegram is a supported user-facing channel. Application-owned bidirectional interfaces use [Agent Link](../ritual-dapp-agent-link/SKILL.md) with Hermes runtime 2; the example below describes the legacy autonomous UAHI configuration, not event-only cognition.

Configure runtime behavior through `openclaw_config_ref`. For a Hermes (`agent_runtime = 2`) agent, configure the work-cycle driver (`uahi`) and the on-chain liveness loop (`heartbeat_chain`) explicitly alongside `channels.telegram` — both default **ON** when omitted (see below), but explicit config keeps you independent of server-side defaults:

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "botToken": "__TELEGRAM_BOT_TOKEN__",
      "dmPolicy": "open",
      "allowFrom": ["*"],
      "groups": {
        "*": {
          "requireMention": false
        }
      }
    }
  },
  "uahi": {
    "enabled": true,
    "tick_sec": 3,
    "app_heartbeat_sec": 10,
    "onboard_mode": "off"
  },
  "heartbeat_chain": {
    "enabled": true,
    "contract_address": "0xDeeA4Df0C958966ED75570a05430BB0D4844a8cc"
  }
}
```

- **`channels.telegram`** — the operator-facing channel (see secret substitution below).
- **`uahi`** — the UAHI runtime tick loop: `tick_sec` (how often the runtime wakes), `app_heartbeat_sec`, `onboard_mode`. **For Hermes (`agent_runtime = 2`), a MISSING `uahi` block defaults the work loop ON** (heartbeat_only mode, ~30 s cadence, `onboard_mode: off`). Only an explicit `"enabled": false` disables it — omission does not. Still configure it explicitly so the cadence and mode are what you intend, not the fallback.
- **`heartbeat_chain`** — the on-chain liveness loop the heartbeat FSM watches: `contract_address` is the `AgentHeartbeat` address (`0xDeeA4Df0C958966ED75570a05430BB0D4844a8cc`). The block carries only `enabled`, `contract_address`, and optional RPC endpoint overrides; `interval_blocks` and `heartbeat_timeout_blocks` are ignored by the spawner and the sidecar. **A MISSING `heartbeat_chain` block defaults on-chain heartbeating ON**; only an explicit `"enabled": false` disables it. Cadence is **contract-only**: the sidecar eth_calls `heartbeatIntervalBlocks()` (uint64, must be > 0; = `defaultTimeout / heartbeatIntervalDivisor` — mainnet uses 10000/5 = 2,000 blocks (dev bootstrap configs use 4000/2 — same 2,000-block interval); local networks typically pin 200/2 = 100 blocks), caches it, and re-reads every 100 blocks. There is NO env/config fallback — a failed or zero read logs an error and the sidecar exits (`os.Exit(1)`) so the revival path takes over.

Use secret substitution for the token:

- `botToken: "__TELEGRAM_BOT_TOKEN__"`
- and include `TELEGRAM_BOT_TOKEN` in the encrypted secrets bundle

This lets a persistent agent expose an operator-facing communication surface without the dApp having to design a custom messaging channel from day one.

### Request ABI — Direct Consumer Input

Encode the following canonical flat 13-field `AgentAsyncEnvelope` and 21-field payload as the `input` argument to `PersistentAgentConsumer.callPersistentAgent(agentId, revision, input)`. Canonical byte-exact encoding is enforced; tuple-wrapped or noncanonical encodings are rejected.

```typescript
import { encodeAbiParameters, parseAbiParameters, keccak256, encodeAbiParameters as enc, toFunctionSelector } from 'viem';

// LLM provider enum: 0=Anthropic, 1=OpenAI, 2=Gemini, 3=xAI, 4=OpenRouter
const LLMProvider = { ANTHROPIC: 0, OPENAI: 1, GEMINI: 2, XAI: 3, OPENROUTER: 4 } as const;

// 21-field persistent V1 executor payload (version first, agentId + revision last)
const PERSISTENT_PAYLOAD_V1_ABI = parseAbiParameters([
  'uint8, address[], bytes[], bytes[], bytes,',                  // version=1, secretOwners, encryptedSecrets, secretSignatures, userPublicKey
  'uint8, string, string,',                                      // provider, model, llmApiKeyRef
  '(string,string,string), (string,string,string),',             // daConfig, soulRef
  '(string,string,string), (string,string,string),',             // agentsRef, userRef
  '(string,string,string), (string,string,string),',             // memoryRef, identityRef
  '(string,string,string), (string,string,string),',             // toolsRef, openclawConfigRef
  'string, string, uint16, uint256, uint64',                     // restoreFromCid, rpcUrls, agentRuntime, agentId, revision
].join(''));

// 13-field flat AgentAsyncEnvelope shared by 0x080C and 0x0820 (NOT a tuple)
const AGENT_ENVELOPE_ABI = parseAbiParameters(
  'address, address, uint64, uint64, bool, address, bytes4, uint64, uint128, uint128, uint256, bytes32, bytes'
);

// Pin a registry-eligible executor under deployment policy (Persistent Agent Preflight #6).
// Require valid HTTP_CALL registration, encryption key, allowlist/exclusions; endpoints may be empty.
const executorAddress = '0x...eligiblePinnedExecutor';
// sponsor: RitualWallet account whose balance backs this async job (must be non-zero).
// The deployed consumer is the immediate precompile caller.
const sponsorAddress = '0x...sponsorEOA';
const consumerAddress = '0x...deployedConsumer';

const executorPayload = encodeAbiParameters(PERSISTENT_PAYLOAD_V1_ABI, [
  1, [], [], [], '0x',                                // version=1, base secret fields (parallel arrays)

  // LLM configuration
  LLMProvider.ANTHROPIC,                              // provider
  'claude-sonnet-4-5-20250929',                       // model
  'ANTHROPIC_API_KEY',                                // llmApiKeyRef — an ARBITRARY name that must match a key in your encrypted secrets map (the examples use 'LLM_API_KEY' for every provider; both are valid as long as ref == secrets key)

  // Storage references (platform, path, keyRef)
  ['hf', 'my-org/agent-data', 'HF_TOKEN'],                 // daConfig — the DA workspace ROOT (HF repo ID / GCS prefix — for gcs it MUST be the canonical `persistent-agents/agent-{agentId}`), NOT a fixed manifest.json: the sidecar writes each manifest to a unique immutable path (HF: manifests/<instanceID>/<64-hex-sha>.json); a mutable manifest.json is coordination metadata only and is never accepted as an on-chain / revival reference
  ['hf', 'my-org/agent-configs/SOUL.md', 'HF_TOKEN'],     // soulRef
  ['', '', ''],                                             // agentsRef (empty)
  ['', '', ''],                                             // userRef (empty)
  ['hf', 'my-org/agent-configs/MEMORY.md', 'HF_TOKEN'],   // memoryRef
  ['hf', 'my-org/agent-configs/IDENTITY.md', 'HF_TOKEN'], // identityRef
  ['hf', 'my-org/agent-configs/TOOLS.md', 'HF_TOKEN'],    // toolsRef
  ['', '', ''],                                             // openclawConfigRef (empty)

  '',                                                       // restoreFromCid (launch-only; stripped in the canonical revival payload)
  `{"ritual":"${process.env.RITUAL_RPC_URL}"}`,             // rpcUrls — JSON-encoded; the agent container uses this to reach the chain
  2,                                                        // agentRuntime — HERMES (2), the default and most-supported runtime (0 = ZeroClaw alternative; 1 legacy-reserved)
  agentId,                                                  // agentId (uint256) — chain-issued, MUST be non-zero; pre-allocated in a prior committed tx
  0n,                                                       // revision (uint64) — application-owned payload revision
]);

// Identity binding: the envelope's applicationContext MUST equal keccak256(abi.encode(agentId, revision))
const applicationContext = keccak256(
  enc(parseAbiParameters('uint256, uint64'), [agentId, 0n]),
);

const encoded = encodeAbiParameters(AGENT_ENVELOPE_ABI, [
  executorAddress,      // executor
  sponsorAddress,       // EOA sponsor with RitualWallet allowance to the consumer
  300n,                 // ttl
  6000n,                // phase2Ttl (~35 min; matches the chain's revival constant)
  true,                 // direct example consumer requires authenticated callbacks
  consumerAddress,      // callbackTarget
  toFunctionSelector('onPersistentAgentResult(bytes32,bytes)'),
  3_000_000n,           // callbackGasLimit (uint64)
  1_000_000_000n,       // callbackMaxFeePerGas (uint128)
  100_000_000n,         // callbackMaxPriorityFeePerGas (uint128)
  0n,                   // callbackValue
  applicationContext,   // applicationContext = keccak256(abi.encode(agentId, revision))
  executorPayload,      // opaque 21-field V1 payload
]);
// `agentId` must come from a prior committed AgentIdentityRegistry.allocateAgentId tx.
// Pass this input to your deployed consumer after the identity allocation has committed.
```

### LLM Provider Enum

```typescript
// LLM provider enum (Persistent Agent only — set as uint8 on-chain field):
const LLMProvider = {
  ANTHROPIC:  0,
  OPENAI:     1,
  GEMINI:     2,
  XAI:        3,
  OPENROUTER: 4,
} as const;
```

> **Note:** Sovereign Agent determines provider via `LLM_PROVIDER` in encrypted secrets (see "Provider Secret Payloads" in Section 3) and additionally supports `"ritual"` (no API key needed). Persistent Agent does **not** support `"ritual"` and only accepts enum values `0..4` above.

### Agent Runtime Enum

```typescript
const AgentRuntime = {
  ZEROCLAW: 0,
  HERMES: 2,
} as const;

// Runtime value 1 still exists in ABI wire format for legacy deployments.
// New integrations should use ZEROCLAW (0) or HERMES (2).
```

### Persistent Agent Wire Format — Envelope (13 fields) + V1 Payload (21 fields)

The chain-visible request is the shared flat 13-field `AgentAsyncEnvelope` (`AGENT_ASYNC_ENVELOPE_FIELD_COUNT = 13`, NOT a tuple), identical for `0x080C` and `0x0820`:

```
Index  Field                           Type      Description
-----  ------------------------------  --------  -----------
0      executor                        address   TEE executor address (MUST not be zero)
1      sponsor                         address   Address sponsoring payment (RitualWallet account, non-zero; approved to the consumer)
2      ttl                             uint64    Time-to-live in blocks (chain-enforced max: 500 blocks)
3      phase2Ttl                       uint64    Phase 2 deadline offset from Phase 1 settlement block (was maxSpawnBlock)
4      callbackEnabled                 bool      All-or-nothing: false => fields 5-10 must ALL be zero
5      callbackTarget                  address   Callback contract address
6      callbackSelector                bytes4    Callback function selector
7      callbackGasLimit                uint64    Gas limit for callback execution
8      callbackMaxFeePerGas            uint128   EIP-1559 max fee per gas
9      callbackMaxPriorityFeePerGas    uint128   EIP-1559 max priority fee (must be <= max fee)
10     callbackValue                   uint256   RITUAL value to send with callback (usually 0)
11     applicationContext              bytes32   Persistent: MUST equal keccak256(abi.encode(agentId, revision))
12     executorPayload                 bytes     Opaque executor-owned request (V1 payload below)
```

The executor decodes `executorPayload` as the strictly-versioned 21-field persistent V1 payload (`expected 21 persistent agent V1 payload fields`; `version != 1` rejected; canonical byte-exact re-encode required):

```
Index  Field                           Type                    Description
-----  ------------------------------  ----------------------  -----------
0      version                         uint8                   MUST be 1
1      secretOwners                    address[]               Explicit owner per encrypted secret blob (parallel to encryptedSecrets/secretSignatures; all empty together when no secrets)
2      encryptedSecrets                bytes[]                 ECIES-encrypted secret blobs
3      secretSignatures                bytes[]                 Owner signatures over the domain-separated secret-authorization payload; signer == secretOwners[i]
4      userPublicKey                   bytes                   User ECIES public key for output encryption (empty = plaintext)
5      provider                        uint8                   LLM provider enum (0=Anthropic, 1=OpenAI, 2=Gemini, 3=xAI, 4=OpenRouter)
6      model                           string                  Model identifier (MUST NOT be empty)
7      llmApiKeyRef                    string                  Placeholder name in encrypted_secrets for LLM API key
8      daConfig                        (string,string,string)  DA layer StorageRef for agent output writes
9      soulRef                         (string,string,string)  SOUL.md — agent personality definition
10     agentsRef                       (string,string,string)  AGENTS.md — operating instructions
11     userRef                         (string,string,string)  USER.md — user profile
12     memoryRef                       (string,string,string)  MEMORY.md — long-term memory
13     identityRef                     (string,string,string)  IDENTITY.md — agent identity
14     toolsRef                        (string,string,string)  TOOLS.md — tool conventions
15     openclawConfigRef               (string,string,string)  Legacy-named runtime config patch (supports __KEY__ substitution)
16     restoreFromCid                  string                  DA manifest CID to restore from. Launch-only: empty = fresh spawn for user-initiated launches; it is stripped (set to "") in the canonical revival payload, and on protocol revivals (AgentHeartbeat-sent spawns) the executor ignores it and uses the on-chain latestManifestCID instead.
17     rpcUrls                         string                  JSON-encoded RPC URLs, e.g. '{"ritual":"http://localhost:8545"}'. An EMPTY string silently strips the container's chain access — always set it, and it must be reachable FROM the executor.
18     agentRuntime                    uint16                  Runtime selector (0=ZeroClaw, 2=Hermes; 1 reserved for legacy OpenClaw deployments)
19     agentId                         uint256                 Chain-issued agent identifier (MUST be non-zero; zero is rejected with InvalidFieldValue / "spawn_agent requires a preallocated chain-issued agentId"). Must be pre-allocated in a prior committed transaction via AgentIdentityRegistry.allocateAgentId — it cannot be caller-invented.
20     revision                        uint64                  Application-owned payload revision; bound with agentId into applicationContext
```

> **`agentId` is committed-state, not request-local.** Allocate it before submitting `callPersistentAgent(uint256 agentId, uint64 revision, bytes input)`. The consumer checks the matching id/revision context; the executor resolves ownership and verifies that the immediate consumer is the owner or approved operator against committed chain state. DKMS bootstrap independently binds the admitted job to that identity.

> **Only one Persistent Agent call per transaction.** The precompile enforces this — a second call in the same tx will fail.

> **Secret signatures are owner-bound and precompile-scoped.** Each `secretSignatures[i]` signs a domain-separated authorization preimage (`RITUAL_SECRET_AUTHORIZATION_V1` || `uint16(len)` || `use_context` || `chainId` || `executor` || `secretOwners[i]` || `keccak256(encryptedSecrets[i])`), **not** the raw ciphertext. For the Persistent Agent the `use_context` is `precompile:0x0000000000000000000000000000000000000820`, so a signature minted for another precompile cannot be replayed here. The recovered signer must equal `secretOwners[i]`.

### Delivery Callback & Events

Your consumer authenticates the callback and emits its result event:

```solidity
// Implement this in your contract:
address constant ASYNC_DELIVERY = 0x508f57AE70967Da28AE0Ab6b95532878c4D0F440;

function onPersistentAgentResult(bytes32 jobId, bytes calldata result) external {
    require(msg.sender == ASYNC_DELIVERY, "unauthorized callback sender");
    // Decode the response fields from `result`
}

// Event emitted by your consumer:
// event PersistentAgentResultDelivered(bytes32 indexed jobId, bytes result);
```

Compute the delivery selector:
```typescript
import { toFunctionSelector } from 'viem';
const deliverySelector = toFunctionSelector('onPersistentAgentResult(bytes32,bytes)');
```

### Phase 1 Response

Phase 1 returns a pending instance ID: `"pending-{txHash[:16]}"` at index 0 — and, critically, the **prelaunch primary wallet address** at index 5 (`gatewayToken`). This is the address you must fund with **≥ 0.01 RITUAL within 120 s** of Phase-1 settlement (Launch Gate row 11). Other fields are empty.

### Phase 2 Response

```typescript
import { decodeAbiParameters, parseAbiParameters } from 'viem';

const [instanceId, gatewayUrl, containerId, checkpointCid, errorMessage, gatewayToken] =
  decodeAbiParameters(
    parseAbiParameters('string, string, string, string, string, string'),
    responseData,
  );
```

```
Index  Field           Type    Description
-----  --------------  ------  -----------
0      instanceId      string  Unique agent instance identifier
1      gatewayUrl      string  Agent gateway URL (the gateway listens on port 18789, injected by the spawner; the 8642 fallback is dead)
2      containerId     string  Docker container ID in the TEE
3      checkpointCid   string  DA manifest CID for state checkpoint
4      errorMessage    string  Error details if spawn failed (empty on success)
5      gatewayToken    string  Phase 1: prelaunch primary wallet address to fund; Phase 2: gateway auth token
```

> All 6 string fields are load-bearing — indices 1 and 5 are `gateway_url`/`gateway_token`, not reserved. Note that Phase-2 delivery is **event-only**: the real success gate is `AgentHeartbeat.getAssignment(agentId).state == ACTIVE && agentAddress != 0` (Launch Gate row 13).

---

## 3. Sovereign Agent (0x080C)

The Sovereign Agent precompile runs AI coding agents (Claude Code, Crush, ZeroClaw) inside a TEE. The executor spawns an ephemeral container, runs the agent, and delivers the result on-chain via callback.

### Supported Harnesses and Providers

| Harness | `cliType` | Description | Supported Providers |
|---------|-----------|-------------|-------------------|
| Claude Code | `0` | Anthropic's Claude Code CLI | Anthropic only |
| Crush | `5` | Lightweight Go agent (charmbracelet/crush) | Anthropic, OpenAI, Gemini, OpenRouter |
| ZeroClaw | `6` | Rust AI agent with tool calling | Anthropic, OpenAI, Gemini, OpenRouter, Ritual gateway |

> Harness types 1-4 exist in some older enums/docs but are unavailable in the supported executor path:
> - 1 (Codex), 2 (Aider), 3 (MCP) are **rejected at chain validation** (chain validation only allows `cliType ∈ {0, 4, 5, 6}`).
> - 4 (OpenClaw) **passes chain validation but is explicitly disabled at the executor** — submitting it returns the error "OpenClaw (type 4) is temporarily disabled; use ZeroClaw (type 6) instead".
>
> Build against **0 (Claude Code), 5 (Crush), 6 (ZeroClaw)** only. **`Hermes` is NOT a sovereign agent harness** — it's a *Persistent Agent* runtime (`agentRuntime = 2` in the Persistent Agent section above). The two enums use different numbering and apply to different precompiles. Do not try to set `cliType = 2` for sovereign — it will be rejected at the chain layer.

> **Recommended default for new sovereign agents:** `cliType = 6` (ZeroClaw) with `LLM_PROVIDER = "ritual"` and `model = "deepseek-ai/DeepSeek-V4-Flash-0731"`. This combination requires no external API keys (the Ritual gateway handles auth via mTLS inside the TEE) and is the lowest-friction path to first-call success — though ritual-provider usage is token-metered per agent, and executors configured with a daily token budget will 429 (`llm_token_budget_exceeded`, `Retry-After: 3600`) once an agent exhausts it, so long-running/chatty agents should account for this when choosing the ritual provider. Switch to Claude Code + Anthropic only if you specifically need Claude's tooling. (See `ritual-dapp-llm` for context-window vs `max_completion_tokens` semantics.)

The provider is determined by the `LLM_PROVIDER` key in `encryptedSecrets`. **`LLM_PROVIDER` is mandatory** — the executor rejects the call with `LLM_PROVIDER not found in secrets` if the key is missing or empty. Always include it explicitly, even when using Anthropic. Valid values: `anthropic`, `openai`, `gemini`, `openrouter`, `ritual`. (Legacy: `google` is normalized to `gemini`.) The `"ritual"` provider does not require an API key and is available for **Sovereign Agent only**. Note: the executor's internal LLM gateway (port 8083) now meters prompt+completion tokens per caller over a rolling 24h window, attributing callers via the `X-Ritual-Agent-Id` header (`"agent:<id>"`, falling back to remote IP). If the executor sets `INTERNAL_LLM_GATEWAY_DAILY_TOKEN_BUDGET` (default 0 = meter-only), over-budget `/v1/chat/completions` calls get HTTP 429 with `Retry-After: 3600` and error code `"llm_token_budget_exceeded"` — agents on the ritual provider must be prepared for this. Per-caller counters are readable at `GET /v1/usage`.

### Switching Harness or Provider Mid-Project

This is a frequent stumbling block — disentangle the two axes before changing anything:

- **`cliType` (harness)**: which CLI runs inside the TEE container — Claude Code, Crush, or ZeroClaw. Goes in the V1 `executorPayload` (`cli_type`, payload field 5) — inside the opaque executor payload. The `payload.*` rows below refer to fields of that 16-field V1 payload.
- **`LLM_PROVIDER` + matching API key (provider)**: which LLM backend that CLI talks to — Anthropic, OpenAI, Gemini, OpenRouter, or the Ritual gateway. Goes in the encrypted secrets JSON.

These are independent. ZeroClaw can talk to Anthropic, Crush can talk to Gemini, etc. (Claude Code is the exception — it only talks to Anthropic.)

**Walkthrough: ZeroClaw + Ritual-hosted model (default) → Claude Code + Anthropic Claude.**

The agent + LLM are both changing; you must change all three of `cliType`, secrets, and `model`:

| Field | Before | After |
|-------|--------|-------|
| `payload.cliType` (V1 payload field 5) | `6` (ZeroClaw) | `0` (Claude Code) |
| `encryptedSecrets` (decrypted JSON) | `{"LLM_PROVIDER":"ritual"}` | `{"LLM_PROVIDER":"anthropic","ANTHROPIC_API_KEY":"sk-ant-..."}` |
| `payload.model` (V1 payload field 11) | `"deepseek-ai/DeepSeek-V4-Flash-0731"` | A Claude model ID, e.g. `"claude-sonnet-4-5-20250929"` or `"claude-haiku-4-5-20251001"` |

**Walkthrough: keep ZeroClaw, switch from the Ritual-hosted model to Anthropic Claude.**

Only secrets + model change; `cliType` stays at `6`:

| Field | Before | After |
|-------|--------|-------|
| `payload.cliType` | `6` (ZeroClaw) | `6` (ZeroClaw) — unchanged |
| `encryptedSecrets` | `{"LLM_PROVIDER":"ritual"}` | `{"LLM_PROVIDER":"anthropic","ANTHROPIC_API_KEY":"sk-ant-..."}` |
| `payload.model` | `"deepseek-ai/DeepSeek-V4-Flash-0731"` | `"claude-sonnet-4-5-20250929"` |

A second source of confusion: the public block explorer (`ritual-scan`) historically only labeled `cliType ∈ {0..4}` and rendered higher values as `UNKNOWN(5)` / `UNKNOWN(6)` — `cliType = 0` always rendered as `claude_code`, so this UI bug bites Crush / ZeroClaw users specifically, not Claude Code switchers. If the scanner UI shows your `cliType` correctly, the chain has accepted the change.

### Preflight Checklist (Run Before Every Launch)

1. Sender has native RITUAL for gas (consumer deployment and submission).
2. Previous async jobs from the EOA have Phase-1 settled or expired; do not submit while the origin is locked.
3. The sponsor's `RitualWallet.availableBalance` covers the reserve, and `allowance(sponsor, consumer)` covers it when sponsor differs from the immediate caller.
4. Select and pin an eligible executor before sealing secrets, using the registry and deployment selection policy.
5. Configure the deployed consumer as callback target, with callbacks enabled and callback value zero.
6. Grant secret access to the consumer for each ciphertext hash before submission.
7. Encrypt secrets per `ritual-dapp-secrets` (ECIES to the pinned executor's `node.executorSecretsAuthPublicKey`, nonce length 12), with exactly **one** secret owner across all blobs.
8. `phase2Ttl` (Phase 2 deadline offset, envelope field 3) must be non-zero and <= 70,000. It may be less than `ttl`. Submitting offset 0 is rejected at RPC with `Phase 2 deadline offset must be non-zero`.
9. `model` must be non-empty and must be an exact provider-routable model identifier (do not rely on shorthand aliases). Before submit, run a provider-side model preflight check and pass the exact model string.
   - Anthropic example: `claude-sonnet-4-5-20250929`
   - OpenAI example: `gpt-4o-mini`
   - Gemini example: `gemini-2.5-flash`
10. `cliType` must be one of: 0 (ClaudeCode), 5 (Crush), or 6 (ZeroClaw). Values 1-4 are unavailable in the supported executor path.

### Provider Secret Payloads

Use one of these encrypted JSON payloads:

```json
{"LLM_PROVIDER":"anthropic","ANTHROPIC_API_KEY":"..."}
```

```json
{"LLM_PROVIDER":"openai","OPENAI_API_KEY":"..."}
```

```json
{"LLM_PROVIDER":"gemini","GEMINI_API_KEY":"..."}
```

```json
{"LLM_PROVIDER":"openrouter","OPENROUTER_API_KEY":"..."}
```

```json
{"LLM_PROVIDER":"ritual"}
```

The `"ritual"` provider does not require an API key and is unavailable for Persistent Agent.

### Critical Constraints

**One pending job per sender.** The chain enforces a single pending async job per sender address via `AsyncJobTracker`. If your previous sovereign agent call hasn't been settled by the executor (or expired via TTL), subsequent calls from the same address are **silently dropped** by the block builder — no error, no revert, the tx just never gets included. Use a fresh sender address or wait for the previous job to complete.

**RitualWallet deposit required.** The sender must have sufficient `availableBalance` deposited in the `RitualWallet` contract (`0xF04076756d8129Baec46Dc0F1c526Baec490C393`). Deposit with native RITUAL (not wrapped tokens):
```solidity
RitualWallet(0xF040...C393).deposit{value: 5 ether}();
```

**EIP-1559 gas parameters.** Transactions must use type 2 (EIP-1559). Set `maxFeePerGas` to at least 20 gwei and `maxPriorityFeePerGas` to at least 1 gwei.

**ECIES encryption.** All secret encryption must follow `ritual-dapp-secrets` — in particular, set the ECIES nonce length to 12 before encrypting. Wrong nonce is the #1 cause of silent agent failures (commitment mined, Phase 1 never settles, sender locked). See "Debugging Silent Failures" below.

**Phase 2 event decode is two-step.** The `SovereignAgentResultDelivered(bytes32,bytes)` event wraps the result in an ABI-encoded `bytes`. You must first decode the outer `bytes`, then decode the inner response tuple:

```python
from eth_abi.abi import decode
raw_data = bytes(log["data"])
(result_bytes,) = decode(["bytes"], raw_data)
success, error, text, _, _, artifacts = decode(
    ["bool", "string", "string", "(string,string,string)", "(string,string,string)", "(string,string,string)[]"],
    result_bytes,
)
```

**Verification criterion.** "Phase 2 event arrived" is not enough. Decode the payload and validate:
- `success == true`
- `error` is empty
- `textResponse` is non-empty if your prompt expects text output

### Defensive decode: when the harness's `text` is not the JSON you asked for

The most painful failure mode for sovereign agents is **not** "Phase 2 never lands" (that has good signals — see `ritual-dapp-longrunning`). It's **"Phase 2 lands and `success == true` but the `text` field isn't the JSON object your contract was relying on"**. This happens because the harness (Claude Code / Crush / ZeroClaw) wraps an LLM call inside its own ReAct loop, and when that inner LLM call fails — most commonly from **upstream context-window overflow** — the harness can fall back to writing its own freeform reasoning trace, an upstream error string, or a partially-formed JSON-ish blob into `text` instead of the structured object your prompt asked for. From your contract's point of view: `success=true`, `error=""`, `text="<long apology / reasoning / error string>"`. Strict JSON parsing then reverts (or worse, parses garbage).

Drivers of this failure (in rough order of frequency):
1. **Context-window budget on the upstream LLM.** Read the model's `max_seq_length` from `ModelPricingRegistry.getModel(name)`. Inside an agent loop, accumulated tool-call replay context fills the window much faster than raw prompt size suggests — budget for replay growth.
2. **`maxTokens` is not a context-window cap.** It limits the *output* the model is allowed to generate. Setting `maxTokens=8192` does not stop a 70K-token prompt from being sent.
3. **Harness reasoning that bleeds into `text`.** When the inner LLM errors mid-iteration, harnesses sometimes return their last reasoning step as the agent's "answer" rather than failing cleanly. The chain layer can't tell the difference; only your decoder can.

**Required consumer pattern.** Every sovereign-agent consumer that expects a structured response must defensively decode in this order:

```solidity
// In your callback (onSovereignAgentResult or equivalent)
function onSovereignAgentResult(bytes32 jobId, bytes calldata result) external {
    require(msg.sender == ASYNC_DELIVERY, "unauthorized");

    // 1. Decode the outer SovereignAgent envelope
    (bool success, string memory error, string memory text, /* convoHistory */, /* output */, /* artifacts */) =
        abi.decode(result, (bool, string, string, (string,string,string), (string,string,string), (string,string,string)[]));

    // 2. Treat success=false OR non-empty error as a hard failure — do not parse text
    if (!success || bytes(error).length != 0) {
        emit AgentFailed(jobId, error);
        return;
    }

    // 3. Treat empty text as a hard failure (harness produced no output)
    if (bytes(text).length == 0) {
        emit AgentFailed(jobId, "empty text");
        return;
    }

    // 4. Try to parse text as your expected schema; on any failure, treat as agent failure (NOT a parse bug)
    //    On-chain JSON parsing is expensive and brittle — prefer parsing off-chain in your indexer / backend
    //    and only commit the parsed result on chain via a separate tx. If you must parse on chain:
    try this.parseAgentJson(text) returns (MyStruct memory parsed) {
        _commitResult(jobId, parsed);
    } catch {
        // text was freeform / malformed — most likely upstream context overflow
        emit AgentFailed(jobId, "text not parseable as expected schema");
    }
}
```

Off-chain decoders (Python / TypeScript) follow the same pattern: `success` first, `error` empty, `text` non-empty, then try JSON parse with a try/catch, and treat parse failure as "agent failed" rather than "schema needs adjusting". If you see frequent text-parse failures, the answer is almost never "tweak the parser" — it's "shrink the prompt", "lower `maxTurns`", or "switch to a model with a larger operational context window".

### Consumer Contracts

Use the complete owner-controlled `SovereignAgentConsumer` in the [example](../../examples/sovereign-agent/README.md). It forwards the canonical input to `0x080C`, tracks the origin job hash, and authenticates `onSovereignAgentResult` against `AsyncDelivery` and the pending job. Configure the consumer as callback target and grant it access to the owner's ciphertext.

### StorageRef Type

StorageRef tuples use `(string, string, string)` — NOT `(string, string, bytes)`:

```typescript
// (platform, path, keyRef) — all strings
type StorageRef = [string, string, string];

// Empty ref:
const emptyRef: StorageRef = ['', '', ''];

// HuggingFace ref:
const hfRef: StorageRef = ['hf', 'my-org/workspace:session.jsonl', 'HF_TOKEN'];
```

### Request ABI — Direct Consumer Input

Encode the following canonical flat 13-field `AgentAsyncEnvelope` and 16-field payload as the `input` argument to `SovereignAgentConsumer.callSovereignAgent(input)`. Canonical byte-exact encoding is enforced.

```typescript
import { encodeAbiParameters, parseAbiParameters, toFunctionSelector } from 'viem';
import { encrypt, ECIES_CONFIG } from 'eciesjs';

ECIES_CONFIG.symmetricNonceLength = 12; // see ritual-dapp-secrets

const CLIType = {
  CLAUDE_CODE: 0,
  CRUSH: 5,
  ZEROCLAW: 6,
} as const;

// 16-field sovereign V1 executor payload (version first)
const SOVEREIGN_PAYLOAD_V1_ABI = parseAbiParameters([
  'uint8, address[], bytes[], bytes[], bytes,',              // version=1, secretOwners, encryptedSecrets, secretSignature, userPublicKey
  'uint16, string,',                                         // cliType, prompt
  '(string,string,string), (string,string,string),',        // convoHistory, output
  '(string,string,string)[],',                               // skills
  '(string,string,string),',                                 // systemPrompt
  'string, string[], uint16, uint32, string',                // model, tools, maxTurns, maxTokens, rpcUrls
].join(''));

// 13-field flat AgentAsyncEnvelope shared by 0x080C and 0x0820 (NOT a tuple)
const AGENT_ENVELOPE_ABI = parseAbiParameters(
  'address, address, uint64, uint64, bool, address, bytes4, uint64, uint128, uint128, uint256, bytes32, bytes'
);

// Encrypt API keys with executor's public key.
// LLM_PROVIDER is mandatory — the executor rejects the call with
// "LLM_PROVIDER not found in secrets" if the key is missing or empty.
// Each blob is wrapped in an owner-bound envelope before ECIES encryption; the
// envelope owner must equal the matching secretOwners[i].
const secretOwner = secretOwnerAddress; // checksummed; signs the secret-authorization payload
const secretEnvelope = JSON.stringify({
  version: 1,
  secret_owner: secretOwner,
  secrets: {
    LLM_PROVIDER: 'anthropic',
    ANTHROPIC_API_KEY: process.env.ANTHROPIC_KEY,
  },
});
const encryptedSecret = encrypt(executorPublicKey.slice(2), Buffer.from(secretEnvelope));

const callbackSelector = toFunctionSelector('onSovereignAgentResult(bytes32,bytes)');

const executorPayload = encodeAbiParameters(SOVEREIGN_PAYLOAD_V1_ABI, [
  1,                                   // version — MUST be 1
  [secretOwner],                       // secretOwners (one owner per blob; parallel to encryptedSecrets/secretSignature)
  [`0x${Buffer.from(encryptedSecret).toString('hex')}`], // encryptedSecrets (bytes[] — owner-bound envelope per blob)
  [secretSignature],                   // secretSignature (owner sig over the precompile:0x...080c authorization payload)
  '0x',                                // userPublicKey (empty = plaintext delivery)

  CLIType.CRUSH,                       // cliType
  'Say hello world',                   // prompt

  ['hf', 'my-org/workspace/sessions/session.jsonl', 'HF_TOKEN'],  // convoHistory (HF-backed memory)
  ['hf', 'my-org/workspace/artifacts/', 'HF_TOKEN'],              // output (HF-backed artifacts)
  [],                                                               // skills (empty)
  ['hf', 'my-org/workspace/prompts/system.md', 'HF_TOKEN'],       // systemPrompt (HF-hosted)

  'claude-sonnet-4-5-20250929',       // model (example Anthropic model id)
  [],                                  // tools (empty = all)
  50,                                  // maxTurns
  8192,                                // maxTokens
  '',                                  // rpcUrls (empty = default)
]);

const encoded = encodeAbiParameters(AGENT_ENVELOPE_ABI, [
  executorAddress,                     // executor (from TEEServiceRegistry)
  sponsorAddress,                      // EOA sponsor with RitualWallet allowance to the consumer
  500n,                                // ttl (blocks until expiry)
  6000n,                               // phase2Ttl (Phase-2/polling deadline; replaces maxPollBlock)
  true,                                // callbackEnabled — required by this consumer
  consumerContractAddress,             // callbackTarget (the deployed consumer)
  callbackSelector,                    // callbackSelector
  3_000_000n,                          // callbackGasLimit (uint64)
  1_000_000_000n,                      // callbackMaxFeePerGas (uint128, 1 gwei)
  100_000_000n,                        // callbackMaxPriorityFeePerGas (uint128)
  0n,                                  // callbackValue — MUST be 0 ("sovereign agent callback value is not supported")
  '0x0000000000000000000000000000000000000000000000000000000000000000', // applicationContext (zero for this consumer)
  executorPayload,                     // opaque 16-field V1 payload
]);
```

### Wire Format — Envelope (13 fields) + Sovereign V1 Payload (16 fields)

The envelope fields (indices 0-12: executor, sponsor, ttl, phase2Ttl, callbackEnabled, callbackTarget, callbackSelector, callbackGasLimit uint64, callbackMaxFeePerGas/MaxPriorityFeePerGas uint128, callbackValue, applicationContext, executorPayload) are shared with the Persistent Agent — see the envelope table in Section 2. The executor decodes `executorPayload` as the 16-field sovereign V1 payload (`expected 16 sovereign agent V1 payload fields`; `version != 1` rejected):

```
Index  Field                           Type                     Description
─────  ─────────────────────────────── ──────────────────────── ────────────────────────────────
0      version                         uint8                    MUST be 1
1      secretOwners                    address[]                Explicit owner per encrypted secret blob (parallel to encryptedSecrets/secretSignature; all three arrays must be EQUAL LENGTH, all empty together when no secrets)
2      encryptedSecrets                bytes[]                  ECIES-encrypted owner-bound secret blobs
3      secretSignature                 bytes[]                  Owner signatures over the domain-separated secret-authorization payload; signer == secretOwners[i]
4      userPublicKey                   bytes                    User ECIES key (empty = plaintext)
5      cliType                         uint16                   0=claude_code, 5=crush, 6=zeroclaw
6      prompt                          string                   Agent prompt
7      convoHistory                    (string,string,string)   Conversation history StorageRef
8      output                          (string,string,string)   Output artifacts StorageRef
9      skills                          (string,string,string)[] Skills array
10     systemPrompt                    (string,string,string)   System prompt StorageRef
11     model                           string                   Model identifier
12     tools                           string[]                 Allowed tools (empty = all)
13     maxTurns                        uint16                   Max conversation turns
14     maxTokens                       uint32                   Max output tokens
15     rpcUrls                         string                   JSON-encoded RPC URLs. An EMPTY string silently strips the container's chain access — always set it, and it must be reachable FROM the executor.
```

The old top-level `pollIntervalBlocks`/`taskIdMarker` fields are deleted; the polling deadline rides `phase2Ttl` on the envelope.

### Data Availability (DA) — Conversation Memory & Artifacts

> For the shared DA architecture (StorageRef type, supported platforms, credential encryption, error handling) see `ritual-dapp-da`. This section covers agent-specific DA patterns.

Sovereign agents are **stateless by default** — each call gets a fresh container. To give an agent memory across calls, you must configure DA StorageRefs. The executor downloads previous state from DA before execution, and uploads updated state after execution.

**Four StorageRef fields control DA:**

| Field | Payload Index | What It Does |
|-------|:---:|---|
| `convoHistory` | 7 | Conversation memory. Executor downloads previous JSONL, injects as conversation context in the prompt, appends a new turn after execution, re-uploads. |
| `output` | 8 | Artifact storage. Executor downloads previous files into `/workspace/artifacts/`, extracts new files after execution, uploads them. |
| `skills` | 9 | Skill definitions. Downloaded and injected as `/workspace/skill_0.md`, `skill_1.md`, etc. Read-only — not re-uploaded. |
| `systemPrompt` | 10 | System prompt. Downloaded and passed to the agent via `--system-prompt`. Read-only — not re-uploaded. |

**Supported DA platforms:**

| Platform | `platform` | Example `path` | `keyRef` | Semantics |
|----------|-----------|----------------|----------|-----------|
| HuggingFace | `'hf'` | `'my-org/agent-workspace/sessions/session.jsonl'` | `'HF_TOKEN'` | Overwrite — same path on each upload |
| GCS | `'gcs'` | `'sovereign-agent/convo_history.jsonl'` | `'GCS_CREDENTIALS'` | Overwrite — object path within bucket (bucket specified in credentials) |
| Pinata | `'pinata'` | `''` (empty for first call, CID for subsequent) | `'DA_PINATA_JWT'` | Append-only — each upload returns a new CID |

**HuggingFace path format:** `org/repo-name/path/to/file` — the first two segments (`org/repo-name`) are the HF dataset repository ID, the rest is the file path within it. Example: `'<your-hf-user>/<your-hf-repo>/sessions/session.jsonl'`.

**GCS path format:** `prefix/path/to/file` — an object key within the GCS bucket. The bucket name is specified in the `GCS_CREDENTIALS` JSON, not in the path. Example: `'sovereign-agent/convo_history.jsonl'` for convo, `'sovereign-agent/artifacts/'` for artifacts directory.

**Pinata path format:** For the first call, pass an empty string `''` — the executor will upload and return a new CID. For subsequent calls, pass the CID from the previous response's `updatedConvoHistory.path` or `updatedOutput.path`. Each upload produces a new immutable CID (content-addressed).

**DA credentials go in `encryptedSecrets`.** Include the credential alongside the LLM API key:

```json
{"ANTHROPIC_API_KEY":"sk-ant-...", "HF_TOKEN":"hf_..."}
```

```json
{"ANTHROPIC_API_KEY":"sk-ant-...", "GCS_CREDENTIALS":"{\"service_account_json\":\"...\",\"bucket\":\"my-bucket\"}"}
```

```json
{"ANTHROPIC_API_KEY":"sk-ant-...", "DA_PINATA_JWT":"eyJ...", "DA_PINATA_GATEWAY":"https://my-gateway.mypinata.cloud"}
```

The `encodeAbiParameters` examples below build the input passed through your deployed sovereign consumer.

**Example: HuggingFace-backed conversation memory + artifacts**

```typescript
// Envelope fields (executor, sponsor, ttl 500n, phase2Ttl, mandatory callback config)
// are set on AGENT_ENVELOPE_ABI / AgentProtocolConfig as shown in the Raw Request ABI section.
const executorPayload = encodeAbiParameters(SOVEREIGN_PAYLOAD_V1_ABI, [
  1, [secretOwner], [`0x${Buffer.from(encryptedSecret).toString('hex')}`], [secretSignature], '0x',
  CLIType.CRUSH, 'What did we talk about last time?',

  ['hf', 'my-org/agent-workspace/sessions/session.jsonl', 'HF_TOKEN'],  // convoHistory
  ['hf', 'my-org/agent-workspace/artifacts/', 'HF_TOKEN'],              // output
  [],                                                                     // skills (empty)
  ['hf', 'my-org/agent-workspace/prompts/system.md', 'HF_TOKEN'],       // systemPrompt

  'claude-sonnet-4-5-20250929', [], 50, 8192, '',
]);
```

**Example: GCS-backed conversation memory + artifacts**

```typescript
// GCS credentials go in encryptedSecrets, wrapped in the owner-bound envelope
const secretEnvelope = JSON.stringify({
  version: 1,
  secret_owner: secretOwner, // must equal the matching secretOwners[i]
  secrets: {
    ANTHROPIC_API_KEY: 'sk-ant-...',
    GCS_CREDENTIALS: JSON.stringify({
      service_account_json: '{"type":"service_account","project_id":"my-project",...}',
      bucket: 'my-ritual-da-bucket',
    }),
  },
});

const executorPayload = encodeAbiParameters(SOVEREIGN_PAYLOAD_V1_ABI, [
  // ... version=1, secret fields, cliType, prompt ...

  ['gcs', 'sovereign-agent/convo_history.jsonl', 'GCS_CREDENTIALS'],  // convoHistory
  ['gcs', 'sovereign-agent/artifacts/', 'GCS_CREDENTIALS'],           // output
  [],                                                                   // skills
  ['', '', ''],                                                         // systemPrompt

  'claude-sonnet-4-5-20250929', [], 50, 8192, '',
]);
```

**Example: Pinata-backed conversation memory (CID chaining)**

```typescript
// First call — empty paths, CIDs returned in Phase 2 response
const firstCallPayload = encodeAbiParameters(SOVEREIGN_PAYLOAD_V1_ABI, [
  // ... version=1, secret fields, cliType, prompt ...

  ['pinata', '', 'DA_PINATA_JWT'],          // convoHistory — empty for first call
  ['pinata', '', 'DA_PINATA_JWT'],          // output — empty for first call
  [],                                        // skills
  ['', '', ''],                              // systemPrompt

  'claude-sonnet-4-5-20250929', [], 50, 8192, '',
]);

// Phase 2 response includes:
//   updatedConvoHistory = { platform: 'pinata', path: 'QmXyz...abc' }
//   updatedOutput       = { platform: 'pinata', path: 'QmDef...123' }

// Second call — pass the CIDs from the first response
const secondCallPayload = encodeAbiParameters(SOVEREIGN_PAYLOAD_V1_ABI, [
  // ... version=1, secret fields, cliType, prompt ...

  ['pinata', 'QmXyz...abc', 'DA_PINATA_JWT'],   // convoHistory — CID from first call
  ['pinata', 'QmDef...123', 'DA_PINATA_JWT'],   // output — manifest CID from first call
  [],
  ['', '', ''],

  'claude-sonnet-4-5-20250929', [], 50, 8192, '',
]);
```

With these configurations, the agent remembers prior conversations and accumulates artifacts across calls.

**How conversation memory works in practice:**
1. If `convoHistory` is set, prior turns are loaded from DA.
2. The agent runs with that prior context.
3. The new turn is appended and persisted back to DA.
4. The response includes an updated conversation reference.

**How artifact persistence works in practice:**
1. If `output` is set, prior artifacts are loaded before the run.
2. The agent can read existing artifacts and create new ones.
3. Updated artifacts are persisted back to DA after the run.
4. The response includes updated artifact references.

**Container statelessness.** Each call creates a fresh container. The only state the agent sees is what the executor downloads from DA. After execution, the container is destroyed. There is no filesystem persistence between calls.

### DKMS — Agent Key Derivation & Asymmetric DA Encryption

> **DKMS DA encryption is agent-only.** Only Sovereign Agent and Persistent Agent precompiles use DKMS-derived encryption. LLM conversation history, multimodal outputs, and FHE ciphertexts are stored as plaintext on the DA provider. See `ritual-dapp-da` for the full DA architecture and DKMS details.

The executor derives agent DA encryption keys inside the TEE. Sovereign DA derivation is bound to the immediate consumer address, with owner-root index zero and the DA purpose lane. Persistent derivation uses the chain-issued `agentId` and revision, with admitted-job bootstrap and distinct runtime/DA purpose lanes. Identity ownership authorizes launch; it is not a substitute for the persistent agent-scoped DKMS namespace.

Agent DA uploads are ECIES-encrypted and decrypted inside the TEE. These DA keys differ from the registry executor key used to seal request credentials. The direct launch examples use the executor key for `encryptedSecrets`; no preliminary DKMS precompile transaction is required.

### Encrypted Inputs — Encrypting Skills & System Prompt to the Agent

Skills and system prompt content can be ECIES-encrypted to the agent's DA public key. This keeps agent instructions private — only the TEE can read them.

**How it works:**
1. Obtain the correct agent-scoped DA public key through a supported key-discovery flow; do not substitute the executor key or an owner-root key for a persistent DA key. The minimal launch examples do not require encrypted input files.
2. ECIES-encrypt the skill/system prompt content with that public key
3. Upload the ciphertext to HF/GCS/Pinata
4. Set `keyRef` to `dkms_encrypted:<credential>` on the StorageRef

The `dkms_encrypted:` prefix tells the executor: "this content is ECIES-encrypted with the agent's DA key — decrypt it after download." The part after `dkms_encrypted:` is the credential name for storage authentication.

```typescript
// Encrypt a system prompt to the agent's DA public key
const systemPromptContent = Buffer.from('You are a DeFi portfolio agent...');
const encrypted = encrypt(agentDAPublicKey.slice(2), systemPromptContent);
// Upload `encrypted` to HF, then reference with dkms_encrypted: prefix:
const systemPrompt: StorageRef = ['hf', 'my-org/workspace/system.encrypted.md', 'dkms_encrypted:HF_TOKEN'];
```

> **Two different encryption targets.** `encryptedSecrets` (payload field 2, `bytes[]`) is encrypted to the **executor's** public key (from `TEEServiceRegistry.node.executorSecretsAuthPublicKey`). `dkms_encrypted:` content is encrypted to the **agent's** purpose-specific DA public key. These are different keys for different purposes: the executor key protects API keys in transit, the agent key protects agent state at rest.

### Private Prompt — Encrypting the Prompt On-Chain

The `prompt` field (payload index 6) is a plaintext string in the on-chain calldata — anyone can read it. To keep the prompt private, use the **template replacement pattern**:

1. Put the real prompt in `encryptedSecrets` under a placeholder key (e.g., `PRIVATE_PROMPT`)
2. Set the on-chain `prompt` field to the placeholder string
3. The executor decrypts the secrets, finds the placeholder in the prompt, and replaces it with the decrypted value

```typescript
// The real prompt goes into encrypted secrets, wrapped in the owner-bound envelope
const secretEnvelope = JSON.stringify({
  version: 1,
  secret_owner: secretOwner, // must equal the matching secretOwners[i]
  secrets: {
    ANTHROPIC_API_KEY: 'sk-ant-...',
    PRIVATE_PROMPT: 'Analyze my DeFi positions and suggest optimizations for maximum yield',
  },
});
const encryptedSecret = encrypt(executorPublicKey.slice(2), Buffer.from(secretEnvelope));

// The on-chain prompt is just the placeholder — visible to everyone but meaningless
const prompt = 'PRIVATE_PROMPT';
```

The executor does `prompt.replaceAll("PRIVATE_PROMPT", decryptedSecrets["PRIVATE_PROMPT"])` before running the agent. Any key in `encryptedSecrets` that appears as a substring in the prompt is replaced. Multiple placeholders are supported.

> **Encrypted to the executor, not the agent.** The private prompt is in `encryptedSecrets`, which is ECIES-encrypted to the **executor's** public key (from `TEEServiceRegistry.node.executorSecretsAuthPublicKey`). This is different from `dkms_encrypted:` content which is encrypted to the agent's DA key.

### Phase 2 Response

```typescript
const [success, error, textResponse, updatedConvo, updatedOutput, artifacts] =
  decodeAbiParameters(
    parseAbiParameters(
      'bool, string, string, (string,string,string), (string,string,string), (string,string,string)[]'
    ),
    responseData,
  );
```

```
Index  Field               Type                      Description
─────  ─────────────────── ───────────────────────── ──────────────────────────
0      success             bool                       Whether execution succeeded
1      error               string                     Error message if failed
2      textResponse        string                     Agent's text output
3      updatedConvoHistory (string,string,string)     Updated conversation StorageRef
4      updatedOutput       (string,string,string)     Updated output StorageRef
5      artifacts           (string,string,string)[]   Output artifact StorageRefs
```

### Delivery Callback & Events

```solidity
// Implement in your contract:
address constant ASYNC_DELIVERY = 0x508f57AE70967Da28AE0Ab6b95532878c4D0F440;

function onSovereignAgentResult(bytes32 jobId, bytes calldata result) external {
    require(msg.sender == ASYNC_DELIVERY, "unauthorized callback sender");
    // jobId = tx hash of your Phase 1 callSovereignAgent transaction
    // result = ABI-encoded response (decode with the schema above)
}

// Compute the selector:
// bytes4(keccak256("onSovereignAgentResult(bytes32,bytes)")) == 0x8ca12055
```

```typescript
// Delivery selector in viem:
const deliverySelector = toFunctionSelector('onSovereignAgentResult(bytes32,bytes)');
// => '0x8ca12055'
```

Event emitted by your contract (define it yourself):
```solidity
event SovereignAgentResultDelivered(bytes32 indexed jobId, bytes result);
```

---

## 4. Common Agent Patterns

### Persistent Agent with Memory

An agent that remembers previous interactions and builds context over time.

Encode the following canonical flat 13-field `AgentAsyncEnvelope` and 21-field payload as the `input` argument to `PersistentAgentConsumer.callPersistentAgent(agentId, revision, input)`. Canonical byte-exact encoding is enforced; tuple-wrapped or noncanonical encodings are rejected.

```typescript
import { encodeAbiParameters, parseAbiParameters, keccak256, toFunctionSelector } from 'viem';

const LLMProvider = { ANTHROPIC: 0, OPENAI: 1, GEMINI: 2, XAI: 3, OPENROUTER: 4 } as const;

// See the Raw Request ABI section for PERSISTENT_PAYLOAD_V1_ABI (21 fields) and
// AGENT_ENVELOPE_ABI (13 fields).

// Pin a registry-eligible executor under deployment policy (Persistent Agent Preflight #6).
// signature binds to the executor, so selection must precede sealing secrets.
const executorAddress = '0x...eligiblePinnedExecutor';
// sponsor: the funded EOA, with RitualWallet allowance to the consumer.
const sponsorAddress = '0x...sponsorEOA';
const consumerAddress = '0x...deployedConsumer';

const revision = 0n;
const executorPayload = encodeAbiParameters(PERSISTENT_PAYLOAD_V1_ABI, [
  1, [], [], [], '0x',                                      // version=1, secret fields

  LLMProvider.ANTHROPIC,
  'claude-sonnet-4-5-20250929',
  'ANTHROPIC_API_KEY',                                      // llmApiKeyRef in encrypted_secrets

  // Storage references (platform, path, keyRef)
  ['hf', 'my-org/portfolio-agent', 'HF_TOKEN'],               // daConfig — DA workspace ROOT (bare HF repo ID); never a fixed manifest.json — manifests get unique immutable per-snapshot paths and a mutable manifest.json is never a chain/revival reference
  ['hf', 'my-org/portfolio-agent/SOUL.md', 'HF_TOKEN'],       // soulRef
  ['', '', ''],                                                 // agentsRef
  ['', '', ''],                                                 // userRef
  ['hf', 'my-org/portfolio-agent/MEMORY.md', 'HF_TOKEN'],     // memoryRef
  ['hf', 'my-org/portfolio-agent/IDENTITY.md', 'HF_TOKEN'],   // identityRef
  ['hf', 'my-org/portfolio-agent/TOOLS.md', 'HF_TOKEN'],      // toolsRef
  ['', '', ''],                                                 // openclawConfigRef

  '',                                                           // restoreFromCid (launch-only)
  `{"ritual":"${process.env.RITUAL_RPC_URL}"}`,                 // rpcUrls — JSON-encoded; the agent container uses this to reach the chain
  2,                                                            // agentRuntime — HERMES (2), the default and most-supported runtime (0 = ZeroClaw alternative)
  agentId,                                                      // agentId (uint256) — chain-issued, MUST be non-zero; pre-allocated in a prior committed tx
  revision,                                                     // revision (uint64)
]);

const applicationContext = keccak256(
  encodeAbiParameters(parseAbiParameters('uint256, uint64'), [agentId, revision]),
);

const persistentInput = encodeAbiParameters(AGENT_ENVELOPE_ABI, [
  executorAddress, sponsorAddress,
  300n,                 // ttl
  6000n,                // phase2Ttl (~35 min; matches the chain's revival constant)
  true,                 // callbacks required by this consumer
  consumerAddress, toFunctionSelector('onPersistentAgentResult(bytes32,bytes)'),
  3_000_000n, 1_000_000_000n, 100_000_000n, 0n,
  applicationContext,   // = keccak256(abi.encode(agentId, revision))
  executorPayload,
]);
```

---

## 5. Multi-Agent Orchestration

The async transaction pool enforces **one pending async job per sender address**. You cannot submit a second agent call from the same wallet while the first is in flight.

**For sequential operations (same wallet):** Wait for Phase 1 completion before submitting the next call. Once Phase 1 settles, the sender slot is freed and a new async transaction can be submitted.

**For concurrent agents:** Use separate wallet addresses for each concurrent agent call. Each wallet can independently have one pending job.

This is a protocol-level constraint enforced by `AsyncJobTracker.hasPendingJobForTxOrigin()`.

---

## 6. Combining Agents with Other Precompiles

An agent can call an HTTP tool whose dApp-side request uses RITHTTP1, but do not conflate the formats. Agent `StorageRef`/DKMS fields remain agent protocol state; RITHTTP1 refs exist only inside the `body` of HTTP `0x0801` or long HTTP `0x0805`. Use RITHTTP1 for large JSON tool arguments, post-hydration API secrets, response artifact fan-out, held tool responses, or selected SSE, and keep agent lifecycle/memory in the agent protocol. See [`../ritual-dapp-http/references/rithttp1.md`](../ritual-dapp-http/references/rithttp1.md).

### Agent + Scheduler: Recurring Sovereign-Agent Tasks

For recurring work, schedule calls to your own consumer and explicitly implement authorization, secret delegation, fee sponsorship, callback correlation, and retry policy. The single-invocation examples do not create or manage recurring schedules.

### Agent + Secrets: Authenticated Tool Access

Pass encrypted API keys so the agent can authenticate with external services. Follow `ritual-dapp-secrets` for the complete ECIES encryption workflow.

```typescript
import { createPublicClient, http, defineChain, encodeAbiParameters, parseAbiParameters } from 'viem';
import { encrypt, ECIES_CONFIG } from 'eciesjs';

ECIES_CONFIG.symmetricNonceLength = 12; // see ritual-dapp-secrets

const ritualChain = defineChain({
  id: 784,
  name: 'Ritual',
  nativeCurrency: { name: 'RITUAL', symbol: 'RITUAL', decimals: 18 },
  rpcUrls: { default: { http: [process.env.RITUAL_RPC_URL!] } },
});
const publicClient = createPublicClient({ chain: ritualChain, transport: http() });

const TEE_SERVICE_REGISTRY = '0xf4495DC72143D44A93AB0ecE4d6D63a216b27839' as const;
const CAPABILITY_HTTP_CALL = 0;

// Get executor's public key from on-chain registry
const services = await publicClient.readContract({
  address: TEE_SERVICE_REGISTRY,
  abi: [{
    name: 'getServicesByCapability',
    type: 'function',
    stateMutability: 'view',
    inputs: [{ name: 'capability', type: 'uint8' }, { name: 'checkValidity', type: 'bool' }],
    outputs: [{
      name: '',
      type: 'tuple[]',
      components: [
        { name: 'node', type: 'tuple', components: [
          { name: 'paymentAddress', type: 'address' },
          { name: 'teeAddress', type: 'address' },
          { name: 'teeType', type: 'uint8' },
          { name: 'executorSecretsAuthPublicKey', type: 'bytes' },
          { name: 'endpoint', type: 'string' },
          { name: 'mTlsSpkiHash', type: 'bytes32' },
          { name: 'capability', type: 'uint8' },
        ]},
        { name: 'isValid', type: 'bool' },
        { name: 'workloadId', type: 'bytes32' },
      ],
    }],
  }] as const,
  functionName: 'getServicesByCapability',
  args: [CAPABILITY_HTTP_CALL, true],
});

// Apply mode-specific eligibility and PIN before sealing secrets. For persistent
// apps require valid HTTP_CALL, a secrets key and deployment allowlist/exclusions.
const executor = pickEligibleExecutor(services); // implement policy; never take services[0] blindly
const executorPubKey = executor.node.executorSecretsAuthPublicKey as `0x${string}`;

// Encrypt secrets with executor's public key using ECIES.
// Each blob is an owner-bound envelope; the three base arrays stay parallel.
const secretOwner = secretOwnerAddress; // checksummed owner that signs the authorization payload
const secretEnvelope = JSON.stringify({
  version: 1,
  secret_owner: secretOwner,
  secrets: {
    ANTHROPIC_API_KEY: process.env.ANTHROPIC_KEY!,
    HF_TOKEN: process.env.HF_TOKEN!,
  },
});
const secretOwners = [secretOwner];
const encryptedSecrets = [
  `0x${Buffer.from(encrypt(executorPubKey.slice(2), Buffer.from(secretEnvelope))).toString('hex')}` as `0x${string}`,
];
const secretSignatures = [secretSignature]; // owner sig over the precompile use_context authorization payload

// Use encryptedSecrets in your Persistent Agent or Sovereign Agent encoding
```

---

## 7. Executor Selection for Agent Precompiles

Both agent precompiles use HTTP_CALL capability (0) for executor selection:

```typescript
import { createPublicClient, http, defineChain } from 'viem';

const ritualChain = defineChain({
  id: 784,
  name: 'Ritual',
  nativeCurrency: { name: 'RITUAL', symbol: 'RITUAL', decimals: 18 },
  rpcUrls: { default: { http: [process.env.RITUAL_RPC_URL!] } },
});
const publicClient = createPublicClient({ chain: ritualChain, transport: http() });

const TEE_SERVICE_REGISTRY = '0xf4495DC72143D44A93AB0ecE4d6D63a216b27839' as const;
const CAPABILITY_HTTP_CALL = 0;

const services = await publicClient.readContract({
  address: TEE_SERVICE_REGISTRY,
  abi: [{
    name: 'getServicesByCapability',
    type: 'function',
    stateMutability: 'view',
    inputs: [{ name: 'capability', type: 'uint8' }, { name: 'checkValidity', type: 'bool' }],
    outputs: [{
      name: '',
      type: 'tuple[]',
      components: [
        { name: 'node', type: 'tuple', components: [
          { name: 'paymentAddress', type: 'address' },
          { name: 'teeAddress', type: 'address' },
          { name: 'teeType', type: 'uint8' },
          { name: 'executorSecretsAuthPublicKey', type: 'bytes' },
          { name: 'endpoint', type: 'string' },
          { name: 'mTlsSpkiHash', type: 'bytes32' },
          { name: 'capability', type: 'uint8' },
        ]},
        { name: 'isValid', type: 'bool' },
        { name: 'workloadId', type: 'bytes32' },
      ],
    }],
  }] as const,
  functionName: 'getServicesByCapability',
  args: [CAPABILITY_HTTP_CALL, true],
});

// Apply mode-specific eligibility and PIN before sealing secrets. For persistent
// apps require valid HTTP_CALL, a secrets key and deployment allowlist/exclusions.
const executor = pickEligibleExecutor(services); // implement policy; never take services[0] blindly
// Use executor.node.teeAddress as the executor field
// Use executor.node.executorSecretsAuthPublicKey to encrypt secrets with ECIES
```

### Checking Executor Health

Pin an eligible executor before sealing secrets. The following is a registry query sketch, not a production selector. Persistent application selection must additionally check encryption keys and deployment allowlist/exclusions (Preflight #6). Operator health probes are separate diagnostics and do not require making private executor endpoints public:

```typescript
import type { PublicClient } from 'viem';

const TEE_SERVICE_REGISTRY = '0xf4495DC72143D44A93AB0ecE4d6D63a216b27839' as const;

const teeServiceRegistryAbi = [{
  name: 'getServicesByCapability',
  type: 'function',
  stateMutability: 'view',
  inputs: [{ name: 'capability', type: 'uint8' }, { name: 'checkValidity', type: 'bool' }],
  outputs: [{
    name: '',
    type: 'tuple[]',
    components: [
      { name: 'node', type: 'tuple', components: [
        { name: 'paymentAddress', type: 'address' },
        { name: 'teeAddress', type: 'address' },
        { name: 'teeType', type: 'uint8' },
        { name: 'executorSecretsAuthPublicKey', type: 'bytes' },
        { name: 'endpoint', type: 'string' },
        { name: 'mTlsSpkiHash', type: 'bytes32' },
        { name: 'capability', type: 'uint8' },
      ]},
      { name: 'isValid', type: 'bool' },
      { name: 'workloadId', type: 'bytes32' },
    ],
  }],
}] as const;

async function findRegisteredExecutor(
  publicClient: PublicClient,
  capability: number,
) {
  const services = await publicClient.readContract({
    address: TEE_SERVICE_REGISTRY,
    abi: teeServiceRegistryAbi,
    functionName: 'getServicesByCapability',
    args: [capability, true],
  });

  for (const service of services) {
    if (service.isValid) { // registry validity only (attestation not expired) — NOT a health check
      return service;
    }
  }
  return null;
}

const CAPABILITY_HTTP_CALL = 0;
const executor = await findRegisteredExecutor(publicClient, CAPABILITY_HTTP_CALL);
if (!executor) {
  throw new Error('No registered executor available for agent calls');
}
```

`isValid` is not a capacity guarantee. Sovereign examples use the health gate below. For persistent applications, public reachability is not an eligibility requirement; an operator with authorized endpoint access can use these diagnostics:

- **Sovereign (`0x080C`)**: `handlers["0x…080C"]` is present and its payload status is `ok`/`healthy`.
- **Persistent (`0x0820`)**: `handlers["0x…0820"]` is present, with `claw_spawner.payload.status == "healthy"` (there is **no** `PERSISTENT_AGENT` registry capability — executors register `HTTP_CALL`; consult deployment admission policy and runtime results); identity slots satisfy `10 − max(capacity.live_agent_ids, capacity.distinct_reserved_slots) ≥ 1`; memory slots satisfy `(capacity.limit_budget_bytes − capacity.effective_limit_bytes) // capacity.startup_limit_bytes ≥ 1`; and `capacity.accounting_available == true`.

If a spawn later fails with `CAPACITY_EXCEEDED` (HTTP 409, `retryable=false`), **switch executors — never retry the same one**; the rejection means that executor's admission budget is full for your request.

---

## Quick Reference

### Persistent Agent (0x0820) Suggested Starting Values

| Field | Default |
|-------|---------|
| `phase2Ttl` | `6000` (~35 min at ~350ms blocks; matches the chain's revival constant; was `maxSpawnBlock`) |
| `callbackEnabled` + callback fields | **callbacks enabled in the example consumer**; callback-free protocol revival uses all-zero callback fields. Liveness rides AgentHeartbeat. All-or-nothing rule: if you set a non-zero `callbackTarget` you must set selector/gas/fee fields yourself; non-zero gas/fee fields with a zero target are invalid. |
| `provider` | `ANTHROPIC` (0) in example scripts |
| `model` | Set explicitly to exact provider model id (no protocol default) |
| `agentRuntime` | `HERMES` (2) — the most-supported runtime; ZeroClaw (0) as the alternative |

### Sovereign Agent (0x080C) Suggested Starting Values

| Field | Default |
|-------|---------|
| `phase2Ttl` | `6000` — Phase 2 deadline offset in blocks |
| `callbackGasLimit` | `3,000,000` (callbacks are MANDATORY for sovereign — `callbackEnabled: true`, `callbackTarget` = consumer) |
| `callbackMaxFeePerGas` | `1,000,000,000` (1 gwei) |
| `callbackMaxPriorityFeePerGas` | `100,000,000` (0.1 gwei) |
| `cliType` | `CRUSH` (5) — recommended for multi-provider |
| `model` | Set explicitly to exact provider model id (no protocol default) |
| `maxTurns` | `50` |
| `maxTokens` | `8192` |
| `ttl` | `500` blocks |

Before submitting, verify your chosen model exists for the selected provider and key scope (provider-side model preflight), then pass that exact model identifier in the request.

### Sovereign Agent Provider × Harness Matrix

| Provider | Claude Code (0) | Crush (5) | ZeroClaw (6) |
|----------|:---:|:---:|:---:|
| Anthropic (`claude-sonnet-4-5-20250929`, etc.) | ✅ | ✅ | ✅ |
| OpenAI (`gpt-4o-mini`, etc.) | ❌ | ✅ | ✅ |
| Gemini (`gemini-2.5-flash`, etc.) | ❌ | ✅ | ✅ |
| OpenRouter (`anthropic/claude-3.5-sonnet`, etc.) | ❌ | ✅ | ✅ |
| Ritual (`{"LLM_PROVIDER":"ritual"}`) | ❌ | ✅ | ✅ |

Set provider via `"LLM_PROVIDER"` in encrypted secrets. For Ritual: `{"LLM_PROVIDER":"ritual"}` (no API key needed).
Ritual provider is sovereign-only and is unavailable in the Persistent Agent provider enum.

### Import Summary

```typescript
import {
  encodeAbiParameters,
  decodeAbiParameters,
  parseAbiParameters,
  toFunctionSelector,
  createPublicClient,
  createWalletClient,
  defineChain,
  http,
} from 'viem';
import { privateKeyToAccount } from 'viem/accounts';
import { encrypt, ECIES_CONFIG } from 'eciesjs';

ECIES_CONFIG.symmetricNonceLength = 12; // see ritual-dapp-secrets

const LLMProvider = { ANTHROPIC: 0, OPENAI: 1, GEMINI: 2, XAI: 3, OPENROUTER: 4 } as const;
const CLIType = { CLAUDE_CODE: 0, CRUSH: 5, ZEROCLAW: 6 } as const;
```

### System Contract Addresses

For canonical system-contract addresses, ABI surfaces, and callback security patterns, see `ritual-dapp-contracts`.

| Contract | Address |
|----------|---------|
| TEEServiceRegistry | `0xf4495DC72143D44A93AB0ecE4d6D63a216b27839` |
| RitualWallet | `0xF04076756d8129Baec46Dc0F1c526Baec490C393` |
| AsyncJobTracker | `0xf00385449fD961925A0B125F5f30b29B682D4bFb` |
| AsyncDelivery | `0x508f57AE70967Da28AE0Ab6b95532878c4D0F440` |
| Scheduler | `0x4E0abeE2233D73E66382b45244F7459B34E1490E` |
| AgentHeartbeat | `0xDeeA4Df0C958966ED75570a05430BB0D4844a8cc` |
| AgentIdentityRegistry | `0x2cbF50F833a3AEfb5c5B27068052cB5585F5c087` |
| SecretsAccessControl | `0x0cEae62e2082829226eF5821Bb662483Db17A71F` |
| Sovereign Agent Precompile | `0x000000000000000000000000000000000000080C` |

### Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `cipher: message authentication failed` | ECIES nonce length mismatch | See `ritual-dapp-secrets` — nonce must be 12, not the library default of 16. |
| Commitment mined, `hasPendingJobForTxOrigin` = true, but Phase 1 never settles. No errors anywhere. | ECIES encryption config wrong (nonce length or cipher). Executor cannot decrypt and silently drops the job. | Fix encryption per `ritual-dapp-secrets`. Use a fresh sender address to unblock. See "Debugging Silent Failures" below. |
| Tx accepted but never mined (silent drop) | Sender has a pending async job | Wait for previous job to complete or use a different sender address. Check: `AsyncJobTracker.hasPendingJobForTxOrigin(txOrigin)` |
| `insufficient wallet balance` | RitualWallet not funded (sponsor `availableBalance` < required reserve) | Deposit RITUAL: `RitualWallet.deposit{value: X}()`. For a sponsored child payer, the sponsor must also `approve(caller, amount)` so `allowance(sponsor, caller) >= reserve` (otherwise `Insufficient wallet allowance`). |
| `invalid async payload` / `agent envelope is not canonical ABI encoding` / `sovereign agent payload is not canonical ABI encoding` | ABI encoding mismatch | Verify StorageRef uses `(string,string,string)` not `(string,string,bytes)`. The decoders enforce the flat **13-field AgentAsyncEnvelope** with **byte-exact canonical re-encoding** (re-encode must equal input — trailing or short bytes rejected), strict callback all-or-nothing validation, and an exact **16-field sovereign V1 payload** count (`expected 16 sovereign agent V1 payload fields`, `version` must be 1). `encryptedSecrets` must be `bytes[]` with parallel `secretOwners`/`secretSignature` arrays of **equal length** (all three empty together when no secrets). The old shaped 26-field sovereign / 29-field persistent layouts are rejected. |
| Phase 2 never arrives (persistent agent armed, but no container / no heartbeat) | **Most common: the spawn was committed to an executor that doesn't run the `0x0820` handler** (a random HTTP-capable executor is not necessarily persistent-capable). Also: executor unreachable, TTL expired, or the spawn actually **failed and the failure delivery was shed** — saturated executors shed failure deliveries, so a failed spawn can present as a pure TTL timeout with nothing on-chain. | **First**, confirm you pinned a persistent executor whose `/health` shows `handlers["0x…0820"]` with `claw_spawner.payload.status=="healthy"` (preflight #6) — registry presence alone is a trap. Then check executor reachability/logs and increase `ttl`. Do not assume "chain/executor down" until you've verified the executor and ruled out a shed failure delivery. |
| Commitment mined, but the job **never settles** at all (no `JobAdded` settlement, no errorMessage, origin stays locked) | Phase-1 failure family A: **authz/decode failure → job dropped** (`Success:false`). The executor rejected authorization (agentId operator, secrets delegation) or could not decode the request; nothing settles on-chain. | Fix authorization (`setAgentOperator`, `grantAccess` to the child contract) and payload encoding. Contrast with the settled-with-error family below — "no Phase 2" alone doesn't identify which happened. |
| Job **settled WITH an error string** (`Success:true` + `errorMessage`, Phase-1 fee charged, no container) | Phase-1 failure family B: **secrets/DKMS/DA errors settle with an error** rather than dropping. Includes multiple distinct secret owners — all `encrypted_secrets` blobs must share exactly **ONE** owner. | Read the `errorMessage`; fix the secrets bundle (single owner, correct ECIES target), DKMS derivation, or DA credentials. The Phase-1 fee is spent either way — preflight before retrying. A sovereign runtime crash settles with the fixed `errorMessage` `diagnostic output withheld (stdout=N bytes, stderr=M bytes)` — the executor never forwards the agent process output; pull the executor/container logs to see it. |
| Phase 1 settled, then the launch dies ~2 minutes later with `PRELAUNCH_FUNDING_FAILED` | Prelaunch primary wallet (Phase-1 response index 5, `gatewayToken`) was not funded **≥ 0.01 RIT within the 120 s window** (executor polls every 1 s). | Non-retryable — the launch is dead. On the next attempt, watch for Phase-1 settlement and fund the decoded prelaunch wallet immediately. |
| Spawn rejected with `CAPACITY_EXCEEDED` (HTTP 409, `retryable=false`) | The pinned executor admission budget is full. | Reconcile the failed launch. Wait for confirmed capacity or explicitly select another eligible executor and re-seal secrets; do not repeatedly submit the same failed launch. |
| `cast send` fails with `already known` | The load-balanced RPC double-forwarded the submission — the tx IS in the pool and will mine. | Recover the hash by (sender, nonce) — see `send_tx` in `examples/persistent-agent/run.sh` — and wait for it to mine. **Never blind-resubmit**: you would race your own tx. |
| Job settles with error `signature signer does not match` | `use_context` casing mismatch in the secret-authorization preimage. | The context string must be lowercase-exact: `precompile:0x0000000000000000000000000000000000000820` (persistent) / `…081b` (DKMS). Re-sign with the exact lowercase string. |
| `NonEmptyPaddingBytes: Boolean must be either 0x0 or 0x1` | Decoding event data directly instead of unwrapping outer `bytes` | Event data is ABI-encoded `bytes`. Decode outer `bytes` first, then decode inner response tuple. |
| Empty text response from Claude Code | Claude Code version outdated in executor image | Not a client issue — executor needs updated sovereign-agent container image. |
| `sovereign_agent_type N is not currently supported` | Invalid or unsupported `cliType` value | Use 0 (ClaudeCode), 5 (Crush), or 6 (ZeroClaw). Values 1-4 are unavailable in the supported executor path. |
| `waitForTransactionReceipt` hangs after submitting an agent call | Phase 1 hasn't settled (usually because executor can't decrypt). Receipt won't appear until settlement. | Don't block on receipt for long-running async precompile txs. Use `cast send --async` or `sendTransaction` and poll for the Phase 2 event by `jobId` topic instead. |
| Agent was **ACTIVE**, then `getAssignment(agentId).revivalStatus` shows **FAILED** | The agent's own runtime crashed after starting — commonly a channel/config force-enabled that the container can't handle, or **unescaped LLM output** breaking a JSON body the agent POSTs. | Pull the executor/container logs; JSON-encode & validate all model output before using it in a request; fix the config. Heartbeat revives up to `MAX_REVIVAL_ATTEMPTS` (3) then removes the slot. This is an agent-code bug, not a chain issue. |

### Debugging Silent Failures

When a sovereign agent call produces a commitment (`hasPendingJobForTxOrigin` = true) but Phase 1 never settles and no error is emitted anywhere, work through this checklist in order:

1. **Check ECIES encryption config.** This is the #1 cause. See `ritual-dapp-secrets` for the mandatory nonce length and setup. A wrong nonce produces `MAC check failed` inside the TEE — but this error is never surfaced on-chain.

2. **Check you encrypted to the correct public key.** The key must be `node.executorSecretsAuthPublicKey` from `TEEServiceRegistry.getServicesByCapability()`. Not `paymentAddress`, not `teeAddress` — those are Ethereum addresses, not ECIES public keys.

3. **Check the secrets JSON format.** Must be valid JSON with the exact key names the provider expects: `{"ANTHROPIC_API_KEY":"sk-..."}`, not `{"api_key":"sk-..."}` and not a bare string.

4. **Check the pinned executor and deployment policy.** Routing uses field 0; there is no automatic fallback. Re-read registry validity, encryption key, allowlist/exclusions and the existing job result. Authorized operator diagnostics can inspect spawner/capacity; an empty registry endpoint is not a failure. Switching executor requires newly sealed secrets and an explicit new launch.

5. **Test encryption locally before submitting on-chain.** Encrypt a payload, then decrypt it with the same keypair using the other language's library (both configured per `ritual-dapp-secrets`). If local decryption fails, on-chain will fail too — and it will fail silently.

6. **Check `cast logs` on AsyncJobTracker, not `cast tx`.** The original tx hash from `sendTransaction` may not match the on-chain tx hash (the builder defers the tx and re-executes it during fulfilled replay). Your tx hash will appear as an indexed topic on the AsyncJobTracker commitment event, not as a standalone transaction.

7. **If the sender is locked and won't clear:** Generate a fresh keypair, fund it, deposit into RitualWallet, and retry. The expiry system cleans up stuck jobs eventually, but during development a fresh wallet is faster than waiting.
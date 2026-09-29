---
name: ritual-dapp-agents
description: Persistent agent and sovereign agent patterns for Ritual dApps. Use when building dApps with long-lived AI services, sovereign agent jobs, or agent-native product flows on Ritual Chain.
---

# Persistent Agent & Sovereign Agent Patterns

> **Runnable examples:**
> - `examples/sovereign-agent/` demonstrates direct precompile caller mode (`0x080C`) for one-shot sovereign jobs.
> - `examples/persistent-agent/` demonstrates direct precompile caller mode (`0x0820`) for one-shot persistent spawn.
> - This skill also documents the contract-harness factory mode (recommended in production) where child harness/launcher contracts are deployed and managed through factory contracts.

> **Before running either example — required user-supplied inputs (elicit these upfront):**
>
> Both `examples/sovereign-agent/run.sh` and `examples/persistent-agent/run.sh`
> fail fast (exit code `2`) if any required variable is unset or still contains
> an unfilled placeholder (`<…>`, `YOUR_…`). If you are an agent running these
> scripts on behalf of a user, ask the user for the following before invoking
> `bash run.sh`:
>
> - `PRIVATE_KEY` — funded 0x-prefixed key on Ritual Chain
> - `RPC_URL` — RPC endpoint (e.g. `https://rpc.ritualfoundation.org`)
> - `LLM_PROVIDER` — one of `anthropic` / `openai` / `gemini` / `openrouter` / `ritual` (the executor rejects calls where this is unset). Sovereign agents may also use `ritual`, which needs no API key.
> - Exactly one matching LLM API key (skip if `LLM_PROVIDER=ritual`): `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY` / `OPENROUTER_API_KEY`
> - `MODEL` — exact provider-routable model id (e.g. `claude-sonnet-4-5-20250929` for Anthropic, `gemini-2.5-flash` for Gemini, `zai-org/GLM-4.7-FP8` for the Ritual gateway)
> - **Sovereign agent additionally requires:** `HF_TOKEN` + `HF_REPO_ID` (a HuggingFace dataset the user owns, in `user/repo` form). The example stores convo history, artifacts, and the system prompt under this repo; there are no defaults.
> - **Persistent agent additionally requires** one DA provider configured:
>   - `DA_PROVIDER=hf` → `HF_TOKEN` + `HF_REPO_ID`
>   - `DA_PROVIDER=gcs` → `GCS_DA_SERVICE_ACCOUNT_JSON` + `GCS_DA_BUCKET` (a bucket the user owns)
>   - `DA_PROVIDER=pinata` → `DA_PINATA_JWT`
>
> Do not guess or fill in placeholder values for any of these. Ask the user.

> **Scope note:** This skill focuses on the two agent primitives most builders will use directly: Persistent Agent (`0x0820`) and Sovereign Agent (`0x080C`).

Ritual Chain provides two enshrined agent primitives for on-chain AI execution:

| Precompile | Address | Purpose |
|------------|---------|---------|
| Persistent Agent | `0x0820` | Long-lived, monitored, revivable agent instance with identity, memory, and DA-backed continuity |
| Sovereign Agent | `0x080C` | High-powered async agent job with skills, tools, convo history, and artifact outputs |

Both follow the async executor pattern: submit a request on-chain, an executor picks it up, runs the agent in a TEE, and delivers the result via callback. Phase 1 of the transaction settles synchronously — the caller's original transaction receives the job identifier as the precompile output. Phase 2 delivers the final result asynchronously via callback once the executor completes.

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

## Factory-First Agent Deployment (Recommended)

Ritual agent deployment now has two distinct operation modes. Do not mix them conceptually:

| Mode | What you control | Contract surface | Best use |
|------|------------------|------------------|----------|
| Direct precompile caller | A consumer contract/EOA that calls precompile directly | `0x080C` (sovereign), `0x0820` (persistent) | Fast prototyping, ABI debugging, minimal demos |
| Factory-backed contract harness | A deterministic child contract per agent workflow | `SovereignAgentFactory -> SovereignAgentHarness`, `PersistentAgentFactory -> PersistentAgentLauncher` | Production launches, recoverable lifecycle control, deterministic ownership/context |

The key terminology distinction:

- **Contract harness/launcher** (deployment primitive): on-chain child contracts created by factories.
- **Agent/tool harness** (runtime primitive): the in-container CLI/tooling runtime (`cliType`, tools policy, model/provider).

When this skill says "factory-backed", it means **contract harness/launcher mode**.

### Where The Factory Contracts Are

Factory contracts are chain contracts. Keep them in your app config and verify at startup.

Known addresses:

```bash
RPC_URL=https://rpc.ritualfoundation.org
SOVEREIGN_FACTORY_ADDRESS=0x9dC4C054e53bCc4Ce0A0Ff09E890A7a8e817f304
PERSISTENT_FACTORY_ADDRESS=0xD4AA9D55215dc8149Af57605e70921Ea16b73591
```

Verify both addresses are real contracts before any launch:

```bash
cast code "0x9dC4C054e53bCc4Ce0A0Ff09E890A7a8e817f304" --rpc-url "$RPC_URL"
cast code "0xD4AA9D55215dc8149Af57605e70921Ea16b73591" --rpc-url "$RPC_URL"
```

The result must not be `0x`.

### Factory Wiring Preflight

Verify factory wiring to core system contracts:

```bash
# Sovereign factory wiring
cast call "$SOVEREIGN_FACTORY_ADDRESS" "scheduler()(address)" --rpc-url "$RPC_URL"
cast call "$SOVEREIGN_FACTORY_ADDRESS" "ritualWallet()(address)" --rpc-url "$RPC_URL"
cast call "$SOVEREIGN_FACTORY_ADDRESS" "teeRegistry()(address)" --rpc-url "$RPC_URL"
cast call "$SOVEREIGN_FACTORY_ADDRESS" "asyncDelivery()(address)" --rpc-url "$RPC_URL"

# Persistent factory wiring
cast call "$PERSISTENT_FACTORY_ADDRESS" "scheduler()(address)" --rpc-url "$RPC_URL"
cast call "$PERSISTENT_FACTORY_ADDRESS" "ritualWallet()(address)" --rpc-url "$RPC_URL"
cast call "$PERSISTENT_FACTORY_ADDRESS" "asyncDelivery()(address)" --rpc-url "$RPC_URL"
```

### Deterministic Child Address + DKMS Context

Both factories deterministically derive child contracts from `(owner, userSalt)`. Always predict first, then launch.

```bash
# `USER_SALT` is bytes32 (example: cast keccak "my-agent-1")
USER_SALT=$(cast keccak "my-agent-1")
OWNER=0xYourEOAOrController

cast call "$SOVEREIGN_FACTORY_ADDRESS" \
  "predictHarness(address,bytes32)(address,bytes32)" \
  "$OWNER" "$USER_SALT" \
  --rpc-url "$RPC_URL"

cast call "$PERSISTENT_FACTORY_ADDRESS" \
  "predictLauncher(address,bytes32)(address,bytes32)" \
  "$OWNER" "$USER_SALT" \
  --rpc-url "$RPC_URL"

cast call "$SOVEREIGN_FACTORY_ADDRESS" \
  "getDkmsDerivation(address,bytes32)(address,uint256,uint8)" \
  "$OWNER" "$USER_SALT" \
  --rpc-url "$RPC_URL"

cast call "$PERSISTENT_FACTORY_ADDRESS" \
  "getDkmsDerivation(address,bytes32)(address,uint256,uint8)" \
  "$OWNER" "$USER_SALT" \
  --rpc-url "$RPC_URL"
```

Builder rule: in both sovereign and persistent payloads, `deliveryTarget` must be the predicted child contract (harness/launcher), not the factory.

### Sovereign Factory Configuration Surface

`SovereignAgentFactory` supports a two-step child flow and compressed one-shot flow.

**Two-step (recommended for observability/control):**
1. `deployHarness(userSalt)`
2. `SovereignAgentHarness.configureFundAndStart(params, schedule, rolling, lockDuration)`

**Compressed (single tx):**
- `launchSovereignCompressed(...)`
- `launchSovereignWithDerivedDkms(...)`

All sovereign factory launch config:

| Group | Field | Type | Notes |
|------|-------|------|------|
| Identity | `userSalt` | `bytes32` | Per-agent deterministic namespace |
| DKMS | `executor` | `address` | Executor for DKMS extraction |
| DKMS | `dkmsTtl` | `uint64` | DKMS extraction TTL |
| DKMS | `dkmsFunding` | `uint256` | Optional native funding for derived DKMS payment address |
| Payload | `params` | `SovereignAgentParams` | Full sovereign request (23-field payload) |
| Scheduler | `schedule.schedulerGas` | `uint32` | Gas for scheduled execute callback |
| Scheduler | `schedule.frequency` | `uint32` | Must be `> 0` |
| Scheduler | `schedule.schedulerTtl` | `uint32` | Scheduler TTL |
| Scheduler | `schedule.maxFeePerGas` | `uint256` | EIP-1559 max fee for scheduler |
| Scheduler | `schedule.maxPriorityFeePerGas` | `uint256` | EIP-1559 tip for scheduler |
| Scheduler | `schedule.value` | `uint256` | Native value sent during scheduled execution |
| Scheduler wallet | `schedulerLockDuration` | `uint256` | RitualWallet lock duration for child payer |
| Scheduler wallet | `schedulerFunding` | `uint256` | Native value deposited into child RitualWallet |
| Rolling mode | `windowNumCalls` | `uint32` | Required in compressed launch; must be `> 0` |
| Rolling mode | `rolling.windowNumCalls` | `uint32` | Number of calls in current rolling window |
| Rolling mode | `rolling.rolloverThresholdBps` | `uint16` | Rollover threshold in bps (1..10000) |
| Rolling mode | `rolling.rolloverRetryEveryCalls` | `uint16` | Retry cadence for successor scheduling |

`SovereignAgentHarness` currently supports wake mode:
- `NONE`
- `ROLLING_FIXED_WINDOW`

No other sovereign wake mode should be treated as active.

### Rolling Window Semantics

The rolling window controls how the harness repeatedly invokes the sovereign agent precompile. Every scheduled callback calls `0x080C` — the threshold only controls when the **next window** gets scheduled.

**How `wakeUp` works on each scheduled callback:**

1. Window promotion: if the pending successor window is now active, promote it.
2. Retired call cleanup: cancel the previous window's leftover schedule.
3. Successor scheduling: if `executionIndex >= thresholdIndex`, attempt to schedule the next window.
4. **Precompile invocation: call `0x080C` with the configured `SovereignAgentParams`. This happens on every callback.**

The threshold does NOT determine whether the precompile gets called. It determines when the harness starts scheduling the next window to ensure continuity.

**`rolloverThresholdBps` explained:** At 5000 (50%) with `windowNumCalls=5`, successor scheduling begins at call 3 of 5 (`thresholdIndex = ceil(5·5000/10000) − 1 = 2`). Higher thresholds (8000 = 80%) mean the harness waits longer before scheduling the next window, leaving fewer retry attempts if successor scheduling fails (executor down, insufficient balance, etc.). Lower thresholds (3000 = 30%) give more retry opportunities but overlap two windows longer.

**`MAX_LIFESPAN` constraint:** The Scheduler enforces `MAX_LIFESPAN = 10,000 blocks` on the recurring schedule horizon:

```
lifespan = frequency × numCalls
lifespan <= 10,000
```

This means `numCalls` is bounded by `frequency`:

```
numCalls <= 10,000 / frequency
```

`ttl` remains a separate per-execution drift/expiry window and is still capped by Scheduler `MAX_TTL`.

| `frequency` | Max `numCalls` |
|-------------|----------------|
| `2000` (default) | `5` |

**Choosing `frequency`:** Each sovereign agent invocation is an async round trip (~60-90s). Set `frequency` to cover this so the next call fires after the previous one settles. With ~350ms block time:

| `frequency` | Wall time | Notes |
|-------------|-----------|-------|
| `2000` | ~11.7 min | **Safe default.** |
| `500` | ~175s | Smaller deployments. |

**Recommended starting values:**

| Field | Value | Rationale |
|-------|-------|-----------|
| `windowNumCalls` | `5` | 5 invocations per window (~58 min from scheduling through the final slot at frequency=2000). Capped by `MAX_LIFESPAN = 10_000`: `2000·5 = 10_000`. |
| `frequency` | `2000` | ~11.7 min between calls. Safe default. |
| `rolloverThresholdBps` | `5000` | Successor scheduling starts at call 3 (index 2), giving 3 retry attempts (wakes 3, 4, 5). |
| `rolloverRetryEveryCalls` | `1` | Retry every call past threshold |
| `schedulerTtl` | `500` | Covers drift + async settlement |

### Factory Launch Preflight Checklist

Run these checks before calling `configureFundAndStart` or any compressed launch function.

1. **Factory address verified**: `cast code "$SOVEREIGN_FACTORY_ADDRESS"` returns non-empty bytecode.
2. **Factory wiring verified**: `scheduler()`, `ritualWallet()`, `teeRegistry()`, `asyncDelivery()` return correct system contract addresses.
3. **Harness address computed**: `predictHarness` (two-step) or `predictCompressedHarness` (compressed).
4. **`deliveryTarget` == predicted harness**: `SovereignAgentParams.deliveryTarget` must equal the predicted child. Mismatch reverts with `InvalidDeliveryTarget()`.
5. **Executor discovered**: `TEEServiceRegistry.getServicesByCapability(0, true)` returns at least one valid executor. Use `node.teeAddress`.
6. **Secrets encrypted correctly**: ECIES with `symmetricNonceLength = 12` to executor's `node.publicKey`. Wrong nonce = silent failure.
7. **`frequency` default 2000**: sovereign agent round trips take ~60-90s. Default **2000** is the safe starting value. `frequency=1` fires every block; sender lock blocks concurrent async jobs, causing precompile reverts.
8. **Lifespan check**: `frequency × numCalls <= 10,000` (Scheduler `MAX_LIFESPAN`). Exceeding this reverts with `ScheduleLifespanExceeded()`.
9. **`schedulerFunding` sufficient**: deposited into harness RitualWallet. Must cover `windowNumCalls` executions. Recommended: 5+ RITUAL for testing.
10. **Gas limit for `configureFundAndStart` >= 3,000,000**: uses ~2.5M gas. Default estimation fails.
11. **`model` is a valid provider-routable identifier**: verify with a direct API call before submitting on-chain.
12. **`schedulerTtl` >= async settlement time**: recommended `500`. Must be large enough for the TxScheduled replay to pass the TTL check after async settlement.
13. **LLM API key has credits**: test the key directly (e.g., `curl` Gemini/Anthropic API) before encrypting it on-chain.

### Sovereign Factory Struct Definitions

```solidity
struct SovereignAgentParams {
    address executor;
    uint256 ttl;
    bytes userPublicKey;
    uint64 pollIntervalBlocks;
    uint64 maxPollBlock;
    string taskIdMarker;
    address deliveryTarget;
    bytes4 deliverySelector;
    uint256 deliveryGasLimit;
    uint256 deliveryMaxFeePerGas;
    uint256 deliveryMaxPriorityFeePerGas;
    uint16 agentType;
    string prompt;
    bytes encryptedSecrets;
    SovereignStorageRef convoHistory;
    SovereignStorageRef output;
    SovereignStorageRef[] skills;
    SovereignStorageRef systemPrompt;
    string model;
    string[] tools;
    uint16 maxTurns;
    uint32 maxTokens;
    string rpcUrls;
}

struct SovereignStorageRef {
    string platform;
    string path;
    string keyRef;
}

struct SovereignScheduleConfig {
    uint32 schedulerGas;
    uint32 frequency;
    uint32 schedulerTtl;
    uint256 maxFeePerGas;
    uint256 maxPriorityFeePerGas;
    uint256 value;
}

struct SovereignRollingConfig {
    uint32 windowNumCalls;
    uint16 rolloverThresholdBps;
    uint16 rolloverRetryEveryCalls;
}
```

### Sovereign Factory ABI (TypeScript)

```typescript
const SOVEREIGN_FACTORY = '0x9dC4C054e53bCc4Ce0A0Ff09E890A7a8e817f304' as const;

const StorageRefTuple = {
  type: 'tuple' as const,
  components: [
    { name: 'platform', type: 'string' },
    { name: 'path', type: 'string' },
    { name: 'keyRef', type: 'string' },
  ],
};

const SovereignAgentParamsTuple = {
  name: 'params',
  type: 'tuple' as const,
  components: [
    { name: 'executor', type: 'address' },
    { name: 'ttl', type: 'uint256' },
    { name: 'userPublicKey', type: 'bytes' },
    { name: 'pollIntervalBlocks', type: 'uint64' },
    { name: 'maxPollBlock', type: 'uint64' },
    { name: 'taskIdMarker', type: 'string' },
    { name: 'deliveryTarget', type: 'address' },
    { name: 'deliverySelector', type: 'bytes4' },
    { name: 'deliveryGasLimit', type: 'uint256' },
    { name: 'deliveryMaxFeePerGas', type: 'uint256' },
    { name: 'deliveryMaxPriorityFeePerGas', type: 'uint256' },
    { name: 'cliType', type: 'uint16' },
    { name: 'prompt', type: 'string' },
    { name: 'encryptedSecrets', type: 'bytes' },
    { ...StorageRefTuple, name: 'convoHistory' },
    { ...StorageRefTuple, name: 'output' },
    { name: 'skills', type: 'tuple[]', components: StorageRefTuple.components },
    { ...StorageRefTuple, name: 'systemPrompt' },
    { name: 'model', type: 'string' },
    { name: 'tools', type: 'string[]' },
    { name: 'maxTurns', type: 'uint16' },
    { name: 'maxTokens', type: 'uint32' },
    { name: 'rpcUrls', type: 'string' },
  ],
};

const SovereignScheduleConfigTuple = {
  name: 'schedule',
  type: 'tuple' as const,
  components: [
    { name: 'schedulerGas', type: 'uint32' },
    { name: 'frequency', type: 'uint32' },
    { name: 'schedulerTtl', type: 'uint32' },
    { name: 'maxFeePerGas', type: 'uint256' },
    { name: 'maxPriorityFeePerGas', type: 'uint256' },
    { name: 'value', type: 'uint256' },
  ],
};

const SovereignRollingConfigTuple = {
  name: 'rolling',
  type: 'tuple' as const,
  components: [
    { name: 'windowNumCalls', type: 'uint32' },
    { name: 'rolloverThresholdBps', type: 'uint16' },
    { name: 'rolloverRetryEveryCalls', type: 'uint16' },
  ],
};

const sovereignFactoryAbi = [
  {
    name: 'deployHarness',
    type: 'function',
    stateMutability: 'nonpayable',
    inputs: [{ name: 'userSalt', type: 'bytes32' }],
    outputs: [{ name: 'harness', type: 'address' }],
  },
  {
    name: 'predictHarness',
    type: 'function',
    stateMutability: 'view',
    inputs: [
      { name: 'owner', type: 'address' },
      { name: 'userSalt', type: 'bytes32' },
    ],
    outputs: [
      { name: 'harness', type: 'address' },
      { name: 'childSalt', type: 'bytes32' },
    ],
  },
  {
    name: 'predictCompressedHarness',
    type: 'function',
    stateMutability: 'view',
    inputs: [
      { name: 'owner', type: 'address' },
      { name: 'userSalt', type: 'bytes32' },
    ],
    outputs: [
      { name: 'harness', type: 'address' },
      { name: 'compressedSalt', type: 'bytes32' },
      { name: 'childSalt', type: 'bytes32' },
    ],
  },
  {
    name: 'getDkmsDerivation',
    type: 'function',
    stateMutability: 'view',
    inputs: [
      { name: 'owner', type: 'address' },
      { name: 'userSalt', type: 'bytes32' },
    ],
    outputs: [
      { name: 'dkmsOwner', type: 'address' },
      { name: 'keyIndex', type: 'uint256' },
      { name: 'keyFormat', type: 'uint8' },
    ],
  },
  {
    name: 'launchSovereignCompressed',
    type: 'function',
    stateMutability: 'payable',
    inputs: [
      { name: 'userSalt', type: 'bytes32' },
      { name: 'executor', type: 'address' },
      { name: 'dkmsTtl', type: 'uint64' },
      { name: 'dkmsFunding', type: 'uint256' },
      SovereignAgentParamsTuple,
      SovereignScheduleConfigTuple,
      { name: 'schedulerLockDuration', type: 'uint256' },
      { name: 'schedulerFunding', type: 'uint256' },
      { name: 'windowNumCalls', type: 'uint32' },
    ],
    outputs: [
      { name: 'harness', type: 'address' },
      { name: 'dkmsPaymentAddress', type: 'address' },
      { name: 'schedulerCallId', type: 'uint256' },
    ],
  },
  {
    name: 'launchSovereignWithDerivedDkms',
    type: 'function',
    stateMutability: 'payable',
    inputs: [
      { name: 'userSalt', type: 'bytes32' },
      { name: 'dkmsPaymentAddress', type: 'address' },
      { name: 'dkmsFunding', type: 'uint256' },
      SovereignAgentParamsTuple,
      SovereignScheduleConfigTuple,
      { name: 'schedulerLockDuration', type: 'uint256' },
      { name: 'schedulerFunding', type: 'uint256' },
      { name: 'windowNumCalls', type: 'uint32' },
    ],
    outputs: [
      { name: 'harness', type: 'address' },
      { name: 'schedulerCallId', type: 'uint256' },
    ],
  },
] as const;

// Harness ABI (deployed by factory)
const sovereignHarnessAbi = [
  {
    name: 'configureFundAndStart',
    type: 'function',
    stateMutability: 'payable',
    inputs: [
      SovereignAgentParamsTuple,
      SovereignScheduleConfigTuple,
      SovereignRollingConfigTuple,
      { name: 'schedulerLockDuration', type: 'uint256' },
    ],
    outputs: [{ name: 'schedulerCallId', type: 'uint256' }],
  },
  {
    name: 'onSovereignAgentResult',
    type: 'function',
    stateMutability: 'nonpayable',
    inputs: [
      { name: 'jobId', type: 'bytes32' },
      { name: 'result', type: 'bytes' },
    ],
    outputs: [],
  },
  {
    name: 'owner',
    type: 'function',
    stateMutability: 'view',
    inputs: [],
    outputs: [{ type: 'address' }],
  },
  {
    name: 'configured',
    type: 'function',
    stateMutability: 'view',
    inputs: [],
    outputs: [{ type: 'bool' }],
  },
  {
    name: 'stop',
    type: 'function',
    stateMutability: 'nonpayable',
    inputs: [],
    outputs: [],
  },
  {
    name: 'restart',
    type: 'function',
    stateMutability: 'nonpayable',
    inputs: [],
    outputs: [],
  },
] as const;
```

### Sovereign Factory Function Selectors

| Selector | Function |
|----------|----------|
| `0x3293993b` | `deployHarness(bytes32)` |
| `0x78165f40` | `predictHarness(address,bytes32)` |
| `0x1b95bb00` | `predictCompressedHarness(address,bytes32)` |
| `0x08ef770d` | `getDkmsDerivation(address,bytes32)` |
| `0x2ea5a636` | `launchSovereignCompressed(...)` |
| `0x9331a9c0` | `launchSovereignWithDerivedDkms(...)` |
| `0x7c041adf` | `launchSovereignCompressedRolling(...)` |
| `0x97e1b064` | `launchSovereignWithDerivedDkmsRolling(...)` |
| `0xb1906702` | `SovereignAgentHarness.configureFundAndStart(...)` |
| `0x8ca12055` | `SovereignAgentHarness.onSovereignAgentResult(bytes32,bytes)` |

### Gas Estimates

| Function | Typical Gas | Notes |
|----------|------------|-------|
| `deployHarness(bytes32)` | ~400,000 | CREATE3 deployment |
| `configureFundAndStart(...)` | ~2,500,000 | Deposits into RitualWallet + creates schedule. **Set gas limit >= 3,000,000.** |
| `launchSovereignCompressed(...)` | ~3,500,000 | DKMS + deploy + configure in one tx. **Set gas limit >= 5,000,000.** |
| `launchSovereignWithDerivedDkms(...)` | ~3,000,000 | Deploy + configure (no DKMS). **Set gas limit >= 4,000,000.** |

Default gas estimation will fail for `configureFundAndStart` and compressed launch functions. Always set an explicit gas limit.

### Sovereign Factory Source

```solidity
// SPDX-License-Identifier: BSD-3-Clause-Clear
pragma solidity ^0.8.28;

import {Initializable} from "@openzeppelin/contracts-upgradeable/proxy/utils/Initializable.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";
import {OwnableUpgradeable} from "@openzeppelin/contracts-upgradeable/access/OwnableUpgradeable.sol";
import {ICREATE3Factory} from "./ICREATE3Factory.sol";
import {SovereignAgentHarness} from "./SovereignAgentHarness.sol";
import {SovereignAgentParams, SovereignRollingConfig, SovereignScheduleConfig} from "./SovereignAgentHarness.sol";
import {DkmsKeyResolver} from "./DkmsKeyResolver.sol";

/// @title SovereignAgentFactory
/// @notice Deterministically deploys one child harness per sovereign agent workflow.
contract SovereignAgentFactory is Initializable, UUPSUpgradeable, OwnableUpgradeable, DkmsKeyResolver {
    uint256 private constant _NOT_ENTERED = 1;
    uint256 private constant _ENTERED = 2;

    ICREATE3Factory public create3Factory;
    address public scheduler;
    address public ritualWallet;
    address public teeRegistry;
    address public asyncDelivery;

    event HarnessPredicted(address indexed owner, bytes32 indexed userSalt, bytes32 indexed childSalt, address harness);
    event HarnessDeployed(address indexed owner, bytes32 indexed userSalt, bytes32 indexed childSalt, address harness);
    event SovereignLaunchCompressed(
        address indexed owner, bytes32 indexed userSalt, address indexed harness,
        address dkmsPaymentAddress, uint32 windowNumCalls, uint16 rolloverThresholdBps,
        uint16 rolloverRetryEveryCalls, uint256 schedulerCallId
    );
    event SovereignLaunchFromDerivedDkms(
        address indexed owner, bytes32 indexed userSalt, address indexed harness,
        address dkmsPaymentAddress, uint32 windowNumCalls, uint16 rolloverThresholdBps,
        uint16 rolloverRetryEveryCalls, uint256 schedulerCallId
    );

    error HarnessAddressMismatch();
    error InvalidValue();
    error InvalidDeliveryTarget();
    error InvalidDkmsOutput();
    error DkmsFundingTransferFailed();
    error InvalidSovereignMode();
    error InvalidCreate3Factory();
    error InvalidScheduler();
    error InvalidRitualWallet();
    error InvalidTeeRegistry();
    error InvalidAsyncDelivery();
    error ReentrantCall();

    modifier nonReentrantLaunch() {
        if (_launchStatus == _ENTERED) revert ReentrantCall();
        _launchStatus = _ENTERED;
        _;
        _launchStatus = _NOT_ENTERED;
    }

    constructor() { _disableInitializers(); }

    function initialize(
        address _initialOwner, address _create3Factory, address _scheduler,
        address _ritualWallet, address _teeRegistry, address _asyncDelivery
    ) external initializer {
        if (_create3Factory == address(0)) revert InvalidCreate3Factory();
        if (_scheduler == address(0)) revert InvalidScheduler();
        if (_ritualWallet == address(0)) revert InvalidRitualWallet();
        if (_teeRegistry == address(0)) revert InvalidTeeRegistry();
        if (_asyncDelivery == address(0)) revert InvalidAsyncDelivery();
        __Ownable_init(_initialOwner);
        __UUPSUpgradeable_init();
        create3Factory = ICREATE3Factory(_create3Factory);
        scheduler = _scheduler;
        ritualWallet = _ritualWallet;
        teeRegistry = _teeRegistry;
        asyncDelivery = _asyncDelivery;
    }

    function _authorizeUpgrade(address) internal override onlyOwner {}

    function deriveChildSalt(address owner, bytes32 userSalt) public pure returns (bytes32) {
        return keccak256(abi.encode(owner, userSalt));
    }

    function predictHarness(address owner, bytes32 userSalt) public view returns (address harness, bytes32 childSalt) {
        childSalt = deriveChildSalt(owner, userSalt);
        harness = create3Factory.getDeployed(address(this), childSalt);
    }

    function predictCompressedHarness(address owner, bytes32 userSalt)
        public view returns (address harness, bytes32 compressedSalt, bytes32 childSalt)
    {
        compressedSalt = keccak256(abi.encode(owner, userSalt));
        (harness, childSalt) = predictHarness(address(this), compressedSalt);
    }

    function getDkmsDerivation(address owner, bytes32 userSalt)
        external view returns (address dkmsOwner, uint256 keyIndex, uint8 keyFormat)
    {
        (dkmsOwner,) = predictHarness(owner, userSalt);
        return (dkmsOwner, 0, 1);
    }

    function deployHarness(bytes32 userSalt) external returns (address harness) {
        bytes32 childSalt = deriveChildSalt(msg.sender, userSalt);
        harness = _deployHarness(msg.sender, userSalt);
        emit HarnessDeployed(msg.sender, userSalt, childSalt, harness);
    }

    function launchSovereignCompressed(
        bytes32 userSalt, address executor, uint64 dkmsTtl, uint256 dkmsFunding,
        SovereignAgentParams calldata params, SovereignScheduleConfig calldata schedule,
        uint256 schedulerLockDuration, uint256 schedulerFunding, uint32 windowNumCalls
    ) external payable nonReentrantLaunch
      returns (address harness, address dkmsPaymentAddress, uint256 schedulerCallId)
    {
        if (windowNumCalls == 0) revert InvalidSovereignMode();
        SovereignRollingConfig memory rolling = SovereignRollingConfig({
            windowNumCalls: windowNumCalls, rolloverThresholdBps: 5000, rolloverRetryEveryCalls: 1
        });
        if (msg.value != dkmsFunding + schedulerFunding) revert InvalidValue();
        (address predicted, bytes32 compressedSalt,) = predictCompressedHarness(msg.sender, userSalt);
        if (params.deliveryTarget != predicted) revert InvalidDeliveryTarget();

        bytes memory dkmsOutput = requestDkmsExtraction(executor, predicted, 0, 1, dkmsTtl);
        if (dkmsOutput.length == 0) revert InvalidDkmsOutput();
        (dkmsPaymentAddress,) = abi.decode(dkmsOutput, (address, bytes));
        if (dkmsPaymentAddress == address(0)) revert InvalidDkmsOutput();
        if (dkmsFunding > 0) {
            (bool funded,) = payable(dkmsPaymentAddress).call{value: dkmsFunding}("");
            if (!funded) revert DkmsFundingTransferFailed();
        }

        harness = _deployHarness(address(this), compressedSalt);
        schedulerCallId = _configureStartAndTransferOwnership(
            harness, params, schedule, rolling, schedulerLockDuration, schedulerFunding, msg.sender
        );
        emit SovereignLaunchCompressed(
            msg.sender, userSalt, harness, dkmsPaymentAddress,
            rolling.windowNumCalls, rolling.rolloverThresholdBps, rolling.rolloverRetryEveryCalls, schedulerCallId
        );
    }

    function launchSovereignWithDerivedDkms(
        bytes32 userSalt, address dkmsPaymentAddress, uint256 dkmsFunding,
        SovereignAgentParams calldata params, SovereignScheduleConfig calldata schedule,
        uint256 schedulerLockDuration, uint256 schedulerFunding, uint32 windowNumCalls
    ) external payable nonReentrantLaunch returns (address harness, uint256 schedulerCallId) {
        if (windowNumCalls == 0) revert InvalidSovereignMode();
        SovereignRollingConfig memory rolling = SovereignRollingConfig({
            windowNumCalls: windowNumCalls, rolloverThresholdBps: 5000, rolloverRetryEveryCalls: 1
        });
        if (msg.value != dkmsFunding + schedulerFunding) revert InvalidValue();
        if (dkmsPaymentAddress == address(0)) revert InvalidDkmsOutput();
        (address predicted, bytes32 compressedSalt,) = predictCompressedHarness(msg.sender, userSalt);
        if (params.deliveryTarget != predicted) revert InvalidDeliveryTarget();

        (harness, schedulerCallId) = _launchWithPreparedDkms(
            compressedSalt, dkmsPaymentAddress, dkmsFunding, params, schedule, rolling,
            schedulerLockDuration, schedulerFunding
        );
        emit SovereignLaunchFromDerivedDkms(
            msg.sender, userSalt, harness, dkmsPaymentAddress,
            rolling.windowNumCalls, rolling.rolloverThresholdBps, rolling.rolloverRetryEveryCalls, schedulerCallId
        );
    }

    function _configureStartAndTransferOwnership(
        address harness, SovereignAgentParams calldata params, SovereignScheduleConfig calldata schedule,
        SovereignRollingConfig memory rolling, uint256 schedulerLockDuration,
        uint256 schedulerFunding, address newOwner
    ) internal returns (uint256 schedulerCallId) {
        SovereignAgentHarness agent = SovereignAgentHarness(harness);
        schedulerCallId = agent.configureFundAndStart{value: schedulerFunding}(
            params, schedule, rolling, schedulerLockDuration
        );
        agent.transferOwnership(newOwner);
    }

    function _deployHarness(address owner, bytes32 userSalt) internal returns (address harness) {
        (address predicted, bytes32 childSalt) = predictHarness(owner, userSalt);
        bytes memory creationCode = abi.encodePacked(
            type(SovereignAgentHarness).creationCode,
            abi.encode(owner, scheduler, ritualWallet, teeRegistry, asyncDelivery)
        );
        harness = create3Factory.deploy(childSalt, creationCode);
        if (harness != predicted) revert HarnessAddressMismatch();
    }

    function _launchWithPreparedDkms(
        bytes32 compressedSalt, address dkmsPaymentAddress, uint256 dkmsFunding,
        SovereignAgentParams calldata params, SovereignScheduleConfig calldata schedule,
        SovereignRollingConfig memory rolling, uint256 schedulerLockDuration, uint256 schedulerFunding
    ) internal returns (address harness, uint256 schedulerCallId) {
        if (dkmsFunding > 0) {
            (bool funded,) = payable(dkmsPaymentAddress).call{value: dkmsFunding}("");
            if (!funded) revert DkmsFundingTransferFailed();
        }
        harness = _deployHarness(address(this), compressedSalt);
        schedulerCallId = _configureStartAndTransferOwnership(
            harness, params, schedule, rolling, schedulerLockDuration, schedulerFunding, msg.sender
        );
    }

    uint256 private _launchStatus;
    uint256[44] private __gap;
}
```

### Sovereign Agent Harness Source

The harness is the child contract deployed by the factory. It manages the rolling window lifecycle and invokes `0x080C` on each scheduled callback.

Key functions:
- `configureFundAndStart(params, schedule, rolling, lockDuration)` — configure + deposit + arm schedule
- `wakeUp(executionIndex, seriesId)` — scheduler callback; handles window promotion, successor scheduling, then calls `0x080C`
- `stop()` — cancels all tracked schedules, sets wake mode to NONE
- `restart()` — stops then re-arms with last config
- `onSovereignAgentResult(jobId, result)` — Phase 2 delivery callback from AsyncDelivery

```solidity
// SPDX-License-Identifier: BSD-3-Clause-Clear
pragma solidity ^0.8.28;

import {IRitualWallet} from "../wallet/IRitualWallet.sol";
import {ITEEServiceRegistry} from "../async/ITEEServiceRegistry.sol";
import {ITEECapabilityPolicy} from "../async/ITEECapabilityPolicy.sol";

// Structs: SovereignAgentParams, SovereignScheduleConfig, SovereignRollingConfig,
//          SovereignStorageRef (see Struct Definitions section above)

enum SovereignWakeMode { NONE, ROLLING_FIXED_WINDOW }
enum SovereignExecutorMode { PINNED, RESOLVE_AT_INVOCATION }

contract SovereignAgentHarness {
    address public constant SOVEREIGN_AGENT_PRECOMPILE = address(0x080C);
    uint256 public constant MAX_EXECUTOR_SCAN = 1;

    ISchedulerHarness public immutable scheduler;
    IRitualWallet public immutable ritualWallet;
    ITEEServiceRegistry public immutable teeRegistry;
    address public immutable asyncDelivery;

    address public owner;
    bool public configured;
    SovereignWakeMode public wakeMode;
    SovereignExecutorMode public executorMode;
    uint256 public activeCallId;
    uint32 public activeNumCalls;
    uint64 public currentSeriesId;
    uint64 public pendingSeriesId;
    uint64 public nextSeriesId;
    uint256 public pendingCallId;
    uint32 public thresholdIndex;
    bool public hasStartConfig;

    SovereignAgentParams internal params;
    bytes internal sovereignInputTemplate;
    SovereignScheduleConfig public scheduleConfig;
    SovereignRollingConfig public rollingConfig;

    // --- Core lifecycle ---

    function configureFundAndStart(
        SovereignAgentParams calldata p,
        SovereignScheduleConfig calldata s,
        SovereignRollingConfig calldata r,
        uint256 lockDuration
    ) external payable onlyOwner returns (uint256 callId) {
        _configure(p, s, r);
        if (msg.value > 0) { ritualWallet.depositFor{value: msg.value}(address(this), lockDuration); }
        return _armRollingWindow(r.windowNumCalls);
    }

    function stop() external onlyOwner {
        // Cancels active + pending + retired schedules, sets wakeMode = NONE
    }

    function restart() external onlyOwner returns (uint256 callId) {
        // Stops if running, then re-arms with last config
    }

    // --- Scheduler callback ---

    function wakeUp(uint256 executionIndex, uint64 seriesId) external onlyScheduler {
        if (wakeMode == SovereignWakeMode.NONE) return;

        // 1. Window promotion: if pending successor is now active, promote it
        if (seriesId == pendingSeriesId && pendingCallId != 0) { /* promote */ }

        // 2. Ignore callbacks for old (non-current) series
        if (seriesId != currentSeriesId) return;

        // 3. Clean up retired window's schedule
        if (retiredCallId != 0) { _tryCancelRetiredCall(); }

        // 4. Past threshold? Try scheduling the next window
        if (pendingCallId == 0 && executionIndex >= thresholdIndex) {
            _tryScheduleSuccessor();
        }

        // 5. ALWAYS invoke the sovereign agent precompile
        _callSovereignPrecompile(executionIndex, seriesId);
    }

    // --- Delivery callback ---

    function onSovereignAgentResult(bytes32 jobId, bytes calldata result)
        external onlyAsyncDelivery
    {
        emit SovereignResult(jobId, result);
    }

    // --- Internal ---

    function _callSovereignPrecompile(uint256 executionIndex, uint64 seriesId) internal {
        bytes memory input = getSovereignAgentInput();
        (bool ok, bytes memory output) = SOVEREIGN_AGENT_PRECOMPILE.call(input);
        if (!ok) revert SovereignCallFailed();
        emit SovereignInvoked(executionIndex, seriesId, output);
    }

    function _resolveExecutor() internal view returns (address) {
        // Uses teeRegistry.pickServiceByCapability(HTTP_CALL, false, seed, 1)
        // Reverts NoValidExecutor if none found
    }

    function _computeThresholdIndex(uint32 numCalls, uint16 thresholdBps) internal pure returns (uint32) {
        uint256 thresholdCount = (uint256(numCalls) * uint256(thresholdBps) + 9999) / 10000;
        if (thresholdCount == 0) thresholdCount = 1;
        return uint32(thresholdCount - 1);
    }
}
```

### Persistent Factory Configuration Surface

`PersistentAgentFactory` also supports two-step and compressed launch.

**Two-step:**
1. `deployLauncher(userSalt)` — deploy child launcher
2. Derive DKMS address via `requestPredictedLauncherDkmsExtraction` or the DKMS precompile (0x081B) and fund it
3. `PersistentAgentLauncher.configureFundAndArm(persistentInput, schedule, lockDuration)` — configure, deposit to RitualWallet, and arm scheduler

**Compressed (single tx, recommended):**
- `launchPersistentCompressed(...)` — performs DKMS derivation + funding + launcher deploy + configure/arm in one tx
- `launchPersistentWithDerivedDkms(...)` — same but skips DKMS derivation (pass pre-derived address)

> **Use compressed mode unless you need step-by-step observability.** The two-step flow requires manually deriving and funding the DKMS address. The compressed flow handles everything atomically.

All persistent factory launch config:

| Group | Field | Type | Notes |
|------|-------|------|------|
| Identity | `userSalt` | `bytes32` | Per-agent deterministic namespace |
| DKMS | `executor` | `address` | Executor for DKMS extraction |
| DKMS | `dkmsTtl` | `uint64` | DKMS extraction TTL |
| DKMS | `dkmsFunding` | `uint256` | **Required** native funding for derived DKMS payment address — agent needs this for heartbeat registration. Use >= 1000 RITUAL for development. |
| Payload | `persistentInput` | `bytes` | Fully ABI-encoded 0x0820 persistent request (26 fields) |
| Scheduler | `schedule.schedulerGas` | `uint32` | Gas for one-shot scheduled launch |
| Scheduler | `schedule.schedulerTtl` | `uint32` | Scheduler TTL |
| Scheduler | `schedule.maxFeePerGas` | `uint256` | EIP-1559 max fee for scheduler |
| Scheduler | `schedule.maxPriorityFeePerGas` | `uint256` | EIP-1559 tip for scheduler |
| Scheduler | `schedule.value` | `uint256` | Native value sent during launch execution |
| Scheduler wallet | `schedulerLockDuration` | `uint256` | RitualWallet lock duration for child payer |
| Scheduler wallet | `schedulerFunding` | `uint256` | Native value deposited into child RitualWallet |

`PersistentAgentLauncher` always arms a one-shot schedule (`numCalls=1`, `frequency=1`) to trigger persistent spawn.

> **`msg.value` must equal `dkmsFunding + schedulerFunding`.** The factory enforces this with `InvalidValue()`. Any mismatch reverts.

### Persistent Factory Struct Definitions

```solidity
struct PersistentLaunchSchedule {
    uint32 schedulerGas;
    uint32 schedulerTtl;
    uint256 maxFeePerGas;
    uint256 maxPriorityFeePerGas;
    uint256 value;
}
```

### Persistent Factory ABI (TypeScript)

```typescript
const PERSISTENT_FACTORY = '0xD4AA9D55215dc8149Af57605e70921Ea16b73591' as const;

const PersistentLaunchScheduleTuple = {
  type: 'tuple' as const,
  components: [
    { name: 'schedulerGas', type: 'uint32' },
    { name: 'schedulerTtl', type: 'uint32' },
    { name: 'maxFeePerGas', type: 'uint256' },
    { name: 'maxPriorityFeePerGas', type: 'uint256' },
    { name: 'value', type: 'uint256' },
  ],
} as const;

const persistentFactoryAbi = [
  {
    name: 'predictLauncher',
    type: 'function',
    stateMutability: 'view',
    inputs: [
      { name: 'owner', type: 'address' },
      { name: 'userSalt', type: 'bytes32' },
    ],
    outputs: [
      { name: 'launcher', type: 'address' },
      { name: 'childSalt', type: 'bytes32' },
    ],
  },
  {
    name: 'predictCompressedLauncher',
    type: 'function',
    stateMutability: 'view',
    inputs: [
      { name: 'owner', type: 'address' },
      { name: 'userSalt', type: 'bytes32' },
    ],
    outputs: [
      { name: 'launcher', type: 'address' },
      { name: 'compressedSalt', type: 'bytes32' },
      { name: 'childSalt', type: 'bytes32' },
    ],
  },
  {
    name: 'getDkmsDerivation',
    type: 'function',
    stateMutability: 'view',
    inputs: [
      { name: 'owner', type: 'address' },
      { name: 'userSalt', type: 'bytes32' },
    ],
    outputs: [
      { name: 'dkmsOwner', type: 'address' },
      { name: 'keyIndex', type: 'uint256' },
      { name: 'keyFormat', type: 'uint8' },
    ],
  },
  {
    name: 'deployLauncher',
    type: 'function',
    stateMutability: 'nonpayable',
    inputs: [{ name: 'userSalt', type: 'bytes32' }],
    outputs: [{ name: 'launcher', type: 'address' }],
  },
  {
    name: 'launchPersistentCompressed',
    type: 'function',
    stateMutability: 'payable',
    inputs: [
      { name: 'userSalt', type: 'bytes32' },
      { name: 'executor', type: 'address' },
      { name: 'dkmsTtl', type: 'uint64' },
      { name: 'dkmsFunding', type: 'uint256' },
      { name: 'persistentInput', type: 'bytes' },
      PersistentLaunchScheduleTuple,
      { name: 'schedulerLockDuration', type: 'uint256' },
      { name: 'schedulerFunding', type: 'uint256' },
    ],
    outputs: [
      { name: 'launcher', type: 'address' },
      { name: 'dkmsPaymentAddress', type: 'address' },
      { name: 'callId', type: 'uint256' },
    ],
  },
  {
    name: 'launchPersistentWithDerivedDkms',
    type: 'function',
    stateMutability: 'payable',
    inputs: [
      { name: 'userSalt', type: 'bytes32' },
      { name: 'dkmsPaymentAddress', type: 'address' },
      { name: 'dkmsFunding', type: 'uint256' },
      { name: 'persistentInput', type: 'bytes' },
      PersistentLaunchScheduleTuple,
      { name: 'schedulerLockDuration', type: 'uint256' },
      { name: 'schedulerFunding', type: 'uint256' },
    ],
    outputs: [
      { name: 'launcher', type: 'address' },
      { name: 'callId', type: 'uint256' },
    ],
  },
] as const;
```

### Persistent Factory Selector Table

| Selector | Function |
|----------|----------|
| `0x40d5e4f4` | `launchPersistentCompressed(bytes32,address,uint64,uint256,bytes,(uint32,uint32,uint256,uint256,uint256),uint256,uint256)` |
| (compute) | `launchPersistentWithDerivedDkms(bytes32,address,uint256,bytes,(uint32,uint32,uint256,uint256,uint256),uint256,uint256)` |
| (compute) | `deployLauncher(bytes32)` |
| `0x08ef770d` | `getDkmsDerivation(address,bytes32)` |
| (compute) | `predictLauncher(address,bytes32)` |
| (compute) | `predictCompressedLauncher(address,bytes32)` |

### Persistent Factory Events

```solidity
event LauncherDeployed(address indexed owner, bytes32 indexed userSalt, bytes32 indexed childSalt, address launcher);
event PersistentLaunchCompressed(
    address indexed owner, bytes32 indexed userSalt, address indexed launcher,
    address dkmsPaymentAddress, uint256 schedulerCallId
);
event PersistentLaunchFromDerivedDkms(
    address indexed owner, bytes32 indexed userSalt, address indexed launcher,
    address dkmsPaymentAddress, uint256 schedulerCallId
);
```

### Persistent Factory Gas Estimates

| Function | Typical Gas | Recommended Gas Limit |
|----------|-------------|----------------------|
| `deployLauncher` | ~500K | 1,000,000 |
| `configureFundAndArm` | ~4.5M | 8,000,000 |
| `launchPersistentCompressed` | ~5-7M | 10,000,000 |

### Compressed vs Two-Step Flow

| | Two-step | Compressed |
|---|---|---|
| **Transactions** | 2 (deployHarness + configureFundAndStart) | 1 (launchSovereignCompressed) |
| **CREATE3 owner** | `msg.sender` (your EOA) | Factory contract (transfers ownership after configure) |
| **Predict function** | `predictHarness(msg.sender, userSalt)` | `predictCompressedHarness(msg.sender, userSalt)` |
| **Salt derivation** | `keccak256(abi.encode(owner, userSalt))` | Double-wrapped: `keccak256(abi.encode(msg.sender, userSalt))` then `keccak256(abi.encode(factory, compressedSalt))` |
| **DKMS** | Separate tx (call `requestPredictedHarnessDkmsExtraction` or use consumer contract) | Inline — factory calls DKMS precompile during launch |
| **When to use** | Observability, debugging, step-by-step control | Production one-shot launch |

**`deliveryTarget` rules:**

- **Compressed flow (sovereign):** `deliveryTarget` must equal `predictCompressedHarness(msg.sender, userSalt)` return value. The compressed flow uses the factory as the intermediate CREATE3 owner.
- **Two-step flow (sovereign):** `deliveryTarget` must equal `predictHarness(msg.sender, userSalt)` return value. Uses msg.sender as the CREATE3 owner.
- **Compressed flow (persistent):** `deliveryTarget` must equal `predictCompressedLauncher(msg.sender, userSalt)`.
- **Two-step flow (persistent):** `deliveryTarget` must equal `predictLauncher(msg.sender, userSalt)`.

Using the wrong predict function causes `InvalidDeliveryTarget()` revert.

### Launch Sequence (Two-Step)

Use this sequence for both sovereign and persistent:

1. Choose `userSalt` and predict child address.
2. Ensure payload callback `deliveryTarget` equals predicted child.
3. Derive DKMS address (call DKMS precompile 0x081B through a consumer contract or via `requestPredictedLauncherDkmsExtraction` on the factory) and **fund it** with native RITUAL. The agent cannot heartbeat without funds.
4. Deploy child with `deployHarness` / `deployLauncher`.
5. Configure + fund + arm child with `configureFundAndStart` / `configureFundAndArm`.
6. Monitor child events and callback result events.

Minimal deploy step:

```bash
cast send "$SOVEREIGN_FACTORY_ADDRESS" \
  "deployHarness(bytes32)(address)" \
  "$USER_SALT" \
  --private-key "$PRIVATE_KEY" \
  --rpc-url "$RPC_URL"

cast send "$PERSISTENT_FACTORY_ADDRESS" \
  "deployLauncher(bytes32)(address)" \
  "$USER_SALT" \
  --private-key "$PRIVATE_KEY" \
  --rpc-url "$RPC_URL"
```

---

## 1. Long-Running (2-Phase) Delivery Pattern

Agent precompiles use a long-running (2-phase) delivery pattern because agent execution takes multiple blocks:

```
Phase 1: Submit Request
  User tx → Precompile → Executor picks up job → Returns jobId (tx hash) to caller

Phase 2: Deliver Result
  Executor completes agent execution → Calls deliveryTarget.deliverySelector(result)
  Your contract receives the callback with the agent's response
```

Phase 1 settles synchronously within the submitting transaction — the caller receives the job ID (transaction hash) as the precompile output. Phase 2 arrives asynchronously via callback once the executor finishes.

### Delivery Configuration

To receive the result on-chain, configure delivery fields in your precompile input:

```typescript
// When encoding with encodeAbiParameters, set the delivery fields:
//
//   deliveryTarget:               '0x...YourConsumerContract',
//   deliverySelector:             '0xaabbccdd',  // function selector for your callback
//   deliveryGasLimit:             3_000_000n,
//   deliveryMaxFeePerGas:         1_000_000_000n,
//   deliveryMaxPriorityFeePerGas: 100_000_000n,
//   deliveryValue:                0n,
```

Setting `deliveryTarget` to `0x0000000000000000000000000000000000000000` means no on-chain delivery — the result is only available off-chain via event logs.

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

**Mitigation:** Query `TEEServiceRegistry.getServicesByCapability(0, true)` before submitting to verify at least one valid executor exists. This doesn't guarantee the executor is healthy, but catches deregistered or expired-attestation scenarios.

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

1. You submit a Persistent Agent request on-chain.
2. The system provisions a long-lived agent instance in a TEE-backed runtime.
3. The agent maintains state through its workspace, memory, and encrypted DA checkpoints.
4. A heartbeat contract monitors whether the agent is still alive.
5. If the agent stops heartbeating, the system can attempt revival from the latest checkpoint.

If you want "my agent keeps existing and working for me," this is the primitive.

### Persistent Agent Preflight (Hard-Stop Checklist)

**Do NOT submit a persistent agent request until every item below is satisfied.** Skipping any item results in a wasted transaction: the precompile call may succeed (Phase 1 + Phase 2) but the agent container will fail silently — no heartbeat, no Telegram, no recovery. You will see a container ID in the Phase 2 response but the agent will be dead.

| # | Check | How to verify | What happens if skipped |
|---|-------|---------------|------------------------|
| 1 | **Real DA credentials** (not mocked, not empty) | Verify GCS bucket exists and SA has `storage.objectAdmin`, or HF token can access repo, or Pinata JWT is valid | Agent cannot checkpoint. Container may start but cannot persist state or be revived. |
| 2 | **DKMS address funded** with native RITUAL (>= 1000 for development) | `cast balance <dkms_address>` after funding | Agent cannot register on heartbeat contract. Nonce stays 0. Agent is operationally dead even though container runs. |
| 3 | **`rpcUrls` is a publicly reachable RPC** (e.g., `https://rpc.ritualfoundation.org`) | Verify the URL is reachable from outside your local machine | Agent cannot post heartbeats, cannot send any on-chain transactions. **Do NOT use `http://172.17.0.1:8545`** — this is a Docker bridge address that only works when the chain runs on the same Docker host as the executor. |
| 4 | **RitualWallet deposit** covers the spawn lifecycle | `cast call RITUAL_WALLET "balanceOf(address)(uint256)" <sender>` | Precompile call reverts with `insufficient wallet balance`. |
| 5 | **No pending async job** on sender | `cast call ASYNC_JOB_TRACKER "hasPendingJobForSender(address)(bool)" <sender>` | Transaction silently dropped by the block builder. |
| 6 | **At least one valid executor** for HTTP_CALL capability | `TEEServiceRegistry.getServicesByCapability(0, true)` returns non-empty | Commitment mined but executor never processes the job. TTL expires, funds locked. |
| 7 | **LLM API key is valid** for the chosen provider | Test the key against the provider's API before encrypting | Agent container fails at LLM initialization. |
| 8 | **`deliveryTarget` matches the predicted launcher** | For compressed: use `predictCompressedLauncher`. For two-step: use `predictLauncher`. | `InvalidDeliveryTarget()` revert, or Phase 2 delivered to wrong contract. |
| 9 | **Gas limit is sufficient** | Use >= 10,000,000 for `launchPersistentCompressed`, >= 8,000,000 for `configureFundAndArm` | Transaction reverts with out-of-gas. All state changes lost. |

> **Use `launchPersistentCompressed` to satisfy checks 2 and 8 atomically.** The compressed flow derives the DKMS address, funds it, deploys the launcher, and arms the scheduler in a single transaction. The two-step flow requires you to handle DKMS derivation and funding manually.

**DA is non-negotiable.** Persistent agents cannot function without real, working DA credentials. Unlike Sovereign Agents (which can execute with empty DA refs), Persistent Agents use DA for state continuity, checkpoint/recovery, and workspace persistence. If your DA credentials are fake or expired, the agent will write its initial state and then die.

Supported DA providers:
- `gcs` — requires GCS service account JSON + bucket name
- `hf` — requires HuggingFace access token + repo ID
- `pinata` — requires Pinata JWT

For credential formats, see `ritual-dapp-da`.

**`rpcUrls` must be reachable from inside the TEE container.** The agent container uses this URL to interact with the chain (heartbeat registration, heartbeat posting, on-chain transactions). The default `http://172.17.0.1:8545` in example scripts is for local development only — it is the Docker bridge network address and is unreachable from remote TEE executors. In production, use `https://rpc.ritualfoundation.org` or your deployment's public RPC.

### Persistent Agent Lifecycle

At a high level, a persistent agent moves through this lifecycle:

1. **Spawned** — your request creates the agent instance and returns a pending id in Phase 1, then a real instance result in Phase 2.
2. **Monitored** — once registered with the heartbeat contract, the agent is treated as alive and expected to keep heartbeating.
3. **Failed** — if it misses its heartbeat deadline, it is marked failed.
4. **Reviving** — the system can attempt to recover the agent from its latest encrypted checkpoint.
5. **Monitored again** — if revival succeeds and the agent heartbeats again, it returns to healthy monitored state.
6. **Removed** — if the agent drops below the contract's minimum balance threshold, it is removed from monitoring rather than endlessly revived.

### Heartbeat, Monitoring, and Revival

Persistent agents are tied to a heartbeat contract that tracks liveness and recovery state.

What the heartbeat system does:

- records the agent's latest successful heartbeat,
- stores the latest manifest / checkpoint reference used for recovery,
- marks agents failed when they miss the timeout window,
- initiates revival attempts,
- returns the agent to healthy state after a successful post-revival heartbeat.

There are **two different heartbeat concepts** you should not confuse:

1. **On-chain heartbeat** — proves liveness to the heartbeat contract and enables recovery.
2. **Agent task heartbeat** — a periodic prompt loop the agent can use for application logic.

The first is about lifecycle and recovery. The second is about behavior.

### How to Monitor a Persistent Agent

Your users and backend systems should monitor persistent agents through the heartbeat contract on the deployment they are using.

Useful view methods include:

- `isAlive(agentAddress)` — whether the contract currently considers the agent monitored/alive
- `getAgentInfo(agentAddress)` — detailed heartbeat metadata for that agent
- `getAgentsNeedingRevival()` — list of currently failed agents awaiting or eligible for revival

At a product level, you should monitor:

- whether the agent is still alive,
- the last successful heartbeat,
- whether the agent is in failed or reviving state,
- the latest checkpoint / manifest reference associated with that agent.

### What Happens If the Agent Stops Responding?

If a persistent agent misses its heartbeat deadline:

- it is marked as **failed**,
- the system can attempt to **revive** it,
- revival uses the agent's latest encrypted checkpoint / manifest reference,
- if the revived agent begins heartbeating again, it returns to healthy state.

If a revival attempt fails, the agent remains failed and can be retried later depending on the deployment's orchestration policy.

### What Happens If the Agent Runs Out of Money?

This is important and easy to miss:

- a persistent agent must maintain the minimum native balance required by the heartbeat contract,
- if it falls below that threshold, it is **removed from monitoring**,
- removal is different from failure: a removed agent is not simply auto-revived forever.

So the practical builder takeaway is:

- if your persistent agent runs out of native funds, you should treat that as an operational incident,
- topping up and resuming may require a fresh registration or fresh spawn path depending on how your deployment manages monitored agents,
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

**DA (Data Availability) Config**: Where the agent stores and retrieves persistent data. The executor derives a DA encryption key from DKMS using the sender's Ethereum address. This key is user-bound (not executor-bound), making agent state portable across executors. All agent DA writes are encrypted — there is currently no public DA option. For DA formats, providers, and credential payloads, see `ritual-dapp-da`.

**Revival Mode**: When `encrypted_secrets` is empty and `restore_from_cid` is non-empty, the executor starts the agent container in bootstrap mode. The container recovers its API keys from the DKMS escrow stored in the DA manifest. This enables automatic agent revival without re-submitting secrets.

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

### Telegram Plugin

Telegram is the supported user-facing plugin/channel you should document for persistent agents today.

Configure runtime behavior through `openclaw_config_ref`:

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
  }
}
```

Use secret substitution for the token:

- `botToken: "__TELEGRAM_BOT_TOKEN__"`
- and include `TELEGRAM_BOT_TOKEN` in the encrypted secrets bundle

This lets a persistent agent expose an operator-facing communication surface without the dApp having to design a custom messaging channel from day one.

### Raw ABI Usage

```typescript
import { encodeAbiParameters, parseAbiParameters } from 'viem';

// LLM provider enum: 0=Anthropic, 1=OpenAI, 2=Gemini, 3=xAI, 4=OpenRouter
const LLMProvider = { ANTHROPIC: 0, OPENAI: 1, GEMINI: 2, XAI: 3, OPENROUTER: 4 } as const;

const PERSISTENT_AGENT_ABI = parseAbiParameters([
  'address, bytes[], uint256, bytes[], bytes,',                  // executor, encryptedSecrets, ttl, secretSignatures, userPublicKey
  'uint64, address, bytes4, uint256, uint256, uint256, uint256,', // maxSpawnBlock, delivery config (target, selector, gasLimit, maxFee, maxPriorityFee, value)
  'uint8, string, string,',                                      // provider, model, llmApiKeyRef
  '(string,string,string), (string,string,string),',             // daConfig, soulRef
  '(string,string,string), (string,string,string),',             // agentsRef, userRef
  '(string,string,string), (string,string,string),',             // memoryRef, identityRef
  '(string,string,string), (string,string,string),',             // toolsRef, openclawConfigRef
  'string, string, uint16',                                      // restoreFromCid, rpcUrls, agentRuntime
].join(''));

// Do not hardcode executor addresses. Select a live executor from
// TEEServiceRegistry.getServicesByCapability(0, true) at request build time.
const executorAddress = '0x...selectedFromRegistry';

const encoded = encodeAbiParameters(PERSISTENT_AGENT_ABI, [
  executorAddress, [], 300n, [], '0x',               // base fields

  // Delivery
  600n,                                               // maxSpawnBlock (~3.5 min at ~350ms blocks)
  '0x...consumerContract',                            // deliveryTarget
  toFunctionSelector('onPersistentAgentResult(bytes32,bytes)'), // deliverySelector
  500_000n,                                           // deliveryGasLimit
  1_000_000_000n,                                     // deliveryMaxFeePerGas
  100_000_000n,                                       // deliveryMaxPriorityFeePerGas
  0n,                                                 // deliveryValue

  // LLM configuration
  LLMProvider.ANTHROPIC,                              // provider
  'claude-sonnet-4-5-20250929',                       // model
  'ANTHROPIC_API_KEY',                                // llmApiKeyRef — placeholder name in encrypted_secrets

  // Storage references (platform, path, keyRef)
  ['hf', 'my-org/agent-data/manifest.json', 'HF_TOKEN'],  // daConfig
  ['hf', 'my-org/agent-configs/SOUL.md', 'HF_TOKEN'],     // soulRef
  ['', '', ''],                                             // agentsRef (empty)
  ['', '', ''],                                             // userRef (empty)
  ['hf', 'my-org/agent-configs/MEMORY.md', 'HF_TOKEN'],   // memoryRef
  ['hf', 'my-org/agent-configs/IDENTITY.md', 'HF_TOKEN'], // identityRef
  ['hf', 'my-org/agent-configs/TOOLS.md', 'HF_TOKEN'],    // toolsRef
  ['', '', ''],                                             // openclawConfigRef (empty)

  '',                                                       // restoreFromCid
  `{"ritual":"${process.env.RITUAL_RPC_URL}"}`,             // rpcUrls — JSON-encoded; the agent container uses this to reach the chain
  0,                                                        // agentRuntime (0=ZeroClaw, 2=Hermes; 1 is legacy-reserved)
]);
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

> **Note:** Sovereign Agent determines provider via `LLM_PROVIDER` in encrypted secrets (see "Provider Secret Payloads" in Section 1) and additionally supports `"ritual"` (no API key needed). Persistent Agent does **not** support `"ritual"` and only accepts enum values `0..4` above.

### Agent Runtime Enum

```typescript
const AgentRuntime = {
  ZEROCLAW: 0,
  HERMES: 2,
} as const;

// Runtime value 1 still exists in ABI wire format for legacy deployments.
// New integrations should use ZEROCLAW (0) or HERMES (2).
```

### Persistent Agent ABI Fields (26 fields)

```
Index  Field                           Type                    Description
-----  ------------------------------  ----------------------  -----------
0      executor                        address                 TEE executor address (MUST not be zero)
1      encryptedSecrets                bytes[]                 ECIES-encrypted secret blobs
2      ttl                             uint256                 Time-to-live in blocks (chain-enforced max: 500 blocks, ~175s at ~350ms block time)
3      secretSignatures                bytes[]                 Signatures over encrypted secrets
4      userPublicKey                   bytes                   User ECIES public key for output encryption (empty = plaintext)
5      maxSpawnBlock                   uint64                  Phase 2 deadline offset from Phase 1 settlement block
6      deliveryTarget                  address                 Callback contract address
7      deliverySelector                bytes4                  Callback function selector
8      deliveryGasLimit                uint256                 Gas limit for callback execution
9      deliveryMaxFeePerGas            uint256                 EIP-1559 max fee per gas
10     deliveryMaxPriorityFeePerGas    uint256                 EIP-1559 max priority fee
11     deliveryValue                   uint256                 RITUAL value to send with callback (usually 0)
12     provider                        uint8                   LLM provider enum (0=Anthropic, 1=OpenAI, 2=Gemini, 3=xAI, 4=OpenRouter)
13     model                           string                  Model identifier (MUST NOT be empty)
14     llmApiKeyRef                    string                  Placeholder name in encrypted_secrets for LLM API key
15     daConfig                        (string,string,string)  DA layer StorageRef for agent output writes
16     soulRef                         (string,string,string)  SOUL.md — agent personality definition
17     agentsRef                       (string,string,string)  AGENTS.md — operating instructions
18     userRef                         (string,string,string)  USER.md — user profile
19     memoryRef                       (string,string,string)  MEMORY.md — long-term memory
20     identityRef                     (string,string,string)  IDENTITY.md — agent identity
21     toolsRef                        (string,string,string)  TOOLS.md — tool conventions
22     openclawConfigRef               (string,string,string)  Legacy-named runtime config patch (supports __KEY__ substitution)
23     restoreFromCid                  string                  DA manifest CID to restore from (empty = fresh spawn)
24     rpcUrls                         string                  JSON-encoded RPC URLs, e.g. '{"ritual":"http://localhost:8545"}'
25     agentRuntime                    uint16                  Runtime selector (0=ZeroClaw, 2=Hermes; 1 reserved for legacy OpenClaw deployments)
```

> **Only one Persistent Agent call per transaction.** The precompile enforces this — a second call in the same tx will fail.

### Delivery Callback & Events

Your contract must implement the callback function and the PrecompileConsumer emits the event:

```solidity
// Implement this in your contract:
address constant ASYNC_DELIVERY = 0x5A16214fF555848411544b005f7Ac063742f39F6;

function onPersistentAgentResult(bytes32 jobId, bytes calldata result) external {
    require(msg.sender == ASYNC_DELIVERY, "unauthorized callback sender");
    // Decode the response fields from `result`
}

// Event emitted by PrecompileConsumer:
// event PersistentAgentResultDelivered(bytes32 indexed jobId, bytes result);
```

Compute the delivery selector:
```typescript
import { toFunctionSelector } from 'viem';
const deliverySelector = toFunctionSelector('onPersistentAgentResult(bytes32,bytes)');
```

### Phase 1 Response

Phase 1 returns a pending instance ID: `"pending-{txHash[:16]}"` (other fields empty).

### Phase 2 Response

```typescript
import { decodeAbiParameters, parseAbiParameters } from 'viem';

const [instanceId, , containerId, checkpointCid, errorMessage] =
  decodeAbiParameters(
    parseAbiParameters('string, string, string, string, string, string'),
    responseData,
  );
```

```
Index  Field           Type    Description
-----  --------------  ------  -----------
0      instanceId      string  Unique agent instance identifier
2      containerId     string  Docker container ID in the TEE
3      checkpointCid   string  DA manifest CID for state checkpoint
4      errorMessage    string  Error details if spawn failed (empty on success)
```

> The response ABI contains 6 string fields. Fields at index 1 and 5 are reserved and should be ignored.

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
> - 1 (Codex), 2 (Aider), 3 (MCP) are **rejected at chain validation** (only `cliType ∈ {0, 4, 5, 6}` is allowed).
> - 4 (OpenClaw) **passes chain validation but is explicitly disabled at the executor** — submitting it returns the error "OpenClaw (type 4) is temporarily disabled; use ZeroClaw (type 6) instead".
>
> Build against **0 (Claude Code), 5 (Crush), 6 (ZeroClaw)** only. **`Hermes` is NOT a sovereign agent harness** — it's a *Persistent Agent* runtime (`agentRuntime = 2` in the Persistent Agent section above). The two enums use different numbering and apply to different precompiles. Do not try to set `cliType = 2` for sovereign — it will be rejected at the chain layer.

> **Recommended default for new sovereign agents:** `cliType = 6` (ZeroClaw) with `LLM_PROVIDER = "ritual"` and `model = "zai-org/GLM-4.7-FP8"`. This combination requires no external API keys (the Ritual gateway handles auth via mTLS inside the TEE) and is the lowest-friction path to first-call success. Switch to Claude Code + Anthropic only if you specifically need Claude's tooling, or if you've hit the model's 128K context window and need a larger one. (See `ritual-dapp-llm` for context-window vs `max_completion_tokens` semantics.)

The provider is determined by the `LLM_PROVIDER` key in `encryptedSecrets`. **`LLM_PROVIDER` is mandatory** — the executor rejects the call with `LLM_PROVIDER not found in secrets` if the key is missing or empty. Always include it explicitly, even when using Anthropic. Valid values: `anthropic`, `openai`, `gemini`, `openrouter`, `ritual`. (Legacy: `google` is normalized to `gemini`.) The `"ritual"` provider does not require an API key and is available for **Sovereign Agent only**.

### Switching Harness or Provider Mid-Project

This is a frequent stumbling block — disentangle the two axes before changing anything:

- **`cliType` (harness)**: which CLI runs inside the TEE container — Claude Code, Crush, or ZeroClaw. Goes in `SovereignAgentParams.agentType`.
- **`LLM_PROVIDER` + matching API key (provider)**: which LLM backend that CLI talks to — Anthropic, OpenAI, Gemini, OpenRouter, or the Ritual gateway. Goes in the encrypted secrets JSON.

These are independent. ZeroClaw can talk to Anthropic, Crush can talk to Gemini, etc. (Claude Code is the exception — it only talks to Anthropic.)

**Walkthrough: ZeroClaw + GLM (default) → Claude Code + Anthropic Claude.**

The agent + LLM are both changing; you must change all three of `cliType`, secrets, and `model`:

| Field | Before | After |
|-------|--------|-------|
| `params.agentType` (`cliType`) | `6` (ZeroClaw) | `0` (Claude Code) |
| `encryptedSecrets` (decrypted JSON) | `{"LLM_PROVIDER":"ritual"}` | `{"LLM_PROVIDER":"anthropic","ANTHROPIC_API_KEY":"sk-ant-..."}` |
| `params.model` | `"zai-org/GLM-4.7-FP8"` | A Claude model ID, e.g. `"claude-sonnet-4-5-20250929"` or `"claude-haiku-4-5-20251001"` |

**Walkthrough: keep ZeroClaw, switch from Ritual GLM to Anthropic Claude.**

Only secrets + model change; `cliType` stays at `6`:

| Field | Before | After |
|-------|--------|-------|
| `params.agentType` | `6` (ZeroClaw) | `6` (ZeroClaw) — unchanged |
| `encryptedSecrets` | `{"LLM_PROVIDER":"ritual"}` | `{"LLM_PROVIDER":"anthropic","ANTHROPIC_API_KEY":"sk-ant-..."}` |
| `params.model` | `"zai-org/GLM-4.7-FP8"` | `"claude-sonnet-4-5-20250929"` |

#### Important harness lifecycle gotcha (probable cause of "I tried to set cliType=0 and it didn't change")

`SovereignAgentHarness._configure` reverts with `AlreadyRunning` if the harness is currently scheduled (`wakeMode != NONE`). If you've already called `configureFundAndStart` once and the schedule is active, **you must call `stop()` first** before calling `configure(...)` again with the new `agentType`. Sequence:

```solidity
// 1. Cancel the active schedule so wakeMode drops back to NONE
sovereignAgentHarness.stop();

// 2. Re-configure with the new params (new agentType, new model, new schedule, etc.)
sovereignAgentHarness.configure(newParams, newSchedule, newRolling);

// 3. Re-arm the schedule (and re-fund RitualWallet if needed)
//    Either fund + arm in one call:
sovereignAgentHarness.configureFundAndStart{value: lockAmount}(newParams, newSchedule, newRolling, lockDuration);
//    or just arm the existing schedule if RitualWallet is already funded:
//    (call into the harness's start path directly per its interface)
```

If you skip the `stop()` call, the new `configure` reverts and your `agentType` change appears to "do nothing" — even though the chain accepts `cliType = 0` perfectly. The executor dispatches `cliType = 0` to Claude Code correctly; there is no executor-side bug.

A second source of confusion: the public block explorer (`ritual-scan`) historically only labeled `cliType ∈ {0..4}` and rendered higher values as `UNKNOWN(5)` / `UNKNOWN(6)` — `cliType = 0` always rendered as `claude_code`, so this UI bug bites Crush / ZeroClaw users specifically, not Claude Code switchers. If the scanner UI shows your `cliType` correctly, the chain has accepted the change.

### Preflight Checklist (Run Before Every Submit)

1. Sender has native RITUAL for gas (Phase 1 submission tx).
2. `AsyncJobTracker.hasPendingJobForSender(sender)` returns `false`. If `true`, the tx is silently dropped.
3. Sender has sufficient locked `RitualWallet` balance. Lock duration must extend past `currentBlock + ttl`. Recommended minimum: 5000 blocks (~29 minutes at ~350ms block time). For development, 100_000 blocks (~9.7 hours) avoids lock-expiry during iteration. See `ritual-dapp-block-time` for conversion formulas and measurement preflight.
4. At least one valid executor exists: `TEEServiceRegistry.getServicesByCapability(0, true)`.
5. Do not hardcode executor addresses as your default pattern. Select from `TEEServiceRegistry` at submit time so calls survive executor churn/restarts.
6. Encrypt secrets per `ritual-dapp-secrets` (ECIES to executor's `node.publicKey`, nonce length 12).
7. `max_poll_block` (Phase 2 offset) must be > `ttl` (Phase 1 TTL) and <= 70,000.
8. `model` must be non-empty and must be an exact provider-routable model identifier (do not rely on shorthand aliases). Before submit, run a provider-side model preflight check and pass the exact model string.
   - Anthropic example: `claude-sonnet-4-5-20250929`
   - OpenAI example: `gpt-4o-mini`
   - Gemini example: `gemini-2.5-flash`
9. `cliType` must be one of: 0 (ClaudeCode), 5 (Crush), or 6 (ZeroClaw). Values 1-4 are unavailable in the supported executor path.

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

**RitualWallet deposit required.** The sender must have RITUAL deposited in the `RitualWallet` contract (`0x532F0dF0896F353d8C3DD8cc134e8129DA2a3948`) with a lock duration that extends past the TTL. Deposit with native RITUAL (not wrapped tokens):
```solidity
RitualWallet(0x532F...3948).deposit{value: 5 ether}(100_000); // lockDuration in blocks (~9.7 hours for dev)
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
1. **Operational context-window cap on the upstream LLM.** The on-chain `max_seq_length` for a model is the *registered* capability; the actually deployed inference endpoint can be configured smaller. The live Ritual gateway currently caps `zai-org/GLM-4.7-FP8` at **64K = 65,536 tokens** even though it is registered at 128K. Inside an agent loop, accumulated tool-call replay context fills 64K much faster than you'd expect — well before you hit 128K. Treat the smaller of the two as your real budget.
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

### Minimal Consumer Contract

Any contract can call the 0x080C precompile. You do NOT need the canonical PrecompileConsumer — write your own:

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract SovereignAgentConsumer {
    address constant SOVEREIGN_AGENT = address(0x080C);
    address constant ASYNC_DELIVERY = 0x5A16214fF555848411544b005f7Ac063742f39F6;

    bytes32 public lastJobId;
    bytes public lastResult;

    event SovereignAgentResultDelivered(bytes32 indexed jobId, bytes result);

    function callSovereignAgent(bytes calldata input) external returns (bytes memory) {
        (bool ok, bytes memory output) = SOVEREIGN_AGENT.call(input);
        require(ok, "precompile call failed");
        return output;
    }

    function onSovereignAgentResult(bytes32 jobId, bytes calldata result) external {
        require(msg.sender == ASYNC_DELIVERY, "unauthorized callback sender");
        lastJobId = jobId;
        lastResult = result;
        emit SovereignAgentResultDelivered(jobId, result);
    }
}
```

Deploy with Foundry: `forge create --rpc-url $RPC --private-key $KEY SovereignAgentConsumer.sol:SovereignAgentConsumer`

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

### Raw ABI Usage

```typescript
import { encodeAbiParameters, parseAbiParameters, toFunctionSelector } from 'viem';
import { encrypt, ECIES_CONFIG } from 'eciesjs';

ECIES_CONFIG.symmetricNonceLength = 12; // see ritual-dapp-secrets

const CLIType = {
  CLAUDE_CODE: 0,
  CRUSH: 5,
  ZEROCLAW: 6,
} as const;

const SOVEREIGN_AGENT_ABI = parseAbiParameters([
  'address, uint256, bytes,',                                // executor, ttl, userPublicKey
  'uint64, uint64, string,',                                 // pollIntervalBlocks, maxPollBlock, taskIdMarker
  'address, bytes4, uint256, uint256, uint256,',             // delivery config
  'uint16, string, bytes,',                                  // cliType, prompt, encryptedSecrets
  '(string,string,string), (string,string,string),',        // convoHistory, output
  '(string,string,string)[],',                               // skills
  '(string,string,string),',                                 // systemPrompt
  'string, string[], uint16, uint32, string',                // model, tools, maxTurns, maxTokens, rpcUrls
].join(''));

// Encrypt API keys with executor's public key.
// LLM_PROVIDER is mandatory — the executor rejects the call with
// "LLM_PROVIDER not found in secrets" if the key is missing or empty.
const secretsJson = JSON.stringify({
  LLM_PROVIDER: 'anthropic',
  ANTHROPIC_API_KEY: process.env.ANTHROPIC_KEY,
});
const encryptedSecrets = encrypt(executorPublicKey.slice(2), Buffer.from(secretsJson));

const deliverySelector = toFunctionSelector('onSovereignAgentResult(bytes32,bytes)');

const encoded = encodeAbiParameters(SOVEREIGN_AGENT_ABI, [
  executorAddress,                     // executor (from TEEServiceRegistry)
  500n,                                // ttl (blocks until expiry)
  '0x',                                // userPublicKey (empty = plaintext delivery)

  5n,                                  // pollIntervalBlocks
  6000n,                               // maxPollBlock
  'SOVEREIGN_AGENT_TASK',              // taskIdMarker

  consumerContractAddress,             // deliveryTarget (your contract)
  deliverySelector,                    // deliverySelector
  3_000_000n,                          // deliveryGasLimit
  1_000_000_000n,                      // deliveryMaxFeePerGas (1 gwei)
  100_000_000n,                        // deliveryMaxPriorityFeePerGas

  CLIType.CRUSH,                       // cliType
  'Say hello world',                   // prompt
  `0x${encryptedSecrets.toString('hex')}`,  // encryptedSecrets (single blob)

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
```

### ABI Fields (23 fields)

```
Index  Field                           Type                     Description
─────  ─────────────────────────────── ──────────────────────── ────────────────────────────────
0      executor                        address                  TEE executor address
1      ttl                             uint256                  Time-to-live in blocks
2      userPublicKey                   bytes                    User ECIES key (empty = plaintext)
3      pollIntervalBlocks              uint64                   Polling frequency
4      maxPollBlock                    uint64                   Polling timeout block
5      taskIdMarker                    string                   Task ID placeholder
6      deliveryTarget                  address                  Callback contract
7      deliverySelector                bytes4                   Callback function selector
8      deliveryGasLimit                uint256                  Callback gas limit
9      deliveryMaxFeePerGas            uint256                  EIP-1559 max fee for callback
10     deliveryMaxPriorityFeePerGas    uint256                  EIP-1559 priority fee for callback
11     cliType                         uint16                   0=claude_code, 5=crush, 6=zeroclaw
12     prompt                          string                   Agent prompt
13     encryptedSecrets                bytes                    ECIES-encrypted secrets (single blob)
14     convoHistory                    (string,string,string)   Conversation history StorageRef
15     output                          (string,string,string)   Output artifacts StorageRef
16     skills                          (string,string,string)[] Skills array
17     systemPrompt                    (string,string,string)   System prompt StorageRef
18     model                           string                   Model identifier
19     tools                           string[]                 Allowed tools (empty = all)
20     maxTurns                        uint16                   Max conversation turns
21     maxTokens                       uint32                   Max output tokens
22     rpcUrls                         string                   JSON-encoded RPC URLs
```

### Data Availability (DA) — Conversation Memory & Artifacts

> For the shared DA architecture (StorageRef type, supported platforms, credential encryption, error handling) see `ritual-dapp-da`. This section covers agent-specific DA patterns.

Sovereign agents are **stateless by default** — each call gets a fresh container. To give an agent memory across calls, you must configure DA StorageRefs. The executor downloads previous state from DA before execution, and uploads updated state after execution.

**Four StorageRef fields control DA:**

| Field | Index | What It Does |
|-------|:---:|---|
| `convoHistory` | 14 | Conversation memory. Executor downloads previous JSONL, injects as conversation context in the prompt, appends a new turn after execution, re-uploads. |
| `output` | 15 | Artifact storage. Executor downloads previous files into `/workspace/artifacts/`, extracts new files after execution, uploads them. |
| `skills` | 16 | Skill definitions. Downloaded and injected as `/workspace/skill_0.md`, `skill_1.md`, etc. Read-only — not re-uploaded. |
| `systemPrompt` | 17 | System prompt. Downloaded and passed to the agent via `--system-prompt`. Read-only — not re-uploaded. |

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

**Example: HuggingFace-backed conversation memory + artifacts**

```typescript
const encoded = encodeAbiParameters(SOVEREIGN_AGENT_ABI, [
  executorAddress, 500n, '0x',
  5n, 10000n, 'SOVEREIGN_AGENT_TASK',
  consumerContract, deliverySelector, 3_000_000n, 1_000_000_000n, 100_000_000n,
  CLIType.CRUSH, 'What did we talk about last time?',
  `0x${encryptedSecrets.toString('hex')}`,

  ['hf', 'my-org/agent-workspace/sessions/session.jsonl', 'HF_TOKEN'],  // convoHistory
  ['hf', 'my-org/agent-workspace/artifacts/', 'HF_TOKEN'],              // output
  [],                                                                     // skills (empty)
  ['hf', 'my-org/agent-workspace/prompts/system.md', 'HF_TOKEN'],       // systemPrompt

  'claude-sonnet-4-5-20250929', [], 50, 8192, '',
]);
```

**Example: GCS-backed conversation memory + artifacts**

```typescript
// GCS credentials go in encryptedSecrets as a JSON blob
const secretsJson = JSON.stringify({
  ANTHROPIC_API_KEY: 'sk-ant-...',
  GCS_CREDENTIALS: JSON.stringify({
    service_account_json: '{"type":"service_account","project_id":"my-project",...}',
    bucket: 'my-ritual-da-bucket',
  }),
});

const encoded = encodeAbiParameters(SOVEREIGN_AGENT_ABI, [
  // ... executor, ttl, delivery config ...

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
const firstCall = encodeAbiParameters(SOVEREIGN_AGENT_ABI, [
  // ... executor, ttl, delivery config ...

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
const secondCall = encodeAbiParameters(SOVEREIGN_AGENT_ABI, [
  // ... executor, ttl, delivery config ...

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

Every sovereign agent invocation derives a **secp256k1 keypair** from DKMS (Decentralized Key Management) inside the TEE. This keypair is bound to the **sender's Ethereum address**, not the executor — making agent state portable across executors.

**What the DKMS keypair provides:**
- **Private key** — stays inside the TEE, used to ECIES-decrypt DA content on download and ECIES-encrypt on upload
- **Public key** — exposed via the DKMS precompile (0x081B), used by external parties to encrypt data TO the agent
- **Ethereum address** — derived from the public key, used for the agent's on-chain transactions

**All agent DA content is ECIES-encrypted.** The executor encrypts uploads with the agent's public key and decrypts downloads with the agent's private key. No plaintext agent DA — content at rest on HF/GCS/Pinata is always ciphertext. Only the TEE can read it.

**Getting the agent's DA public key** — call the DKMS precompile (0x081B):

```typescript
// The DKMS precompile returns (address, publicKey) for a given owner
// Use the owner's address (sender) to derive the agent's keypair
const dkmsResult = await callDkmsPrecompile(executorAddress, senderAddress, 0, 1);
const [agentAddress, agentDAPublicKey] = decodeDkmsResponse(dkmsResult);
// agentDAPublicKey is 65 bytes (uncompressed secp256k1, 0x04 prefix)
```

### Encrypted Inputs — Encrypting Skills & System Prompt to the Agent

Skills and system prompt content can be ECIES-encrypted to the agent's DA public key. This keeps agent instructions private — only the TEE can read them.

**How it works:**
1. Get the agent's DA public key from the DKMS precompile (0x081B)
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

> **Two different encryption targets.** `encryptedSecrets` (field 13) is encrypted to the **executor's** public key (from `TEEServiceRegistry.node.publicKey`). `dkms_encrypted:` content is encrypted to the **agent's** DA public key (from DKMS precompile 0x081B). These are different keys for different purposes: the executor key protects API keys in transit, the agent key protects agent state at rest.

### Private Prompt — Encrypting the Prompt On-Chain

The `prompt` field (index 12) is a plaintext string in the on-chain calldata — anyone can read it. To keep the prompt private, use the **template replacement pattern**:

1. Put the real prompt in `encryptedSecrets` under a placeholder key (e.g., `PRIVATE_PROMPT`)
2. Set the on-chain `prompt` field to the placeholder string
3. The executor decrypts the secrets, finds the placeholder in the prompt, and replaces it with the decrypted value

```typescript
// The real prompt goes into encrypted secrets
const secretsJson = JSON.stringify({
  ANTHROPIC_API_KEY: 'sk-ant-...',
  PRIVATE_PROMPT: 'Analyze my DeFi positions and suggest optimizations for maximum yield',
});
const encryptedSecrets = encrypt(executorPublicKey.slice(2), Buffer.from(secretsJson));

// The on-chain prompt is just the placeholder — visible to everyone but meaningless
const prompt = 'PRIVATE_PROMPT';
```

The executor does `prompt.replaceAll("PRIVATE_PROMPT", decryptedSecrets["PRIVATE_PROMPT"])` before running the agent. Any key in `encryptedSecrets` that appears as a substring in the prompt is replaced. Multiple placeholders are supported.

> **Encrypted to the executor, not the agent.** The private prompt is in `encryptedSecrets`, which is ECIES-encrypted to the **executor's** public key (from `TEEServiceRegistry.node.publicKey`). This is different from `dkms_encrypted:` content which is encrypted to the agent's DA key.

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
address constant ASYNC_DELIVERY = 0x5A16214fF555848411544b005f7Ac063742f39F6;

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

```typescript
import { encodeAbiParameters, parseAbiParameters, toFunctionSelector } from 'viem';

const LLMProvider = { ANTHROPIC: 0, OPENAI: 1, GEMINI: 2, XAI: 3, OPENROUTER: 4 } as const;

const PERSISTENT_AGENT_ABI = parseAbiParameters([
  'address, bytes[], uint256, bytes[], bytes,',
  'uint64, address, bytes4, uint256, uint256, uint256, uint256,',
  'uint8, string, string,',
  '(string,string,string), (string,string,string),',
  '(string,string,string), (string,string,string),',
  '(string,string,string), (string,string,string),',
  '(string,string,string), (string,string,string),',
  'string, string, uint16',
].join(''));

// Select from TEEServiceRegistry at runtime (do not hardcode).
const executorAddress = '0x...selectedFromRegistry';

const encoded = encodeAbiParameters(PERSISTENT_AGENT_ABI, [
  executorAddress, [], 300n, [], '0x',
  600n,                                                     // maxSpawnBlock (~3.5 min at ~350ms blocks)
  '0x...YourContract',
  toFunctionSelector('onPersistentAgentResult(bytes32,bytes)'),
  500_000n,
  1_000_000_000n, 100_000_000n, 0n,

  LLMProvider.ANTHROPIC,
  'claude-sonnet-4-5-20250929',
  'ANTHROPIC_API_KEY',                                      // llmApiKeyRef in encrypted_secrets

  // Storage references (platform, path, keyRef)
  ['hf', 'my-org/portfolio-agent/manifest.json', 'HF_TOKEN'], // daConfig
  ['hf', 'my-org/portfolio-agent/SOUL.md', 'HF_TOKEN'],       // soulRef
  ['', '', ''],                                                 // agentsRef
  ['', '', ''],                                                 // userRef
  ['hf', 'my-org/portfolio-agent/MEMORY.md', 'HF_TOKEN'],     // memoryRef
  ['hf', 'my-org/portfolio-agent/IDENTITY.md', 'HF_TOKEN'],   // identityRef
  ['hf', 'my-org/portfolio-agent/TOOLS.md', 'HF_TOKEN'],      // toolsRef
  ['', '', ''],                                                 // openclawConfigRef

  '',                                                           // restoreFromCid
  `{"ritual":"${process.env.RITUAL_RPC_URL}"}`,                 // rpcUrls — JSON-encoded; the agent container uses this to reach the chain
  0,                                                            // agentRuntime (0=ZeroClaw)
]);
```

---

## 5. Multi-Agent Orchestration

The async transaction pool enforces **one pending async job per sender address**. You cannot submit a second agent call from the same wallet while the first is in flight.

**For sequential operations (same wallet):** Wait for Phase 1 completion before submitting the next call. Once Phase 1 settles (the job ID is returned), the sender slot is freed and a new async transaction can be submitted.

**For concurrent agents:** Use separate wallet addresses for each concurrent agent call. Each wallet can independently have one pending job.

This is a protocol-level constraint enforced by `AsyncJobTracker.hasPendingJobForSender()`.

---

## 6. Combining Agents with Other Precompiles

### Agent + Scheduler: Recurring Sovereign-Agent Tasks

Use the Scheduler to trigger sovereign agent jobs on a schedule:

```solidity
function scheduledSovereignTask() external {
    require(msg.sender == SCHEDULER, "Only scheduler");
    bytes memory request = buildSovereignAgentRequest();
    (bool ok, ) = SOVEREIGN_AGENT_PRECOMPILE.call(request);
    require(ok, "Sovereign agent call failed");
}
```

### Agent + Secrets: Authenticated Tool Access

Pass encrypted API keys so the agent can authenticate with external services. Follow `ritual-dapp-secrets` for the complete ECIES encryption workflow.

```typescript
import { createPublicClient, http, defineChain, encodeAbiParameters, parseAbiParameters } from 'viem';
import { encrypt, ECIES_CONFIG } from 'eciesjs';

ECIES_CONFIG.symmetricNonceLength = 12; // see ritual-dapp-secrets

const ritualChain = defineChain({
  id: 1979,
  name: 'Ritual',
  nativeCurrency: { name: 'RITUAL', symbol: 'RITUAL', decimals: 18 },
  rpcUrls: { default: { http: [process.env.RITUAL_RPC_URL!] } },
});
const publicClient = createPublicClient({ chain: ritualChain, transport: http() });

const TEE_SERVICE_REGISTRY = '0x9644e8562cE0Fe12b4deeC4163c064A8862Bf47F' as const;
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
          { name: 'publicKey', type: 'bytes' },
          { name: 'endpoint', type: 'string' },
          { name: 'certPubKeyHash', type: 'bytes32' },
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

const executor = services[0];
const executorPubKey = executor.node.publicKey as `0x${string}`;

// Encrypt secrets with executor's public key using ECIES
const secretsJson = JSON.stringify({
  ANTHROPIC_API_KEY: process.env.ANTHROPIC_KEY!,
  HF_TOKEN: process.env.HF_TOKEN!,
});
const encryptedSecrets = [
  `0x${encrypt(executorPubKey.slice(2), Buffer.from(secretsJson)).toString('hex')}` as `0x${string}`,
];

// Use encryptedSecrets in your Persistent Agent or Sovereign Agent encoding
```

---

## 7. Executor Selection for Agent Precompiles

Both agent precompiles use HTTP_CALL capability (0) for executor selection:

```typescript
import { createPublicClient, http, defineChain } from 'viem';

const ritualChain = defineChain({
  id: 1979,
  name: 'Ritual',
  nativeCurrency: { name: 'RITUAL', symbol: 'RITUAL', decimals: 18 },
  rpcUrls: { default: { http: [process.env.RITUAL_RPC_URL!] } },
});
const publicClient = createPublicClient({ chain: ritualChain, transport: http() });

const TEE_SERVICE_REGISTRY = '0x9644e8562cE0Fe12b4deeC4163c064A8862Bf47F' as const;
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
          { name: 'publicKey', type: 'bytes' },
          { name: 'endpoint', type: 'string' },
          { name: 'certPubKeyHash', type: 'bytes32' },
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

const executor = services[0];
// Use executor.node.teeAddress as the executor field
// Use executor.node.publicKey to encrypt secrets with ECIES
```

### Checking Executor Health

Before submitting an agent job, verify the executor is available:

```typescript
import type { PublicClient } from 'viem';

const TEE_SERVICE_REGISTRY = '0x9644e8562cE0Fe12b4deeC4163c064A8862Bf47F' as const;

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
        { name: 'publicKey', type: 'bytes' },
        { name: 'endpoint', type: 'string' },
        { name: 'certPubKeyHash', type: 'bytes32' },
        { name: 'capability', type: 'uint8' },
      ]},
      { name: 'isValid', type: 'bool' },
      { name: 'workloadId', type: 'bytes32' },
    ],
  }],
}] as const;

async function findHealthyExecutor(
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
    if (service.isValid) {
      return service;
    }
  }
  return null;
}

const CAPABILITY_HTTP_CALL = 0;
const executor = await findHealthyExecutor(publicClient, CAPABILITY_HTTP_CALL);
if (!executor) {
  throw new Error('No healthy executor available for agent calls');
}
```

---

## Quick Reference

### Persistent Agent (0x0820) Suggested Starting Values

| Field | Default |
|-------|---------|
| `maxSpawnBlock` | `600` (~3.5 min at ~350ms blocks) |
| `deliveryGasLimit` | `100,000` |
| `deliveryMaxFeePerGas` | `1,000,000,000` (1 gwei) |
| `deliveryMaxPriorityFeePerGas` | `100,000,000` (0.1 gwei) |
| `provider` | `ANTHROPIC` (0) in example scripts |
| `model` | Set explicitly to exact provider model id (no protocol default) |
| `agentRuntime` | `ZEROCLAW` (0) |

### Sovereign Agent (0x080C) Suggested Starting Values

| Field | Default |
|-------|---------|
| `pollIntervalBlocks` | `5` |
| `maxPollBlock` | `6000` |
| `deliveryGasLimit` | `3,000,000` |
| `deliveryMaxFeePerGas` | `1,000,000,000` (1 gwei) |
| `deliveryMaxPriorityFeePerGas` | `100,000,000` (0.1 gwei) |
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
| TEEServiceRegistry | `0x9644e8562cE0Fe12b4deeC4163c064A8862Bf47F` |
| RitualWallet | `0x532F0dF0896F353d8C3DD8cc134e8129DA2a3948` |
| AsyncJobTracker | `0xC069FFCa0389f44eCA2C626e55491b0ab045AEF5` |
| AsyncDelivery | `0x5A16214fF555848411544b005f7Ac063742f39F6` |
| Scheduler | `0x56e776BAE2DD60664b69Bd5F865F1180ffB7D58B` |
| Sovereign Agent Precompile | `0x000000000000000000000000000000000000080C` |

### Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `cipher: message authentication failed` | ECIES nonce length mismatch | See `ritual-dapp-secrets` — nonce must be 12, not the library default of 16. |
| Commitment mined, `hasPendingJobForSender` = true, but Phase 1 never settles. No errors anywhere. | ECIES encryption config wrong (nonce length or cipher). Executor cannot decrypt and silently drops the job. | Fix encryption per `ritual-dapp-secrets`. Use a fresh sender address to unblock. See "Debugging Silent Failures" below. |
| Tx accepted but never mined (silent drop) | Sender has a pending async job | Wait for previous job to complete or use a different sender address. Check: `AsyncJobTracker.hasPendingJobForSender(sender)` |
| `insufficient wallet balance` | RitualWallet not funded | Deposit RITUAL: `RitualWallet.deposit{value: X}(lockDuration)`. Lock must extend past `currentBlock + ttl`. |
| `invalid async payload: SovereignAgentRequest: Field extraction failed` | ABI encoding mismatch | Verify StorageRef uses `(string,string,string)` not `(string,string,bytes)`. Verify all 23 fields are present. |
| Phase 2 never arrives | Executor unreachable or TTL expired | Check `TEEServiceRegistry.getServicesByCapability(0, true)` returns valid executors. Increase `ttl`. |
| `NonEmptyPaddingBytes: Boolean must be either 0x0 or 0x1` | Decoding event data directly instead of unwrapping outer `bytes` | Event data is ABI-encoded `bytes`. Decode outer `bytes` first, then decode inner response tuple. |
| Empty text response from Claude Code | Claude Code version outdated in executor image | Not a client issue — executor needs updated sovereign-agent container image. |
| `sovereign_agent_type N is not currently supported` | Invalid or unsupported `cliType` value | Use 0 (ClaudeCode), 5 (Crush), or 6 (ZeroClaw). Values 1-4 are unavailable in the supported executor path. |
| `waitForTransactionReceipt` hangs after submitting an agent call | Phase 1 hasn't settled (usually because executor can't decrypt). Receipt won't appear until settlement. | Don't block on receipt for long-running async precompile txs. Use `cast send --async` or `sendTransaction` and poll for the Phase 2 event by `jobId` topic instead. |

### Debugging Silent Failures

When a sovereign agent call produces a commitment (`hasPendingJobForSender` = true) but Phase 1 never settles and no error is emitted anywhere, work through this checklist in order:

1. **Check ECIES encryption config.** This is the #1 cause. See `ritual-dapp-secrets` for the mandatory nonce length and setup. A wrong nonce produces `MAC check failed` inside the TEE — but this error is never surfaced on-chain.

2. **Check you encrypted to the correct public key.** The key must be `node.publicKey` from `TEEServiceRegistry.getServicesByCapability()`. Not `paymentAddress`, not `teeAddress` — those are Ethereum addresses, not ECIES public keys.

3. **Check the secrets JSON format.** Must be valid JSON with the exact key names the provider expects: `{"ANTHROPIC_API_KEY":"sk-..."}`, not `{"api_key":"sk-..."}` and not a bare string.

4. **Executor routing is handled entirely by the protocol.** You only need `teeAddress` and `publicKey` from `TEEServiceRegistry`. The `endpoint` field in the registry is internal executor infrastructure — it is not relevant for dApp submission and should not be used for routing or health checks.

5. **Test encryption locally before submitting on-chain.** Encrypt a payload, then decrypt it with the same keypair using the other language's library (both configured per `ritual-dapp-secrets`). If local decryption fails, on-chain will fail too — and it will fail silently.

6. **Check `cast logs` on AsyncJobTracker, not `cast tx`.** The original tx hash from `sendTransaction` may not match the on-chain tx hash (the builder defers the tx and re-executes it during fulfilled replay). Your tx hash will appear as an indexed topic on the AsyncJobTracker commitment event, not as a standalone transaction.

7. **If the sender is locked and won't clear:** Generate a fresh keypair, fund it, deposit into RitualWallet, and retry. The expiry system cleans up stuck jobs eventually, but during development a fresh wallet is faster than waiting.

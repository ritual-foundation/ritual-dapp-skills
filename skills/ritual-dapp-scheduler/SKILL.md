---
name: ritual-dapp-scheduler
description: Scheduled operations for Ritual dApps. Use when building dApps with time-delayed execution, recurring tasks, or automated workflows.
---

# Scheduled Operations — Ritual dApp Patterns

## Overview

The Scheduler contract (`0x4E0abeE2233D73E66382b45244F7459B34E1490E`) enables time-delayed and recurring execution of on-chain calls. Any contract call can be scheduled to run at a future block, repeat at fixed intervals, or execute as a one-shot delayed action. The Scheduler works with all precompiles — synchronous (JQ, Ed25519, SECP256R1) and async (HTTP, LLM, Agent, Long-Running HTTP, Image, Audio, Video).

Only **contracts** can schedule — not EOAs. The Scheduler always calls back `msg.sender`, so your contract must call `schedule()` directly.

When a scheduled call triggers an async precompile, the system automatically detects it during simulation, creates a commitment, routes to an executor, and settles. Each recurrence independently triggers a new async lifecycle.

**Scheduler**: `0x4E0abeE2233D73E66382b45244F7459B34E1490E`
**RitualWallet**: `0xF04076756d8129Baec46Dc0F1c526Baec490C393`
**Chain ID**: 784

---

## Call States

```
enum CallState {
    SCHEDULED,   // 0 — registered, waiting for trigger block
    EXECUTING,   // 1 — trigger block reached, callback running
    COMPLETED,   // 2 — all executions finished (terminal)
    CANCELLED,   // 3 — user cancelled (terminal)
    EXPIRED      // 4 — overall deadline passed (terminal)
}
```

For recurring calls, the cycle is: `SCHEDULED → EXECUTING → SCHEDULED → EXECUTING → ... → EXECUTING → COMPLETED`. The call stays in the `SCHEDULED ↔ EXECUTING` loop until all `numCalls` are done, then transitions to `COMPLETED`.

Individual executions can be skipped (TTL drift exceeded, insufficient funds, predicate skip — `CallExecutionSkipped` with reason `PredicateFalse` or `PredicateCheckFailed`) without killing the whole schedule. The schedule only dies when it reaches COMPLETED, CANCELLED, or EXPIRED.

Execution fees are **not** deducted at schedule time — only at execution time. The one charge taken at `schedule()` is the non-refundable residency fee (`SCHEDULED_RESIDENCY_FEE_PER_BLOCK = 1e13` wei × blocks until the schedule's expiry block, credited to the proposer). If a call is cancelled or expires, no execution fees were ever taken — the residency fee is not refunded. The rest of the balance stays in RitualWallet.

---

## Scheduled Callbacks — `onScheduledExecution`

The Scheduler delivers **every** scheduled call by calling `onScheduledExecution(uint256 executionIndex, bytes calldata payload)` on your target contract (interface `IScheduledCallback`). The `data` you pass to `schedule()` is handed back **verbatim** as `payload`. Your contract MUST implement this entrypoint and gate it on `msg.sender == scheduler`:

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IScheduledCallback {
    function onScheduledExecution(uint256 executionIndex, bytes calldata payload)
        external payable;
}

contract MyScheduled is IScheduledCallback {
    address constant SCHEDULER = 0x4E0abeE2233D73E66382b45244F7459B34E1490E;

    function onScheduledExecution(uint256 executionIndex, bytes calldata payload)
        external
        payable
        override
    {
        require(msg.sender == SCHEDULER, "only scheduler");
        // The payload format is YOURS — decode exactly what you encoded at schedule time.
        (uint256 myArg) = abi.decode(payload, (uint256));
        // ... do work, keyed off executionIndex ...
    }
}
```

From the skills repository root, `python3 scripts/test_scheduler_callback.py` compiles this literal callback with public Foundry tools and checks its caller gate and payload decoding. These controlled checks do not execute a live schedule. Set `SCHEDULER` to your selected deployment's verified address before deploying.

Encode the payload however your callback expects (it is opaque to the Scheduler) and pass it as `data`:

```solidity
bytes memory data = abi.encode(myArg);   // delivered verbatim as `payload`
uint256 callId = scheduler.schedule(data, gas, numCalls, frequency);
```

---

## Scheduler ABI

```typescript
const SCHEDULER = '0x4E0abeE2233D73E66382b45244F7459B34E1490E' as const;

const schedulerAbi = [
  { type: 'error', name: 'CallNotFound', inputs: [] },
  {
    name: 'schedule',
    type: 'function',
    stateMutability: 'nonpayable',
    inputs: [
      { name: 'data', type: 'bytes' },
      { name: 'gas', type: 'uint32' },
      { name: 'startBlock', type: 'uint32' },
      { name: 'numCalls', type: 'uint32' },
      { name: 'frequency', type: 'uint32' },
      { name: 'ttl', type: 'uint32' },
      { name: 'maxFeePerGas', type: 'uint256' },
      { name: 'maxPriorityFeePerGas', type: 'uint256' },
      { name: 'value', type: 'uint256' },
      { name: 'sponsor', type: 'address' },
    ],
    outputs: [{ type: 'uint256' }],
  },
  {
    name: 'schedule',
    type: 'function',
    stateMutability: 'nonpayable',
    inputs: [
      { name: 'data', type: 'bytes' },
      { name: 'gas', type: 'uint32' },
      { name: 'numCalls', type: 'uint32' },
      { name: 'frequency', type: 'uint32' },
    ],
    outputs: [{ type: 'uint256' }],
  },
  {
    name: 'cancel',
    type: 'function',
    stateMutability: 'nonpayable',
    inputs: [{ name: 'callId', type: 'uint256' }],
    outputs: [],
  },
  {
    name: 'calls',
    type: 'function',
    stateMutability: 'view',
    inputs: [{ name: 'callId', type: 'uint256' }],
    outputs: [
      { name: 'to', type: 'address' },
      { name: 'sponsor', type: 'address' },
      { name: 'startBlock', type: 'uint32' },
      { name: 'numCalls', type: 'uint32' },
      { name: 'frequency', type: 'uint32' },
      { name: 'gas', type: 'uint32' },
      { name: 'ttl', type: 'uint32' },
      { name: 'state', type: 'uint8' },
      { name: 'maxFeePerGas', type: 'uint256' },
      { name: 'maxPriorityFeePerGas', type: 'uint256' },
      { name: 'value', type: 'uint256' },
      { name: 'data', type: 'bytes' },
    ],
  },
  {
    name: 'getCallState',
    type: 'function',
    stateMutability: 'view',
    inputs: [{ name: 'callId', type: 'uint256' }],
    outputs: [{ name: 'state', type: 'uint8' }],
  },
] as const;
```

The 4-param minimal overload auto-sets: `startBlock = block.number + frequency`, `ttl = 0`, `maxFeePerGas = block.basefee`, `maxPriorityFeePerGas = 0`, `value = 0`, `sponsor = msg.sender`.

---

## TypeScript: Schedule a Single Delayed Execution

Use the `ScheduledJQConsumer` below, deployed with the verified Scheduler address. Its owner EOA calls the consumer; the consumer then calls `Scheduler.schedule()` and receives the callback. Calling `Scheduler.schedule()` directly from the EOA reverts `SenderNotContract()`.

Set `SCHEDULED_CONSUMER_ADDRESS` to that deployment and use its owner key. Fund the consumer's RitualWallet with `depositForFees()` before scheduling (see Fee Management); depositing into the EOA's wallet does not fund this self-sponsored consumer.

```typescript
import {
  createPublicClient, createWalletClient, defineChain, http,
  getAddress, parseAbi, stringToHex,
} from 'viem';
import { privateKeyToAccount } from 'viem/accounts';

const ritualChain = defineChain({
  id: 784,
  name: 'Ritual Chain',
  nativeCurrency: { name: 'RITUAL', symbol: 'RITUAL', decimals: 18 },
  rpcUrls: { default: { http: [process.env.RITUAL_RPC_URL!] } },
});

const account = privateKeyToAccount(process.env.PRIVATE_KEY! as `0x${string}`);
const publicClient = createPublicClient({ chain: ritualChain, transport: http() });
const walletClient = createWalletClient({ account, chain: ritualChain, transport: http() });

const gasPrice = await publicClient.getGasPrice();
const consumer = getAddress(process.env.SCHEDULED_CONSUMER_ADDRESS!);
const consumerAbi = parseAbi([
  'function scheduleRecurringTransform(string jqFilter,bytes inputJson,uint32 frequency,uint32 numCalls,uint32 gasLimit,uint256 maxFeePerGas)',
  'function depositForFees() payable',
  'function cancelSchedule()',
]);

const hash = await walletClient.writeContract({
  address: consumer,
  abi: consumerAbi,
  functionName: 'scheduleRecurringTransform',
  args: [
    '.v',
    stringToHex('{"v":"ritual"}'),
    150,          // first execution 150 blocks after the creation transaction
    1,            // one execution
    300_000,      // gas budget
    gasPrice,     // maxFeePerGas
  ],
});
```

## TypeScript: Schedule Recurring Execution

```typescript
const hash = await walletClient.writeContract({
  address: consumer,
  abi: consumerAbi,
  functionName: 'scheduleRecurringTransform',
  args: [
    '.v',
    stringToHex('{"v":"ritual"}'),
    50,           // first execution after 50 blocks, then every 50 blocks
    24,           // 24 executions; fund residency plus the execution budget
    300_000,
    gasPrice,
  ],
});
```

This consumer uses `ttl = 100` and `sponsor = address(this)`. To cancel an active schedule, its owner calls the consumer's `cancelSchedule()`; the consumer is the Scheduler's authorized caller. The example stores one active schedule ID, so cancel or complete it before creating another schedule you need to manage through that ID.

## TypeScript: Query and Monitor

```typescript
import { BaseError, ContractFunctionRevertedError } from 'viem';

try {
  // Only active schedule rows remain readable through calls()/getCallState().
  const state = await publicClient.readContract({
    address: SCHEDULER,
    abi: schedulerAbi,
    functionName: 'getCallState',
    args: [callId],
  });
  console.log('Active state:', state); // 0=SCHEDULED, 1=EXECUTING
} catch (error) {
  const revert = error instanceof BaseError
    ? error.walk((cause) => cause instanceof ContractFunctionRevertedError)
    : undefined;
  if (revert instanceof ContractFunctionRevertedError && revert.data?.errorName === 'CallNotFound') {
    console.log('No active row; reconcile recorded schedule events.');
  } else {
    throw error;
  }
}
```

Persist `CallCompleted`, `CallCancelled`, and `CallExpired` events for terminal history. Completion, cancellation, and expiry delete the active row; `CallNotFound` alone cannot distinguish those outcomes from an unknown call ID.

---

## Solidity: ScheduledConsumer Contract

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

interface IRitualWallet {
    function deposit() external payable;
}

interface IScheduler {
    function schedule(
        bytes calldata data,
        uint32 gas,
        uint32 startBlock,
        uint32 numCalls,
        uint32 frequency,
        uint32 ttl,
        uint256 maxFeePerGas,
        uint256 maxPriorityFeePerGas,
        uint256 value,
        address sponsor
    ) external returns (uint256 callId);

    function cancel(uint256 callId) external;
}

interface IScheduledCallback {
    function onScheduledExecution(uint256 executionIndex, bytes calldata payload) external payable;
}

contract ScheduledJQConsumer is IScheduledCallback {
    address constant JQ_PRECOMPILE = 0x0000000000000000000000000000000000000803;
    address constant RITUAL_WALLET = 0xF04076756d8129Baec46Dc0F1c526Baec490C393;
    IScheduler public immutable scheduler;

    address public owner;
    uint256 public activeScheduleId;
    uint256 public executionCount;
    bytes public lastResult;

    event Scheduled(uint256 indexed callId, uint256 frequency, uint256 numCalls);
    event Executed(uint256 indexed executionIndex, bytes result);

    modifier onlyOwner() {
        require(msg.sender == owner, "Not owner");
        _;
    }

    modifier onlyScheduler() {
        require(msg.sender == address(scheduler), "unauthorized");
        _;
    }

    constructor(address _scheduler) {
        owner = msg.sender;
        scheduler = IScheduler(_scheduler);
    }

    function depositForFees() external payable {
        IRitualWallet(RITUAL_WALLET).deposit{value: msg.value}();
    }

    function scheduleRecurringTransform(
        string calldata jqFilter,
        bytes calldata inputJson,
        uint32 frequency,
        uint32 numCalls,
        uint32 gasLimit,
        uint256 maxFeePerGas
    ) external onlyOwner {
        bytes memory data = abi.encode(jqFilter, inputJson);   // delivered verbatim as payload

        activeScheduleId = scheduler.schedule(
            data,
            gasLimit,
            uint32(block.number) + frequency,
            numCalls,
            frequency,
            100,
            maxFeePerGas,
            0,
            0,
            address(this)
        );

        emit Scheduled(activeScheduleId, frequency, numCalls);
    }

    function onScheduledExecution(uint256 executionIndex, bytes calldata payload)
        external
        payable
        override
        onlyScheduler
    {
        (string memory jqFilter, bytes memory inputJson) = abi.decode(payload, (string, bytes));
        bytes memory input = abi.encode(jqFilter, string(inputJson), uint8(2)); // explicit string output
        (bool success, bytes memory result) = JQ_PRECOMPILE.call(input);
        require(success, "JQ precompile call failed");

        lastResult = result;
        executionCount++;
        emit Executed(executionIndex, result);
    }

    function cancelSchedule() external onlyOwner {
        require(activeScheduleId != 0, "No active schedule");
        scheduler.cancel(activeScheduleId);
        activeScheduleId = 0;
    }

    receive() external payable {}
}
```

---

## Scheduler + Async Precompiles

When a scheduled call triggers an async precompile (HTTP 0x0801, LLM 0x0802, etc.), both lifecycles run:

1. Trigger block → `TxScheduled` (0x10) from `0xfa7e`
2. Builder simulates → detects async precompile inside the callback
3. `TxAsyncCommitment` (0x11) with `origin_tx = scheduled_tx_hash`
4. Executor processes in TEE
5. Scheduled tx re-executed with async result injected
6. `TxAsyncSettlement` (0x12) distributes fees
7. If more executions remain, loops back to step 1

### Scheduled HTTP Consumer

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract ScheduledHTTPConsumer is IScheduledCallback {
    struct StorageRef {
        string platform;
        string path;
        string keyRef;
    }

    address constant HTTP_PRECOMPILE = 0x0000000000000000000000000000000000000801;
    address constant RITUAL_WALLET = 0xF04076756d8129Baec46Dc0F1c526Baec490C393;
    IScheduler public immutable scheduler;

    address public owner;
    uint256 public activeScheduleId;
    uint256 public executionCount;

    event HTTPCallSubmitted(uint256 indexed executionIndex);

    modifier onlyOwner() { require(msg.sender == owner, "Not owner"); _; }
    modifier onlyScheduler() { require(msg.sender == address(scheduler), "unauthorized"); _; }

    constructor(address _scheduler) {
        owner = msg.sender;
        scheduler = IScheduler(_scheduler);
    }

    function depositForFees() external payable {
        IRitualWallet(RITUAL_WALLET).deposit{value: msg.value}();
    }

    function scheduleRecurringHTTPCall(
        address executor,
        string calldata url,
        uint32 frequency,
        uint32 numCalls,
        uint32 gasLimit,
        uint256 maxFeePerGas
    ) external onlyOwner {
        bytes memory data = abi.encode(executor, url);   // delivered verbatim as payload

        activeScheduleId = scheduler.schedule(
            data, gasLimit,
            uint32(block.number) + frequency,
            numCalls, frequency, 100,
            maxFeePerGas, 0, 0, address(this)
        );
    }

    function onScheduledExecution(uint256 executionIndex, bytes calldata payload)
        external
        payable
        override
        onlyScheduler
    {
        (address executor, string memory url) = abi.decode(payload, (address, string));
        bytes memory encoded = abi.encode(
            executor,
            address(this),      // sponsor: this consumer funds the async request
            new address[](0),   // secretOwners
            new bytes[](0),     // encryptedSecrets
            uint256(50),        // ttl
            new bytes[](0),     // secretSignatures
            bytes(""),          // userPublicKey
            url,
            uint8(1),           // GET
            new string[](0), new string[](0),
            bytes(""),          // body
            uint256(0),         // dkmsKeyIndex
            uint8(0),           // dkmsKeyFormat
            false,              // piiEnabled
            StorageRef("", "", "") // outputStorageRef tuple: inline response
        );

        (bool ok,) = HTTP_PRECOMPILE.call(encoded);
        require(ok, "HTTP precompile failed");

        executionCount++;
        emit HTTPCallSubmitted(executionIndex);
    }

    function cancelSchedule() external onlyOwner {
        require(activeScheduleId != 0, "No active schedule");
        scheduler.cancel(activeScheduleId);
        activeScheduleId = 0;
    }

    receive() external payable {}
}
```

### Scheduled Long-Running HTTP Consumer

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract ScheduledLongRunningConsumer is IScheduledCallback {
    address constant SCHEDULER = 0x4E0abeE2233D73E66382b45244F7459B34E1490E;
    address constant LONG_HTTP = address(0x0805);
    address constant ASYNC_DELIVERY = 0x508f57AE70967Da28AE0Ab6b95532878c4D0F440;

    bytes public encodedRequest;
    string public latestResult;

    event JobSubmitted(uint256 blockNumber);
    event JobCompleted(bytes32 indexed jobId, string result);

    function setRequest(bytes calldata _encodedRequest) external {
        encodedRequest = _encodedRequest;
    }

    function onScheduledExecution(uint256 executionIndex, bytes calldata) external payable override {
        require(msg.sender == SCHEDULER, "only scheduler");
        (bool ok,) = LONG_HTTP.call(encodedRequest);
        require(ok, "Long-running HTTP failed");
        emit JobSubmitted(block.number);
    }

    function onLongRunningResult(bytes32 jobId, bytes calldata result) external {
        require(msg.sender == ASYNC_DELIVERY, "unauthorized callback");
        (uint16 statusCode, , , bytes memory body, string memory errorMessage) =
            abi.decode(result, (uint16, string[], string[], bytes, string));
        if (statusCode >= 200 && statusCode < 300 && bytes(errorMessage).length == 0) {
            latestResult = string(body);
            emit JobCompleted(jobId, latestResult);
        }
    }
}
```

The `deliveryTarget` and `deliverySelector` in your long-running HTTP request must point to this contract's `onLongRunningResult` function. `msg.sender` in the callback is always `ASYNC_DELIVERY` (`0x508f57AE70967Da28AE0Ab6b95532878c4D0F440`).

If an EOA sponsors this consumer (`sponsor != address(this)`), approve it with `MAX_ALLOWANCE` before scheduling — `schedule()` pulls the residency fee through the allowance and requires the remainder to cover one max execution cost, and each execution deducts its own cost; the nested 0x0805 wallet reserve is checked against whatever allowance is left at callback time, so an allowance sized only to residency + max execution cost has nothing left for it (WalletReserve eviction, see Fee Management). Self-sponsored (`sponsor = address(this)`) contracts are unaffected but must hold enough `availableBalance` for residency + execution + the long-running Phase-2 escrow.

---

## Sponsor Semantics

The `sponsor` parameter specifies whose RitualWallet balance is debited at execution time. The sponsor must be `msg.sender`, or must have granted `msg.sender` a RitualWallet allowance via `RITUAL_WALLET.approve(msg.sender, amount)` covering at least the residency fee + `maxExecutionCost`. `schedule()` pulls only the residency fee through the allowance (a finite allowance is decremented by that amount), then requires the remaining `RITUAL_WALLET.allowance(sponsor, msg.sender) >= maxExecutionCost` (else reverts `UnauthorizedSponsor`) and `availableBalance(sponsor) >= maxExecutionCost`. Each execution then deducts its own cost from the sponsor's balance and allowance.

- **Contract pays for itself**: pass `address(this)` in Solidity
- **EOA pays**: the consumer must pass the EOA address as `sponsor`, and the EOA must approve that consumer in RitualWallet. The included `ScheduledJQConsumer` instead pays from its own wallet.
- **Sponsored**: a third party (the sponsor) calls `RITUAL_WALLET.approve(yourConsumerContract, amount)` to grant an allowance, then you pass their address as the `sponsor` arg. If the scheduled callback calls an async precompile (0x0801/0x0802/0x0805/...), `amount` MUST be `MAX_ALLOWANCE = 2**256 - 1` — the builder checks the async job's wallet reserve against the allowance left after `schedule()` and each execution, so an allowance sized only to residency + max execution cost has nothing left for the nested async commitment and the call is evicted with `WalletReserve`. `MAX_ALLOWANCE` is never decremented.

---

## Fee Management

```
maxExecutionCost per execution = (gasLimit × maxFeePerGas) + value
residencyFee (once, at schedule time, non-refundable) = SCHEDULED_RESIDENCY_FEE_PER_BLOCK × (expiryBlock − block.number)
SCHEDULED_RESIDENCY_FEE_PER_BLOCK = 1e13 wei (0.00001 RITUAL) per block — credited to the proposer via creditProposer
```

`SCHEDULED_RESIDENCY_FEE_PER_BLOCK` is an owner-settable storage value (`setScheduledResidencyFeePerBlock`), currently 1e13 wei — read it from the Scheduler contract rather than hard-coding it.

There is no fixed per-execution fee. Funding is just-in-time per execution, not lifetime-escrowed. Scheduling N calls does NOT require `N × maxExecutionCost` up front — at creation the sponsor pays the residency fee and then only needs `availableBalance`/allowance for ONE max-cost execution. Each execution re-checks and debits via `deductScheduledExecutionFeesFrom(sponsor, call.to, ...)` at execution time, not at schedule time. Unused gas is refunded after each execution.

**Nested-async allowance gotcha.** `schedule()` pulls only the residency fee through the allowance and requires the remainder to cover one max execution cost; each execution deducts its own cost. When the scheduled callback invokes an async precompile (0x0801/0x0802/0x0805/...), the builder checks `allowance[<sponsor field in the async precompile input>][<consumer contract>]` against that job's wallet reserve — an allowance sized only to residency + max execution cost has nothing left for it. The builder then issues a cleanup commitment with reason `ScheduledAsyncCleanupReason::WalletReserve` that evicts the schedule; read it via `Scheduler.scheduledAsyncCleanupReason(callId, executionIndex)`. Fix: the sponsor grants `RitualWallet.approve(consumerContract, MAX_ALLOWANCE)` — `MAX_ALLOWANCE` is never decremented.

If funds are insufficient at execution time, the Scheduler emits `CallSkippedInsufficientFunds(callId indexed, to indexed, sponsor indexed, requiredAmount, availableAmount)` and may emit `CallEvictedInsufficientFunds` (same signature), which evicts the remaining schedule rather than skipping a single execution. A basefee spike above `maxFeePerGas` does NOT cause insolvency — the Scheduler recomputes `requiredAmount` via `effectiveFeePerGas = baseFee + priorityFee` and keeps the job scheduled for a later block.

Run this funding step before the single-execution submission above. For recurrence, recalculate `blocksUntilExpiry` with that schedule's frequency/count/TTL and provide execution funds as they are needed. The included consumer sponsors itself; the EOA separately needs native funds for its transactions.

```typescript
const RITUAL_WALLET = '0xF04076756d8129Baec46Dc0F1c526Baec490C393' as const;
const SCHEDULED_RESIDENCY_FEE_PER_BLOCK = 10_000_000_000_000n; // 1e13 wei per block, charged once at schedule(); owner-settable — prefer reading Scheduler.SCHEDULED_RESIDENCY_FEE_PER_BLOCK()

const walletAbi = [
  { name: 'deposit', type: 'function', stateMutability: 'payable',
    inputs: [], outputs: [] },
  { name: 'approve', type: 'function', stateMutability: 'nonpayable',
    inputs: [{ name: 'caller', type: 'address' }, { name: 'amount', type: 'uint256' }], outputs: [] },
  { name: 'availableBalance', type: 'function', stateMutability: 'view',
    inputs: [{ name: 'account', type: 'address' }], outputs: [{ type: 'uint256' }] },
] as const;

// The contract validates funds/allowance for a single max-cost execution, not the full
// N-call total. Prove balance for one execution (add headroom if desired), plus the
// residency fee schedule() deducts up front: fee-per-block × (expiryBlock − now), where
// expiryBlock = startBlock + frequency × (numCalls − 1) + ttl.
const blocksUntilExpiry = 150n + 100n;   // startBlock offset (150) + frequency × (numCalls − 1) (0) + ttl (100)
const residencyFee = SCHEDULED_RESIDENCY_FEE_PER_BLOCK * blocksUntilExpiry;
const maxCostPerExec = gasPrice * 300_000n + residencyFee;

const balance = await publicClient.readContract({
  address: RITUAL_WALLET, abi: walletAbi, functionName: 'availableBalance', args: [consumer],
});

if (balance < maxCostPerExec) {
  const depositHash = await walletClient.writeContract({
    address: consumer, abi: consumerAbi, functionName: 'depositForFees',
    args: [], value: maxCostPerExec - balance,
  });
  const receipt = await publicClient.waitForTransactionReceipt({ hash: depositHash });
  if (receipt.status !== 'success') throw new Error('Consumer funding failed');
}
```

---

## Block Interval Reference

| Interval | Blocks (at ~350ms/block, conservative baseline) |
|----------|--------------------------|
| 1 minute | 172 |
| 5 minutes | 858 |
| 15 minutes | 2,572 |
| 1 hour | 10,286 |
| 6 hours | 61,715 |
| 12 hours | 123,429 |
| 1 day | 246,858 |
| 1 week | 1,728,000 |

Use `ritual-dapp-block-time` to recompute these intervals from recent blocks.

---

## Predicates

### Frequency is a degenerate predicate

Without predicates, `frequency = N` is itself a predicate — it's equivalent to `(block.number - startBlock) % N == 0`. A fixed modular arithmetic condition. You know exactly when every call fires.

Predicates generalize this. Instead of a fixed temporal pattern, a predicate can encode **any boolean condition**: price thresholds, state-dependent logic, cross-contract checks, time-of-day patterns. The schedule becomes event-driven rather than time-driven.

To unlock this: set `frequency = 1` and use `numCalls` as a **budget**. With `frequency = 1`, the schedule is eligible every block. The predicate is the sole gatekeeper. `numCalls` controls how many times the predicate is allowed to trigger before the schedule is exhausted.

```
frequency = N, no predicate  → fixed temporal pattern (fire every N blocks, N times)
frequency = 1, predicate     → arbitrary condition checked every block, numCalls = budget
frequency = N, predicate     → arbitrary condition sampled every N blocks (cheaper but slower)
```

### Interface

```solidity
interface IScheduledPredicate {
    function shouldExecute(
        address target,      // Call.to: the contract the Scheduler will call back
        uint256 callId,
        uint256 executionIndex
    ) external view returns (bool);
}
```

Predicates are called via `staticcall` — they cannot modify state. `Scheduler.execute` caps each predicate staticcall at `MAX_PREDICATE_GAS = 100_000`; the block builder additionally budgets 10,000,000 gas per block for all predicate evaluations. Only an exact 32-byte return word equal to `1` counts as true — any other value, short returndata, revert, or OOG is treated as not-true.

If a predicate reverts or runs out of gas, the scheduled transaction is skipped for that block (same as returning false). The Scheduler emits `CallExecutionSkipped(callId, executionIndex, PredicateSkipReason.{PredicateFalse,PredicateCheckFailed})`, the execution index stays pending for a later attempt, and the skip reason is consensus-validated by node software. The first argument passed to `shouldExecute` is the scheduled call's target (`Call.to`).

### Where Predicates Apply in the Lifecycle

**For synchronous scheduled calls** (JQ, Ed25519): the predicate gates whether the entire execution happens.

**For async scheduled calls** (HTTP, LLM, Agent): the predicate gates whether **Phase 1 (the commitment)** happens. Once triggered, the commitment → executor → settlement lifecycle is autonomous. The predicate is NOT re-evaluated during settlement or Phase 2 delivery.

### Example 1: One-shot sync at exact block

Fire a JQ transform at exactly block 200 (current block is 0). With `frequency = 1`, execution index `i` is expected at `startBlock + i`. `numCalls` must cover the gap to the target block — and `numCalls` is hard-capped at `MAX_NUM_CALLS = 256`, so a `frequency = 1` one-shot can only target a block within 256 of `startBlock`. To reach a block further out at `frequency = 1`, use a larger `frequency` (so the target slot index stays under 256) or re-schedule a fresh window from the callback.

```solidity
contract BlockTargetPredicate is IScheduledPredicate {
    uint256 public immutable targetBlock;

    constructor(uint256 _targetBlock) {
        targetBlock = _targetBlock;
    }

    function shouldExecute(address, uint256, uint256) external view returns (bool) {
        return block.number == targetBlock;
    }
}
```

```solidity
uint256 callId = scheduler.schedule(
    abi.encode(filter, input),   // verbatim payload for onScheduledExecution
    200_000,                    // gas
    uint32(block.number) + 1,   // startBlock = 1
    200,                        // numCalls — budget covers blocks 1 through 200 (max 256)
    1,                          // frequency (eligible every block)
    50,                         // ttl
    1 gwei, 0, 0,
    address(this),
    address(blockPredicate)     // fires at block 200
);
```

With `numCalls = 1`, the only execution slot is index 0 at `startBlock`. If the target block is outside `startBlock + scheduler_ttl`, the predicate never fires and the schedule expires. `numCalls` must be large enough to keep the schedule alive until the target — but no larger than `MAX_NUM_CALLS = 256` (values above 256 revert `InvalidNumCalls()`).

```
Block 1 to 199:  predicate returns false each block → nothing happens
Block 200:       predicate returns true → JQ runs → execution consumed
```

### Example 2: One-shot async at exact block

Same predicate, but callback calls the HTTP precompile. The predicate only gates the trigger — async settlement is autonomous:

```solidity
uint256 callId = scheduler.schedule(
    abi.encode(executor, url),   // verbatim payload for onScheduledExecution
    300_000,
    uint32(block.number) + 1,
    200,                        // numCalls — budget covers blocks 1 through 200 (max 256)
    1,                          // frequency
    50,                         // scheduler_ttl (must cover async settlement too)
    1 gwei, 0, 0,
    address(this),
    address(blockPredicate)     // fires at block 200
);
```

```
Block 199:  predicate returns false → nothing
Block 200:  predicate returns true  → TxScheduled → callback → HTTP precompile
            → TxAsyncCommitment (predicate NOT re-evaluated)
Block 202:  Executor settles → TxAsyncSettlement (predicate NOT re-evaluated)
```

### Example 3: Recurring conditional — price oracle

Fire an HTTP call every time an oracle reports a price above a threshold. Use `frequency = 1` so the predicate is checked every block. Set `numCalls` to the trigger budget — up to the `MAX_NUM_CALLS = 256` ceiling.

```solidity
contract PriceThresholdPredicate is IScheduledPredicate {
    address public immutable oracle;
    uint256 public immutable threshold;

    constructor(address _oracle, uint256 _threshold) {
        oracle = _oracle;
        threshold = _threshold;
    }

    function shouldExecute(address, uint256, uint256) external view returns (bool) {
        (, int256 price,,,) = IAggregator(oracle).latestRoundData();
        return uint256(price) > threshold;
    }
}
```

```solidity
uint256 callId = scheduler.schedule(
    abi.encode(executor, url),   // verbatim payload for onScheduledExecution
    300_000,
    uint32(block.number) + 1,
    256,                        // numCalls (budget: up to 256 triggers — the MAX_NUM_CALLS cap)
    1,                          // frequency = 1 (check every block)
    50,                         // ttl
    1 gwei, 0, 0,
    address(this),
    address(pricePredicate)
);
```

Why `frequency = 1` and not `frequency = 300`?

- `frequency = 1, numCalls = 256`: predicate checked every block. If the price crosses at block N, the call fires at block N. Maximum responsiveness (256 is the `MAX_NUM_CALLS` budget ceiling).
- `frequency = 300, numCalls = 33`: predicate only checked every 300 blocks, and the budget is much smaller because the lifespan `frequency × (numCalls − 1) + ttl` must not exceed `MAX_LIFESPAN`. If the price crosses at block N, the call won't fire until the next multiple of 300. Up to ~1.75 minutes delay at the ~350ms baseline.

The tradeoff is builder overhead: `frequency = 1` means the builder evaluates the predicate every block (up to 100K gas per evaluation, subsidized by the proposer). For high-frequency conditions, `frequency = 1` is the right choice. For expensive predicates or when latency tolerance is acceptable, a higher frequency reduces builder cost.

### Sizing numCalls for predicates (capped at 256)

With `numCalls = 1`, the schedule is COMPLETED after the first trigger. If your predicate fires at block 500,000, you're done — no more triggers even if the condition is met again at block 500,100.

With `numCalls = 256` (the `MAX_NUM_CALLS` cap), the predicate can trigger up to 256 times across the schedule's lifetime. Each trigger consumes one unit of budget. When the budget is exhausted, the schedule transitions to COMPLETED.

`numCalls` with a predicate is a **budget cap**, not a scheduling parameter. Set it high enough to cover your expected trigger frequency over the schedule's lifetime, but it cannot exceed `MAX_NUM_CALLS = 256` (values above 256 revert `InvalidNumCalls()`) and must also keep the lifespan `frequency × (numCalls − 1) + ttl <= 10,000` (`MAX_LIFESPAN`). To cover more than 256 triggers, re-schedule a fresh window from inside the callback.

---

## Scheduled Async: The Scheduler TTL Is the Binding Constraint

When a scheduled callback calls an async precompile, there are two TTLs — but the scheduler TTL is the one that kills you.

When the async result comes back, the builder **replays** the original `TxScheduled`. This runs `Scheduler.execute()` on-chain. Inside execute(), the TTL check runs:

```solidity
uint32 executionExpiryBlock = expectedBlock + call.ttl;
if (uint32(block.number) > executionExpiryBlock) {
    emit CallSkippedTTLExpired(...);
    return; // callback never runs, precompile never called, async result never consumed
}
```

If the scheduler TTL has passed by the time the settlement replay happens, the callback never fires, the async result is never consumed, and the settlement is invalid. The builder won't include it.

**This means: the scheduler TTL must cover the ENTIRE async lifecycle — from trigger to settlement replay.** It's not just "drift tolerance for when the callback first fires." The replayed TxScheduled must also pass the TTL check.

### The two TTLs

- **Scheduler TTL** — `expectedBlock + scheduler_ttl` is the deadline for the **replayed TxScheduled** to execute. Both the initial trigger AND the settlement replay must happen within this window.
- **Async TTL** — `commit_block + async_ttl` is the deadline for the executor to submit results. If this expires, the async job is cleaned up.

The effective deadline is: `min(expectedBlock + scheduler_ttl, commit_block + async_ttl)`

Since `commit_block ≈ expectedBlock` (commitment happens in the same block or shortly after the trigger), the binding constraint is usually **whichever TTL is smaller**.

### Why scheduler_ttl = 3 with a 9-block operation fails

```
Block 1: Expected execution block. scheduler_ttl=3, async_ttl=10.
Block 1: Scheduler fires. Commitment created. Async expiry = 1 + 10 = 11.
          Scheduler deadline = 1 + 3 = 4.
Block 10: Executor ready to settle (operation took 9 blocks).
           Builder tries to replay TxScheduled at block 10.
           Scheduler.execute() checks: block.number (10) > expectedBlock + ttl (1 + 3 = 4).
           → CallSkippedTTLExpired. Callback never runs. Settlement invalid.
❌ The async TTL (11) hasn't expired, but the scheduler TTL (4) has.
   The scheduler TTL is the binding constraint.
```

The fix: `scheduler_ttl >= expected_async_settlement_time`. If the HTTP call takes up to 9 blocks, set scheduler_ttl to at least 15-20 to be safe.

### Sender lock behavior

**Scheduled transactions bypass the per-txOrigin lock entirely.** Scheduled/system txs set `txOrigin = ZERO` and are therefore exempt from nonce-locking: the async pool does not insert them into `tx_origin_index`, so `is_sender_locked()` returns false for them. Multiple scheduled async jobs from the same caller CAN be in-flight simultaneously. The only constraint is per-block deduplication — keyed on the per-block uniqueness set `seen_tx_origins` (block-verification) / `local_async_commitment_tx_origins` (nodebuilder payload builder) — i.e. one async commitment per txOrigin per block building cycle.

### Scenario 1: Happy path

```
scheduler_ttl=50, async_ttl=100. Operation takes 3 blocks.

Block 1000: Expected. Scheduler fires. Commitment created.
Block 1003: Executor settles. Builder replays TxScheduled.
            Scheduler.execute(): block 1003 <= 1000 + 50 ✅
            Async: block 1003 <= 1000 + 100 ✅
✅ Both TTLs satisfied. Result delivered.
```

### Scenario 2: Scheduler TTL expires before settlement

```
scheduler_ttl=10, async_ttl=100. Operation takes 15 blocks.

Block 1000: Scheduler fires. Commitment created.
Block 1015: Executor ready. Builder tries to replay TxScheduled.
            Scheduler.execute(): block 1015 > 1000 + 10 = 1010 ❌
            → CallSkippedTTLExpired. Settlement invalid.
❌ Async TTL (1100) is fine, but scheduler TTL (1010) is blown.
   Fix: increase scheduler_ttl to cover the async settlement time.
```

### Scenario 3: Async TTL expires (scheduler is fine)

```
scheduler_ttl=100, async_ttl=5. Operation takes 10 blocks.

Block 1000: Scheduler fires. Commitment created. Async expiry = 1005.
Block 1010: Executor ready, but async TTL expired at block 1005.
            Job cleaned up by AsyncJobTracker. No result to settle.
❌ Scheduler TTL (1100) is fine, but async job expired.
   Fix: increase async_ttl in your abi.encode.
```

### Scenario 4: Scheduler fires late, tight window

```
scheduler_ttl=50, async_ttl=100. Operation takes 3 blocks.

Block 1000: Expected execution block.
Block 1048: Scheduler fires (late, within TTL). Commitment created.
            Scheduler deadline still = 1000 + 50 = 1050.
            Only 2 blocks left for settlement!
Block 1051: Executor settles. Block 1051 > 1050. ❌ Too late.
❌ The scheduler fired late, leaving no room for async settlement.
   Fix: scheduler_ttl must cover BOTH drift AND settlement time.
```

This is the critical insight: scheduler_ttl isn't just drift tolerance. It's `max_drift + max_settlement_time`.

### Scenario 5: Wallet insufficient

```
Block 1000: Builder simulates, detects async precompile.
            Wallet balance / allowance check (at parent state) → insufficient for the
            nested async job's wallet reserve. This is NOT a silent drop-and-retry: the
            builder emits a Scheduler cleanup commitment with reason WalletReserve
            (readable via Scheduler.scheduledAsyncCleanupReason(callId, executionIndex))
            that terminally evicts the scheduled call (ScheduledAsyncEvicted).
❌ Typical cause with sponsor != caller: the builder checks
   allowance[<sponsor field in the async precompile input>][<consumer contract>], and an
   allowance sized only to residency + max execution cost (what schedule() requires)
   has nothing left for the async reserve. Fix: approve the consumer with MAX_ALLOWANCE.
   This builder-level WalletReserve cleanup (parent-state wallet check) is distinct
   from the on-chain Scheduler.execute fee deduction: when the replayed
   Scheduler.execute() itself finds insufficient funds it emits
   CallSkippedInsufficientFunds and may emit CallEvictedInsufficientFunds (evicting
   the remaining schedule) rather than retrying indefinitely.
```

### Scenario 6: Recurring — no cascade blocking

```
frequency=100, scheduler_ttl=50, async_ttl=100.

Block 1000: Execution 0 fires. Commitment. (Caller NOT locked — exempt)
Block 1003: Execution 0 settles within scheduler TTL. ✅
Block 1100: Execution 1 fires. Independent commitment.
Block 1103: Execution 1 settles. ✅
```

Even if execution 0 hasn't settled when execution 1 fires, both can have in-flight commitments because scheduled txs bypass the sender lock.

### Scenario 7: Long-running (2-phase) — scheduler TTL only constrains Phase 1

For long-running (2-phase) precompiles, the TxScheduled is replayed during **Phase 1 settlement**, not Phase 2 delivery. Phase 2 delivery is a separate system tx (`AsyncDelivery.deliver()`) that doesn't go through `Scheduler.execute()`.

```
scheduler_ttl=50, async_ttl=100, max_poll_block=5000.

Block 1000: Scheduler fires. Phase 1 commitment.
Block 1003: Phase 1 settlement. Builder replays TxScheduled.
            Scheduler.execute(): 1003 <= 1000 + 50 ✅ (scheduler TTL OK)
            Phase 1 settles. Sender lock released.
Block 6003: Phase 2 delivery arrives (within max_poll_block).
            AsyncDelivery.deliver() calls your callback.
            This does NOT go through Scheduler.execute() — no scheduler TTL check.
✅ Scheduler TTL only constrains Phase 1. Phase 2 has its own deadline.
```

So for long-running precompiles:
- Phase 1 deadline: `expectedBlock + scheduler_ttl` (scheduler is binding)
- Phase 2 deadline: `phase1_settlement_block + max_poll_block` (independent of scheduler)

### Summary

| Scenario | Binding Constraint | Outcome |
|---|---|---|
| scheduler_ttl > settlement time | Async TTL | Works if async_ttl is also sufficient |
| scheduler_ttl < settlement time | Scheduler TTL | Settlement fails — CallSkippedTTLExpired |
| Late trigger + tight scheduler_ttl | Scheduler TTL | Drift eats into settlement window |
| Wallet insufficient | Builder WalletReserve cleanup | `WalletReserve` cleanup commitment evicts the schedule (terminal); with sponsor != caller the usual cause is an allowance sized only to residency + max execution cost, leaving nothing for the nested async reserve — grant `MAX_ALLOWANCE` |
| Recurring | Per-execution independent | No cascade (sender lock exempt) |
| Long-running Phase 1 | Scheduler TTL | Phase 1 must settle within scheduler TTL |
| Long-running Phase 2 | max_poll_block | Independent of scheduler TTL |

### How to size your TTLs

```
scheduler_ttl >= max_expected_drift + max_expected_settlement_blocks

async_ttl >= max_expected_settlement_blocks

For safety:
  scheduler_ttl = 2 × (max_expected_drift + max_expected_settlement_blocks)
  async_ttl = 2 × max_expected_settlement_blocks
```

For long-running precompiles, the scheduler TTL only needs to cover Phase 1 settlement (typically fast — a few blocks). Phase 2 is governed by `max_poll_block` independently.

### Deposit sizing

You don't need to lock up funds for all executions upfront. Apart from the one-time residency fee taken at `schedule()`, fees are deducted per-execution at execution time. You can top up your RitualWallet balance between executions with just-in-time deposits — as long as the balance is sufficient when each execution fires.

---

## Deterministic TxScheduled Hash Derivation (RPC-Only)

When users ask "what are the transaction hashes for the scheduled executions?", they usually mean the downstream `TxScheduled` hashes (`type=0x10`) generated from the schedule-submission transaction.

For one schedule flow, there are multiple related hashes:

- **Schedule-submission tx hash** — the original user transaction that called `Scheduler.schedule(...)`
- **Scheduled tx hash** — deterministic hash for each execution index (`executionIndex = 0..numCalls-1`)
- **Commitment tx hash** — async commitment transaction (`type=0x11`) when the scheduled callback triggers an async precompile
- **Settlement tx hash** — async settlement transaction (`type=0x12`) after executor processing

Use the embedded utility from:
`agents/debugger-reference/scheduled-async-rpc-runbook.md` (see "Embedded Utility A").

```bash
python3 /tmp/scheduled_txs.py \
  --hash <SCHEDULE_SUBMISSION_TX_HASH> \
  --rpc-url https://rpc.ritualfoundation.org
```

Example output:

```text
source_tx=0x...
events_found=1

call[0] id=7 caller=0x... start=123456 num_calls=3 frequency=20 ttl=100
  index=  0 block=    123456 scheduled_hash=0x...
  index=  1 block=    123476 scheduled_hash=0x...
  index=  2 block=    123496 scheduled_hash=0x...
```

Notes:
- The embedded utility decodes Scheduler `CallScheduled` events from the origin receipt.
- It reconstructs each `TxScheduled` hash using canonical scheduled-transaction signing fields.
- This gives deterministic expected hashes before you search for commitment/settlement transactions.
- It uses `cast keccak` for hashing, so Foundry `cast` must be installed.

---

## Quick Reference

| Item | Value |
|------|-------|
| Scheduler | `0x4E0abeE2233D73E66382b45244F7459B34E1490E` |
| RitualWallet | `0xF04076756d8129Baec46Dc0F1c526Baec490C393` |
| System account | `0xfa7e` — triggers execution during block building |
| Chain ID | 784 |
| CallState enum | 0=SCHEDULED, 1=EXECUTING, 2=COMPLETED, 3=CANCELLED, 4=EXPIRED |
| Terminal states | COMPLETED (2), CANCELLED (3), EXPIRED (4) |
| Fee model | `(gasLimit × maxFeePerGas) + value` per execution, no fixed per-execution fee (funded just-in-time; only one max-cost execution proven at creation, not × numCalls) |
| SCHEDULED_RESIDENCY_FEE_PER_BLOCK | 1e13 wei (0.00001 RITUAL) per block × blocks until expiry — charged once at `schedule()`, non-refundable, paid to the proposer via `creditProposer`; owner-settable via `setScheduledResidencyFeePerBlock`, so read it from the contract |
| Recurring | `1 < numCalls <= 256, frequency >= 1` |
| Single-shot | `numCalls = 1, frequency = 1` |
| Callback | Scheduler calls `IScheduledCallback.onScheduledExecution(executionIndex, payload)`; `data` passed to `schedule()` is delivered verbatim as `payload` |
| Only contracts | EOAs cannot call `schedule()` |
| Max async calls | One async precompile call per scheduled execution |
| MAX_TTL | 500 (deployment-immutable) |
| MAX_NUM_CALLS | 256 — `numCalls` must satisfy `1 <= numCalls <= 256`. Values `0` or `> 256` revert `InvalidNumCalls()`. Separate from and additional to MAX_LIFESPAN. |
| MAX_LIFESPAN | 10,000 blocks — the lifespan `frequency × (numCalls − 1) + ttl` must not exceed this. Reverts `ScheduleLifespanExceeded()`. |
| Callback gas limit | must be > 0 — `schedule()` reverts `InvalidGasLimit()` (selector 0x98bdb2e0) when gas == 0 |

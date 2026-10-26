---
name: ritual-dapp-wallet
description: RitualWallet integration for Ritual dApps. Use when depositing fees, checking available/reserved balances, approving caller allowances, or withdrawing funds.
---

# RitualWallet Integration

## What It Is

RitualWallet (`0xF04076756d8129Baec46Dc0F1c526Baec490C393`) is the escrow contract through which all fees flow in the Ritual system. Deposits immediately credit an `availableBalance` (no time lock). During scheduled and async execution the system moves funds from `availableBalance` to `reservedBalance` via per-job escrows, then on settlement credits the recipients' `availableBalance` (pull-payment, emitting `EscrowPaymentCredited`) so they can `withdraw()`, or refunds the funds back to the sponsor's available balance.

## Interface

```solidity
interface IRitualWallet {
    enum EscrowStatus { NONE, ACTIVE, SETTLED, EXPIRED }
    struct Escrow { address sponsor; uint256 reserved; uint256 paid; uint64 expiryBlock; EscrowStatus status; }

    function deposit() external payable;
    function depositFor(address account) external payable;
    function withdraw(uint256 amount) external;

    // System-only (onlySchedulerOrAsyncDelivery): credits msg.value to the block proposer's
    // availableBalance and emits ProposerPayment; the proposer pulls via withdraw() like any balance.
    function creditProposer(address proposer, uint256 callId) external payable;
    event ProposerPayment(address indexed proposer, uint256 amount, uint256 callId);

    function availableBalance(address account) external view returns (uint256);
    function reservedBalance(address account) external view returns (uint256);

    // ERC20-style sponsor -> caller allowance (async/scheduled funding)
    function allowance(address sponsor, address caller) external view returns (uint256);
    function approve(address caller, uint256 amount) external;
    function increaseAllowance(address caller, uint256 amount) external;
    function decreaseAllowance(address caller, uint256 amount) external;

    function escrows(bytes32 escrowId) external view returns (Escrow memory);
}
```

| Function | What It Does |
|---|---|
| `deposit()` | Deposit RITUAL into your `availableBalance` (no lock) |
| `depositFor(account)` | Deposit RITUAL into another account's `availableBalance` |
| `withdraw(amount)` | Withdraw from `availableBalance`. Reverts `InsufficientBalance` if `amount > availableBalance`. No lock gate. |
| `availableBalance(account)` | Returns the account's spendable balance in wei |
| `reservedBalance(account)` | Returns funds escrowed for in-flight jobs in wei (account total = available + reserved) |
| `allowance(sponsor, caller)` / `approve(caller, amount)` | ERC20-style allowance letting `caller` spend `sponsor`'s funds for async/scheduled jobs (also `increaseAllowance` / `decreaseAllowance`) |

### Key behaviors:

- **No time lock** — deposits are immediately available; there is no `lockDuration`, no monotonic lock, and no `lockUntil`. Withdrawals are gated only by `availableBalance`, never by a lock.
- **Async funding is balance + allowance gated** — the reth commitment validator checks the sponsor's `availableBalance >= required reserve` (executor + commitment + inclusion fees + Phase 2 callback cost) and, when the sponsor differs from the caller, `allowance[sponsor][caller] >= reserve`. There is no lock-duration check; underfunding surfaces as `InsufficientBalance` / `Insufficient wallet allowance`, not a lock-duration error.
- **Direct RITUAL transfer** — sending raw RITUAL to the contract (no function call) credits your `availableBalance` via `receive()`.
- **Execution gas fees are deducted only at execution time** — during the system transaction, not at submit. The one up-front charge is the scheduler slot residency fee (`SCHEDULED_RESIDENCY_FEE_PER_BLOCK` × blocks until expiry; the per-block rate is owner-settable via `setScheduledResidencyFeePerBlock` and is currently 1e13 wei), which `Scheduler.schedule()` pulls from the sponsor and credits to the block proposer's wallet balance via `creditProposer`. If you schedule a call and your balance is insufficient when it fires, the execution is skipped, not reverted.

### Who needs the deposit: sponsor, caller, txOrigin

Async and scheduled funding split the old single "sender" into three roles:
- **sponsor** — the RitualWallet account that is **billed** (`ReserveConfig.sponsor`, precompile field 1 / `job_sponsor`), read from the commitment escrow. Billing reads `availableBalance(sponsor)`. The sponsor must be encoded explicitly and must be non-zero. In simple self-pay flows, set it to the signing EOA; in app-backed flows, set it to the funded contract or third-party account that should pay.
- **caller** — `msg.sender` of the precompile-invoking frame. It gates the wallet **allowance** (`allowance[sponsor][caller]`).
- **txOrigin** — the originating EOA, used only for nonce/sender locking. It is set to zero for system txs, which disables their locking.

For **two-phase async precompiles** (image, audio, video, Sovereign Agent, Persistent Agent, long-running HTTP), the RitualWallet balance check at commitment time is performed against the **sponsor** (not necessarily the recovered transaction signer). The chain reads `availableBalance(sponsor)` and, when `sponsor != caller`, also requires `allowance[sponsor][caller] >= reserve`.

This means:
- If your contract calls `WALLET.deposit{value: ...}()`, the deposit goes to `address(this)` (the contract). This is correct when the contract itself is the sponsor. Scheduled callbacks are invoked on the scheduling contract, so a sponsored schedule should approve that dApp contract as caller, not the system Scheduler address.
- For **async precompiles**, the billed account is the **sponsor** (`ReserveConfig.sponsor`), and the balance/allowance check is against that sponsor. In the simple self-pay case, encode the signing EOA as sponsor and make sure that EOA has its own deposit. A contract or third-party account can be designated sponsor and funded instead — letting one account sponsor an app contract's async job. The `insufficient wallet balance` error names the **sponsor** account, not always the EOA signer.
- Use `depositFor(eoaAddress)` to deposit for a specific account from a contract, or have the account call `deposit()` directly. A contract can also sponsor a caller via `approve(caller, amount)` / `allowance` instead of (or in addition to) `depositFor`.

**Approve when sponsor != caller.** After depositing, if the caller that reserves funds differs from the sponsor, the sponsor must call `RitualWallet.approve(caller, amount)` — the async precompile-invoking consumer contract for contract-mediated async calls, the scheduling dApp contract for scheduled calls, and for a **Persistent Agent** the `AgentHeartbeat` contract — typically with `MAX_ALLOWANCE = 2**256 - 1`. Without this allowance the consumer's `reserveFrom` / deduct call reverts with `InsufficientAllowance` and the precompile / scheduled call fails. When `caller == sponsor` (self-pay), no `approve` is needed. Finite allowances are decremented per reserve/deduct; `MAX_ALLOWANCE` is treated as infinite and is never decremented. **Gotcha for scheduled callbacks that invoke an async precompile:** `Scheduler.schedule()` decrements a finite allowance by the residency fee and requires the remainder to cover one max execution cost (`maxFeePerGas × gas + value`). The nested async reserve is then checked separately against `allowance[<sponsor in the async input>][<consumer contract>]` — an allowance sized only to residency + max execution cost has nothing left for it, and the builder evicts the schedule with a wallet-reserve cleanup. Grant `MAX_ALLOWANCE` to the scheduling consumer contract instead.

For a **Persistent Agent**, the agent (acting as its own RitualWallet sponsor) must approve the `AgentHeartbeat` contract — `RitualWallet.approve(AgentHeartbeat, MAX_ALLOWANCE)` — so the `AgentHeartbeat` contract (the caller) can pull the agent's deposited RitualWallet funds (revival fees) via the sponsor→caller allowance mechanism. This is normally handled automatically by the persistent-agent heartbeat sidecar (`ensureHeartbeatRevivalApproval`) on startup: it reads `allowance(agentAddr /*sponsor*/, AgentHeartbeat /*caller*/)` (wallet address from env `RITUAL_WALLET_ADDRESS`) and, if below max, sends `approve(AgentHeartbeat, maxUint256)` from the agent.

## TypeScript ABI

```typescript
const RITUAL_WALLET = '0xF04076756d8129Baec46Dc0F1c526Baec490C393' as const;

const ritualWalletAbi = [
  {
    name: 'deposit', type: 'function', stateMutability: 'payable',
    inputs: [],
    outputs: [],
  },
  {
    name: 'depositFor', type: 'function', stateMutability: 'payable',
    inputs: [{ name: 'account', type: 'address' }],
    outputs: [],
  },
  {
    name: 'withdraw', type: 'function', stateMutability: 'nonpayable',
    inputs: [{ name: 'amount', type: 'uint256' }],
    outputs: [],
  },
  {
    name: 'availableBalance', type: 'function', stateMutability: 'view',
    inputs: [{ name: 'account', type: 'address' }],
    outputs: [{ type: 'uint256' }],
  },
  {
    name: 'reservedBalance', type: 'function', stateMutability: 'view',
    inputs: [{ name: 'account', type: 'address' }],
    outputs: [{ type: 'uint256' }],
  },
  {
    name: 'allowance', type: 'function', stateMutability: 'view',
    inputs: [{ name: 'sponsor', type: 'address' }, { name: 'caller', type: 'address' }],
    outputs: [{ type: 'uint256' }],
  },
  {
    name: 'approve', type: 'function', stateMutability: 'nonpayable',
    inputs: [{ name: 'caller', type: 'address' }, { name: 'amount', type: 'uint256' }],
    outputs: [],
  },
  {
    name: 'increaseAllowance', type: 'function', stateMutability: 'nonpayable',
    inputs: [{ name: 'caller', type: 'address' }, { name: 'amount', type: 'uint256' }],
    outputs: [],
  },
  {
    name: 'decreaseAllowance', type: 'function', stateMutability: 'nonpayable',
    inputs: [{ name: 'caller', type: 'address' }, { name: 'amount', type: 'uint256' }],
    outputs: [],
  },
  {
    name: 'escrows', type: 'function', stateMutability: 'view',
    inputs: [{ name: 'escrowId', type: 'bytes32' }],
    outputs: [{
      type: 'tuple',
      components: [
        { name: 'sponsor', type: 'address' },
        { name: 'reserved', type: 'uint256' },
        { name: 'paid', type: 'uint256' },
        { name: 'expiryBlock', type: 'uint64' },
        { name: 'status', type: 'uint8' },
      ],
    }],
  },
] as const;
```

## TypeScript: Deposit and Check Balance

```typescript
import {
  createPublicClient, createWalletClient, defineChain, http, parseEther, formatEther,
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

// Check current available + reserved balances
const available = await publicClient.readContract({
  address: RITUAL_WALLET, abi: ritualWalletAbi,
  functionName: 'availableBalance', args: [account.address],
});
const reserved = await publicClient.readContract({
  address: RITUAL_WALLET, abi: ritualWalletAbi,
  functionName: 'reservedBalance', args: [account.address],
});

console.log(`Available: ${formatEther(available)} RITUAL`);
console.log(`Reserved:  ${formatEther(reserved)} RITUAL`);
console.log(`Total:     ${formatEther(available + reserved)} RITUAL`);

// Deposit 0.5 RITUAL (immediately available, no lock)
const depositHash = await walletClient.writeContract({
  address: RITUAL_WALLET, abi: ritualWalletAbi,
  functionName: 'deposit',
  args: [],
  value: parseEther('0.5'),
});
await publicClient.waitForTransactionReceipt({ hash: depositHash });
```

## TypeScript: Withdraw

```typescript
const available = await publicClient.readContract({
  address: RITUAL_WALLET, abi: ritualWalletAbi,
  functionName: 'availableBalance', args: [account.address],
});

const hash = await walletClient.writeContract({
  address: RITUAL_WALLET, abi: ritualWalletAbi,
  functionName: 'withdraw',
  args: [available], // withdraw entire available balance (no lock gate)
});
await publicClient.waitForTransactionReceipt({ hash });
console.log(`Withdrew ${formatEther(available)} RITUAL`);
```

## Solidity: Contract Integration

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

interface IRitualWallet {
    function deposit() external payable;
    function availableBalance(address account) external view returns (uint256);
    function reservedBalance(address account) external view returns (uint256);
    function withdraw(uint256 amount) external;
}

contract MyDApp {
    IRitualWallet constant WALLET = IRitualWallet(0xF04076756d8129Baec46Dc0F1c526Baec490C393);

    function depositFees() external payable {
        WALLET.deposit{value: msg.value}();
    }

    function checkFeeBalance() external view returns (uint256 available, uint256 reserved) {
        available = WALLET.availableBalance(address(this));
        reserved = WALLET.reservedBalance(address(this));
    }

    function withdrawFees(uint256 amount) external {
        WALLET.withdraw(amount);
    }

    receive() external payable {}
}
```

## React: Balance Display Component

```typescript
import { useAccount, useReadContract } from 'wagmi';
import { formatEther } from 'viem';

const RITUAL_WALLET = '0xF04076756d8129Baec46Dc0F1c526Baec490C393' as const;

const walletAbi = [
  { name: 'availableBalance', type: 'function', stateMutability: 'view',
    inputs: [{ name: 'account', type: 'address' }], outputs: [{ type: 'uint256' }] },
  { name: 'reservedBalance', type: 'function', stateMutability: 'view',
    inputs: [{ name: 'account', type: 'address' }], outputs: [{ type: 'uint256' }] },
] as const;

function WalletBalance() {
  const { address } = useAccount();

  const { data: available } = useReadContract({
    address: RITUAL_WALLET, abi: walletAbi,
    functionName: 'availableBalance', args: address ? [address] : undefined,
    query: { enabled: !!address },
  });

  const { data: reserved } = useReadContract({
    address: RITUAL_WALLET, abi: walletAbi,
    functionName: 'reservedBalance', args: address ? [address] : undefined,
    query: { enabled: !!address },
  });

  if (!address) return <p>Connect wallet</p>;

  return (
    <div>
      <p>Available: {available !== undefined ? formatEther(available) : '...'} RITUAL</p>
      <p>Reserved: {reserved !== undefined ? formatEther(reserved) : '...'} RITUAL</p>
    </div>
  );
}
```

## How Funds Flow

RitualWallet is the single payment surface for all three execution models. Each model moves funds differently.

### Scheduled Transactions

```
Sponsor's RitualWallet
  │
  ├─ schedule(): residency fee (1e13 wei/block × blocks to expiry) ──► RITUAL_WALLET.creditProposer{value}(block.coinbase, callId)
  │                                                                     (ProposerPayment; proposer's available balance)
  ├─ deductScheduledExecutionFeesFrom() ──► Scheduler (receives RITUAL)
  │                                │
  │                                ├─ target.call{gas, value}(data)  ← callback executes
  │                                │
  │                                ├─ _distributeGasFees(): base fee × gasUsed ──► BURN_ADDRESS (burned)
  │                                │                        priority tip × gasUsed ──► RITUAL_WALLET.creditProposer{value}(block.coinbase, callId)
  │                                │                        (both capped at the sponsor-funded gas budget)
  │                                │
  │                                └─ refundGas() ──► sponsor's available balance (unused gas returned)
  │
  └─ residual RITUAL persists in Scheduler / returns to sponsor
```

The Scheduler holds RITUAL only during the callback. After execution, unused funds return to the sponsor's available balance.

**Who gets paid:** The base-fee portion of consumed callback gas is burned; the priority-fee tip (`min(maxPriorityFeePerGas, maxFeePerGas − basefee) × gasUsed`, capped at the gas budget) and the up-front residency fee are credited to the block proposer's RitualWallet balance (`creditProposer` → `ProposerPayment(proposer, amount, callId)`, pulled later via `withdraw()` — no proposer-controlled code runs); unused gas is refunded to the sponsor's available balance.

### Async Short-Running Transactions (HTTP, LLM)

```
Sponsor's RitualWallet (reserved escrow, keyed by jobId)
  │
  └─ AsyncDelivery.settle() ──► RITUAL_WALLET.settle(jobId, Payment[3], 0, 0, close=true)
                              ├─ Executor             (executorFee)
                              ├─ Commitment Validator (commitmentFee)
                              └─ Inclusion Validator  (inclusionFee)
```

Funds come from the per-job escrow (created when `reserveFrom` moved the sponsor's available → reserved), not from a loose user balance. `AsyncDelivery.settle()` builds `Payment[3]{executor, commitmentValidator, inclusionValidator}` and calls `RITUAL_WALLET.settle(jobId, payments, 0, 0, close=true)`, then `removeJob`. `settle()` does not push funds to each `Payment` recipient: for each non-zero payment it credits the recipient's available balance (`_balances[to] += amount`) and emits `EscrowPaymentCredited(escrowId, recipient, amount)`. The recipients (executor + validators) must subsequently call `withdraw()` to pull their RITUAL. `EscrowSettled` is still emitted at the end of `settle()`.

**Who gets paid:** The executor who ran the computation, the validator who included the commitment, and the validator who included the settlement. These recipients are **credited** to their RitualWallet available balance at settlement (`EscrowPaymentCredited`), not paid directly — they pull their funds via `withdraw()`. This removes the prior failure mode where a recipient with a reverting fallback could revert the whole settlement.

### Async Long-Running Transactions (Sovereign Agent, Persistent Agent, Long HTTP, Image, ZK, etc.)

Two settlement events, one per phase:

**Phase 1 (commitment settled):**
```
Sponsor's RitualWallet (reserved escrow, keyed by jobId)
  └─ AsyncDelivery.settle() ──► RITUAL_WALLET.settle(jobId, Payment[3], 0, 0, close=false)
                                  └─ Executor + Commitment Validator + Inclusion Validator
```
`close=false` keeps the escrow open for Phase 2.

**Phase 2 (delivery callback):**
```
Sponsor's RitualWallet (reserved escrow, keyed by jobId)
  │  AsyncDelivery.deliver() reads sponsor = RITUAL_WALLET.escrows(jobId).sponsor
  │
  └─ RITUAL_WALLET.settle(jobId, Payment[2], 0, 0, close=true)  ← settles + closes escrow
       ├─ Executor    (Phase 2 work fee)
       └─ callbackBudget = effectiveFeePerGas × callbackGasLimit + callbackValue ──► AsyncDelivery
                                │
                                ├─ target.call{gas, value}(selector, jobId, result)  ← callback
                                │
                                ├─ refundGas(sponsor, ...) ──► sponsor's available balance (unused gas + value if reverted)
                                │
                                ├─ base fee × gasConsumed ──► BURN_ADDRESS (burned)
                                └─ tip = (effectiveFeePerGas − basefee) × gasConsumed ──► RITUAL_WALLET.creditProposer{value: tip}(block.coinbase, uint256(jobId))
                                   (capped at callbackGasBudget; emits ProposerPayment)
```

Residual RITUAL in AsyncDelivery persists post-settlement and is refunded to the sponsor's available balance. Refunds go to the escrow sponsor, not necessarily the user.

**Who gets paid:** Phase 1 — executor + two validators. Phase 2 — executor again (for polling/generation work), plus the callback target receives the result (and optionally RITUAL via `deliveryValue`); the base fee of consumed callback gas is burned and the priority-fee tip is credited to the block proposer's RitualWallet balance via `creditProposer` (`ProposerPayment(proposer, tip, uint256(jobId))`, pulled via `withdraw()`).

---

## How Much to Deposit

| Use Case | Deposit Estimate (with headroom) |
|---|---|
| Single HTTP call | 0.02 RITUAL (the reserve alone is `HTTP_EXECUTOR_BASE_FEE_WEI` 0.01 RIT + 0.35 gwei × (input + 5120) bytes, so exactly 0.01 is not enough) |
| Single LLM call | The commitment reserve is the worst-case rate-card escrow `max(llmBaseFeeWei + llmFeeWeiPerOutputToken × maxSeqLen, 1e16)` — ≈2.26 RIT for `deepseek-ai/DeepSeek-V4-Flash-0731` (2.1584e12 wei/token × 1,048,576). The realized fee is far lower and the difference is refunded at settlement, but `availableBalance(sponsor)` must cover the full reserve at submit |
| Sovereign Agent job | **1 RITUAL per intended run** as headroom. The charge is deterministic, not depth-dependent: Phase 1 `SOVEREIGN_AGENT_PHASE1_SETTLEMENT_FEE_WEI` (0.018 RIT) + fixed max-work lockup `agent_escrow_lockup(50, 500)` (~0.121 RIT) + output-byte fee (≤ ~3.6e12 wei at the 10 KiB cap) + callback gas escrow — ~0.14 RIT floor per run regardless of iterations/tool calls |
| Persistent Agent job | Commitment reserve = Phase 1 executor fee `PERSISTENT_AGENT_EXECUTOR_FEE_WEI` 1e13 wei + the Phase 2 spawn fee `PERSISTENT_AGENT_SPAWN_FEE_WEI` 0.10 RIT (pre-reserved at commitment, paid to the executor on spawn delivery) + a 1 KiB output-byte fee + callback escrow; see the persistent funding table in ritual-dapp-agents for the consumer/prelaunch/heartbeat budget |
| Scheduled recurring (N calls) | per-execution cost = `(gasLimit × maxFeePerGas) + value`; plus the up-front residency fee `SCHEDULED_RESIDENCY_FEE_PER_BLOCK` (1e13 wei) × (expiryBlock − currentBlock) blocks, where `expiryBlock = startBlock + frequency × (numCalls − 1) + ttl` and `startBlock = currentBlock + frequency`, i.e. frequency × numCalls + ttl blocks, charged at `schedule()`; N × per-execution cost + residency as recommended headroom for the full run |
| Image / Audio / Video generation | Submit-time reserves are worst-case formulas over the model's `ModelPricingRegistry` rate card: image `imageFeeWeiPerPixel × 2048² × max(200 / imageStepsBaseline, 1)`; audio `audioFeeWeiPerSecond × 900 s`; video `(videoBaseFeeWei + videoFeeWeiPerPixelSecond × 2048² × 60 s) × max(200 / videoStepsBaseline, 1) × max(60 / videoFpsBaseline, 1)`. Genesis rate cards: black-forest-labs/FLUX.2-klein-4B 39.6 gwei/px (min 5e14 wei); Wan2.2 2.05e17 wei base + 1.456e12 wei/px·s; LFM2.5 audio 3.33e13 wei/s (min 1e14 wei). Resulting reserves: image ≈ **2.2 RITUAL**; audio ≈ 0.03 RITUAL; video ≈ **13,750 RITUAL**. Read `ModelPricingRegistry.getModel(name)` on the chain you target — deposit at least the reserve, not the realized fee |

> With just-in-time funding only one max-cost execution must be funded/allowed at schedule time; the `N ×` figure above is recommended headroom for the full run, not a protocol requirement to escrow up front.

### Where the cost actually comes from (and why agent calls dominate)

For most long-running async lanes the per-call cost surfaces in **Phase 2**, not Phase 1; the sovereign agent is the exception — its Phase 1 settlement fee (0.018 RIT) is a large share of a deterministic ~0.14 RIT per run. The base constants (in wei):

| Component | Constant | Notes |
|-----------|----------|-------|
| HTTP executor base fee | `HTTP_EXECUTOR_BASE_FEE_WEI = 10_000_000_000_000_000` (0.01 RIT) | Per call, plus 0.35 gwei/byte for request / response body; the commitment reserve is `http_executor_fee(input_len, HTTP_CALL_MAX_OUTPUT_BYTES)` = 0.01 RIT + 0.35 gwei × (input + 5120), so a single HTTP call needs slightly more than 0.01 RITUAL |
| LLM executor fee (per-model rate card) | `llmBaseFeeWei`, `llmFeeWeiPerInputToken`, `llmFeeWeiPerOutputToken`, `llmCachedInputDiscountBps` — per model in `ModelPricingRegistry` (slots +13..+16), not constants in `constants.rs` | `fee = llmBaseFeeWei + inRate × fresh_prompt + inRate × (cachedBps / 10000) × cached_prompt + outRate × completion` (`llm_compute_fee_wei`). Linear in tokens and cache-aware. A model with input rate 0 has no LLM pricing and the job is rejected. |
| LLM error fee (when `has_error=true` is returned) | `LLM_ERROR_EXECUTOR_FEE_WEI = 10_000_000_000_000_000` (0.01 RIT) | Even failed LLM calls pay an executor fee, equal to the HTTP base fee. |
| Sovereign Agent Phase 1 settlement | `SOVEREIGN_AGENT_PHASE1_SETTLEMENT_FEE_WEI = 18_000_000_000_000_000` (0.018 RIT) | Fixed per run. |
| Sovereign Agent iteration fee (lockup sizing only) | `SOVEREIGN_AGENT_ITERATION_FEE_WEI = 115_000_000_000_000` (0.000115 RITUAL) | Sizes the fixed max-work lockup only: every completion pays `agent_escrow_lockup(SOVEREIGN_AGENT_MAX_ITERATIONS = 50, SOVEREIGN_AGENT_MAX_TOOL_CALLS = 500)` = 50 × 1.15e14 + 500 × 2.3e14 ≈ 1.2075e17 wei (~0.121 RIT) regardless of how many iterations actually ran (`calculate_agent_fees_phase2`). |
| Sovereign Agent tool-call fee (lockup sizing only) | `SOVEREIGN_AGENT_TOOL_CALL_FEE_WEI = 230_000_000_000_000` (0.00023 RITUAL) | Multiplied by the fixed cap `SOVEREIGN_AGENT_MAX_TOOL_CALLS = 500` inside the same max-work lockup charged on every completion; the actual tool-call count does not change the fee. |
| Long-running HTTP per-poll-block fee | `FEE_PER_POLL_BLOCK_WEI = 1_000_000_000_000` (0.000001 RITUAL per block) | Used to pre-reserve worst-case Phase 2 polling cost for long-running HTTP (0x0805). |

For **long-running HTTP (0x0805)** the commitment PRE-RESERVES a worst-case Phase-2 polling escrow at submit time, in addition to the Phase-1 `http_executor_fee`. The total reserve is `http_executor_fee(input_len, HTTP_CALL_MAX_OUTPUT_BYTES) + long_running_http_phase2_escrow(input)`, where `long_running_http_phase2_escrow = FEE_PER_POLL_BLOCK_WEI × (ttl + max_poll_block) + http_executor_fee(0, HTTP_CALL_MAX_OUTPUT_BYTES)` (a worst-case payload fee). So a larger `ttl` / `max_poll_block` linearly raises the up-front `availableBalance` reserve. `max_poll_block` (the offset added to `ttl`) must be non-zero (else `Long-running HTTP max_poll_block offset must be non-zero`), and `ttl + max_poll_block` must not overflow `u64`. 

Plus the user always pays the **callback gas escrow**: `deliveryGasLimit × deliveryMaxFeePerGas + deliveryValue` — this is escrowed at submit time and a portion is refunded if the callback uses less. For a `deliveryGasLimit` of `500_000` at 1 gwei that's `5×10¹⁴ wei = 0.0005 RITUAL` of escrow per call. For **long-running HTTP (0x0805)**, the commitment also escrows a worst-case polling fee `FEE_PER_POLL_BLOCK_WEI × (ttl + max_poll_block)` plus a worst-case payload fee at submit time, so the reserved amount grows with `max_poll_block` (and `ttl`), not just the callback budget.

For a sovereign agent run the executor fee is deterministic — iterations and tool calls are not metered: `calculate_agent_fees_phase2(output_len) = agent_escrow_lockup(50, 500) + http_output_byte_fee(output_len)` ≈ `1.2075e17 + 3.5e8 × output_bytes` wei, i.e. ~0.121 RITUAL per completion (+ at most 3.584e12 wei for the `SOVEREIGN_AGENT_OUTPUT_SIZE_BYTES = 10 * 1024` cap; larger output is rejected by `validate_phase2_payload_len`). Add Phase 1 (1.8e16 wei) and a 500K-gas callback at 1 gwei (5e14 wei): `1.8e16 + 1.2075e17 + 5e14 ≈ 1.39e17 wei ≈ 0.14 RITUAL` per run from these constants. The commitment reserve is `calculate_agent_fees_phase1().executor_fee + agent_escrow_lockup(50, 500) + http_output_byte_fee(10 KiB)` plus the callback gas escrow. `http_output_byte_fee` excludes the HTTP base fee, so the 0.01 RIT HTTP base fee is NOT re-charged on agent delivery. What moves the cost above that floor is only **(a)** a larger callback `callbackGasLimit` × `callbackMaxFeePerGas` budget (13-field `AgentAsyncEnvelope`; `pollIntervalBlocks` / `maxPollBlock` do not exist on the agent envelope — the Phase-2 deadline is `phase2Ttl`) or **(b)**, for LLM calls the agent makes on its own account, the model's on-chain LLM rate card (per-token input/output rates and base fee in `ModelPricingRegistry`). Treat **1 RITUAL per sovereign run** as conservative sizing guidance, not permission to spend; query current rates and classify the deployment first.

### Deposit sizing rules of thumb

| Goal | Recommended initial deposit |
|---|---|
| Build + test 1 sovereign agent end-to-end | **5 RITUAL** (5 runs of headroom) |
| Run a single sovereign agent on a recurring schedule | **`numRuns × 1 RITUAL` + safety margin** |
| Just test HTTP / LLM / multimodal precompiles | **1 RITUAL** is plenty for ~10-100 calls |

If you blow through a deposit faster than expected, it's almost always one of: oversized callback gas budget (`deliveryGasLimit`, or `callbackGasLimit` on the agent envelope), or — for long-running HTTP (0x0805) only — `maxPollBlock` set higher than needed (the chain bills polling work). Agent Phase 2 is a fixed max-work lockup plus an output-byte fee, so a deep agent loop costs the same as a shallow one. Read the per-tx `Delivered` event for `gasConsumed` and `gasRefunded` and back-fit.

## Events to Watch

```typescript
import { parseAbiItem } from 'viem';

// Watch for deposits
const depositLogs = await publicClient.getLogs({
  address: RITUAL_WALLET,
  event: parseAbiItem('event Deposit(address indexed account, uint256 amount)'),
  args: { account: account.address },
});

// Watch for withdrawals
const withdrawLogs = await publicClient.getLogs({
  address: RITUAL_WALLET,
  event: parseAbiItem('event Withdrawal(address indexed account, uint256 amount)'),
  args: { account: account.address },
});

// Watch for fee deductions (scheduled + async)
const feeLogs = await publicClient.getLogs({
  address: RITUAL_WALLET,
  event: parseAbiItem('event FeeDeduction(address indexed sponsor, uint256 amount, uint256 callId)'),
  args: { sponsor: account.address },
});

// Watch for escrow settlement credits (pull-payment).
// Recipients (executors/operators) are CREDITED at settlement, not paid directly;
// they must call withdraw() to pull. Indexers should listen for EscrowPaymentCredited
// (the credit) plus the Withdrawal event above (the pull).
const creditLogs = await publicClient.getLogs({
  address: RITUAL_WALLET,
  event: parseAbiItem('event EscrowPaymentCredited(bytes32 indexed escrowId, address indexed recipient, uint256 amount)'),
  args: { recipient: account.address },
});

// Watch for block-proposer payouts (scheduler residency fee, scheduled execution tips,
// async delivery tips). These are credited via creditProposer and surface as
// ProposerPayment, NOT EscrowPaymentCredited. callId = scheduler callId, or
// uint256(jobId) when credited by AsyncDelivery. Proposers pull via withdraw().
const proposerLogs = await publicClient.getLogs({
  address: RITUAL_WALLET,
  event: parseAbiItem('event ProposerPayment(address indexed proposer, uint256 amount, uint256 callId)'),
  args: { proposer: account.address },
});
```

## Common Errors

| Error | Cause | Fix |
|---|---|---|
| `InsufficientBalance` | `withdraw()` with amount > `availableBalance`, or `deposit()` with `msg.value = 0` | Check `availableBalance` first, or send RITUAL with deposit |
| `InsufficientAllowance` | A consumer's `reserveFrom` / deduct call ran but `allowance[sponsor][caller]` is too low | Have the sponsor `approve(consumerContract, amount)` (typically `MAX_ALLOWANCE`) before the async/scheduled call |
| `TransferFailed` | The wallet's native-token push back to the caller failed (a `withdraw()` to a contract with no `receive()`, or a failed scheduler-fee deduction (the wallet pushing collected fees to the Scheduler)) — it does not fire from escrow settlement payouts | Add `receive() external payable {}` to a contract that calls `withdraw()`. Settlement does not push funds to payment recipients: `_settle` credits each recipient's available balance (`EscrowPaymentCredited`) and the recipient pulls via `withdraw()`, so a reverting fallback on a payee cannot brick settlement |

## Quick Reference

| Item | Value |
|------|-------|
| RitualWallet address | `0xF04076756d8129Baec46Dc0F1c526Baec490C393` |
| Chain ID | 784 |
| `deposit()` | Immediately credits available balance (no lock) |
| `availableBalance(account)` | Spendable balance in wei |
| `reservedBalance(account)` | Escrowed-for-in-flight-jobs balance in wei (total = available + reserved; a payment is a drop in the available + reserved total, not in available alone) |
| `allowance(sponsor, caller)` / `approve(caller, amount)` | ERC20-style caller allowance for async/scheduled funding |
| `withdraw(amount)` / `withdraw(amount, bytes32[] expiredEscrows)` | Withdraw from available (no lock gate); the overload sweeps caller-supplied expired escrows back to available first |
| Min lock duration | None enforced — no lock-duration check on async commitments. Reth validates sponsor `availableBalance >= fees` and `allowance[sponsor][caller]`, not lock duration. |

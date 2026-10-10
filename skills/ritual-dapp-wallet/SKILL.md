---
name: ritual-dapp-wallet
description: RitualWallet integration for Ritual dApps. Use when depositing fees, checking balances, managing lock durations, or withdrawing funds.
---

# RitualWallet Integration

## What It Is

RitualWallet (`0x532F0dF0896F353d8C3DD8cc134e8129DA2a3948`) is the escrow contract through which all fees flow in the Ritual system. Users and contracts deposit RITUAL with a time lock. The system deducts fees from these balances during scheduled and async execution.

## Interface

```solidity
interface IRitualWallet {
    function deposit(uint256 lockDuration) external payable;
    function depositFor(address user, uint256 lockDuration) external payable;
    function withdraw(uint256 amount) external;
    function balanceOf(address user) external view returns (uint256);
    function lockUntil(address user) external view returns (uint256);
}
```

| Function | What It Does |
|---|---|
| `deposit(lockDuration)` | Deposit RITUAL, locked for `lockDuration` blocks from now |
| `depositFor(user, lockDuration)` | Deposit RITUAL for someone else |
| `withdraw(amount)` | Withdraw after lock expires. Reverts with `FundsLocked` if locked. |
| `balanceOf(user)` | Returns the user's balance in wei |
| `lockUntil(user)` | Returns the block number when the lock expires |

### Key behaviors:

- **Lock is monotonic** — new deposits only extend the lock, never shorten it. If you deposit with `lockDuration = 100` and later deposit with `lockDuration = 50`, the lock stays at the first value.
- **No minimum lock duration** — the contract accepts any value including 0. But the reth commitment validator checks `lockUntil >= commit_block + ttl` when accepting async commitments, so in practice you need a lock that covers your async operation window.
- **Direct RITUAL transfer** — sending raw RITUAL to the contract (no function call) credits your balance with 0 lock extension via `receive()`.
- **Fees are never deducted at schedule/submit time** — only during system transaction execution. If you schedule a call and your balance is insufficient when it fires, the execution is skipped, not reverted.

### Who needs the deposit: EOA vs Contract

For **two-phase async precompiles** (image, audio, video, Sovereign Agent, Persistent Agent, long-running HTTP), the RitualWallet balance check at commitment time is performed against the **EOA that signs the transaction**, not the contract that calls the precompile. The chain recovers the signer from the original transaction and checks `balanceOf(signer)`.

This means:
- If your contract calls `WALLET.deposit{value: ...}(lockDuration)`, the deposit goes to `address(this)` (the contract). This is correct for **scheduled transactions** where the Scheduler is the payer.
- For **async precompiles called from an EOA** (or from a contract where the EOA is the signer), the EOA must have its own deposit. Depositing only into the contract's balance will fail with `insufficient wallet balance (user: <EOA address>)`.
- Use `depositFor(eoaAddress, lockDuration)` to deposit for a specific EOA from a contract, or have the EOA call `deposit()` directly.

## TypeScript ABI

```typescript
const RITUAL_WALLET = '0x532F0dF0896F353d8C3DD8cc134e8129DA2a3948' as const;

const ritualWalletAbi = [
  {
    name: 'deposit', type: 'function', stateMutability: 'payable',
    inputs: [{ name: 'lockDuration', type: 'uint256' }],
    outputs: [],
  },
  {
    name: 'depositFor', type: 'function', stateMutability: 'payable',
    inputs: [
      { name: 'user', type: 'address' },
      { name: 'lockDuration', type: 'uint256' },
    ],
    outputs: [],
  },
  {
    name: 'withdraw', type: 'function', stateMutability: 'nonpayable',
    inputs: [{ name: 'amount', type: 'uint256' }],
    outputs: [],
  },
  {
    name: 'balanceOf', type: 'function', stateMutability: 'view',
    inputs: [{ name: 'user', type: 'address' }],
    outputs: [{ type: 'uint256' }],
  },
  {
    name: 'lockUntil', type: 'function', stateMutability: 'view',
    inputs: [{ name: 'user', type: 'address' }],
    outputs: [{ type: 'uint256' }],
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
  id: 1979,
  name: 'Ritual Chain',
  nativeCurrency: { name: 'RITUAL', symbol: 'RITUAL', decimals: 18 },
  rpcUrls: { default: { http: [process.env.RITUAL_RPC_URL!] } },
});

const account = privateKeyToAccount(process.env.PRIVATE_KEY! as `0x${string}`);
const publicClient = createPublicClient({ chain: ritualChain, transport: http() });
const walletClient = createWalletClient({ account, chain: ritualChain, transport: http() });

// Check current balance and lock
const balance = await publicClient.readContract({
  address: RITUAL_WALLET, abi: ritualWalletAbi,
  functionName: 'balanceOf', args: [account.address],
});
const lockExpiry = await publicClient.readContract({
  address: RITUAL_WALLET, abi: ritualWalletAbi,
  functionName: 'lockUntil', args: [account.address],
});
const currentBlock = await publicClient.getBlockNumber();

console.log(`Balance: ${formatEther(balance)} RITUAL`);
console.log(`Lock expires at block ${lockExpiry} (current: ${currentBlock})`);
console.log(`Locked: ${currentBlock < lockExpiry}`);

// Deposit 0.5 RITUAL with 10,000 block lock
const depositHash = await walletClient.writeContract({
  address: RITUAL_WALLET, abi: ritualWalletAbi,
  functionName: 'deposit',
  args: [10000n],
  value: parseEther('0.5'),
});
await publicClient.waitForTransactionReceipt({ hash: depositHash });
```

## TypeScript: Withdraw After Lock Expires

```typescript
const lockExpiry = await publicClient.readContract({
  address: RITUAL_WALLET, abi: ritualWalletAbi,
  functionName: 'lockUntil', args: [account.address],
});
const currentBlock = await publicClient.getBlockNumber();

if (currentBlock >= lockExpiry) {
  const balance = await publicClient.readContract({
    address: RITUAL_WALLET, abi: ritualWalletAbi,
    functionName: 'balanceOf', args: [account.address],
  });

  const hash = await walletClient.writeContract({
    address: RITUAL_WALLET, abi: ritualWalletAbi,
    functionName: 'withdraw',
    args: [balance], // withdraw everything
  });
  await publicClient.waitForTransactionReceipt({ hash });
  console.log(`Withdrew ${formatEther(balance)} RITUAL`);
} else {
  console.log(`Funds locked until block ${lockExpiry} (${lockExpiry - currentBlock} blocks remaining)`);
}
```

## Solidity: Contract Integration

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

interface IRitualWallet {
    function deposit(uint256 lockDuration) external payable;
    function balanceOf(address user) external view returns (uint256);
    function lockUntil(address user) external view returns (uint256);
    function withdraw(uint256 amount) external;
}

contract MyDApp {
    IRitualWallet constant WALLET = IRitualWallet(0x532F0dF0896F353d8C3DD8cc134e8129DA2a3948);

    function depositFees(uint256 lockBlocks) external payable {
        WALLET.deposit{value: msg.value}(lockBlocks);
    }

    function checkFeeBalance() external view returns (uint256 balance, uint256 lockExpiry, bool isLocked) {
        balance = WALLET.balanceOf(address(this));
        lockExpiry = WALLET.lockUntil(address(this));
        isLocked = block.number < lockExpiry;
    }

    function withdrawFees(uint256 amount) external {
        require(block.number >= WALLET.lockUntil(address(this)), "still locked");
        WALLET.withdraw(amount);
    }

    receive() external payable {}
}
```

## React: Balance Display Component

```typescript
import { useAccount, useReadContract } from 'wagmi';
import { formatEther } from 'viem';

const RITUAL_WALLET = '0x532F0dF0896F353d8C3DD8cc134e8129DA2a3948' as const;

const walletAbi = [
  { name: 'balanceOf', type: 'function', stateMutability: 'view',
    inputs: [{ name: 'user', type: 'address' }], outputs: [{ type: 'uint256' }] },
  { name: 'lockUntil', type: 'function', stateMutability: 'view',
    inputs: [{ name: 'user', type: 'address' }], outputs: [{ type: 'uint256' }] },
] as const;

function WalletBalance() {
  const { address } = useAccount();

  const { data: balance } = useReadContract({
    address: RITUAL_WALLET, abi: walletAbi,
    functionName: 'balanceOf', args: address ? [address] : undefined,
    query: { enabled: !!address },
  });

  const { data: lockExpiry } = useReadContract({
    address: RITUAL_WALLET, abi: walletAbi,
    functionName: 'lockUntil', args: address ? [address] : undefined,
    query: { enabled: !!address },
  });

  if (!address) return <p>Connect wallet</p>;

  return (
    <div>
      <p>Balance: {balance !== undefined ? formatEther(balance) : '...'} RITUAL</p>
      <p>Lock expires: block {lockExpiry?.toString() ?? '...'}</p>
    </div>
  );
}
```

Check for `undefined` rather than truthiness: `0n` is a successfully loaded zero balance, but it is
falsy and would otherwise leave a newly funded account showing the loading placeholder.

## How Funds Flow

RitualWallet is the single payment surface for all three execution models. Each model moves funds differently.

### Scheduled Transactions

```
User's RitualWallet
  │
  ├─ deductExecutionFees() ──► Scheduler (receives RITUAL)
  │                                │
  │                                ├─ target.call{gas, value}(data)  ← callback executes
  │                                │
  │                                └─ refundGas() ──► User's RitualWallet (unused gas returned)
  │
  └─ REVM burns Scheduler balance (fund sink — remaining RITUAL destroyed)
```

The Scheduler holds RITUAL only during the callback. After execution, REVM zeros the Scheduler's balance so no funds leak to the block proposer or accumulate in the contract.

**Who gets paid:** Nobody external — the user pays for gas, unused gas is refunded, and the remainder is burned.

### Async Short-Running Transactions (HTTP, LLM)

```
User's RitualWallet
  │
  └─ settlePhase1Fees() ──► Three recipients paid atomically:
                              ├─ Executor         (executorFee)
                              ├─ Commitment Validator (commitmentFee)
                              └─ Inclusion Validator  (inclusionFee)
```

No fund sink needed here — `settlePhase1Fees` pays the three parties directly from the user's balance. There's no intermediate contract holding funds.

**Who gets paid:** The executor who ran the computation, the validator who included the commitment, and the validator who included the settlement.

### Async Long-Running Transactions (Sovereign Agent, Persistent Agent, Long HTTP, Image, ZK, etc.)

Two settlement events, one per phase:

**Phase 1 (commitment settled):**
```
User's RitualWallet
  └─ settlePhase1Fees() ──► Executor + Commitment Validator + Inclusion Validator
```

**Phase 2 (delivery callback):**
```
User's RitualWallet
  │
  ├─ payExecutor() ──► Executor (Phase 2 work fee)
  │
  ├─ deductExecutionFees() ──► AsyncDelivery (receives RITUAL for callback)
  │                                │
  │                                ├─ target.call{gas, value}(selector, jobId, result)  ← callback
  │                                │
  │                                └─ refundGas() ──► User's RitualWallet (unused gas + value if reverted)
  │
  └─ REVM burns AsyncDelivery balance (fund sink — remaining RITUAL destroyed)
```

AsyncDelivery follows the same fund sink pattern as the Scheduler: it holds RITUAL only during the callback, then REVM zeros its balance.

**Who gets paid:** Phase 1 — executor + two validators. Phase 2 — executor again (for polling/generation work), plus the callback target receives the result (and optionally RITUAL via `deliveryValue`).

---

## How Much to Deposit

| Use Case | Lock Duration | Deposit Estimate (with headroom) |
|---|---|---|
| Single HTTP call | `ttl + buffer` (~600 blocks) | 0.01 RITUAL |
| Single LLM call | `ttl + buffer` (~600 blocks) | 0.05 RITUAL (model + token-count dependent) |
| Sovereign Agent job | `ttl + maxPollBlock` (~1500 blocks min, often more) | **1 RITUAL per intended run** (deep agents with several iterations + tool calls have been measured at **0.5 - 1 RITUAL** — one user reported 0.86 RITUAL for a single run) |
| Persistent Agent job | `ttl + maxPollBlock` (~1500 blocks) | 0.5 - 1 RITUAL (similar shape to Sovereign) |
| Scheduled recurring (N calls) | `startBlock + frequency * numCalls - block.number` | N × (per-call cost + `gasLimit × maxFeePerGas`) |
| Image / Audio / Video generation | `ttl + maxPollBlock` (~1500 blocks) | 0.01+ RITUAL (resolution / duration dependent) |

> **Lock duration on Ritual's ~350ms conservative baseline:** 5,000 blocks ≈ 29 minutes, 10,000 ≈ 58 minutes. For development, use `100,000` blocks (~9.7 hours) to avoid lock expiry during iteration. The lock only extends (never shortens), so over-locking has no downside. Confirm against current cadence with `ritual-dapp-block-time`.

### Where the cost actually comes from (and why agent calls dominate)

Most of the per-call cost surfaces in **Phase 2** of long-running async, not Phase 1. The base constants (in wei) are:

| Component | Constant | Notes |
|-----------|----------|-------|
| HTTP executor base fee | `HTTP_EXECUTOR_BASE_FEE_WEI = 2_500_000_000_000` | Per call, plus per-byte rates for request / response body |
| LLM executor gas price | `LLM_EXECUTOR_GAS_PRICE_WEI = 1_000_000_000` (1 gwei) | Multiplied by `llm_compute_gas(prompt_tokens, completion_tokens, model.params_b, model.theta)`. Bigger prompts and bigger models cost more, super-linearly past 2K and 4K tokens. |
| LLM error fee (when `has_error=true` is returned) | `LLM_ERROR_EXECUTOR_FEE_WEI = 500_000_000_000` (0.0000005 ETH) | Even failed LLM calls pay a small executor fee. |
| Sovereign Agent Phase 1 settlement | `SOVEREIGN_AGENT_PHASE1_SETTLEMENT_FEE_WEI = 500_000_000_000` (0.0000005 ETH) | Tiny — just orchestration. |
| Sovereign Agent per ReAct iteration | `SOVEREIGN_AGENT_ITERATION_FEE_WEI = 115_000_000_000_000` (0.000115 ETH) | Each LLM-step iteration adds this. |
| Sovereign Agent per tool call | `SOVEREIGN_AGENT_TOOL_CALL_FEE_WEI = 230_000_000_000_000` (0.00023 ETH) | Each tool execution adds this. |

Plus the user always pays the **callback gas escrow**: `deliveryGasLimit × deliveryMaxFeePerGas + deliveryValue` — this is escrowed at submit time and a portion is refunded if the callback uses less. For a `deliveryGasLimit` of `500_000` at 1 gwei that's `5×10¹⁴ wei = 0.0005 RITUAL` of escrow per call.

For a sovereign agent run at, say, 30 iterations + 10 tool calls + a 500K-gas callback at 1 gwei: `30 × 1.15e14 + 10 × 2.3e14 + 5e14 = ~6.25e15 wei ≈ 0.006 RITUAL` from these constants. The user-reported **0.86 RITUAL** is much higher than the bare per-iteration sum — that delta typically comes from **(a)** larger callback `deliveryGasLimit` × `deliveryMaxFeePerGas` budgets, **(b)** deeper iterations / more tool calls than expected, **(c)** higher `pollIntervalBlocks` / `maxPollBlock` keeping the executor busy longer, or **(d)** model-dependent LLM gas formula (large models like 355B GLM cost much more than small models per token). Treat **1 RITUAL per sovereign run** as a safe upper bound for your faucet sizing on testnet.

### Faucet sizing rules of thumb

| Goal | Recommended initial faucet |
|---|---|
| Build + test 1 sovereign agent end-to-end | **5 RITUAL** (5 runs of headroom) |
| Run a single sovereign agent on a recurring schedule | **`numRuns × 1 RITUAL` + safety margin** |
| Just test HTTP / LLM / multimodal precompiles | **1 RITUAL** is plenty for ~10-100 calls |

If you blow through a faucet faster than expected, it's almost always one of: oversized `deliveryGasLimit`, `maxPollBlock` set higher than needed (the chain bills polling work), or an agent loop that ran way more iterations than `maxIterations` would suggest because of nested tool calls. Read the per-tx `Delivered` event for `gasConsumed` and `gasRefunded` and back-fit.

## Events to Watch

```typescript
import { parseAbiItem } from 'viem';

// Watch for deposits
const depositLogs = await publicClient.getLogs({
  address: RITUAL_WALLET,
  event: parseAbiItem('event Deposit(address indexed user, uint256 amount, uint256 lockUntil)'),
  args: { user: account.address },
});

// Watch for withdrawals
const withdrawLogs = await publicClient.getLogs({
  address: RITUAL_WALLET,
  event: parseAbiItem('event Withdrawal(address indexed user, uint256 amount)'),
  args: { user: account.address },
});

// Watch for fee deductions (scheduled + async)
const feeLogs = await publicClient.getLogs({
  address: RITUAL_WALLET,
  event: parseAbiItem('event FeeDeduction(address indexed user, uint256 amount, uint256 callId)'),
  args: { user: account.address },
});
```

## Common Errors

| Error | Cause | Fix |
|---|---|---|
| `InsufficientBalance` | `withdraw()` with amount > balance, or `deposit()` with `msg.value = 0` | Check balance first, or send RITUAL with deposit |
| `FundsLocked` | `withdraw()` before lock expires | Wait for `block.number >= lockUntil(address)` |
| `TransferFailed` | Contract can't receive RITUAL (missing `receive()`) | Add `receive() external payable {}` to your contract |

## Quick Reference

| Item | Value |
|------|-------|
| RitualWallet address | `0x532F0dF0896F353d8C3DD8cc134e8129DA2a3948` |
| Chain ID | 1979 |
| `deposit(lockDuration)` | Lock in blocks, monotonic (only extends) |
| `balanceOf(user)` | Balance in wei |
| `lockUntil(user)` | Block number when lock expires |
| `withdraw(amount)` | Only after lock expires |
| Min lock duration | None enforced in contract (reth checks `lockUntil >= commit_block + ttl`) |

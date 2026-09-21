---
name: ritual-dapp-frontend
description: Frontend development for Ritual dApps with async transaction state machines, wagmi/viem hooks, and event subscriptions. Use when building React/Next.js frontends for Ritual.
version: 1.0.0
---

# Ritual dApp Frontend

Build React/Next.js frontends for Ritual Chain dApps. Use wagmi v2 (`^2.12.0`) + viem v2. The encoding logic (viem) is framework-agnostic; the hooks below are React-specific.

---

## Critical: writeContractAsync Breaks on Async Precompiles

Async precompiles (HTTP 0x0801, LLM 0x0802, etc.) are not deployed contracts — they are handled at the EVM level. wagmi's `writeContractAsync` runs `simulateContract` (which uses `eth_call`) before sending, and `eth_call` against a precompile returns "call to non-contract address".

**Any `useWriteContract` call to a function that internally calls an async precompile will always revert in simulation.**

Use `useSendTransaction` with `encodeFunctionData` instead to skip simulation:

```typescript
import { encodeFunctionData } from "viem";
import { useSendTransaction } from "wagmi";

const { sendTransactionAsync } = useSendTransaction();

const data = encodeFunctionData({
  abi: contractAbi,
  functionName: "yourAsyncFunction",
  args: [executor, ttl],
});

const hash = await sendTransactionAsync({
  to: contractAddress,
  data,
  gas: 2_000_000n,
});
```

This applies to ANY contract function that calls an async precompile internally. Use `useWriteContract` only for pure reads or functions that don't touch async precompiles.

---

## 1. Chain Configuration

Define the Ritual chain ONCE and reference everywhere:

```typescript
import { defineChain } from "viem";

export const ritualChain = defineChain({
  id: 1979,
  name: "Ritual",
  nativeCurrency: { name: "RITUAL", symbol: "RITUAL", decimals: 18 },
  rpcUrls: {
    default: {
      http: [process.env.NEXT_PUBLIC_RPC_URL ?? "https://rpc.ritualfoundation.org"],
    },
  },
  blockExplorers: {
    default: { name: "Ritual Explorer", url: "https://explorer.ritualfoundation.org" },
  },
});
```

### ChainGuard — Block UI on Wrong Chain

```tsx
import { useAccount, useSwitchChain } from "wagmi";
import { ritualChain } from "@/lib/chain";

export function ChainGuard({ children }: { children: React.ReactNode }) {
  const { chain, isConnected } = useAccount();
  const { switchChain, isPending } = useSwitchChain();

  if (isConnected && chain?.id !== ritualChain.id) {
    return (
      <button
        onClick={() => switchChain({ chainId: ritualChain.id })}
        disabled={isPending}
        className="px-4 py-2 bg-amber-500/10 border border-amber-500 text-amber-400 rounded-lg text-sm
                   focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500/50
                   focus-visible:ring-offset-2 focus-visible:ring-offset-black"
      >
        {isPending ? "Switching..." : "Switch to Ritual Chain"}
      </button>
    );
  }

  return <>{children}</>;
}
```

### Browser RPC Proxy (Critical Pitfall)

Frontend frameworks make JSON-RPC calls **from the user's browser**. If the Ritual RPC endpoint is not publicly accessible from the browser (internal IP, firewall-blocked), **all contract reads silently fail** — the UI shows empty data with no error.

**Symptoms:** `useReadContract` returns `undefined`. dApp works server-side but shows nothing in browser. Network tab shows failed RPC requests.

**Fix:** Proxy through a Next.js API route:

```typescript
// app/api/rpc/route.ts
import { NextRequest, NextResponse } from "next/server";

const RPC_URL = process.env.RITUAL_RPC_URL ?? "https://rpc.ritualfoundation.org";

export async function POST(req: NextRequest) {
  const body = await req.json();
  const res = await fetch(RPC_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return NextResponse.json(await res.json());
}
```

Then configure wagmi transport:

```typescript
import { createConfig, http } from "wagmi";
import { ritualChain } from "./chain";

export const wagmiConfig = createConfig({
  chains: [ritualChain],
  connectors: [injected()],
  transports: {
    [ritualChain.id]: http("/api/rpc"),
  },
});
```

Use the proxy when the RPC is not browser-accessible. The public `https://rpc.ritualfoundation.org` endpoint is browser-accessible.

---

## 2. Async Transaction State Machine

Ritual precompile calls pass through up to 9 states from submission to settlement. Some states map directly to on-chain events; others are UI-interpolated with no on-chain signal:

| State | On-chain signal | Source |
|-------|----------------|--------|
| SUBMITTING | — | Local (wallet interaction) |
| PENDING_COMMITMENT | — | Local (tx sent, awaiting inclusion) |
| COMMITTED | `JobAdded` event | AsyncJobTracker |
| EXECUTOR_PROCESSING | — | UI-interpolated (time since COMMITTED) |
| RESULT_READY | `Phase1Settled` event (long-running only) | AsyncJobTracker |
| PENDING_SETTLEMENT | — | UI-interpolated (long-running async only, awaiting callback) |
| SETTLED | `ResultDelivered(success=true)` (long-running) or `JobRemoved(completed=true)` + `spcCalls` in receipt (short-running) | AsyncJobTracker or receipt |
| FAILED | `SettlementFailed`, `DeliveryFailed`, `ResultDelivered(success=false)`, or `JobRemoved(completed=false)` from cleanup | AsyncDelivery / AsyncJobTracker |
| EXPIRED | — | Derived (current block > commit block + TTL); confirmed by cleanup `JobRemoved(completed=false)` |

> **What `Phase1Settled` actually means (it's a footgun).** This event does NOT mean the underlying job is done. It is emitted from `AsyncJobTracker.markPhase1Settled` only for **long-running** precompiles, after `AsyncDelivery.settle` has paid the executor + validators for Phase 1. At that point:
> - **Short-running** (HTTP, LLM, ONNX, JQ, DKMS, …): `Phase1Settled` is **never emitted**. The result is already in the receipt's `spcCalls` and `JobRemoved(completed=true)` fires instead.
> - **Long-running** (Long HTTP, Sovereign Agent, Persistent Agent, Image / Audio / Video, ZK, FHE): `Phase1Settled` means the executor has *committed to starting* the off-chain work and the Phase 2 deadline is now armed. The actual job result lands later via `ResultDelivered` + `Delivered`. For these jobs, the "Phase 1 result" is just the **task ID**, not the final payload.
>
> So map `Phase1Settled → RESULT_READY` only for long-running async, and treat `RESULT_READY` as "executor accepted the job" rather than "result available".

### State Diagram

```
User submits tx
       │
       ▼
  SUBMITTING ──────► FAILED (tx reverted / user rejected)
       │
       ▼
PENDING_COMMITMENT ──► EXPIRED (no executor within TTL)
       │
       ▼
   COMMITTED ──────► FAILED (executor errored)
       │
       ▼
EXECUTOR_PROCESSING
       │
       ▼
  RESULT_READY ────► FAILED (delivery failed)
       │
       ▼
PENDING_SETTLEMENT
       │
       ▼
    SETTLED ◄──────── (final success state)
```

### Full TypeScript Types

```typescript
export type AsyncTxStatus =
  | "SUBMITTING"
  | "PENDING_COMMITMENT"
  | "COMMITTED"
  | "EXECUTOR_PROCESSING"
  | "RESULT_READY"
  | "PENDING_SETTLEMENT"
  | "SETTLED"
  | "FAILED"
  | "EXPIRED";

export interface AsyncTxSubmitting { status: "SUBMITTING" }

export interface AsyncTxPendingCommitment {
  status: "PENDING_COMMITMENT";
  txHash: `0x${string}`;
  submittedAt: number;
  ttlBlocks: number;
}

export interface AsyncTxCommitted {
  status: "COMMITTED";
  txHash: `0x${string}`;
  jobId: `0x${string}`;
  executor: `0x${string}`;
  committedBlock: number;
}

export interface AsyncTxExecutorProcessing {
  status: "EXECUTOR_PROCESSING";
  txHash: `0x${string}`;
  jobId: `0x${string}`;
  executor: `0x${string}`;
  startBlock: number;
  estimatedBlocks: number;
}

export interface AsyncTxResultReady {
  status: "RESULT_READY";
  txHash: `0x${string}`;
  jobId: `0x${string}`;
  settledBlock: number;
}

export interface AsyncTxPendingSettlement {
  status: "PENDING_SETTLEMENT";
  txHash: `0x${string}`;
  jobId: `0x${string}`;
  deliveryTxHash?: `0x${string}`;
}

export interface AsyncTxSettled {
  status: "SETTLED";
  txHash: `0x${string}`;
  jobId: `0x${string}`;
  result: unknown;
  settlementTxHash: `0x${string}`;
  settledBlock: number;
  gasUsed: number;
}

export interface AsyncTxFailed {
  status: "FAILED";
  txHash?: `0x${string}`;
  jobId?: `0x${string}`;
  error: string;
  errorCategory: ErrorCategory;
  failedAt: AsyncTxStatus;
}

export interface AsyncTxExpired {
  status: "EXPIRED";
  txHash: `0x${string}`;
  submittedAt: number;
  expiredAt: number;
  ttlBlocks: number;
}

export type AsyncTxState =
  | AsyncTxSubmitting
  | AsyncTxPendingCommitment
  | AsyncTxCommitted
  | AsyncTxExecutorProcessing
  | AsyncTxResultReady
  | AsyncTxPendingSettlement
  | AsyncTxSettled
  | AsyncTxFailed
  | AsyncTxExpired;

export type ErrorCategory = "wallet" | "contract" | "async" | "network";
```

### State Transition Logic

```typescript
export function canTransition(from: AsyncTxStatus, to: AsyncTxStatus): boolean {
  const valid: Record<AsyncTxStatus, AsyncTxStatus[]> = {
    SUBMITTING: ["PENDING_COMMITMENT", "FAILED"],
    PENDING_COMMITMENT: ["COMMITTED", "EXPIRED", "FAILED"],
    COMMITTED: ["EXECUTOR_PROCESSING", "FAILED"],
    EXECUTOR_PROCESSING: ["RESULT_READY", "FAILED"],
    RESULT_READY: ["PENDING_SETTLEMENT", "SETTLED", "FAILED"],
    PENDING_SETTLEMENT: ["SETTLED", "FAILED"],
    SETTLED: [],
    FAILED: [],
    EXPIRED: [],
  };
  return valid[from]?.includes(to) ?? false;
}

export function isTerminalState(status: AsyncTxStatus): boolean {
  return status === "SETTLED" || status === "FAILED" || status === "EXPIRED";
}
```

### Transaction Store

Use Zustand with `persist` for localStorage persistence. The store shape tracks in-flight Ritual transactions:

```typescript
import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { AsyncTxState, AsyncTxStatus } from "@/types/asyncTx";

interface TrackedTransaction {
  id: string;
  precompileType: "http" | "llm" | "agent" | "longhttp" | "image" | "audio" | "video";
  state: AsyncTxState;
  createdAt: number;
  updatedAt: number;
  label?: string;
}

interface AsyncTxStore {
  transactions: Record<string, TrackedTransaction>;
  addTransaction: (id: string, precompileType: TrackedTransaction["precompileType"], label?: string) => void;
  updateState: (id: string, newState: AsyncTxState) => void;
  getTransaction: (id: string) => TrackedTransaction | undefined;
  getActiveTransactions: () => TrackedTransaction[];
  clearSettled: () => void;
}

export const useAsyncTxStore = create<AsyncTxStore>()(
  persist(
    (set, get) => ({
      transactions: {},
      addTransaction: (id, precompileType, label) =>
        set((s) => ({
          transactions: { ...s.transactions, [id]: { id, precompileType, state: { status: "SUBMITTING" }, createdAt: Date.now(), updatedAt: Date.now(), label } },
        })),
      updateState: (id, newState) =>
        set((s) => {
          const existing = s.transactions[id];
          if (!existing) return s;
          return { transactions: { ...s.transactions, [id]: { ...existing, state: { ...existing.state, ...newState }, updatedAt: Date.now() } } };
        }),
      getTransaction: (id) => get().transactions[id],
      getActiveTransactions: () => Object.values(get().transactions).filter((tx) => !isTerminalState(tx.state.status)),
      clearSettled: () =>
        set((s) => ({
          transactions: Object.fromEntries(Object.entries(s.transactions).filter(([, tx]) => !isTerminalState(tx.state.status))),
        })),
    }),
    { name: "ritual-async-tx" },
  ),
);
```

Transactions survive page refresh. The `persist` middleware writes to localStorage keyed by `"ritual-async-tx"`.

---

## 3. spcCalls Receipt Parsing

When a short-running async precompile (HTTP `0x0801`, LLM `0x0802`) settles, the result is in the transaction receipt's `spcCalls` field — a Ritual-specific extension not present on standard EVM receipts.

```typescript
import { decodeAbiParameters } from "viem";

interface RitualReceipt {
  spcCalls?: Array<{ input: `0x${string}`; output: `0x${string}` }>;
}

function extractSpcResult(receipt: unknown): `0x${string}` | null {
  const spcCalls = (receipt as RitualReceipt).spcCalls;
  if (!spcCalls || spcCalls.length === 0) return null;
  return spcCalls[0].output;
}

function decodeHTTPResponse(output: `0x${string}`) {
  const [statusCode, headerKeys, headerValues, body, errorMessage] =
    decodeAbiParameters(
      [{ type: "uint16" }, { type: "string[]" }, { type: "string[]" }, { type: "bytes" }, { type: "string" }],
      output,
    );
  return {
    statusCode,
    headers: Object.fromEntries(headerKeys.map((k, i) => [k, headerValues[i]])),
    body: new TextDecoder().decode(Buffer.from((body as string).slice(2), 'hex')),
    error: errorMessage || null,
  };
}
```

---

## 4. Core Hooks

### useRitualWrite — Bypass Broken eth_call Simulation

```typescript
import { useSendTransaction } from "wagmi";
import { encodeFunctionData, type Abi } from "viem";

export function useRitualWrite() {
  const { sendTransactionAsync } = useSendTransaction();

  async function write({
    address, abi, functionName, args = [], value, gas = 300_000n, nonce,
  }: {
    address: `0x${string}`;
    abi: Abi;
    functionName: string;
    args?: unknown[];
    value?: bigint;
    gas?: bigint;
    nonce?: number;
  }) {
    const data = encodeFunctionData({ abi, functionName, args });
    return sendTransactionAsync({ to: address, data, value, gas, nonce });
  }

  return { write };
}
```

### useAsyncJobEvents — Watch AsyncJobTracker

The AsyncJobTracker uses `bytes32` job IDs (not `uint256`). The on-chain events are:

- **`JobAdded`** — emitted when a job is committed by the chain (maps to `COMMITTED` state)
- **`Phase1Settled`** — emitted only for **long-running** async, when the executor's Phase 1 settlement TX has paid Phase 1 fees and armed the Phase 2 deadline (maps to `RESULT_READY` for long-running). **Not emitted for short-running async** — short-running jobs jump straight from `JobAdded` to `JobRemoved(completed=true)` via `AsyncDelivery.Settled`.
- **`ResultDelivered`** — emitted when the long-running callback actually delivers (maps to `SETTLED` if `success=true`, `FAILED` if `success=false`)
- **`AsyncDelivery.SettlementFailed` / `DeliveryFailed`** — payment-side failures (insufficient RitualWallet balance for Phase 1 fees or Phase 2 callback gas+value); job lingers until cleanup removes it as expired
- **`JobRemoved`** — emitted when a job is cleaned up

Note: `EXECUTOR_PROCESSING` and `PENDING_SETTLEMENT` are UI-interpolated states — there is no on-chain event for them. Derive them from timing (blocks elapsed since `JobAdded`).

```typescript
import { useWatchContractEvent, useAccount } from "wagmi";
import { useAsyncTxStore } from "@/stores/asyncTxStore";

const ASYNC_JOB_TRACKER = "0xC069FFCa0389f44eCA2C626e55491b0ab045AEF5" as const;

const asyncJobTrackerAbi = [
  {
    type: "event", name: "JobAdded",
    inputs: [
      { name: "executor", type: "address", indexed: true },
      { name: "jobId", type: "bytes32", indexed: true },
      { name: "precompileAddress", type: "address", indexed: true },
      { name: "commitBlock", type: "uint256", indexed: false },
      { name: "precompileInput", type: "bytes", indexed: false },
      { name: "senderAddress", type: "address", indexed: false },
      { name: "previousBlockHash", type: "bytes32", indexed: false },
      { name: "previousBlockNumber", type: "uint256", indexed: false },
      { name: "previousBlockTimestamp", type: "uint256", indexed: false },
      { name: "ttl", type: "uint256", indexed: false },
      { name: "createdAt", type: "uint256", indexed: false },
    ],
  },
  {
    type: "event", name: "Phase1Settled",
    inputs: [
      { name: "jobId", type: "bytes32", indexed: true },
      { name: "executor", type: "address", indexed: true },
      { name: "settledBlock", type: "uint256", indexed: false },
    ],
  },
  {
    type: "event", name: "ResultDelivered",
    inputs: [
      { name: "jobId", type: "bytes32", indexed: true },
      { name: "target", type: "address", indexed: true },
      { name: "success", type: "bool", indexed: false },
    ],
  },
  {
    type: "event", name: "JobRemoved",
    inputs: [
      { name: "executor", type: "address", indexed: true },
      { name: "jobId", type: "bytes32", indexed: true },
      { name: "completed", type: "bool", indexed: true },
    ],
  },
  {
    type: "function", name: "hasPendingJobForSender",
    inputs: [{ name: "sender", type: "address" }],
    outputs: [{ type: "bool" }],
    stateMutability: "view",
  },
] as const;

export function useAsyncJobEvents({ txId, enabled = true }: { txId: string; enabled?: boolean }) {
  const { address } = useAccount();
  const updateState = useAsyncTxStore((s) => s.updateState);
  const getTransaction = useAsyncTxStore((s) => s.getTransaction);

  useWatchContractEvent({
    address: ASYNC_JOB_TRACKER,
    abi: asyncJobTrackerAbi,
    eventName: "JobAdded",
    enabled: enabled && !!address,
    onLogs: (logs) => {
      for (const log of logs) {
        if (log.args.senderAddress?.toLowerCase() !== address?.toLowerCase()) continue;
        const tx = getTransaction(txId);
        if (!tx || tx.state.status !== "PENDING_COMMITMENT") continue;
        updateState(txId, {
          status: "COMMITTED",
          txHash: tx.state.txHash,
          jobId: log.args.jobId!,
          executor: log.args.executor as `0x${string}`,
          committedBlock: Number(log.args.commitBlock),
        });
      }
    },
  });

  useWatchContractEvent({
    address: ASYNC_JOB_TRACKER,
    abi: asyncJobTrackerAbi,
    eventName: "Phase1Settled",
    enabled: enabled && !!address,
    onLogs: (logs) => {
      for (const log of logs) {
        const tx = getTransaction(txId);
        if (!tx) continue;
        if (tx.state.jobId && log.args.jobId !== tx.state.jobId) continue;
        if (tx.state.status === "COMMITTED" || tx.state.status === "EXECUTOR_PROCESSING") {
          updateState(txId, {
            status: "RESULT_READY",
            txHash: tx.state.txHash,
            jobId: log.args.jobId!,
            settledBlock: Number(log.args.settledBlock),
          });
        }
      }
    },
  });

  useWatchContractEvent({
    address: ASYNC_JOB_TRACKER,
    abi: asyncJobTrackerAbi,
    eventName: "ResultDelivered",
    enabled: enabled && !!address,
    onLogs: (logs) => {
      for (const log of logs) {
        const tx = getTransaction(txId);
        if (!tx || tx.state.status !== "RESULT_READY") continue;
        if (tx.state.jobId && log.args.jobId !== tx.state.jobId) continue;
        updateState(txId, {
          status: log.args.success ? "SETTLED" : "FAILED",
          txHash: tx.state.txHash,
          jobId: log.args.jobId!,
          deliverySuccess: log.args.success,
        });
      }
    },
  });
}
```

### useSenderLock — Detect One-Async-Per-EOA Constraint

The chain rejects async submissions when the sender already has a pending job. Check before allowing submit:

```typescript
import { useAccount, useReadContract } from "wagmi";

export function useSenderLock() {
  const { address } = useAccount();

  const { data: isLocked, refetch } = useReadContract({
    address: ASYNC_JOB_TRACKER,
    abi: asyncJobTrackerAbi,
    functionName: "hasPendingJobForSender",
    args: address ? [address] : undefined,
    query: { enabled: !!address, refetchInterval: 5_000 },
  });

  return {
    isLocked: isLocked ?? false,
    refetch,
    message: isLocked ? "You have a pending async job — wait for settlement before submitting another." : null,
  };
}
```

### useRitualWallet — Balance, Deposit, Withdraw

```typescript
import { useAccount, useReadContract, useWaitForTransactionReceipt } from "wagmi";
import { parseEther, formatEther } from "viem";
import { useRitualWrite } from "./useRitualWrite";
import { useState, useCallback } from "react";

const RITUAL_WALLET = "0x532F0dF0896F353d8C3DD8cc134e8129DA2a3948" as const;

const ritualWalletAbi = [
  { type: "function", name: "balanceOf", inputs: [{ name: "user", type: "address" }], outputs: [{ type: "uint256" }], stateMutability: "view" },
  { type: "function", name: "lockUntil", inputs: [{ name: "user", type: "address" }], outputs: [{ type: "uint256" }], stateMutability: "view" },
  { type: "function", name: "deposit", inputs: [{ name: "lockDuration", type: "uint256" }], outputs: [], stateMutability: "payable" },
  { type: "function", name: "withdraw", inputs: [{ name: "amount", type: "uint256" }], outputs: [], stateMutability: "nonpayable" },
] as const;

export function useRitualWallet() {
  const { address } = useAccount();
  const { write } = useRitualWrite();

  const { data: balance, refetch: refetchBalance } = useReadContract({
    address: RITUAL_WALLET,
    abi: ritualWalletAbi,
    functionName: "balanceOf",
    args: address ? [address] : undefined,
    query: { enabled: !!address, refetchInterval: 12_000 },
  });

  const { data: lockUntilBlock } = useReadContract({
    address: RITUAL_WALLET,
    abi: ritualWalletAbi,
    functionName: "lockUntil",
    args: address ? [address] : undefined,
    query: { enabled: !!address },
  });

  const [pendingTxHash, setPendingTxHash] = useState<`0x${string}` | undefined>();
  const { isLoading: isConfirming } = useWaitForTransactionReceipt({ hash: pendingTxHash, query: { enabled: !!pendingTxHash } });

  const deposit = useCallback(async (amountEther: string, lockDurationBlocks: bigint = 5000n) => {
    const hash = await write({ address: RITUAL_WALLET, abi: ritualWalletAbi, functionName: "deposit", args: [lockDurationBlocks], value: parseEther(amountEther) });
    setPendingTxHash(hash);
    return hash;
  }, [write]);

  const withdraw = useCallback(async (amountEther: string) => {
    const hash = await write({ address: RITUAL_WALLET, abi: ritualWalletAbi, functionName: "withdraw", args: [parseEther(amountEther)] });
    setPendingTxHash(hash);
    return hash;
  }, [write]);

  return { balance, balanceFormatted: balance ? formatEther(balance) : "0", lockUntilBlock, deposit, withdraw, isConfirming, refetchBalance };
}
```

### useDepositGate — Block Submit Until Funded

```typescript
import { useRitualWallet } from "./useRitualWallet";
import { useMemo } from "react";

export function useDepositGate(estimatedFeeWei: bigint) {
  const { balance, deposit, isConfirming } = useRitualWallet();

  const hasSufficientDeposit = useMemo(() => {
    if (!balance) return false;
    return balance >= estimatedFeeWei;
  }, [balance, estimatedFeeWei]);

  return {
    hasSufficientDeposit,
    shortfall: balance ? (estimatedFeeWei > balance ? estimatedFeeWei - balance : 0n) : estimatedFeeWei,
    deposit,
    isConfirming,
    message: hasSufficientDeposit ? null : "Insufficient RitualWallet deposit. Deposit RITUAL before submitting.",
  };
}
```

### useBlockProgress — Block-Based Operation Tracking

```typescript
import { useBlockNumber } from "wagmi";
import { useMemo } from "react";

export function useBlockProgress({ startBlock, estimatedBlocks, enabled = true }: { startBlock: number; estimatedBlocks: number; enabled?: boolean }) {
  const { data: currentBlock } = useBlockNumber({ watch: enabled, query: { refetchInterval: 4_000 } });

  return useMemo(() => {
    if (!currentBlock) return { progress: 0, blocksElapsed: 0, blocksRemaining: estimatedBlocks, isComplete: false };
    const elapsed = Math.max(0, Number(currentBlock) - startBlock);
    const remaining = Math.max(0, estimatedBlocks - elapsed);
    return { progress: Math.min(1, elapsed / estimatedBlocks), blocksElapsed: elapsed, blocksRemaining: remaining, isComplete: elapsed >= estimatedBlocks, currentBlock: Number(currentBlock) };
  }, [currentBlock, startBlock, estimatedBlocks]);
}
```

---

## 5. Precompile Encoding / Decoding

Canonical encode/decode functions. Reference these from hooks — don't duplicate.

### HTTP Call (0x0801)

13-field canonical encoding (includes DKMS fields). For non-DKMS flows, pass `dkmsKeyIndex: 0n` and `dkmsKeyFormat: 0`. See `ritual-dapp-http` skill for full HTTP precompile details.

```typescript
import { encodeAbiParameters, decodeAbiParameters, type Hex } from "viem";

export function encodeHTTPCallRequest(params: {
  executor: `0x${string}`;
  url: string;
  method: "GET" | "POST" | "PUT" | "DELETE" | "PATCH";
  headerKeys?: string[];
  headerValues?: string[];
  body?: string;
  ttl?: bigint;
  encryptedSecrets?: `0x${string}`[];
  secretSignatures?: `0x${string}`[];
  userPublicKey?: `0x${string}`;
  dkmsKeyIndex?: bigint;
  dkmsKeyFormat?: number;
  piiEnabled?: boolean;
}): Hex {
  const methodCode = { GET: 1, POST: 2, PUT: 3, DELETE: 4, PATCH: 5 }[params.method];
  return encodeAbiParameters(
    [
      { type: "address" }, { type: "bytes[]" }, { type: "uint256" },
      { type: "bytes[]" }, { type: "bytes" },
      { type: "string" }, { type: "uint8" },
      { type: "string[]" }, { type: "string[]" }, { type: "bytes" },
      { type: "uint256" }, { type: "uint8" },
      { type: "bool" },
    ],
    [
      params.executor,
      params.encryptedSecrets ?? [],
      params.ttl ?? 100n,
      params.secretSignatures ?? [],
      params.userPublicKey ?? "0x",
      params.url,
      methodCode,
      params.headerKeys ?? [],
      params.headerValues ?? [],
      params.body ? (`0x${Buffer.from(params.body).toString("hex")}` as Hex) : "0x",
      params.dkmsKeyIndex ?? 0n,
      params.dkmsKeyFormat ?? 0,
      params.piiEnabled ?? false,
    ],
  );
}

export function decodeHTTPCallResponse(data: Hex) {
  const [statusCode, headerKeys, headerValues, body, errorMessage] =
    decodeAbiParameters(
      [{ type: "uint16" }, { type: "string[]" }, { type: "string[]" }, { type: "bytes" }, { type: "string" }],
      data,
    );
  const headers: Record<string, string> = {};
  headerKeys.forEach((k, i) => { headers[k] = headerValues[i]; });
  return {
    statusCode, headers,
    body: new TextDecoder().decode(Buffer.from((body as string).slice(2), 'hex')),
    error: errorMessage || null,
    get jsonBody() { return JSON.parse(new TextDecoder().decode(Buffer.from((body as string).slice(2), 'hex'))); },
  };
}
```

### Sovereign Agent (0x080C)

```typescript
export function encodeAgentCallRequest(params: {
  executor: `0x${string}`;
  prompt: string;
  tools?: string[];
  maxIterations?: number;
  maxToolCalls?: number;
  maxTokens?: number;
  temperatureScaled?: number;
  ttl?: bigint;
  deliveryTarget?: `0x${string}`;
  deliverySelector?: `0x${string}`;
}): Hex {
  return encodeAbiParameters(
    [
      { type: "address" }, { type: "bytes[]" }, { type: "uint256" },
      { type: "bytes[]" }, { type: "bytes" },
      { type: "uint64" }, { type: "uint64" }, { type: "string" },
      { type: "address" }, { type: "bytes4" }, { type: "uint256" },
      { type: "uint256" }, { type: "uint256" }, { type: "uint256" },
      { type: "string" }, { type: "string[]" },
      { type: "uint16" }, { type: "uint16" }, { type: "uint32" },
      { type: "uint16" }, { type: "bool" },
    ],
    [
      params.executor, [], params.ttl ?? 200n, [], "0x",
      5n, 1000n, "AGENT_TASK",
      params.deliveryTarget ?? "0x0000000000000000000000000000000000000000",
      params.deliverySelector ?? "0x00000000",
      3_000_000n, 1_000_000_000n, 100_000_000n, 0n,
      params.prompt, params.tools ?? [],
      params.maxIterations ?? 10, params.maxToolCalls ?? 20,
      params.maxTokens ?? 1024, params.temperatureScaled ?? 70, false,
    ],
  );
}

export function decodeAgentPhase2(data: Hex) {
  const [version, success, response, stoppedReason, iterations, toolCalls, errorMessage] =
    decodeAbiParameters(
      [{ type: "uint8" }, { type: "bool" }, { type: "string" }, { type: "string" }, { type: "uint16" }, { type: "uint16" }, { type: "string" }],
      data,
    );
  return { version, success, response, stoppedReason, iterations, toolCalls, errorMessage };
}
```

---

## 6. Fee Estimation

Ritual charges executor fees from RitualWallet deposits. HTTP fees use fixed per-byte constants. LLM fees use a gas-based model with per-model parameters from the on-chain `ModelPricingRegistry`.

### HTTP Fee Constants (verified from chain)

```typescript
export const HTTP_FEE_CONSTANTS = {
  BASE_FEE_WEI: 2_500_000_000_000n,
  PER_INPUT_BYTE_WEI: 350_000_000n,
  PER_OUTPUT_BYTE_WEI: 350_000_000n,
  DEFAULT_LOCK_DURATION: 5000n,
} as const;
```

### useHTTPFeeEstimate

```typescript
import { useMemo } from "react";
import { HTTP_FEE_CONSTANTS } from "@/lib/fees";

export function useHTTPFeeEstimate(estimatedInputBytes = 256, estimatedOutputBytes = 4096) {
  return useMemo(() => {
    const baseFee = HTTP_FEE_CONSTANTS.BASE_FEE_WEI;
    const inputFee = BigInt(estimatedInputBytes) * HTTP_FEE_CONSTANTS.PER_INPUT_BYTE_WEI;
    const outputFee = BigInt(estimatedOutputBytes) * HTTP_FEE_CONSTANTS.PER_OUTPUT_BYTE_WEI;
    const totalFee = baseFee + inputFee + outputFee;
    return { baseFee, inputFee, outputFee, totalFee, lockDuration: HTTP_FEE_CONSTANTS.DEFAULT_LOCK_DURATION, depositRecommendation: totalFee * 2n };
  }, [estimatedInputBytes, estimatedOutputBytes]);
}
```

### LLM Fee Model

LLM fees are **not** fixed per-token constants. The actual fee is computed as `total_gas × 1_000_000_000 (1 gwei)`, where `total_gas` depends on model-specific parameters (`theta`, `params_b`) from the `ModelPricingRegistry`. Query the registry to check if a model exists; for deposit sizing, use a conservative amount (0.1–1 RITUAL covers most single calls based on working e2e tests).

```typescript
const MODEL_PRICING_REGISTRY = "0x7A85F48b971ceBb75491b61abe279728F4c4384f" as const;

const modelPricingAbi = [
  { type: "function", name: "modelExists", inputs: [{ name: "modelName", type: "string" }], outputs: [{ type: "bool" }], stateMutability: "view" },
] as const;

export function useModelCheck(model?: string) {
  const { data: exists } = useReadContract({
    address: MODEL_PRICING_REGISTRY,
    abi: modelPricingAbi,
    functionName: "modelExists",
    args: model ? [model] : undefined,
    query: { enabled: !!model },
  });
  return { modelRegistered: exists ?? null };
}
```

---

## 7. SSE Streaming Consumer for LLM

Connect to Ritual's streaming service for real-time token delivery:

```typescript
import { useState, useCallback, useRef } from "react";
import { useWalletClient } from "wagmi";

interface StreamingState {
  status: "idle" | "submitting" | "signing" | "streaming" | "done" | "error";
  txHash?: `0x${string}`;
  text: string;
  tokens: number;
  error?: string;
}

export function useStreamingLLM(streamingServiceUrl = "https://streaming.ritualfoundation.org") {
  const [state, setState] = useState<StreamingState>({ status: "idle", text: "", tokens: 0 });
  const abortControllerRef = useRef<AbortController | null>(null);
  const { data: walletClient } = useWalletClient();

  const stream = useCallback(async (txHash: `0x${string}`) => {
    if (!walletClient) return;

    setState((s) => ({ ...s, status: "signing", txHash }));

    const timestamp = BigInt(Math.floor(Date.now() / 1000));
    const signature = await walletClient.signTypedData({
      domain: { name: "Ritual Streaming Service", version: "1", chainId: 1979 },
      types: { StreamRequest: [{ name: "txHash", type: "bytes32" }, { name: "timestamp", type: "uint256" }] },
      primaryType: "StreamRequest",
      message: { txHash, timestamp },
    });

    setState((s) => ({ ...s, status: "streaming" }));

    const controller = new AbortController();
    abortControllerRef.current = controller;

    // Uses path param + auth headers (NOT query params) — matches LLM skill SSE pattern.
    // Cannot use EventSource because it doesn't support custom headers.
    const response = await fetch(`${streamingServiceUrl}/v1/stream/${txHash}`, {
      headers: {
        "Accept": "text/event-stream",
        "Authorization": `Bearer ${signature}`,
        "X-Timestamp": timestamp.toString(),
      },
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(`Stream HTTP ${response.status}`);

    const reader = response.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop()!;
      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const payload = line.slice(6);
        if (payload === "[DONE]") { setState((s) => ({ ...s, status: "done" })); return; }
        const data = JSON.parse(payload);
        if (data.type === "token" && data.content) {
          setState((s) => ({ ...s, text: s.text + data.content, tokens: s.tokens + 1 }));
        }
        if (data.type === "error") { setState((s) => ({ ...s, status: "error", error: data.error })); return; }
      }
    }
    setState((s) => ({ ...s, status: "done" }));
  }, [walletClient, streamingServiceUrl]);

  const stop = useCallback(() => { abortControllerRef.current?.abort(); setState((s) => ({ ...s, status: "done" })); }, []);
  const reset = useCallback(() => { stop(); setState({ status: "idle", text: "", tokens: 0 }); }, [stop]);

  return { state, stream, stop, reset };
}
```

---

## 8. Transaction Flow Patterns

### Pattern 1: HTTP Call (short-running async — result in receipt)

```typescript
import { useAccount, useWalletClient } from "wagmi";
import { useCallback, useId } from "react";
import { useAsyncTxStore } from "@/stores/asyncTxStore";
import { useAsyncJobEvents } from "@/hooks/useAsyncJobEvents";
import { encodeHTTPCallRequest } from "@/lib/encoding";

const HTTP_PRECOMPILE = "0x0000000000000000000000000000000000000801" as const;

export function useHTTPCall() {
  const txId = useId();
  const { data: walletClient } = useWalletClient();
  const addTransaction = useAsyncTxStore((s) => s.addTransaction);
  const updateState = useAsyncTxStore((s) => s.updateState);
  const getTransaction = useAsyncTxStore((s) => s.getTransaction);

  useAsyncJobEvents({ txId, enabled: !!getTransaction(txId) });

  const submit = useCallback(async (options: {
    url: string; method?: "GET" | "POST"; headers?: Record<string, string>;
    body?: string; executor: `0x${string}`; ttl?: bigint; label?: string;
  }) => {
    addTransaction(txId, "http", options.label);
    try {
      const encoded = encodeHTTPCallRequest({
        executor: options.executor,
        url: options.url,
        method: options.method ?? "GET",
        headerKeys: Object.keys(options.headers ?? {}),
        headerValues: Object.values(options.headers ?? {}),
        body: options.body,
        ttl: options.ttl,
      });
      const hash = await walletClient!.sendTransaction({ to: HTTP_PRECOMPILE, data: encoded, gas: 2_000_000n });
      updateState(txId, { status: "PENDING_COMMITMENT", txHash: hash, submittedAt: Date.now(), ttlBlocks: Number(options.ttl ?? 100n) });
      return hash;
    } catch (err) {
      updateState(txId, { status: "FAILED", error: err instanceof Error ? err.message : "Transaction failed", errorCategory: "wallet", failedAt: "SUBMITTING" });
      throw err;
    }
  }, [txId, walletClient, addTransaction, updateState]);

  return { txId, submit, state: getTransaction(txId)?.state ?? null };
}
```

### Pattern 2: Sovereign Agent (long-running async — result via callback)

```typescript
import { useSendTransaction } from "wagmi";
import { useCallback, useId } from "react";
import { useAsyncTxStore } from "@/stores/asyncTxStore";
import { useAsyncJobEvents } from "@/hooks/useAsyncJobEvents";
import { encodeAgentCallRequest } from "@/lib/encoding";

const SOVEREIGN_AGENT_PRECOMPILE = "0x000000000000000000000000000000000000080C" as const;

export function useAgentCall() {
  const txId = useId();
  const { sendTransactionAsync } = useSendTransaction();
  const addTransaction = useAsyncTxStore((s) => s.addTransaction);
  const updateState = useAsyncTxStore((s) => s.updateState);
  const getTransaction = useAsyncTxStore((s) => s.getTransaction);

  useAsyncJobEvents({ txId, enabled: !!getTransaction(txId) });

  const submit = useCallback(async (options: {
    executor: `0x${string}`; prompt: string; tools?: string[];
    maxIterations?: number; ttl?: bigint;
    deliveryTarget?: `0x${string}`; deliverySelector?: `0x${string}`; label?: string;
  }) => {
    addTransaction(txId, "agent", options.label);
    try {
      const encoded = encodeAgentCallRequest(options);
      const hash = await sendTransactionAsync({ to: SOVEREIGN_AGENT_PRECOMPILE, data: encoded, gas: 3_000_000n });
      updateState(txId, { status: "PENDING_COMMITMENT", txHash: hash, submittedAt: Date.now(), ttlBlocks: Number(options.ttl ?? 200n) });
      return hash;
    } catch (err) {
      updateState(txId, { status: "FAILED", error: err instanceof Error ? err.message : "Sovereign Agent call failed", errorCategory: "contract", failedAt: "SUBMITTING" });
      throw err;
    }
  }, [txId, sendTransactionAsync, addTransaction, updateState]);

  return { txId, submit, state: getTransaction(txId)?.state ?? null };
}
```

### Nonce Management for Multi-Transaction Flows

When a submit flow requires sequential transactions (deposit → register → submit), stale nonces cause `"replacement transaction underpriced"`. Fetch the confirmed nonce at the start and increment:

```typescript
import { usePublicClient } from "wagmi";

async function multiTxFlow(publicClient: ReturnType<typeof usePublicClient>, userAddress: `0x${string}`) {
  let nonce = await publicClient!.getTransactionCount({ address: userAddress, blockTag: "pending" });

  const hash1 = await sendTransactionAsync({ to: WALLET, data: depositData, nonce });
  await publicClient!.waitForTransactionReceipt({ hash: hash1 });
  nonce++;

  const hash2 = await sendTransactionAsync({ to: CONTRACT, data: submitData, nonce });
}
```

If a user gets stuck with "replacement transaction underpriced", they need to "Clear activity data" in MetaMask (Settings → Advanced → Clear activity tab data) to reset MetaMask's nonce cache.

---

## 9. UI Components

These are Ritual-specific component patterns. The styling/layout is standard Tailwind — only the data contracts and Ritual-specific state mapping matter. See the `ritual-dapp-design` skill for full design system guidance.

### AsyncTransactionStatus

Renders the 9-state lifecycle. Ritual-specific requirements:
- Map `AsyncTxState.status` to a label/color/animation config
- Show `jobId` (bytes32, display as truncated hex) when available
- For `EXECUTOR_PROCESSING`: use `useBlockProgress` to show block-based progress (no on-chain signal — interpolate from blocks elapsed since `JobAdded.commitBlock`)
- For `FAILED`: display `error` message and `errorCategory`
- Include a step indicator (7 non-terminal steps) showing progress through the pipeline

```typescript
interface AsyncTransactionStatusProps {
  state: AsyncTxState;
  compact?: boolean;
}

const STATUS_CONFIG: Record<AsyncTxStatus, { label: string; icon: string; color: string }> = {
  SUBMITTING:          { label: "Submitting",         icon: "↗", color: "blue" },
  PENDING_COMMITMENT:  { label: "Awaiting Executor",  icon: "◎", color: "yellow" },
  COMMITTED:           { label: "Executor Committed", icon: "✓", color: "cyan" },
  EXECUTOR_PROCESSING: { label: "Processing",         icon: "⟳", color: "green" },
  RESULT_READY:        { label: "Result Ready",       icon: "◆", color: "lime" },
  PENDING_SETTLEMENT:  { label: "Settling",           icon: "⧖", color: "green" },
  SETTLED:             { label: "Settled",             icon: "✔", color: "green" },
  FAILED:              { label: "Failed",              icon: "✕", color: "red" },
  EXPIRED:             { label: "Expired",             icon: "⏱", color: "gray" },
};
```

### RitualWalletCard

Displays RitualWallet balance and deposit/withdraw controls. Ritual-specific requirements:
- Use `useRitualWallet()` for balance, `lockUntilBlock`, deposit/withdraw actions
- Use `useSenderLock()` to show lock indicator (amber dot + message when locked)
- Show balance in RITUAL with 4 decimal places (`formatEther`)
- Show lock-until block number when locked

### PrecompileSelector

Grid of available precompiles for user selection. Ritual-specific data:

```typescript
const PRECOMPILES = [
  { id: "http",     name: "HTTP Call",  address: "0x0801", category: "data" },
  { id: "llm",      name: "LLM",       address: "0x0802", category: "inference" },
  { id: "longhttp", name: "Long HTTP",  address: "0x0805", category: "data" },
  { id: "zk",       name: "ZK Proof",   address: "0x0806", category: "data" },
  { id: "sovereign", name: "Sovereign Agent", address: "0x080C", category: "agent" },
  { id: "image",    name: "Image Gen",  address: "0x0818", category: "multimodal" },
  { id: "audio",    name: "Audio Gen",  address: "0x0819", category: "multimodal" },
  { id: "video",    name: "Video Gen",  address: "0x081A", category: "multimodal" },
] as const;
```

### FeeEstimateDisplay

Shows fee breakdown. Format wei to RITUAL: `Number(wei) / 1e18`, display with 4 decimal places. Show `totalFee` and `lockDuration` (in blocks).

---

## 10. Error Handling

Ritual-specific error codes to match against in `error.message`. Standard wallet errors (user rejected, insufficient funds) use normal wagmi/viem patterns.

| Code | Category | Match string | Recoverable | Ritual-specific guidance |
|------|----------|-------------|-------------|------------------------|
| `SENDER_LOCKED` | async | `"sender locked"`, `"pending job"` | Yes | Wait for current job to settle. Check `hasPendingJobForSender`. |
| `INSUFFICIENT_DEPOSIT` | contract | `"insufficient deposit"`, `"wallet balance"` | Yes | Deposit RITUAL into RitualWallet before submitting. |
| `NO_EXECUTOR` | contract | `"no executor"`, `"executor not found"` | Yes | No executor available. Retry shortly or pick a different executor. |
| `JOB_EXPIRED` | async | `"job expired"`, `"ttl exceeded"` | Yes | Increase TTL or retry during lower activity. |
| `DELIVERY_FAILED` | async | `"callback failed"`, `"delivery failed"` | No | Check callback function for reverts or gas limit. |

```typescript
export type ErrorCategory = "wallet" | "contract" | "async" | "network";
```

---

## 11. Contract Addresses

```typescript
export const RITUAL_ADDRESSES = {
  PRECOMPILE: {
    HTTP_CALL:        "0x0000000000000000000000000000000000000801",
    LLM:              "0x0000000000000000000000000000000000000802",
    LONG_RUNNING_HTTP:"0x0000000000000000000000000000000000000805",
    ZK_LONG_RUNNING_ASYNC: "0x0000000000000000000000000000000000000806",
    SOVEREIGN_AGENT:  "0x000000000000000000000000000000000000080C",
    IMAGE_CALL:       "0x0000000000000000000000000000000000000818",
    AUDIO_CALL:       "0x0000000000000000000000000000000000000819",
    VIDEO_CALL:       "0x000000000000000000000000000000000000081A",
  },
  SYSTEM: {
    WALLET:               "0x532F0dF0896F353d8C3DD8cc134e8129DA2a3948",
    ASYNC_JOB_TRACKER:    "0xC069FFCa0389f44eCA2C626e55491b0ab045AEF5",
    TEE_SERVICE_REGISTRY: "0x9644e8562cE0Fe12b4deeC4163c064A8862Bf47F",
    SCHEDULER:            "0x56e776BAE2DD60664b69Bd5F865F1180ffB7D58B",
    SECRETS_ACCESS_CTRL:  "0xf9BF1BC8A3e79B9EBeD0fa2Db70D0513fecE32FD",
    MODEL_PRICING:        "0x7A85F48b971ceBb75491b61abe279728F4c4384f",
  },
} as const;
```

---

## 12. Cross-References to Other Skills

| Need | Skill | What it provides |
|------|-------|-----------------|
| HTTP precompile encoding details | `ritual-dapp-http` | Full 13-field ABI, method codes, secrets, PII mode |
| LLM precompile encoding details | `ritual-dapp-llm` | Message format, model selection, conversation history |
| Executor discovery & selection | `ritual-dapp-precompiles` | TEEServiceRegistry queries, capability checks |
| Long-running HTTP | `ritual-dapp-longrunning` | Poll/result URL encoding, phase 2 callback |
| Sovereign Agent | `ritual-dapp-agents` | Agent encoding, tool registration, iteration limits |
| Contract deployment patterns | `ritual-dapp-contracts` | System contract addresses, ABI references |
| Secrets & encryption | `ritual-dapp-secrets` | ECIES encryption, SecretsAccessControl |
| Storage & DA | `ritual-dapp-da` | StorageRef format, GCS/HF/Pinata credentials, output URI handling |
| Design system | `ritual-dapp-design` | Color palette, typography, component patterns |
| Wallet & deposit flow | `ritual-dapp-wallet` | RitualWallet details, lock mechanics |

Do not re-implement logic covered by these skills. Import the encoding/decoding functions they specify and use them in your hooks.

---

## Quick Reference

| Task | Hook / Component | Notes |
|------|------------------|-------|
| Connect wallet | Standard wagmi `useConnect` + `ChainGuard` | — |
| Bypass eth_call simulation | `useRitualWrite()` | Required for any async precompile call |
| Track async tx lifecycle | `useAsyncJobEvents({ txId })` | Uses `JobAdded`, `Phase1Settled`, `ResultDelivered` events |
| Check sender lock | `useSenderLock()` | Calls `hasPendingJobForSender` on AsyncJobTracker |
| Check deposit sufficiency | `useDepositGate(estimatedFee)` | Compare RitualWallet balance to estimated fee |
| Wallet balance + deposit | `useRitualWallet()` | `balanceOf`, `lockUntil`, `deposit`, `withdraw` |
| Block progress | `useBlockProgress({ startBlock, estimatedBlocks })` | UI-interpolated, no on-chain signal |
| HTTP fee estimate | `useHTTPFeeEstimate(inputBytes, outputBytes)` | Uses verified chain constants |
| LLM model check | `useModelCheck(model)` | Queries `ModelPricingRegistry.modelExists` |
| Parse spcCalls | `extractSpcResult(receipt)` + `decodeHTTPResponse(output)` | Short-running async precompiles only |
| Encode HTTP request | `encodeHTTPCallRequest(params)` | 13-field canonical format |
| Encode Sovereign Agent request | `encodeAgentCallRequest(params)` | See `ritual-dapp-agents` skill for field details |
| LLM streaming | `useStreamingLLM()` | SSE from `streaming.ritualfoundation.org` |

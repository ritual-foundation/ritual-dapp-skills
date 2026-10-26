---
name: ritual-dapp-frontend
description: Frontend development for Ritual dApps with async transaction state machines, wagmi/viem hooks, and event subscriptions. Use when building React/Next.js frontends for Ritual.
version: 1.0.0
---

# Ritual dApp Frontend

For persistent Hermes chat and controls, read [Agent Link](../ritual-dapp-agent-link/SKILL.md). It specifies application-hosted HTTP/WebSocket endpoints, durable event ingestion, scoped turn state, text snapshots, approvals, and cancellation.

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
  id: 784,
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
import { NextResponse } from 'next/server';

const RPC_URL = process.env.RITUAL_RPC_URL ?? 'https://rpc.ritualfoundation.org';
const MAX_BODY_BYTES = 100_000;
const ALLOWED_METHODS = new Set([
  'eth_blockNumber', 'eth_call', 'eth_chainId', 'eth_estimateGas',
  'eth_feeHistory', 'eth_gasPrice', 'eth_getBalance', 'eth_getBlockByHash',
  'eth_getBlockByNumber', 'eth_getCode', 'eth_getLogs',
  'eth_getTransactionByHash', 'eth_getTransactionCount',
  'eth_getTransactionReceipt', 'eth_maxPriorityFeePerGas',
]);

function rpcError(status: number, code: number, message: string, id: string | number | null = null) {
  return NextResponse.json({ jsonrpc: '2.0', error: { code, message }, id },
    { status, headers: { 'Cache-Control': 'no-store' } });
}

export async function POST(req: Request) {
  if (Number(req.headers.get('content-length') ?? '0') > MAX_BODY_BYTES) {
    return rpcError(413, -32600, 'Request too large');
  }
  // Count bytes while reading, even if Content-Length is absent or inaccurate.
  const reader = req.body?.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  if (reader) {
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        size += value.byteLength;
        if (size > MAX_BODY_BYTES) {
          await reader.cancel();
          return rpcError(413, -32600, 'Request too large');
        }
        chunks.push(value);
      }
    } catch { return rpcError(400, -32600, 'Unreadable request'); }
    finally { reader.releaseLock(); }
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  const raw = new TextDecoder().decode(bytes);
  let body: unknown;
  try { body = JSON.parse(raw); } catch { return rpcError(400, -32700, 'Parse error'); }
  if (!body || Array.isArray(body) || typeof body !== 'object') {
    return rpcError(400, -32600, 'Invalid JSON-RPC request');
  }
  const { jsonrpc, method, params, id = null } = body as Record<string, unknown>;
  if (jsonrpc !== '2.0' || typeof method !== 'string' ||
      !(id === null || typeof id === 'string' || (typeof id === 'number' && Number.isFinite(id))) ||
      !(params === undefined || Array.isArray(params) || (params !== null && typeof params === 'object'))) {
    return rpcError(400, -32600, 'Invalid JSON-RPC request');
  }
  if (!ALLOWED_METHODS.has(method)) return rpcError(403, -32601, 'Method not allowed', id);
  try {
    const response = await fetch(RPC_URL, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: raw,
      cache: 'no-store', signal: AbortSignal.timeout(10_000),
    });
    const responseBody = await response.text();
    return new NextResponse([204, 205, 304].includes(response.status) ? null : responseBody, {
      status: response.status,
      headers: { 'Content-Type': response.headers.get('content-type') ?? 'application/json', 'Cache-Control': 'no-store' },
    });
  } catch { return rpcError(504, -32000, 'RPC upstream unavailable', id); }
}
```

This read-method allowlist rejects batches and transaction submission. Wallets may submit through their own provider; if the application needs server-proxied writes, add an authenticated, rate-limited submission route explicitly. Enforce request duration, body limits and per-user/IP rate limits at the hosting edge too. Never expose `admin_*`, `debug_*`, `personal_*`, or unlocked-account methods.

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
| FAILED | `ResultDelivered(success=false)` / `AsyncDelivery.Delivered(success=false)`, or `JobRemoved(completed=false)` from cleanup | AsyncDelivery / AsyncJobTracker |
| EXPIRED | — | Derived (current block > commit block + TTL); confirmed by cleanup `JobRemoved(completed=false)` |

> **What `Phase1Settled` actually means (it's a footgun).** This event does NOT mean the underlying job is done. It is emitted from `AsyncJobTracker.markPhase1Settled` only for **long-running** precompiles, after `AsyncDelivery.settle` has paid the executor + validators for Phase 1. At that point:
> - **Short-running** (HTTP, LLM, JQ, DKMS, …): `Phase1Settled` is **never emitted**. The result is already in the receipt's `spcCalls` and `JobRemoved(completed=true)` fires instead.
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
  submittedBlock?: bigint; // capture before sending, for bounded terminal-event replay
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
  gasUsed: bigint;
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
    PENDING_COMMITMENT: ["COMMITTED", "PENDING_SETTLEMENT", "EXPIRED", "FAILED"],
    COMMITTED: ["EXECUTOR_PROCESSING", "RESULT_READY", "PENDING_SETTLEMENT", "FAILED"],
    EXECUTOR_PROCESSING: ["RESULT_READY", "PENDING_SETTLEMENT", "FAILED"],
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
import { createJSONStorage, persist } from "zustand/middleware";
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
          return { transactions: { ...s.transactions, [id]: { ...existing, state: newState, updatedAt: Date.now() } } };
        }),
      getTransaction: (id) => get().transactions[id],
      getActiveTransactions: () => Object.values(get().transactions).filter((tx) => !isTerminalState(tx.state.status)),
      clearSettled: () =>
        set((s) => ({
          transactions: Object.fromEntries(Object.entries(s.transactions).filter(([, tx]) => !isTerminalState(tx.state.status))),
        })),
    }),
    {
      name: "ritual-async-tx",
      storage: createJSONStorage(() => localStorage, {
        replacer: (_key, value) =>
          typeof value === "bigint" ? { __ritualBigInt: value.toString() } : value,
        reviver: (_key, value) => {
          if (
            value && typeof value === "object" && "__ritualBigInt" in value && Object.keys(value).length === 1 &&
            typeof value.__ritualBigInt === "string" && /^-?\d+$/.test(value.__ritualBigInt)
          ) return BigInt(value.__ritualBigInt);
          return value;
        },
      }),
    },
  ),
);
```

Transactions survive page refresh. The `persist` middleware writes to localStorage keyed by `"ritual-async-tx"`.

---

## 3. spcCalls Receipt Parsing

When a short-running async precompile (HTTP `0x0801`, LLM `0x0802`) settles, the result is in the transaction receipt's `spcCalls` field — a Ritual-specific extension not present on standard EVM receipts.

```typescript
import { hexToBytes, decodeAbiParameters } from "viem";

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
    body: new TextDecoder().decode(hexToBytes(body)),
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
- **Payment-side failures** — settlement payouts are **pull-payment**: `_settle` credits each recipient's internal available balance and emits `EscrowPaymentCredited(bytes32 indexed escrowId, address indexed recipient, uint256 amount)` (recipients later call `withdraw` to pull their RITUAL), so a payee that cannot receive funds does not revert settlement. Settlement reverts only with `SettlementExceedsReserve` when the per-job escrow is under-reserved; otherwise the failure surfaces as `AsyncDelivery.Delivered(success=false)` / `ResultDelivered(success=false)` when the Phase 2 callback itself reverts. There are no dedicated `SettlementFailed` / `DeliveryFailed` events
- **`JobRemoved`** — emitted when a job is cleaned up

`JobRemoved(completed=true)` starts receipt reconciliation for HTTP/LLM. `PENDING_SETTLEMENT` retains that receipt hash and retries transient RPC failures, including after remount. Long-running jobs still wait for their delivery event. Copy [settlement.ts](../../examples/short-settlement/settlement.ts) into `src/lib/short-settlement.ts`; it verifies the exact job/emitter and returns complete settlement metadata plus bare SPC output. Decode that output using the originating request’s codec before rendering a successful application result. The hook replays missed terminal events from the saved committed/submission block on remount. Custom HTTP/LLM submitters must preserve `submittedBlock` before sending, as `useHTTPCall` below does; older records without either block need the included backend indexer’s historical lookup.

```typescript
import { useWatchContractEvent, useAccount, usePublicClient } from "wagmi";
import { useEffect, useCallback } from "react";
import { readShortSettlement, InvalidSettlement } from "@/lib/short-settlement";
import { useAsyncTxStore } from "@/stores/asyncTxStore";

const ASYNC_JOB_TRACKER = "0xf00385449fD961925A0B125F5f30b29B682D4bFb" as const;

const asyncJobTrackerAbi = [
  {
    type: "event", name: "JobAdded",
    inputs: [
      { name: "executor", type: "address", indexed: true },
      { name: "jobId", type: "bytes32", indexed: true },
      { name: "precompileAddress", type: "address", indexed: true },
      { name: "commitBlock", type: "uint256", indexed: false },
      { name: "precompileInput", type: "bytes", indexed: false },
      { name: "callerAddress", type: "address", indexed: false },
      { name: "txOrigin", type: "address", indexed: false },
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
    type: "function", name: "hasPendingJobForTxOrigin",
    inputs: [{ name: "txOrigin", type: "address" }],
    outputs: [{ type: "bool" }],
    stateMutability: "view",
  },
] as const;

export function useAsyncJobEvents({ txId, enabled = true }: { txId: string; enabled?: boolean }) {
  const { address } = useAccount();
  const publicClient = usePublicClient();
  const transaction = useAsyncTxStore((s) => s.transactions[txId]);
  const updateState = useAsyncTxStore((s) => s.updateState);
  const getTransaction = useAsyncTxStore((s) => s.getTransaction);

  useWatchContractEvent({
    address: ASYNC_JOB_TRACKER,
    abi: asyncJobTrackerAbi,
    eventName: "JobAdded",
    enabled: enabled && !!address,
    onLogs: (logs) => {
      if (!address) return;
      for (const log of logs) {
        const user = address.toLowerCase();
        const caller = log.args.callerAddress?.toLowerCase();
        const txOrigin = log.args.txOrigin?.toLowerCase();
        // Direct precompile calls have callerAddress == the EOA. Contract-mediated
        // calls have callerAddress == consumer contract and txOrigin == the EOA.
        if (caller !== user && txOrigin !== user) continue;
        const tx = getTransaction(txId);
        if (!tx || tx.state.status !== "PENDING_COMMITMENT") continue;
        // For these EOA submissions, jobId is the origin hash, not the commitment log's transactionHash.
        if (log.args.jobId?.toLowerCase() !== tx.state.txHash.toLowerCase()) continue;
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
        if (tx.state.status === "COMMITTED" || tx.state.status === "EXECUTOR_PROCESSING") {
          if (log.args.jobId?.toLowerCase() !== tx.state.jobId.toLowerCase()) continue;
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
        if (log.args.jobId?.toLowerCase() !== tx.state.jobId.toLowerCase()) continue;
        if (log.args.success) {
          // Read the delivery receipt and application result before constructing SETTLED.
          updateState(txId, {
            status: "PENDING_SETTLEMENT",
            txHash: tx.state.txHash,
            jobId: log.args.jobId!,
            deliveryTxHash: log.transactionHash,
          });
        } else {
          updateState(txId, {
            status: "FAILED",
            txHash: tx.state.txHash,
            jobId: log.args.jobId!,
            error: "Async result delivery failed",
            errorCategory: "async",
            failedAt: "RESULT_READY",
          });
        }
      }
    },
  });

  const onRemoved = useCallback((logs: readonly any[]) => {
      for (const log of logs) {
        const tx = getTransaction(txId);
        if (!tx || !("txHash" in tx.state) || !tx.state.txHash ||
            ["SETTLED", "FAILED", "EXPIRED"].includes(tx.state.status)) continue;
        const expectedJob = "jobId" in tx.state ? tx.state.jobId : tx.state.txHash;
        if (!expectedJob || log.args.jobId?.toLowerCase() !== expectedJob.toLowerCase()) continue;
        if (!log.args.completed) {
          updateState(txId, { status: "FAILED", txHash: tx.state.txHash, jobId: expectedJob,
            error: "Job removed without completion (expired or failed)", errorCategory: "async", failedAt: tx.state.status });
        } else if (tx.precompileType === "http" || tx.precompileType === "llm") {
          updateState(txId, { status: "PENDING_SETTLEMENT", txHash: tx.state.txHash,
            jobId: expectedJob, deliveryTxHash: log.transactionHash });
        }
      }
  }, [txId, getTransaction, updateState]);
  useWatchContractEvent({
    address: ASYNC_JOB_TRACKER, abi: asyncJobTrackerAbi, eventName: "JobRemoved",
    enabled: enabled && !!address, onLogs: onRemoved,
  });

  // Replay terminal logs missed while the component was unmounted.
  useEffect(() => {
    const state = transaction?.state;
    if (!enabled || !publicClient || !state || !("txHash" in state) || !state.txHash ||
        !transaction || (transaction.precompileType !== "http" && transaction.precompileType !== "llm") ||
        ["SETTLED", "FAILED", "EXPIRED", "PENDING_SETTLEMENT"].includes(state.status)) return;
    const fromBlock = "committedBlock" in state ? BigInt(state.committedBlock)
      : "submittedBlock" in state && state.submittedBlock !== undefined ? BigInt(state.submittedBlock) : undefined;
    if (fromBlock === undefined) return;
    const jobId = "jobId" in state ? state.jobId : state.txHash;
    let cancelled = false, busy = false;
    const replay = async () => {
      if (busy) return;
      busy = true;
      try {
        const logs = await publicClient.getContractEvents({ address: ASYNC_JOB_TRACKER,
          abi: asyncJobTrackerAbi, eventName: "JobRemoved", args: { jobId }, fromBlock, toBlock: "latest" });
        if (!cancelled) onRemoved(logs);
      } catch { /* Keep the saved state and retry transient RPC errors. */ }
      finally { busy = false; }
    };
    void replay();
    const timer = setInterval(() => { void replay(); }, 2_000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [enabled, publicClient, transaction, onRemoved]);

  useEffect(() => {
    const tx = transaction;
    if (!enabled || !publicClient || !tx || tx.state.status !== "PENDING_SETTLEMENT" ||
        !tx.state.deliveryTxHash || (tx.precompileType !== "http" && tx.precompileType !== "llm")) return;
    const state = tx.state;
    let cancelled = false, busy = false;
    const isCurrent = () => {
      const current = getTransaction(txId)?.state;
      return !cancelled && current?.status === "PENDING_SETTLEMENT" &&
        current.txHash === state.txHash && current.deliveryTxHash === state.deliveryTxHash;
    };
    const reconcile = async () => {
      if (busy) return;
      busy = true;
      try {
        const settled = await readShortSettlement(publicClient, {
          originHash: state.txHash, jobId: state.jobId, settlementHash: state.deliveryTxHash!,
          tracker: ASYNC_JOB_TRACKER,
          precompile: tx.precompileType === "http"
            ? "0x0000000000000000000000000000000000000801"
            : "0x0000000000000000000000000000000000000802",
        });
        if (isCurrent()) updateState(txId, settled);
      } catch (error) {
        if (isCurrent() && error instanceof InvalidSettlement) {
          updateState(txId, { status: "FAILED", txHash: state.txHash, jobId: state.jobId,
            error: error.message, errorCategory: "async", failedAt: "PENDING_SETTLEMENT" });
        }
        // An unavailable receipt or transient RPC failure remains pending and retries.
      } finally { busy = false; }
    };
    void reconcile();
    const timer = setInterval(() => { void reconcile(); }, 2_000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [enabled, publicClient, transaction, txId, getTransaction, updateState]);

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
    functionName: "hasPendingJobForTxOrigin",
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

const RITUAL_WALLET = "0xF04076756d8129Baec46Dc0F1c526Baec490C393" as const;

const ritualWalletAbi = [
  { type: "function", name: "availableBalance", inputs: [{ name: "account", type: "address" }], outputs: [{ type: "uint256" }], stateMutability: "view" },
  { type: "function", name: "reservedBalance", inputs: [{ name: "account", type: "address" }], outputs: [{ type: "uint256" }], stateMutability: "view" },
  { type: "function", name: "allowance", inputs: [{ name: "sponsor", type: "address" }, { name: "caller", type: "address" }], outputs: [{ type: "uint256" }], stateMutability: "view" },
  { type: "function", name: "deposit", inputs: [], outputs: [], stateMutability: "payable" },
  { type: "function", name: "approve", inputs: [{ name: "caller", type: "address" }, { name: "amount", type: "uint256" }], outputs: [], stateMutability: "nonpayable" },
  { type: "function", name: "withdraw", inputs: [{ name: "amount", type: "uint256" }], outputs: [], stateMutability: "nonpayable" },
] as const;

export function useRitualWallet() {
  const { address } = useAccount();
  const { write } = useRitualWrite();

  const { data: balance, refetch: refetchBalance } = useReadContract({
    address: RITUAL_WALLET,
    abi: ritualWalletAbi,
    functionName: "availableBalance",
    args: address ? [address] : undefined,
    query: { enabled: !!address, refetchInterval: 12_000 },
  });

  const [pendingTxHash, setPendingTxHash] = useState<`0x${string}` | undefined>();
  const { isLoading: isConfirming } = useWaitForTransactionReceipt({ hash: pendingTxHash, query: { enabled: !!pendingTxHash } });

  const deposit = useCallback(async (amountEther: string) => {
    const hash = await write({ address: RITUAL_WALLET, abi: ritualWalletAbi, functionName: "deposit", args: [], value: parseEther(amountEther) });
    setPendingTxHash(hash);
    return hash;
  }, [write]);

  const withdraw = useCallback(async (amountEther: string) => {
    const hash = await write({ address: RITUAL_WALLET, abi: ritualWalletAbi, functionName: "withdraw", args: [parseEther(amountEther)] });
    setPendingTxHash(hash);
    return hash;
  }, [write]);

  return { balance, balanceFormatted: balance ? formatEther(balance) : "0", deposit, withdraw, isConfirming, refetchBalance };
}
```

### useDepositGate — Block Submit Until Funded

This simple hook covers self-pay flows where the connected wallet is also the encoded `sponsor`. For contract-mediated or third-party-sponsored calls, gate on the sponsor account instead and also require `allowance(sponsor, caller) >= estimatedFeeWei`, where `caller` is the consumer contract that invokes the precompile.

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

16-field canonical encoding (includes `sponsor`, `secret_owners`, the DKMS fields, and `output_storage_ref`). For non-DKMS flows, pass `dkmsKeyIndex: 0n` and `dkmsKeyFormat: 0`. See `ritual-dapp-http` skill for full HTTP precompile details.

When using RITHTTP1, pass `hexToBytes(encodeRitHttp1(...))` as `params.body`, keep `piiEnabled=false` and `outputStorageRef=["","",""]`, then decode the settled bytes by their `RITOUT1` prefix. The helper below treats strings as legacy UTF-8 bodies and Uint8Array as raw bytes; do not pass the hexadecimal envelope as a text string or JSON-stringify it. The exact codec, OpenAI DA-slot example, and result fields are in [`../ritual-dapp-http/references/rithttp1.md`](../ritual-dapp-http/references/rithttp1.md).

```typescript
import { hexToBytes, toHex, encodeAbiParameters, decodeAbiParameters, type Hex } from "viem";

export function encodeHTTPCallRequest(params: {
  executor: `0x${string}`;
  sponsor: `0x${string}`;
  secretOwners?: `0x${string}`[];
  url: string;
  method: "GET" | "POST" | "PUT" | "DELETE" | "PATCH";
  headerKeys?: string[];
  headerValues?: string[];
  body?: string | Uint8Array;
  ttl?: bigint;
  encryptedSecrets?: `0x${string}`[];
  secretSignatures?: `0x${string}`[];
  userPublicKey?: `0x${string}`;
  dkmsKeyIndex?: bigint;
  dkmsKeyFormat?: number;
  piiEnabled?: boolean;
  outputStorageRef?: [string, string, string];
}): Hex {
  const methodCode = { GET: 1, POST: 2, PUT: 3, DELETE: 4, PATCH: 5 }[params.method];
  return encodeAbiParameters(
    [
      { type: "address" }, { type: "address" }, { type: "address[]" }, { type: "bytes[]" }, { type: "uint256" },
      { type: "bytes[]" }, { type: "bytes" },
      { type: "string" }, { type: "uint8" },
      { type: "string[]" }, { type: "string[]" }, { type: "bytes" },
      { type: "uint256" }, { type: "uint8" },
      { type: "bool" },
      { type: 'tuple', components: [{ type: 'string' }, { type: 'string' }, { type: 'string' }] },
    ],
    [
      params.executor,
      params.sponsor,
      params.secretOwners ?? [],
      params.encryptedSecrets ?? [],
      params.ttl ?? 100n,
      params.secretSignatures ?? [],
      params.userPublicKey ?? "0x",
      params.url,
      methodCode,
      params.headerKeys ?? [],
      params.headerValues ?? [],
      params.body ? (toHex(params.body) as Hex) : "0x",
      params.dkmsKeyIndex ?? 0n,
      params.dkmsKeyFormat ?? 0,
      params.piiEnabled ?? false,
      params.outputStorageRef ?? ["", "", ""],
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
    body: new TextDecoder().decode(hexToBytes(body)),
    error: errorMessage || null,
    get jsonBody() { return JSON.parse(new TextDecoder().decode(hexToBytes(body))); },
  };
}
```

### Sovereign Agent (0x080C)

```typescript
import { parseAbiParameters } from "viem";

// Canonical input forwarded by your deployed SovereignAgentConsumer to 0x080C.
// See ritual-dapp-agents for deployment, wallet allowance and secret delegation.
// The chain-visible request is the canonical flat 13-field AgentAsyncEnvelope (shared with 0x0820, NOT a tuple);
// byte-exact canonical encoding is enforced ("agent envelope is not canonical ABI encoding").
const AGENT_ENVELOPE_ABI = parseAbiParameters(
  "address, address, uint64, uint64, bool, address, bytes4, uint64, uint128, uint128, uint256, bytes32, bytes",
);
// executorPayload: opaque 16-field sovereign V1 payload (version=1 first).
// phase2Ttl (envelope field 3) is the Phase 2 deadline offset in blocks (non-zero, <= 70,000).
const SOVEREIGN_PAYLOAD_V1_ABI = parseAbiParameters(
  "uint8, address[], bytes[], bytes[], bytes, uint16, string, (string,string,string), (string,string,string), (string,string,string)[], (string,string,string), string, string[], uint16, uint32, string",
);
type StorageRef = readonly [string, string, string];
const EMPTY_REF: StorageRef = ["", "", ""];

export function encodeAgentCallRequest(params: {
  executor: `0x${string}`;
  sponsor: `0x${string}`;            // funded EOA sponsor; approve the consumer as RitualWallet spender
  prompt: string;
  model: string;
  secretOwners?: readonly `0x${string}`[];
  encryptedSecrets?: readonly `0x${string}`[];
  secretSignatures?: readonly `0x${string}`[];
  userPublicKey?: `0x${string}`;
  cliType?: number;                  // 0 = claude_code, 5 = crush, 6 = zeroclaw
  tools?: string[];
  maxTurns?: number;
  maxTokens?: number;
  convoHistory?: StorageRef;
  output?: StorageRef;
  skills?: StorageRef[];
  systemPrompt?: StorageRef;
  rpcUrls?: string;
  ttl?: bigint;
  phase2Ttl?: bigint;
  callbackTarget: `0x${string}`;     // deployed consumer; callbacks enabled, callbackValue zero
  callbackSelector: `0x${string}`;   // e.g. toFunctionSelector("onSovereignAgentResult(bytes32,bytes)")
  callbackGasLimit?: bigint;         // uint64
  callbackMaxFeePerGas?: bigint;     // uint128
  callbackMaxPriorityFeePerGas?: bigint; // uint128 (<= callbackMaxFeePerGas)
  applicationContext?: `0x${string}`;
}): Hex {
  const executorPayload = encodeAbiParameters(SOVEREIGN_PAYLOAD_V1_ABI, [
    1, params.secretOwners ?? [], params.encryptedSecrets ?? [],
    params.secretSignatures ?? [], params.userPublicKey ?? "0x",
    params.cliType ?? 0, params.prompt,
    params.convoHistory ?? EMPTY_REF, params.output ?? EMPTY_REF,
    params.skills ?? [], params.systemPrompt ?? EMPTY_REF,
    params.model, params.tools ?? [],
    params.maxTurns ?? 10, params.maxTokens ?? 1024, params.rpcUrls ?? "",
  ]);
  return encodeAbiParameters(AGENT_ENVELOPE_ABI, [
    params.executor, params.sponsor, params.ttl ?? 200n, params.phase2Ttl ?? 1000n,
    true, params.callbackTarget, params.callbackSelector,
    params.callbackGasLimit ?? 3_000_000n,
    params.callbackMaxFeePerGas ?? 1_000_000_000n,
    params.callbackMaxPriorityFeePerGas ?? 100_000_000n,
    0n,                                                    // callbackValue — MUST be 0 ("sovereign agent callback value is not supported")
    params.applicationContext ?? "0x0000000000000000000000000000000000000000000000000000000000000000",
    executorPayload,
  ]);
}

export function decodeAgentPhase2(data: Hex) {
  const [success, errorMessage, response, updatedConvoHistory, updatedOutput, artifacts] =
    decodeAbiParameters(
      parseAbiParameters("bool, string, string, (string,string,string), (string,string,string), (string,string,string)[]"),
      data,
    );
  return { success, errorMessage, response, updatedConvoHistory, updatedOutput, artifacts };
}
```

---

## 6. Fee Estimation

Ritual charges executor fees from RitualWallet deposits. HTTP fees use fixed per-byte constants. LLM fees use a linear, cache-aware per-token rate card (base fee + input rate + output rate + cached-input discount bps) stored per model in the on-chain `ModelPricingRegistry`.

### HTTP Fee Constants

```typescript
export const HTTP_FEE_CONSTANTS = {
  BASE_FEE_WEI: 10_000_000_000_000_000n, // 0.01 RIT
  PER_INPUT_BYTE_WEI: 350_000_000n,
  PER_OUTPUT_BYTE_WEI: 350_000_000n,
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
    return { baseFee, inputFee, outputFee, totalFee, depositRecommendation: totalFee * 2n };
  }, [estimatedInputBytes, estimatedOutputBytes]);
}
```

### LLM Fee Model

LLM fees are per-token rates that vary by model. `fee_wei = llmBaseFeeWei + llmFeeWeiPerInputToken × fresh_prompt + llmFeeWeiPerInputToken × cached_prompt × llmCachedInputDiscountBps/10000 + llmFeeWeiPerOutputToken × completion`, with all four values read from `ModelPricingRegistry.getModel(model)` (fields 14-17 of `ModelInfo`; a model whose input rate is 0 has no LLM pricing and the job is rejected). Query the registry to check if a model exists (extend `modelPricingAbi` with `getModel(string)`, which returns the 17-field `ModelInfo` tuple whose last four `uint256`s are the LLM rate card — see `ritual-dapp-llm` — to compute a client-side estimate from those rates); for deposit sizing, use a conservative amount (0.1–1 RITUAL covers most single calls).

```typescript
const MODEL_PRICING_REGISTRY = "0xd190Aa03c401ef5CEcE00927b522974c0f330b97" as const;

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

## 7. SSE Streaming Consumer for LLM and RITHTTP1

Connect to Ritual's streaming service for real-time token delivery:

The authentication, URL, and fetch-based SSE transport are shared. Native LLM streaming uses Ritual's token event schema shown below. RITHTTP1 selectors receive complete upstream SSE data strings. Its STREAM pipe carries base64 RITPIPE1 records or encrypted records in the service's token field. Decode/bind those records, then interpret the selected payload (UTF8 text or selected provider JSON). RITOUT1 encoding 4 returns ordered per-pipe results, so public usage, live private text and a collected DA answer can coexist.

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

    const controller = new AbortController();
    abortControllerRef.current = controller;
    try {
      const timestamp = BigInt(Math.floor(Date.now() / 1000));
      const signature = await walletClient.signTypedData({
        domain: { name: "Ritual Streaming Service", version: "1", chainId: 784 },
        types: { StreamRequest: [{ name: "txHash", type: "bytes32" }, { name: "timestamp", type: "uint256" }] },
        primaryType: "StreamRequest",
        message: { txHash, timestamp },
      });

      if (controller.signal.aborted) return;
      setState((s) => ({ ...s, status: "streaming" }));

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
          if (data.token) {
            setState((s) => ({ ...s, text: s.text + data.token, tokens: s.tokens + 1 }));
          }
          if (data.error) { setState((s) => ({ ...s, status: "error", error: data.error })); return; }
          if (data.done) { setState((s) => ({ ...s, status: "done" })); return; }
        }
      }
      throw new Error("Stream ended before a completion event");
    } catch (error) {
      if (controller.signal.aborted) return;
      setState((s) => ({ ...s, status: "error", error: error instanceof Error ? error.message : "Stream failed" }));
      throw error;
    }
  }, [walletClient, streamingServiceUrl]);

  const stop = useCallback(() => { abortControllerRef.current?.abort(); setState((s) => ({ ...s, status: "done" })); }, []);
  const reset = useCallback(() => { stop(); setState({ status: "idle", text: "", tokens: 0 }); }, [stop]);

  return { state, stream, stop, reset };
}
```

For RITHTTP1, copy the included [rithttp-private-io.ts](../../examples/rithttp/rithttp-private-io.ts) and [request/result codec](../../examples/rithttp/rithttp.ts) into your application's `src/lib/` and install their public dependencies with Bun. Both public and encrypted STREAM tokens are base64 binary data; public frames still have a RITPIPE1 header. The selected encoding/selector determines what the payload means.

```typescript
import type { Hex } from "viem";
import { decodePipeRecord, decryptPipeRecord, verifyStreamFrames } from "@/lib/rithttp-private-io";

// Fresh state for each admitted request. These values come from its signed configuration.
function selectedTextStream(jobId: Hex, pipeIndex: number, encrypted: boolean, privateKey?: Hex) {
  const frames: Uint8Array[] = [];
  let pendingText = "";
  return {
    consume(data: string) {
      const event = JSON.parse(data) as { token?: string; done?: boolean; error?: string };
      if (event.error) throw new Error("stream delivery failed");
      if (event.token === undefined) return; // done does not prove settlement
      const frame = Uint8Array.from(atob(event.token), c => c.charCodeAt(0));
      const binding = { jobId, pipeIndex, encoding: 1, sequence: frames.length };
      if (encrypted && !privateKey) throw new Error("missing recipient key");
      const payload = encrypted
        ? decryptPipeRecord(privateKey!, frame, binding)
        : decodePipeRecord(frame, binding);
      frames.push(frame); // exact transmitted bytes, before decoding text
      pendingText += new TextDecoder("utf-8", { fatal: true }).decode(payload);
      // Display pendingText as provisional, with an explicit pending state.
    },
    accept(settled: { kind: number; encoding: number; encrypted: boolean; success: boolean;
      sha256: Hex; sizeBytes: bigint; itemCount: number }) {
      // Caller first authenticates canonical RITOUT1, expected array length/index and job.
      if (!settled.success || settled.kind !== 1 || settled.encoding !== 1 || settled.encrypted !== encrypted)
        throw new Error("unexpected stream result");
      verifyStreamFrames(frames, { ...settled, jobId, pipeIndex }, privateKey);
      return pendingText; // only now promote to accepted text
    },
  };
}
```

This snippet expects a UTF8 selector emitting text deltas. A JSON selector requires a parser for its selected JSON instead. Obtain the STREAM result at the requested **index**, not the first result of any kind. Its SHA-256 covers length-prefixed transmitted records/ciphertexts, `sizeBytes` is selected plaintext bytes and `itemCount` is the selected frame count. Missing/reordered frames fail verification. A DA answer is independently collected/encrypted and must be verified against its own result with `verifyCollectedOutput`; it is not the stream's ciphertext archive. Preserve valid usage accounting even when live delivery fails. See the [private-I/O reference](../ritual-dapp-http/references/rithttp1-private-io.md).


---

## 8. Transaction Flow Patterns

### Pattern 1: HTTP Call (short-running async — result in receipt)

```typescript
import { useAccount, useWalletClient, usePublicClient } from "wagmi";
import { useCallback, useId } from "react";
import { useAsyncTxStore } from "@/stores/asyncTxStore";
import { useAsyncJobEvents } from "@/hooks/useAsyncJobEvents";
import { encodeHTTPCallRequest } from "@/lib/encoding";

const HTTP_PRECOMPILE = "0x0000000000000000000000000000000000000801" as const;

export function useHTTPCall() {
  const txId = useId();
  const publicClient = usePublicClient();
  const { data: walletClient } = useWalletClient();
  const addTransaction = useAsyncTxStore((s) => s.addTransaction);
  const updateState = useAsyncTxStore((s) => s.updateState);
  const transaction = useAsyncTxStore((s) => s.transactions[txId]);

  useAsyncJobEvents({ txId, enabled: !!transaction });

  const submit = useCallback(async (options: {
    url: string; method?: "GET" | "POST"; headers?: Record<string, string>;
    body?: string; executor: `0x${string}`; sponsor: `0x${string}`; ttl?: bigint; label?: string;
  }) => {
    addTransaction(txId, "http", options.label);
    try {
      const encoded = encodeHTTPCallRequest({
        executor: options.executor,
        sponsor: options.sponsor,
        url: options.url,
        method: options.method ?? "GET",
        headerKeys: Object.keys(options.headers ?? {}),
        headerValues: Object.values(options.headers ?? {}),
        body: options.body,
        ttl: options.ttl,
      });
      if (!publicClient || !walletClient) throw new Error("Connect a wallet and chain client");
      const submittedBlock = await publicClient.getBlockNumber();
      const hash = await walletClient!.sendTransaction({ to: HTTP_PRECOMPILE, data: encoded, gas: 2_000_000n });
      updateState(txId, { status: "PENDING_COMMITMENT", txHash: hash, submittedBlock, submittedAt: Date.now(), ttlBlocks: Number(options.ttl ?? 100n) });
      return hash;
    } catch (err) {
      updateState(txId, { status: "FAILED", error: err instanceof Error ? err.message : "Transaction failed", errorCategory: "wallet", failedAt: "SUBMITTING" });
      throw err;
    }
  }, [txId, walletClient, publicClient, addTransaction, updateState]);

  return { txId, submit, state: transaction?.state ?? null };
}
```

### Pattern 2: Sovereign Agent (long-running async — result via callback)

```typescript
import { encodeFunctionData } from "viem";
import { useSendTransaction } from "wagmi";
import { useCallback, useId } from "react";
import { useAsyncTxStore } from "@/stores/asyncTxStore";
import { useAsyncJobEvents } from "@/hooks/useAsyncJobEvents";
import { encodeAgentCallRequest } from "@/lib/encoding";

const sovereignConsumerAbi = [{
  type: "function", name: "callSovereignAgent", stateMutability: "nonpayable",
  inputs: [{ name: "input", type: "bytes" }], outputs: [{ name: "result", type: "bytes" }],
}] as const;

export function useAgentCall() {
  const txId = useId();
  const { sendTransactionAsync } = useSendTransaction();
  const addTransaction = useAsyncTxStore((s) => s.addTransaction);
  const updateState = useAsyncTxStore((s) => s.updateState);
  const transaction = useAsyncTxStore((s) => s.transactions[txId]);

  useAsyncJobEvents({ txId, enabled: !!transaction });

  // Deploy the owner-controlled consumer and configure wallet/secret permissions first.
  const submit = useCallback(async (options: {
    consumerAddress: `0x${string}`;
    secretOwners?: readonly `0x${string}`[]; encryptedSecrets?: readonly `0x${string}`[];
    secretSignatures?: readonly `0x${string}`[]; userPublicKey?: `0x${string}`;
    cliType?: number;
    executor: `0x${string}`; sponsor: `0x${string}`; prompt: string; model: string; tools?: string[];
    maxTurns?: number; ttl?: bigint; phase2Ttl?: bigint;
    callbackSelector: `0x${string}`; label?: string;
  }) => {
    addTransaction(txId, "agent", options.label);
    try {
      const encoded = encodeAgentCallRequest({ ...options, callbackTarget: options.consumerAddress });
      const data = encodeFunctionData({ abi: sovereignConsumerAbi, functionName: "callSovereignAgent", args: [encoded] });
      const hash = await sendTransactionAsync({ to: options.consumerAddress, data, gas: 3_000_000n });
      updateState(txId, { status: "PENDING_COMMITMENT", txHash: hash, submittedAt: Date.now(), ttlBlocks: Number(options.ttl ?? 200n) });
      return hash;
    } catch (err) {
      updateState(txId, { status: "FAILED", error: err instanceof Error ? err.message : "Sovereign Agent call failed", errorCategory: "contract", failedAt: "SUBMITTING" });
      throw err;
    }
  }, [txId, sendTransactionAsync, addTransaction, updateState]);

  return { txId, submit, state: transaction?.state ?? null };
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
- Use `useRitualWallet()` for available balance, deposit/withdraw actions
- Use `useSenderLock()` to show lock indicator (amber dot + message when locked)
- Show balance in RITUAL with 4 decimal places (`formatEther`)

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

Shows fee breakdown. Format wei to RITUAL: `Number(wei) / 1e18`, display with 4 decimal places. Show `totalFee`.

---

## 10. Error Handling

Ritual-specific error codes to match against in `error.message`. Standard wallet errors (user rejected, insufficient funds) use normal wagmi/viem patterns.

| Code | Category | Match string | Recoverable | Ritual-specific guidance |
|------|----------|-------------|-------------|------------------------|
| `SENDER_LOCKED` | async | `"sender locked"`, `"pending job"` | Yes | Wait for current job to settle. Check `hasPendingJobForTxOrigin`. |
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
    WALLET:               "0xF04076756d8129Baec46Dc0F1c526Baec490C393",
    ASYNC_JOB_TRACKER:    "0xf00385449fD961925A0B125F5f30b29B682D4bFb",
    TEE_SERVICE_REGISTRY: "0xf4495DC72143D44A93AB0ecE4d6D63a216b27839",
    SCHEDULER:            "0x4E0abeE2233D73E66382b45244F7459B34E1490E",
    SECRETS_ACCESS_CTRL:  "0x0cEae62e2082829226eF5821Bb662483Db17A71F",
    MODEL_PRICING:        "0xd190Aa03c401ef5CEcE00927b522974c0f330b97",
  },
} as const;
```

---

## 12. Cross-References to Other Skills

| Need | Skill | What it provides |
|------|-------|-----------------|
| HTTP precompile encoding details | `ritual-dapp-http` | Full 16-field ABI, method codes, secrets, PII mode |
| LLM precompile encoding details | `ritual-dapp-llm` | Message format, model selection, conversation history |
| Executor discovery & selection | `ritual-dapp-precompiles` | TEEServiceRegistry queries, capability checks |
| Long-running HTTP | `ritual-dapp-longrunning` | Poll/result URL encoding, phase 2 callback |
| Sovereign Agent | `ritual-dapp-agents` | Agent envelope, consumer launch, secrets, funding |
| Contract deployment patterns | `ritual-dapp-contracts` | System contract addresses, ABI references |
| Secrets & encryption | `ritual-dapp-secrets` | ECIES encryption, SecretsAccessControl |
| Storage & DA | `ritual-dapp-da` | StorageRef format, GCS/HF/Pinata credentials, output URI handling |
| Design system | `ritual-dapp-design` | Color palette, typography, component patterns |
| Wallet & deposit flow | `ritual-dapp-wallet` | RitualWallet details, available/reserved balances, sponsor→caller allowance, per-job escrow |

Do not re-implement logic covered by these skills. Import the encoding/decoding functions they specify and use them in your hooks.

---

## Quick Reference

| Task | Hook / Component | Notes |
|------|------------------|-------|
| Connect wallet | Standard wagmi `useConnect` + `ChainGuard` | — |
| Bypass eth_call simulation | `useRitualWrite()` | Required for any async precompile call |
| Track async tx lifecycle | `useAsyncJobEvents({ txId })` | Uses `JobAdded`, `Phase1Settled`, `ResultDelivered`, `JobRemoved` and verified receipts |
| Check sender lock | `useSenderLock()` | Calls `hasPendingJobForTxOrigin` on AsyncJobTracker |
| Check deposit sufficiency | `useDepositGate(estimatedFee)` | Compare RitualWallet balance to estimated fee |
| Wallet balance + deposit | `useRitualWallet()` | `availableBalance`, `deposit`, `withdraw` |
| Block progress | `useBlockProgress({ startBlock, estimatedBlocks })` | UI-interpolated, no on-chain signal |
| HTTP fee estimate | `useHTTPFeeEstimate(inputBytes, outputBytes)` | Uses verified chain constants |
| LLM model check | `useModelCheck(model)` | Queries `ModelPricingRegistry.modelExists` |
| Parse spcCalls | `extractSpcResult(receipt)` + `decodeHTTPResponse(output)` | Short-running async precompiles only |
| Encode HTTP request | `encodeHTTPCallRequest(params)` | 16-field canonical format |
| Encode Sovereign Agent request | `encodeAgentCallRequest(params)` | See `ritual-dapp-agents` skill for field details |
| LLM streaming | `useStreamingLLM()` | SSE from `streaming.ritualfoundation.org` |

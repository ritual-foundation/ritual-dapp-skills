---
name: ritual-dapp-longrunning
description: Long-running HTTP precompile (0x0805) patterns for Ritual dApps. Use when building dApps with submit-poll-deliver workflows, background API jobs, multi-minute external tasks, JQ-based result extraction, or long-running (2-phase) async delivery.
---

# Long-Running HTTP Patterns

The Long-Running HTTP precompile (`0x0805`) enables on-chain requests to external APIs that take minutes or hours to complete. Unlike the standard HTTP precompile (`0x0801`) which settles in a single short-running async cycle (seconds), Long-Running HTTP uses a 2-phase submit-poll-deliver pattern with configurable JQ extraction queries.

> **Execution Model: Long-running (2-phase) async.** Phase 1 submits the initial HTTP request and returns a `taskId` (settled on-chain like a normal short-running async call). Phase 2 is a separate delivery transaction: the executor polls the external API off-chain, extracts the result via JQ, and delivers it to your contract via `AsyncDelivery`. Both phases require a funded `RitualWallet` — see `ritual-dapp-wallet` for deposit flows.
>
> **When to use 0x0805 vs 0x0801:** Use Long-Running HTTP when the external API has a submit-then-poll pattern, expected response time exceeds ~30 seconds, or the result comes from a different endpoint than the submission. Use standard HTTP (`0x0801`, see `ritual-dapp-http`) when the API responds within seconds in a single request/response cycle.
>
> **Constraints:** Max encoded input size is 10 KB. The `AsyncJobTracker` contract enforces a max Phase 2 deadline offset of 70,000 blocks. The caller's `RitualWallet` must have sufficient deposited RITUAL to cover executor fees and delivery gas costs; unfunded wallets are rejected during async payload validation. Wallet lock duration is also validated: `lockUntil(sender)` must be at least `commit_block + ttl`.

## How It Works

```
┌──────────────┐     ┌──────────────┐     ┌───────────────┐     ┌──────────────┐
│  User / dApp │     │  Precompile  │     │   Executor    │     │ External API │
│              │     │   0x0805     │     │   (TEE)       │     │              │
└──────┬───────┘     └──────┬───────┘     └──────┬────────┘     └──────┬───────┘
       │                    │                    │                     │
       │  1. Submit request │                    │                     │
       │───────────────────>│                    │                     │
       │                    │  2. Route to       │                     │
       │                    │     executor       │                     │
       │                    │───────────────────>│                     │
       │                    │                    │  3. Initial HTTP    │
       │                    │                    │     request         │
       │                    │                    │────────────────────>│
       │                    │                    │                     │
       │                    │                    │  4. Returns task_id │
       │                    │                    │<────────────────────│
       │                    │                    │                     │
       │  5. Phase 1:       │                    │                     │
       │     taskId returned │                    │                     │
       │<───────────────────│                    │                     │
       │                    │                    │                     │
       │                    │                    │  6. Poll status     │
       │                    │                    │     (every N blocks)│
       │                    │                    │────────────────────>│
       │                    │                    │<────────────────────│
       │                    │                    │  ... repeat ...     │
       │                    │                    │                     │
       │                    │                    │  7. Status: done    │
       │                    │                    │<────────────────────│
       │                    │                    │                     │
       │                    │                    │  8. Fetch result    │
       │                    │                    │     (optional)      │
       │                    │                    │────────────────────>│
       │                    │                    │<────────────────────│
       │                    │                    │                     │
       │  9. Phase 2:       │                    │                     │
       │     deliver result │                    │                     │
       │     to contract    │                    │                     │
       │<───────────────────│<───────────────────│                     │
       │                    │                    │                     │
```

**Three phases**:

1. **Submit**: Your dApp sends the initial HTTP request configuration to precompile `0x0805`. The executor makes the initial HTTP call and returns a `taskId`.
2. **Poll**: The executor periodically hits the poll URL (with the task ID substituted in), checks the status using a JQ query, and waits until the job is done.
3. **Deliver**: Once the status query indicates completion, the executor extracts the result (via JQ), and delivers it to your contract via callback.

---

### Async Guardrails

- **One `0x0805` call per transaction:** The precompile enforces a single long-running HTTP call during fresh simulation.
- **Sender async lock in mempool:** While one async transaction is pending for a sender, additional async transactions from the same sender can be rejected with `sender locked due to existing async transaction in pool`.
- **Wallet lock monotonicity:** `RitualWallet.deposit(lockDuration)` only extends `lockUntil` (it never shortens it). For development, prefer long lock windows so `lockUntil >= commit_block + ttl` remains true at settlement.

---

## 1. viem Helper-Contract Usage

This helper-contract pattern shows the full lifecycle using raw viem:

```typescript
import { defineChain, createWalletClient, http, toFunctionSelector, encodeAbiParameters, parseAbiParameters } from 'viem';
import { privateKeyToAccount } from 'viem/accounts';

const ritualChain = defineChain({
  id: 1979,
  name: 'Ritual',
  nativeCurrency: { name: 'RITUAL', symbol: 'RITUAL', decimals: 18 },
  rpcUrls: { default: { http: [process.env.RITUAL_RPC_URL!] } },
});

const account = privateKeyToAccount(process.env.PRIVATE_KEY! as `0x${string}`);
const walletClient = createWalletClient({ account, chain: ritualChain, transport: http() });

const LONG_RUNNING_HTTP_PRECOMPILE = '0x0000000000000000000000000000000000000805' as const;

const callbackSelector = toFunctionSelector(
  'onLongRunningResult(bytes32,bytes)'
);

const LONG_HTTP_ABI = parseAbiParameters([
  'address, bytes[], uint256, bytes[], bytes,',             // base executor fields
  'uint64, uint64, string,',                                // polling config
  'address, bytes4, uint256, uint256, uint256, uint256,',   // delivery config
  'string, uint8, string[], string[], bytes, string,',      // initial HTTP request
  'string, uint8, string[], string[], bytes, string,',      // poll request
  'string, uint8, string[], string[], bytes, string,',      // result request
  'uint256, uint8, bool',                                   // DKMS + PII
].join(''));

const encoded = encodeAbiParameters(LONG_HTTP_ABI, [
  '0x...executorAddress',                        // TEE executor (from TEEServiceRegistry)
  [], 200n, [], '0x',                           // base fields

  // Polling configuration
  5n, 1000n, '{{TASK_ID}}',

  // Delivery
  contractAddress, callbackSelector, 300_000n,
  1_000_000_000n, 100_000_000n, 0n,

  // Initial HTTP request
  'https://api.example.com/research',
  2,                                            // POST
  ['Content-Type'], ['application/json'],       // headers
  new TextEncoder().encode(JSON.stringify({ query: 'AI trends 2026' })),
  '.task_id',                                   // taskIdJsonPath

  // Poll request
  'https://api.example.com/status/{{TASK_ID}}',
  1,                                            // GET
  [], [],                                       // no extra headers
  new Uint8Array(0),                            // no body
  '.status == "completed"',                     // statusJsonPath

  // Result request (empty = use poll response)
  '', 0, [], [], new Uint8Array(0),
  '.result',                                    // resultJsonPath

  // DKMS + PII
  0n, 0, false,
]);

const hash = await walletClient.sendTransaction({
  to: LONG_RUNNING_HTTP_PRECOMPILE,
  data: encoded,
  gas: 3_000_000n,
});
```

---

## 2. ABI Reference

The Long-Running HTTP request has 35 ABI fields organized into sections:

### Base Executor Fields

```
executor           address   — TEE executor address
encryptedSecrets   bytes[]   — ECIES-encrypted secrets (API keys via SECRET_NAME string replacement)
ttl                uint256   — Time-to-live in blocks
secretSignatures   bytes[]   — Signatures over encrypted secrets
userPublicKey      bytes     — User's public key for encrypted outputs
```

### Polling Configuration

```
pollIntervalBlocks  uint64   — How often (in blocks) the executor checks job status
maxPollBlock        uint64   — Block number after which polling stops (timeout)
taskIdMarker        string   — Placeholder string replaced with actual task ID in URLs
```

### Delivery Configuration

```
deliveryTarget               address  — Contract to receive the final result (0x0 = no delivery)
deliverySelector             bytes4   — Callback function selector
deliveryGasLimit             uint256  — Gas limit for the delivery transaction
deliveryMaxFeePerGas         uint256  — EIP-1559 max fee for delivery
deliveryMaxPriorityFeePerGas uint256  — EIP-1559 priority fee for delivery
deliveryValue                uint256  — RITUAL value to send with delivery callback
```

### Initial HTTP Request

```
url             string    — URL for the initial request
method          uint8     — HTTP method (0=NOOP/invalid, 1=GET, 2=POST, 3=PUT, 4=DELETE, 5=PATCH)
headersKeys     string[]  — Header names
headersValues   string[]  — Header values (parallel array with headersKeys)
body            bytes     — Request body (empty for GET)
taskIdJsonPath  string    — JQ expression to extract the task ID from the initial response
```

### Poll Request

```
pollUrl            string    — URL to check job status (use taskIdMarker for substitution)
pollMethod         uint8     — HTTP method for polling (usually 1=GET)
pollHeadersKeys    string[]  — Header names for poll requests
pollHeadersValues  string[]  — Header values for poll requests
pollBody           bytes     — Body for poll requests (usually empty)
statusJsonPath     string    — JQ expression that returns true when job is complete
```

### Result Request

```
resultUrl            string    — URL to fetch the final result (if different from poll URL)
resultMethod         uint8     — HTTP method for result fetch
resultHeadersKeys    string[]  — Header names for result requests
resultHeadersValues  string[]  — Header values for result requests
resultBody           bytes     — Body for result requests
resultJsonPath       string    — JQ expression to extract the result from the response
```

### Advanced Options

```
dkmsKeyIndex   uint256  — DKMS key index for encrypted delivery (0 = disabled)
dkmsKeyFormat  uint8    — Key format (0 = disabled, 1 = Eth)
piiEnabled     bool     — enable secret string replacement (SECRET) and PII redaction
```

---

## 3. Polling Configuration

### pollIntervalBlocks

Controls how frequently the executor checks the external API for completion. Use ~350ms as the conservative block-time baseline (and confirm on your target RPC with `ritual-dapp-block-time`).

```
pollIntervalBlocks = 5     → Poll every ~1.75 seconds (aggressive, for fast APIs)
pollIntervalBlocks = 25    → Poll every ~8.75 seconds (balanced default)
pollIntervalBlocks = 150   → Poll every ~52.5 seconds (relaxed, for slow APIs)
pollIntervalBlocks = 300   → Poll every ~105 seconds (~1.75 minutes, for very slow jobs)
```

Choose based on the expected job duration and API rate limits. Setting `pollIntervalBlocks` too low wastes executor resources and may trigger API rate limits (non-retryable — the job gets dropped).

```typescript
// Fast API (returns in < 30 seconds)
pollIntervalBlocks: 5n,
maxPollBlock: 750n,    // ~262 second timeout (~4.4 min)

// Medium API (returns in 1-5 minutes)
pollIntervalBlocks: 25n,
maxPollBlock: 2_572n,  // ~15 minute timeout

// Slow API (returns in 5-30 minutes)
pollIntervalBlocks: 150n,
maxPollBlock: 15_000n, // ~87.5 minute timeout

// Very slow API (returns in hours)
pollIntervalBlocks: 300n,
maxPollBlock: 70_000n, // ~6.8 hour timeout (chain max)
```

### maxPollBlock

A **relative offset** (in blocks) from the Phase 1 settlement block. The executor internally computes the deadline as `settledBlock + maxPollBlock`. If the current block exceeds this deadline, the job is considered timed out and no delivery is made.

`maxPollBlock` must be `> ttl` and `<= 70_000` for two-phase precompiles on current chain rules.

Calculate it as:

```
maxPollBlock = expectedDuration / blockTime * safetyMultiplier
```

For a 5-minute expected job at ~0.35s blocks with 3x safety:

```
maxPollBlock = (5 * 60 / 0.35) * 3 ≈ 2572 blocks
```

> **Note:** Polling does not begin immediately after Phase 1 returns the task ID. The executor waits for Phase 1 settlement confirmation on-chain before starting to poll. Factor this gap into your timeout calculations.

### JQ Queries

The executor uses JQ (a JSON query language) to extract data from API responses. Three JQ queries control the flow:

#### taskIdJsonPath

Extracts the task ID from the initial response. Applied to the JSON body returned by the initial `url` request.

```
API returns: { "job_id": "abc-123", "status": "queued" }
taskIdJsonPath: ".job_id"
Result: "abc-123"
```

```
API returns: { "data": { "task": { "id": 42 } } }
taskIdJsonPath: ".data.task.id"
Result: 42
```

#### statusJsonPath

Applied to the poll response. Must return a boolean — `true` means the job is complete.

```
API returns: { "status": "completed", "progress": 100 }
statusJsonPath: '.status == "completed"'
Result: true → job is done, proceed to result fetch

API returns: { "status": "processing", "progress": 65 }
statusJsonPath: '.status == "completed"'
Result: false → keep polling
```

Common patterns:

```
'.status == "completed"'           — Exact string match
'.status == "done" or .status == "finished"'  — Multiple statuses
'.progress >= 100'                 — Numeric threshold
'.completed == true'               — Boolean field
'.state | IN("success", "done")'   — Set membership
```

#### resultJsonPath

Extracts the final result from either the poll response or the result URL response. Applied after `statusJsonPath` returns `true`.

```
API returns: { "result": { "summary": "...", "score": 95 }, "metadata": {...} }
resultJsonPath: ".result"
Result: { "summary": "...", "score": 95 }
```

```
API returns: { "output": "The analysis shows..." }
resultJsonPath: ".output"
Result: "The analysis shows..."
```

### taskIdMarker

A placeholder string that gets replaced with the actual task ID in poll/result URLs. There is no protocol-enforced default marker; `{{TASK_ID}}` is a common convention.

```typescript
// In the request:
pollUrl: 'https://api.example.com/status/{{TASK_ID}}',
taskIdMarker: '{{TASK_ID}}',

// After initial request returns taskId = "job-abc123":
// Executor polls: https://api.example.com/status/job-abc123
```

You can use any marker string, but `{{TASK_ID}}` is the convention:

```typescript
// Custom marker
pollUrl: 'https://api.example.com/check?id=__JOB__',
taskIdMarker: '__JOB__',
```

The marker is also substituted in:
- `resultUrl` — for fetching the final result
- `pollBody` — if the task ID needs to be in the poll request body
- `resultBody` — if the task ID needs to be in the result request body

---

## 4. Solidity Consumer Contract

> **Prerequisites:** The transaction sender's `RitualWallet` must be funded with sufficient RITUAL before calling any async precompile. See `ritual-dapp-wallet` for deposit flows. If unfunded, async payload validation rejects the transaction.
>
> **Important job ID semantics:** The callback `jobId` is the async job identifier (origin transaction hash), not `keccak256(taskId)`. You cannot derive callback `jobId` from the returned `taskId` inside Solidity.

### LongRunningHTTPConsumer.sol

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract LongRunningHTTPConsumer {
    address public constant LONG_RUNNING_HTTP_PRECOMPILE = address(0x0805);
    // AsyncDelivery proxy — msg.sender for all async callbacks
    address constant ASYNC_DELIVERY_SENDER = 0x5A16214fF555848411544b005f7Ac063742f39F6;
    address constant TX_HASH_PRECOMPILE = address(0x0830);

    struct JobResult {
        uint16 statusCode;
        bytes body;
        string errorMessage;
        uint256 completedBlock;
    }

    mapping(bytes32 => JobResult) public results;
    mapping(bytes32 => bool) public pendingJobs;

    event JobSubmitted(bytes32 indexed jobId, string taskId, uint256 blockNumber);
    event JobCompleted(bytes32 indexed jobId, uint16 statusCode, uint256 dataLength);
    event JobFailed(bytes32 indexed jobId, string reason);

    /// @notice Submit a long-running HTTP job
    /// @param encodedRequest ABI-encoded LongRunningHTTPCallRequest
    function initiateJob(bytes calldata encodedRequest) external payable {
        // Add application-specific access control here if processing the result
        // can change privileged state.
        bytes32 jobId = _trackCurrentJob();

        (bool ok, bytes memory rawOutput) = LONG_RUNNING_HTTP_PRECOMPILE.call(
            encodedRequest
        );
        require(ok, "Long-running HTTP precompile failed");

        // Async precompiles return (bytes simmedInput, bytes actualOutput)
        (, bytes memory actualOutput) = abi.decode(rawOutput, (bytes, bytes));
        string memory taskId = abi.decode(actualOutput, (string));
        emit JobSubmitted(jobId, taskId, block.number);
    }

    /// @notice Callback from AsyncDelivery when the job completes
    /// @dev The function selector must match deliverySelector exactly.
    ///      AsyncDelivery invokes: target.call(abi.encodeWithSelector(selector, jobId, result)).
    ///      Your callback must accept BOTH parameters: (bytes32 jobId, bytes result).
    function onLongRunningResult(bytes32 jobId, bytes calldata result) external {
        require(msg.sender == ASYNC_DELIVERY_SENDER, "unauthorized callback");
        require(pendingJobs[jobId], "unknown or fulfilled job");
        delete pendingJobs[jobId];

        // Result is an HTTPCallResponse: (statusCode, headerKeys, headerValues, body, errorMessage)
        (uint16 statusCode, , , bytes memory body, string memory errorMessage) =
            abi.decode(result, (uint16, string[], string[], bytes, string));

        results[jobId] = JobResult({
            statusCode: statusCode,
            body: body,
            errorMessage: errorMessage,
            completedBlock: block.number
        });

        if (statusCode >= 200 && statusCode < 300 && bytes(errorMessage).length == 0) {
            emit JobCompleted(jobId, statusCode, body.length);
            _processResult(jobId, body);
        } else {
            string memory reason = bytes(errorMessage).length > 0
                ? errorMessage
                : "HTTP error";
            emit JobFailed(jobId, reason);
        }
    }

    /// @notice Override this to process the result body
    function _processResult(bytes32 jobId, bytes memory body) internal virtual {}

    function getResult(bytes32 jobId) external view returns (JobResult memory) {
        return results[jobId];
    }

    function _trackCurrentJob() internal returns (bytes32 jobId) {
        (bool ok, bytes memory output) = TX_HASH_PRECOMPILE.staticcall("");
        require(ok && output.length == 32, "tx hash unavailable");
        jobId = abi.decode(output, (bytes32));
        require(!pendingJobs[jobId], "job already pending");
        pendingJobs[jobId] = true;
    }

}
```

`encodedRequest` must set `deliveryTarget = address(this)` and use
`this.onLongRunningResult.selector`. Checking AsyncDelivery alone is insufficient because another caller
can put this contract and selector into its own delivery configuration.

### Specialized Consumer: AI Research Assistant

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "./LongRunningHTTPConsumer.sol";

contract AIResearchConsumer is LongRunningHTTPConsumer {
    struct ResearchResult {
        string query;
        string summary;
        uint256 timestamp;
        bool processed;
    }

    mapping(bytes32 => ResearchResult) public research;

    event ResearchSubmitted(string taskId, string query);
    event ResearchCompleted(bytes32 indexed jobId, string summary);

    function submitResearch(
        bytes calldata encodedRequest,
        string calldata query
    ) external payable {
        (bool ok, bytes memory rawOutput) = LONG_RUNNING_HTTP_PRECOMPILE.call(
            encodedRequest
        );
        require(ok, "Precompile call failed");

        (, bytes memory actualOutput) = abi.decode(rawOutput, (bytes, bytes));
        string memory taskId = abi.decode(actualOutput, (string));
        emit JobSubmitted(taskId, block.number);
        emit ResearchSubmitted(taskId, query);
    }

    function _processResult(bytes32 jobId, bytes memory body) internal override {
        string memory summary = abi.decode(body, (string));
        // jobId comes from AsyncDelivery callback and is not derivable from taskId.
        // Persist by callback jobId and correlate taskId off-chain via events if needed.
        research[jobId].query = "";
        research[jobId].summary = summary;
        research[jobId].timestamp = block.timestamp;
        research[jobId].processed = true;
        emit ResearchCompleted(jobId, summary);
    }
}
```

---

## 5. Frontend: useAsyncJob Hook

A React hook for submitting long-running jobs and tracking their progress.

### useAsyncJob Hook

```typescript
import { useState, useCallback, useEffect, useRef } from 'react';
import {
  usePublicClient,
  useWalletClient,
  useWatchContractEvent,
  useBlockNumber,
} from 'wagmi';
import type { Hex } from 'viem';

type AsyncJobStatus =
  | 'idle'
  | 'submitting'
  | 'pending'
  | 'polling'
  | 'completed'
  | 'failed'
  | 'timeout';

interface AsyncJobState {
  status: AsyncJobStatus;
  taskId: string | null;
  result: unknown;
  error: string | null;
  submittedBlock: bigint | null;
  currentBlock: bigint | null;
  maxPollBlock: bigint | null;
  progressPercent: number;
}

const INITIAL_STATE: AsyncJobState = {
  status: 'idle',
  taskId: null,
  result: null,
  error: null,
  submittedBlock: null,
  currentBlock: null,
  maxPollBlock: null,
  progressPercent: 0,
};

interface UseAsyncJobOptions {
  consumerAddress: `0x${string}`;
  consumerAbi: readonly unknown[];
}

export function useAsyncJob({
  consumerAddress,
  consumerAbi,
}: UseAsyncJobOptions) {
  const [state, setState] = useState<AsyncJobState>(INITIAL_STATE);
  const publicClient = usePublicClient();
  const { data: walletClient } = useWalletClient();
  const { data: blockNumber } = useBlockNumber({ watch: true });

  // Update block progress
  useEffect(() => {
    if (
      blockNumber &&
      state.submittedBlock &&
      state.maxPollBlock &&
      (state.status === 'pending' || state.status === 'polling')
    ) {
      const elapsed = blockNumber - state.submittedBlock;
      // maxPollBlock is a relative offset, so use it directly as total
      const total = state.maxPollBlock;
      const progress = total > 0n
        ? Math.min(Number((elapsed * 100n) / total), 99)
        : 0;

      setState((prev) => ({
        ...prev,
        currentBlock: blockNumber,
        progressPercent: progress,
        status: progress > 0 ? 'polling' : prev.status,
      }));

      if (elapsed >= state.maxPollBlock) {
        setState((prev) => ({
          ...prev,
          status: 'timeout',
          error: `Job exceeded maxPollBlock offset (${state.maxPollBlock} blocks)`,
        }));
      }
    }
  }, [blockNumber, state.submittedBlock, state.maxPollBlock, state.status]);

  // Listen for completion — fetch full result via getResult() after event
  useWatchContractEvent({
    address: consumerAddress,
    abi: consumerAbi,
    eventName: 'JobCompleted',
    async onLogs(logs) {
      for (const log of logs) {
        const args = (log as unknown as { args: { jobId: `0x${string}` } }).args;
        const result = await publicClient!.readContract({
          address: consumerAddress,
          abi: consumerAbi,
          functionName: 'getResult',
          args: [args.jobId],
        });
        setState((prev) => ({
          ...prev,
          status: 'completed',
          result,
          progressPercent: 100,
        }));
      }
    },
  });

  // Listen for failures
  useWatchContractEvent({
    address: consumerAddress,
    abi: consumerAbi,
    eventName: 'JobFailed',
    onLogs(logs) {
      for (const log of logs) {
        const args = (log as unknown as { args: Record<string, unknown> }).args;
        setState((prev) => ({
          ...prev,
          status: 'failed',
          error: args.reason as string,
        }));
      }
    },
  });

  const submitJob = useCallback(
    async (
      encodedRequest: Hex,
      maxPollBlock: bigint,
    ) => {
      if (!walletClient || !publicClient) {
        setState((prev) => ({
          ...prev,
          status: 'failed',
          error: 'Wallet not connected',
        }));
        return;
      }

      setState({ ...INITIAL_STATE, status: 'submitting' });

      try {
        const txHash = await walletClient.writeContract({
          address: consumerAddress,
          abi: consumerAbi,
          functionName: 'initiateJob',
          args: [encodedRequest],
        });

        // On some Ritual async flows, the origin tx hash may not expose a direct receipt.
        // If this call times out, resolve via AsyncJobTracker JobAdded (jobId == origin tx hash),
        // then follow the commitment tx receipt (`originalTx` / `originTx` fields).
        const receipt = await publicClient.waitForTransactionReceipt({
          hash: txHash,
        });

        if (receipt.status === 'reverted') {
          setState((prev) => ({
            ...prev,
            status: 'failed',
            error: 'Transaction reverted',
          }));
          return;
        }

        const currentBlock = await publicClient.getBlockNumber();

        setState((prev) => ({
          ...prev,
          status: 'pending',
          submittedBlock: currentBlock,
          currentBlock,
          maxPollBlock,
        }));
      } catch (err) {
        setState((prev) => ({
          ...prev,
          status: 'failed',
          error: err instanceof Error ? err.message : 'Unknown error',
        }));
      }
    },
    [walletClient, publicClient, consumerAddress, consumerAbi],
  );

  const reset = useCallback(() => {
    setState(INITIAL_STATE);
  }, []);

  return {
    ...state,
    submitJob,
    reset,
    isLoading:
      state.status === 'submitting' ||
      state.status === 'pending' ||
      state.status === 'polling',
    blocksElapsed: state.submittedBlock && state.currentBlock
      ? Number(state.currentBlock - state.submittedBlock)
      : 0,
    blocksRemaining: state.maxPollBlock && state.currentBlock && state.submittedBlock
      ? Math.max(0, Number(state.maxPollBlock - (state.currentBlock - state.submittedBlock)))
      : null,
  };
}
```

### Usage: Research Assistant UI

```tsx
import { useState } from 'react';
import { encodeAbiParameters, toFunctionSelector } from 'viem';
import { useAsyncJob } from './hooks/useAsyncJob';
import { RESEARCH_CONSUMER_ABI } from './abi/researchConsumer';
import { LONG_HTTP_ABI } from './abi/longRunningHttp'; // See Section 1 for definition

function ResearchAssistant() {
  const [query, setQuery] = useState('');

  const {
    status,
    result,
    error,
    progressPercent,
    blocksElapsed,
    blocksRemaining,
    isLoading,
    submitJob,
    reset,
  } = useAsyncJob({
    consumerAddress: '0x...ResearchConsumer',
    consumerAbi: RESEARCH_CONSUMER_ABI,
  });

  const handleSubmit = async () => {
    const MAX_POLL_BLOCK = 500n;

    const encoded = encodeAbiParameters(LONG_HTTP_ABI, [
      '0x...executor', [], 200n, [], '0x',
      5n, MAX_POLL_BLOCK, '{{TASK_ID}}',
      '0x...ResearchConsumer',
      toFunctionSelector('onLongRunningResult(bytes32,bytes)'),
      300_000n, 1_000_000_000n, 100_000_000n, 0n,
      'https://api.research-service.com/analyze',
      2, ['Content-Type'], ['application/json'],
      new TextEncoder().encode(JSON.stringify({ query })),
      '.task_id',
      'https://api.research-service.com/status/{{TASK_ID}}',
      1, [], [], new Uint8Array(0),
      '.status == "completed"',
      '', 0, [], [], new Uint8Array(0),
      '.result.summary',
      0n, 0, false,
    ]);

    await submitJob(encoded, MAX_POLL_BLOCK);
  };

  return (
    <div className="research-panel">
      <div className="input-section">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="What would you like to research?"
          disabled={isLoading}
        />
        <button onClick={handleSubmit} disabled={isLoading || !query}>
          {isLoading ? 'Researching...' : 'Start Research'}
        </button>
      </div>

      {(status === 'pending' || status === 'polling') && (
        <div className="progress-section">
          <div className="progress-bar">
            <div
              className="progress-fill"
              style={{ width: `${progressPercent}%` }}
            />
          </div>
          <div className="progress-info">
            <span>{progressPercent}% complete</span>
            <span>{blocksElapsed} blocks elapsed</span>
            {blocksRemaining !== null && (
              <span>~{Math.ceil(blocksRemaining * 0.35)}s remaining</span>
            )}
          </div>
          <p className="status-text">
            {status === 'pending'
              ? 'Job submitted, waiting for executor...'
              : 'Executor polling for results...'}
          </p>
        </div>
      )}

      {status === 'completed' && result && (
        <div className="result-section">
          <h3>Research Complete</h3>
          <div className="result-content">{String(result)}</div>
          <button onClick={reset}>New Research</button>
        </div>
      )}

      {status === 'failed' && (
        <div className="error-section">
          <p>Research failed: {error}</p>
          <button onClick={reset}>Try Again</button>
        </div>
      )}

      {status === 'timeout' && (
        <div className="timeout-section">
          <p>Research timed out after {blocksElapsed} blocks.</p>
          <p>The external API may still be processing. Try again with a higher timeout.</p>
          <button onClick={reset}>Reset</button>
        </div>
      )}
    </div>
  );
}
```

---

## 6. Combining with Scheduler

The Scheduler contract can trigger long-running jobs on a recurring basis — e.g., a scheduled job kicks off a long-running AI generation task daily. See `ritual-dapp-scheduler` for the full Scheduler API.

### Scheduled Long-Running Job Contract

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract ScheduledResearchConsumer {
    address public constant LONG_RUNNING_HTTP_PRECOMPILE = address(0x0805);
    address public constant SCHEDULER = 0x56e776BAE2DD60664b69Bd5F865F1180ffB7D58B;
    // AsyncDelivery proxy — msg.sender for all async callbacks
    address constant ASYNC_DELIVERY_SENDER = 0x5A16214fF555848411544b005f7Ac063742f39F6;

    address public owner;
    bytes public encodedRequest;
    uint256 public lastRunBlock;
    string public latestResult;

    event ScheduledJobSubmitted(uint256 blockNumber, string taskId);
    event ScheduledJobCompleted(uint256 blockNumber, string result);

    constructor() {
        owner = msg.sender;
    }

    function setRequest(bytes calldata _encodedRequest) external {
        require(msg.sender == owner, "Only owner");
        encodedRequest = _encodedRequest;
    }

    function executeScheduledJob() external {
        require(
            msg.sender == SCHEDULER || msg.sender == owner,
            "Only scheduler or owner"
        );

        (bool ok, bytes memory rawOutput) = LONG_RUNNING_HTTP_PRECOMPILE.call(
            encodedRequest
        );
        require(ok, "Long-running HTTP call failed");

        (, bytes memory actualOutput) = abi.decode(rawOutput, (bytes, bytes));
        string memory taskId = abi.decode(actualOutput, (string));
        lastRunBlock = block.number;

        emit ScheduledJobSubmitted(block.number, taskId);
    }

    function onLongRunningResult(bytes32 jobId, bytes calldata result) external {
        require(msg.sender == ASYNC_DELIVERY_SENDER, "unauthorized callback");

        (uint16 statusCode, , , bytes memory body, string memory errorMessage) =
            abi.decode(result, (uint16, string[], string[], bytes, string));

        if (statusCode >= 200 && statusCode < 300 && bytes(errorMessage).length == 0) {
            latestResult = abi.decode(body, (string));
            emit ScheduledJobCompleted(block.number, latestResult);
        }
    }
}
```

### Setting Up the Schedule (TypeScript)

```typescript
import { createWalletClient, http, defineChain, toFunctionSelector } from 'viem';
import { privateKeyToAccount } from 'viem/accounts';

const ritualChain = defineChain({
  id: 1979,
  name: 'Ritual',
  nativeCurrency: { name: 'RITUAL', symbol: 'RITUAL', decimals: 18 },
  rpcUrls: { default: { http: [process.env.RITUAL_RPC_URL!] } },
});

const account = privateKeyToAccount(process.env.PRIVATE_KEY! as `0x${string}`);
const walletClient = createWalletClient({ account, chain: ritualChain, transport: http() });

const SCHEDULER = '0x56e776BAE2DD60664b69Bd5F865F1180ffB7D58B' as const;

// Schedule the job to run every 24 hours (~246_858 blocks at ~0.35s/block)
await walletClient.writeContract({
  address: SCHEDULER,
  abi: [{
    name: 'schedule',
    type: 'function',
    stateMutability: 'nonpayable',
    inputs: [
      { name: 'target', type: 'address' },
      { name: 'selector', type: 'bytes4' },
      { name: 'intervalBlocks', type: 'uint256' },
      { name: 'maxExecutions', type: 'uint256' },
      { name: 'gasLimit', type: 'uint256' },
    ],
    outputs: [],
  }] as const,
  functionName: 'schedule',
  args: [
    '0x...ScheduledResearchConsumer',
    toFunctionSelector('executeScheduledJob()'),
    246_858n,  // ~24 hours at ~0.35s/block
    0n,        // unlimited
    500_000n,
  ],
});
```

---

## 7. Secret Injection for Authenticated APIs

Most real-world APIs require authentication. Use encrypted secrets with the `SECRET_NAME` string replacement pattern:

```typescript
import { createPublicClient, http, encodeAbiParameters } from 'viem';
import { encrypt } from 'eciesjs';

// ritualChain and publicClient setup — same as Section 1

const TEE_SERVICE_REGISTRY = '0x9644e8562cE0Fe12b4deeC4163c064A8862Bf47F' as const;
const CAPABILITY_HTTP = 0;

// Find an executor and get its public key
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
  args: [CAPABILITY_HTTP, true],
});
const executor = services[0];

// Encrypt API key with executor's public key using ECIES
const secretJson = JSON.stringify({ API_KEY: process.env.RESEARCH_API_KEY! });
const encryptedSecrets = [
  `0x${encrypt(executor.node.publicKey.slice(2), Buffer.from(secretJson)).toString('hex')}` as `0x${string}`,
];

const encoded = encodeAbiParameters(LONG_HTTP_ABI, [
  executor.node.teeAddress, encryptedSecrets, 200n, [], '0x',

  // Polling
  5n, 500n, '{{TASK_ID}}',

  // Delivery
  '0x...consumer', '0x...', 300_000n,
  1_000_000_000n, 100_000_000n, 0n,

  // Initial HTTP request — API_KEY is substituted by executor at runtime
  'https://api.premium-research.com/jobs',
  1, ['Content-Type', 'Authorization'], ['application/json', 'Bearer API_KEY'],
  new TextEncoder().encode(JSON.stringify({ query: 'AI trends' })),
  '.job_id',

  // Poll request
  'https://api.premium-research.com/jobs/{{TASK_ID}}/status',
  1, ['Authorization'], ['Bearer {{API_KEY}}'],
  new Uint8Array(0),
  '.done == true',

  // Result (use poll response)
  '', 0, [], [], new Uint8Array(0),
  '.result',

  0n, 0, false,
]);
```

The executor decrypts the secrets inside the TEE and replaces `API_KEY` with the actual value before making HTTP requests. The secret never appears on-chain.

---

## 8. Error Handling & Failure Modes

### Failure Mode Reference

| Failure | What Happens | What to Do |
|---------|-------------|------------|
| **RitualWallet unfunded** | Async payload validation rejects the transaction before job creation | Ensure sender's RitualWallet is funded before submission. See `ritual-dapp-wallet`. |
| **Insufficient lock duration** | Async payload validation rejects before job creation (`Insufficient lock duration`) | Ensure `RitualWallet.lockUntil(sender) >= commit_block + ttl`; extend lock with a larger `deposit(lockDuration)`. |
| **Sender locked by existing async tx** | Pool rejects additional async tx from same sender while one is pending | Use separate EOAs for concurrent async jobs, or wait until the pending async tx settles. |
| **Origin tx receipt not found** | Some async flows expose only the commitment tx receipt (`type=0x11`); `eth_getTransactionReceipt(originTxHash)` may timeout/null | Resolve via `AsyncJobTracker` `JobAdded` (`jobId == originTxHash`) and read the commitment tx receipt fields (`originalTx` / `originTx`). |
| **Multiple `0x0805` calls in one tx** | Precompile rejects additional long-running calls in the same transaction | Split each long-running HTTP request into its own transaction. |
| **Timeout** (`maxPollBlock` exceeded) | Executor stops polling, no delivery is made | Resubmit with a higher `maxPollBlock`. Note: this creates a **new** job — the external API may have already finished the original, causing a duplicate. |
| **Initial HTTP request fails** (non-2xx) | Phase 1 settles but no task ID is extracted | The JQ `taskIdJsonPath` query returns null/error. No polling starts. No delivery. |
| **JQ query returns null/empty** | Task ID, status check, or result extraction produces nothing | Verify JQ queries locally with `curl ... \| jq '<query>'` before on-chain submission. |
| **Poll URL returns errors** | Executor retries up to 3 times for transient failures, then drops the job | No delivery is made. Frontend should handle the timeout case. |
| **API rate-limits during polling** | Non-retryable failure — job is dropped immediately | Set `pollIntervalBlocks` high enough to respect API rate limits. |
| **Delivery callback reverts** | `AsyncDelivery` emits `DeliveryFailed` event — result is lost | Increase `deliveryGasLimit`, simplify callback logic, verify `deliverySelector` matches exactly. Monitor `DeliveryFailed` events. |
| **Executor goes down mid-polling** | Job is orphaned — no other executor picks it up | No automatic recovery. Resubmit. |
| **Secret decryption fails in TEE** | Executor can't decrypt `encryptedSecrets` — job fails silently | Ensure you encrypt with the correct executor's public key from `TEEServiceRegistry`. |

### Debugging: TX Mined But Callback Missing

If the submit transaction appears successful but no callback arrives:

1. Check the async lifecycle events in order:
   - `AsyncJobTracker.JobAdded` (job entered tracker)
   - `AsyncDelivery.Settled` + `AsyncJobTracker.Phase1Settled` (Phase 1 settled — see footgun warning below)
   - `AsyncDelivery.Delivered` / `AsyncDelivery.DeliveryFailed` and `AsyncJobTracker.ResultDelivered` (Phase 2 outcome)
2. If `eth_getTransactionReceipt(originTxHash)` is null, resolve via `JobAdded` (topic[2] = origin tx hash/job id) and inspect the commitment receipt (`originalTx` / `originTx` fields).
3. If you see `JobRemoved(... completed=false)` without Phase 2 delivery events, treat it as a dropped/orphaned async job and resubmit after fixing root cause (poll endpoint, selector/gas, executor availability, or credentials).
4. Re-validate callback signature + selector pairing:
   - selector must target `onLongRunningResult(bytes32,bytes)`
   - callback must be authorized to accept calls from `AsyncDelivery`

### FAQ: "Phase1Settled fired but Phase2 never lands" (sovereign agent / long HTTP / multimodal)

This is the single most common confusing failure mode. Before debugging, internalize what `Phase1Settled` actually means:

> `Phase1Settled` is emitted from `AsyncJobTracker.markPhase1Settled` **after** `AsyncDelivery.settle` has paid Phase 1 fees and armed the Phase 2 deadline. It means the executor **committed to starting** the off-chain job, NOT that the job has finished. The actual work (LLM calls, agent ReAct iterations, image generation, polling an external API, etc.) runs **after** this event. Phase 2 lands later via `ResultDelivered` + `Delivered`.

If `Phase1Settled` is on chain but you never see `ResultDelivered` for the same `jobId`, walk through these in order. The first three cover the colleague-reported root causes; the rest cover the rest of the failure surface.

**1. RitualWallet underfunded for Phase 2** (most common cause).
Phase 2 separately debits two things from the user's RitualWallet: the executor work fee, then the callback gas+value. Phase 1 only covers Phase 1 fees, so a wallet with just enough for Phase 1 will Phase1Settle and then fail Phase 2:

| Symptom | Root cause | Where it shows up |
|---------|-----------|-------------------|
| `Phase1Settled` then `AsyncDelivery.DeliveryFailed(jobId, user, "insufficient funds for executor")` | `RitualWallet.payExecutor` returned false | Job lingers until cleanup, then `JobRemoved(completed=false)`. |
| `Phase1Settled` then `DeliveryFailed(jobId, user, "insufficient funds for callback gas + value")` then `ResultDelivered(jobId, ..., success=false)` | `RitualWallet.deductExecutionFees` returned 0 | `AsyncJobTracker.markDelivered(..., success=false)` |
| `Phase1Settled` then nothing for a very long time, no `DeliveryFailed` | Executor cancelled the job (see #2) | Off-chain |

Fix: top up RitualWallet to cover the *expected* Phase 2 cost for your precompile, **with headroom**. For sovereign agent calls budget at least `~1 RITUAL` per intended run (a moderately deep agent run with several iterations + a few tool calls + a generous callback gas cap can land in the **0.5 - 1 RITUAL** range; one user reported 0.86 RITUAL for a single sovereign call). For long HTTP, budget your `deliveryGasLimit * deliveryMaxFeePerGas + deliveryValue + executor work fee` per call. See `ritual-dapp-wallet` for the cost breakdown and the underlying per-iteration / per-tool-call constants.

**2. Sovereign agent (or other timed long-runner) hit `maxPollBlock`** (silent — no on-chain failure event).
The sovereign executor cancels the job context when `currentBlock > settledBlock + maxPollBlock` and **does not call `deliverResult`**. Same pattern for long HTTP polling. Symptom: `Phase1Settled` exists, no `ResultDelivered`, eventually `JobRemoved(completed=false)` from cleanup once the bucket expires.

Fix: increase `maxPollBlock` on resubmit. For agents that run many ReAct iterations, the default `10000` blocks (~58 min at ~350 ms/block) can be tight. For agents that wait for slow tool calls, bump it.

**3. Upstream LLM / model context-window overflow inside the agent loop**.
If your sovereign-agent prompt + accumulated tool/context grows past the **operational** context window of whichever LLM the harness inside the agent talks to, that inner LLM call fails. Different harnesses recover differently:
- **Claude Code (`cliType=0`)**: usually returns an error to the agent loop, which may abort.
- **ZeroClaw (`cliType=6`)**: depends on the underlying provider; observed cases where the agent terminates with no graceful Phase 2 result, *or* writes the upstream LLM's freeform reasoning/error text into the harness's `text` output instead of the structured JSON your consumer contract expects (see `ritual-dapp-agents` for the defensive-decode pattern).
- **GLM via the Ritual gateway** (`LLM_PROVIDER=ritual`): the on-chain `max_seq_length` for `zai-org/GLM-4.7-FP8` is registered at 128K, **but the live Ritual gateway currently caps the deployed endpoint at 64K = 65,536 tokens**. Practical context inside an agent loop fills faster than expected because of repeated tool-call replays, so 64K is hit much sooner than the 128K nominal would suggest. Assume **64K** as the real budget for hosted GLM unless you have measured larger.

The executor does **not** preflight token counts; oversized prompts surface as upstream HTTP errors that the harness may or may not turn into a graceful Phase 2.

Fix options, in order of cheapness:
1. Lower the agent's `maxTurns` / `maxIterations` so the running context can't blow past the model's window.
2. Switch to a model with a larger context window, or to a different provider with `LLM_PROVIDER` (see `ritual-dapp-agents`).
3. Restructure the agent prompt to summarize tool output instead of accumulating raw transcripts.

**4. Callback reverts inside your consumer contract**.
`Phase1Settled` → `Delivered(success=false)` → `ResultDelivered(success=false)`. Revert reasons commonly seen: ABI mismatch on the callback selector, accessing storage that requires an `onlyAsyncDelivery` modifier with the wrong address, or running out of the `deliveryGasLimit` you specified.

Fix: simulate the callback off-chain with the actual delivered bytes, raise `deliveryGasLimit`, double-check `deliverySelector` matches `onLongRunningResult(bytes32,bytes)` exactly.

**5. Encrypted secrets unreadable in the TEE**.
You encrypted with the wrong executor's pubkey (or the executor that picked up the job is not the one you encrypted to). Symptom: Phase1Settled fires but the executor errors out reading secrets and `Phase 2` never lands cleanly. Always re-fetch the executor pubkey from `TEEServiceRegistry` immediately before encrypting, and pass the same executor address into the precompile call so a *different* executor can't pick up your job.

**6. Quick triage commands**.

```bash
# Was Phase 1 actually settled?
cast call $ASYNC_JOB_TRACKER "isPhase1Settled(bytes32)(bool)" $JOB_ID --rpc-url $RPC

# Is the job still tracked?
cast call $ASYNC_JOB_TRACKER "getJob(bytes32)" $JOB_ID --rpc-url $RPC

# Did AsyncDelivery emit a SettlementFailed or DeliveryFailed for this job?
cast logs --address $ASYNC_DELIVERY \
  'SettlementFailed(bytes32,address,string)' \
  'DeliveryFailed(bytes32,address,string)' \
  --from-block <commitBlock> --rpc-url $RPC | grep -i $JOB_ID

# What does the user's RitualWallet hold right now?
cast call $RITUAL_WALLET "balanceOf(address)(uint256)" $USER --rpc-url $RPC
cast call $RITUAL_WALLET "lockUntilOf(address)(uint256)" $USER --rpc-url $RPC
```

If `isPhase1Settled = true` but no `ResultDelivered` and no `DeliveryFailed`: you are in case #2 (executor cancelled silently). If you see a `DeliveryFailed`: it's case #1 (insufficient funds) or #4 (callback revert). If neither and balance is healthy: it's case #3 (LLM/agent error inside the harness) or #5 (secrets / wrong executor) — pull the executor logs.

### Resolve Commitment Tx From Async Origin Hash (RPC-Only)

If you only have an async origin hash (or a scheduled hash that became async), resolve the corresponding commitment transactions via `AsyncJobTracker.JobAdded`.

Use the embedded utility from:
`agents/debugger-reference/scheduled-async-rpc-runbook.md` (see "Embedded Utility B").

```bash
python3 /tmp/commitment_tx.py \
  --hash <ASYNC_ORIGIN_HASH> \
  --lookback 2000 \
  --rpc-url https://rpc.ritualfoundation.org
```

Example output:

```text
origin_tx=0x...
lookback=2000
matches=1
[0] block=123456 tx=0x... job_id=0x... executor=0x... commit_block=123456 ttl=100 status=phase1_settled_waiting_for_removal

latest_commitment_tx=0x...
```

The embedded utility reports:
- commitment tx hash(es)
- executor selected for each commitment
- commit block + ttl and inferred expiry block
- lifecycle hints inferred from `Phase1Settled` and `JobRemoved`

### Common Encoding Errors

| Error | Cause | Solution |
|-------|-------|----------|
| `Precompile call failed` | Invalid ABI encoding or input > 10 KB | Verify field count, types, and total size |
| Empty task ID | `taskIdJsonPath` doesn't match initial response JSON | Check actual API response structure |
| `statusJsonPath` never true | Wrong field name or status value | Check exact poll response JSON |
| Delivery reverted | Wrong callback selector or insufficient gas | Match `deliverySelector` to function signature exactly |

---

## Quick Reference

### Default Values

| Field | Default |
|-------|---------|
| `pollIntervalBlocks` | `1` |
| `maxPollBlock` | `1000` |
| `deliveryGasLimit` | `200,000` |
| `deliveryMaxFeePerGas` | `1,000,000,000` (1 gwei) |
| `deliveryMaxPriorityFeePerGas` | `100,000,000` (0.1 gwei) |
| `deliveryValue` | `0` |
| `taskIdJsonPath` | `.task_id` |
| `pollMethod` | `GET` |
| `statusJsonPath` | `.status == "done"` |
| `resultJsonPath` | `.result` |
| `resultMethod` | `GET` |
| `dkmsKeyIndex` | `0` (disabled) |
| `dkmsKeyFormat` | `0` (disabled) |
| `piiEnabled` | `false` |

### HTTP Method Encoding

| Method | Code |
|--------|------|
| NOOP (invalid) | 0 |
| GET | 1 |
| POST | 2 |
| PUT | 3 |
| DELETE | 4 |
| PATCH | 5 |

### Import Summary

```typescript
// All encoding/decoding with viem
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
import { encrypt } from 'eciesjs';  // for secret encryption

// Executor selection: read from TEEServiceRegistry (0x9644e8562cE0Fe12b4deeC4163c064A8862Bf47F)
// Request encoding: encodeAbiParameters with LONG_HTTP_ABI (see Section 1)
// Phase 1 raw output: (bytes simmedInput, bytes actualOutput) — unwrap before decoding
// Phase 1 task ID: decodeAbiParameters(parseAbiParameters('string'), actualOutput)
// Phase 2 callback result: (uint16, string[], string[], bytes, string) — HTTPCallResponse format
// DKMS key format: 0 = disabled, 1 = Eth
```

### Common Patterns at a Glance

```typescript
// Pattern 1: Simple poll-and-deliver (using LONG_HTTP_ABI from Section 1)
const simple = encodeAbiParameters(LONG_HTTP_ABI, [
  executor, [], 200n, [], '0x',
  25n, 4_500n, '{{TASK_ID}}',
  consumer, selector, 200_000n, 1_000_000_000n, 100_000_000n, 0n,
  'https://api.example.com/start', 2, [], [],            // 2 = POST
  new TextEncoder().encode(JSON.stringify({ query })), '.task_id',
  'https://api.example.com/status/{{TASK_ID}}', 1, [], [], new Uint8Array(0),  // 1 = GET
  '.done == true',
  '', 0, [], [], new Uint8Array(0), '.result',
  0n, 0, false,
]);

// Pattern 2: Separate result endpoint — set resultUrl field:
//   'https://api.example.com/result/{{TASK_ID}}', 1, [], [], new Uint8Array(0), '.output',

// Pattern 3: Authenticated with secrets — encrypt with ECIES:
//   import { encrypt } from 'eciesjs';
//   const encrypted = encrypt(executorPubKey.slice(2), Buffer.from(JSON.stringify({ KEY: apiKey })));
//   Pass encrypted in encryptedSecrets field, use 'KEY' in headers.

// Pattern 4: Long-running with generous timeout:
//   pollIntervalBlocks: 171n,    // poll every ~60s at ~0.35s/block
//   maxPollBlock: 70_000n,       // ~6.8 hour timeout (chain max)
//   deliveryGasLimit: 500_000n,
```

---
name: ritual-dapp-http
description: HTTP call precompile patterns for Ritual dApps. Use when building dApps that fetch external data, call APIs, or interact with web services on-chain.
---

# HTTP Call Precompile — Ritual dApp Patterns

## Overview

The HTTP Call precompile (`0x0801`) lets smart contracts on Ritual Chain make external HTTP requests. You send a transaction to the precompile address; a TEE-verified executor performs the HTTP call off-chain and the result is settled back on-chain asynchronously.

**Execution model — short-running async (split-phase compute):**

1. Block builder simulates your transaction, detects the `0x0801` call, creates a commitment.
2. A TEE executor picks up the job and performs the HTTP request off-chain.
3. After fulfillment is available, the builder re-executes your deferred transaction with the settled output injected (fulfilled replay).

See `ritual-dapp-overview` for the full async lifecycle.

**Constraints:**
- **One short-running async call per transaction.** You cannot make two async precompile calls in one tx. Batch multiple HTTP needs into a single request (e.g., JSON-RPC batch). You CAN combine one HTTP call with synchronous precompiles (JQ, ONNX) in the same tx.
- **Current network policy: one async commitment per sender per block.** If you submit two async transactions in the same block, only the first is included. Wait for receipt before sending the next.
- **Use EIP-1559 fee fields in all examples.** Submit with `maxFeePerGas` and `maxPriorityFeePerGas`. If a legacy tx fails with `transaction type not supported`, switch to Type-2 fields.

**Priority path for dApp agents (recommended order):**
1. Plain HTTP (`0x0801`) GET/POST.
2. HTTP result + JQ filter (`0x0803`) for deterministic extraction.
3. Secret injection (request credentials).
4. Response encryption (`userPublicKey`).
5. dKMS payment path (x402 flows only).

```
┌──────────┐    call(0x0801)    ┌──────────────┐    HTTP request    ┌─────────────┐
│  Your Tx │ ───────────────▶  │  Precompile  │ ────────────────▶  │  External   │
│          │                   │   0x0801     │                    │  API / URL  │
└──────────┘                   └──────────────┘                    └─────────────┘
     │                              │                                    │
     │  commitment created          │  TEE executor picks up job         │
     │                              │◀───── response ───────────────────│
     │  result settled asynchronously│
     │◀─────────────────────────────│
```

---

## 1. Preflight Checklist

Complete these steps before submitting any HTTP call transaction.

### Step 1: Find an Executor

Query the `TEEServiceRegistry` for executors with `HTTP_CALL` capability. The `teeAddress` is what you pass as the `executor` field. The `publicKey` is needed if you encrypt secrets.

> **Resolve the executor off-chain.** Query `TEEServiceRegistry` from your client or
> script and pass `teeAddress` into your contract as an argument. Do not look the
> executor up from inside the contract function that issues the 0x0801 call. Avoid
> an on-chain lookup at that point; the HTTP call may fail without a clear error.

```typescript
import { createPublicClient, http, defineChain } from 'viem';
import type { Address, Hex } from 'viem';

const ritualChain = defineChain({
  id: 1979,
  name: 'Ritual',
  nativeCurrency: { name: 'RITUAL', symbol: 'RITUAL', decimals: 18 },
  rpcUrls: { default: { http: [process.env.RITUAL_RPC_URL || 'https://rpc.ritualfoundation.org'] } },
});

const publicClient = createPublicClient({ chain: ritualChain, transport: http() });

const TEE_SERVICE_REGISTRY = '0x9644e8562cE0Fe12b4deeC4163c064A8862Bf47F' as const;
const TEE_SERVICE_REGISTRY_ABI = [
  {
    inputs: [
      { name: 'capability', type: 'uint8' },
      { name: 'checkValidity', type: 'bool' },
    ],
    name: 'getServicesByCapability',
    outputs: [{
      type: 'tuple[]',
      components: [
        { name: 'node', type: 'tuple', components: [
          { name: 'paymentAddress', type: 'address' },
          { name: 'teeAddress', type: 'address' },
          { name: 'teeType', type: 'uint8' },
          { name: 'publicKey', type: 'bytes' },
          { name: 'endpoint', type: 'string' }, // infra metadata only; not part of HTTPCallRequest payload
          { name: 'certPubKeyHash', type: 'bytes32' },
          { name: 'capability', type: 'uint8' },
        ]},
        { name: 'isValid', type: 'bool' },
        { name: 'workloadId', type: 'bytes32' },
      ],
    }],
    stateMutability: 'view',
    type: 'function',
  },
] as const;

const HTTP_CALL_CAPABILITY = 0;

const services = await publicClient.readContract({
  address: TEE_SERVICE_REGISTRY,
  abi: TEE_SERVICE_REGISTRY_ABI,
  functionName: 'getServicesByCapability',
  args: [HTTP_CALL_CAPABILITY, true],
});

if (services.length === 0) throw new Error('No HTTP executors available');

const executorAddress: Address = services[0].node.teeAddress;
const executorPublicKey: Hex = services[0].node.publicKey as Hex;
```

**Important:**
- Only `executor` (address) is part of the HTTP precompile request payload.
- The registry `endpoint` field is infrastructure metadata and is **not** encoded into `HTTPCallRequest`.

### Step 2: Deposit into RitualWallet

The executor charges a fee deducted from your `RitualWallet` balance. Deposit before your first call.

```typescript
import { parseEther, formatEther } from 'viem';

const RITUAL_WALLET = '0x532F0dF0896F353d8C3DD8cc134e8129DA2a3948' as const;
const RITUAL_WALLET_ABI = [
  { inputs: [{ name: 'user', type: 'address' }], name: 'balanceOf', outputs: [{ type: 'uint256' }], stateMutability: 'view', type: 'function' },
  { inputs: [{ name: 'lockDuration', type: 'uint256' }], name: 'deposit', outputs: [], stateMutability: 'payable', type: 'function' },
] as const;

const balance = await publicClient.readContract({
  address: RITUAL_WALLET,
  abi: RITUAL_WALLET_ABI,
  functionName: 'balanceOf',
  args: [account.address],
});

if (balance < parseEther('0.01')) {
  const hash = await walletClient.writeContract({
    address: RITUAL_WALLET,
    abi: RITUAL_WALLET_ABI,
    functionName: 'deposit',
    args: [5000n],              // lock duration in blocks
    value: parseEther('0.05'),
  });
  await publicClient.waitForTransactionReceipt({ hash });
}
```

**How much to deposit:** The executor fee formula is `BASE_FEE + (input_bytes × 0.35 gwei) + (output_bytes × 0.35 gwei)` where `BASE_FEE ≈ 0.0000025 RITUAL`. Start with `0.01` as a bootstrap example only. Real usage depends on payload/response sizes and endpoint behavior.

### Step 3: TTL Rules

The `ttl` field sets how many blocks the executor has to fulfill the request.

- **Must be > 0.** Zero TTL is rejected at the RPC layer.
- **Must be ≤ 500 blocks** (default `MAX_TTL_BLOCKS`, configurable per network). The RPC rejects higher values.
- Typical value: `100n` (a few minutes on Ritual Chain).

### Step 4: Understand Async Output

Async precompile results are wrapped in an envelope: `(bytes simmedInput, bytes actualOutput)`.

- **During `eth_call` simulation:** `actualOutput` is empty (`0x`). This is expected — the executor hasn't run yet.
- **In a settled transaction receipt:** `actualOutput` contains the full HTTP response ABI.
- **Always decode the envelope first**, then decode the inner response.

---

## 2. Constants & ABI Reference

Define these once and reuse everywhere.

```typescript
import { encodeAbiParameters, decodeAbiParameters } from 'viem';
import type { Address, Hex } from 'viem';

const HTTP_PRECOMPILE = '0x0000000000000000000000000000000000000801' as const;

const HTTP_METHOD = {
  GET: 1,
  POST: 2,
  PUT: 3,
  DELETE: 4,
  PATCH: 5,
  HEAD: 6,
  OPTIONS: 7,
} as const;
```

### Supported Methods

| Method    | Code | Body Typically Sent? |
|-----------|------|----------------------|
| `GET`     | 1    | No                   |
| `POST`    | 2    | Yes                  |
| `PUT`     | 3    | Yes                  |
| `DELETE`  | 4    | No                   |
| `PATCH`   | 5    | Yes                  |
| `HEAD`    | 6    | No                   |
| `OPTIONS` | 7    | No                   |

Method code `0` is invalid and rejected by the chain.
For bodyless methods, pass `body: '0x'`.

### Request ABI (13 fields)

```typescript
const HTTP_REQUEST_ABI = [
  { type: 'address' },   // executor — from TEEServiceRegistry.node.teeAddress
  { type: 'bytes[]' },   // encryptedSecrets — ECIES-encrypted secret blobs (or [])
  { type: 'uint256' },   // ttl — blocks until expiry (1–500)
  { type: 'bytes[]' },   // secretSignatures — EIP-191 signatures over raw encrypted bytes (or [])
  { type: 'bytes' },     // userPublicKey — for encrypted responses (or 0x)
  { type: 'string' },    // url — target URL (https:// required; supports SECRET_NAME templates)
  { type: 'uint8' },     // method — HTTP method code (1–7, see table above)
  { type: 'string[]' },  // headerKeys — request header names
  { type: 'string[]' },  // headerValues — request header values (must match headerKeys length)
  { type: 'bytes' },     // body — request body (0x for bodyless methods)
  { type: 'uint256' },   // dkmsKeyIndex — dKMS key derivation index (0 = not using dKMS)
  { type: 'uint8' },     // dkmsKeyFormat — dKMS key format (0 = default)
  { type: 'bool' },      // piiEnabled (independent executor-side service flag)
] as const;
```

This skill uses the 13-field HTTP request layout shown above.
`piiEnabled` is independent of both secret injection (`encryptedSecrets` + `secretSignatures`) and response encryption (`userPublicKey`).

### Response ABI (5 fields)

```typescript
const HTTP_RESPONSE_ABI = [
  { type: 'uint16' },    // statusCode — HTTP status (200, 404, etc.)
  { type: 'string[]' },  // headerKeys — response header names
  { type: 'string[]' },  // headerValues — response header values
  { type: 'bytes' },     // body — response body bytes
  { type: 'string' },    // errorMessage — empty on success; set on executor/chain errors
] as const;
```

---

## 3. Encode & Decode Helpers

Use these throughout your codebase instead of repeating the ABI arrays.

### Encode Request

```typescript
import { encodeAbiParameters, toHex } from 'viem';
import type { Address, Hex } from 'viem';

interface HTTPRequestParams {
  executor: Address;
  url: string;
  method: number;
  headerKeys?: string[];
  headerValues?: string[];
  body?: Hex;
  ttl?: bigint;
  encryptedSecrets?: Hex[];
  secretSignatures?: Hex[];
  userPublicKey?: Hex;
  dkmsKeyIndex?: bigint;
  dkmsKeyFormat?: number;
  piiEnabled?: boolean;
}

function encodeHTTPRequest(params: HTTPRequestParams): Hex {
  return encodeAbiParameters(HTTP_REQUEST_ABI, [
    params.executor,
    params.encryptedSecrets ?? [],
    params.ttl ?? 100n,
    params.secretSignatures ?? [],
    params.userPublicKey ?? '0x',
    params.url,
    params.method,
    params.headerKeys ?? [],
    params.headerValues ?? [],
    params.body ?? '0x',
    params.dkmsKeyIndex ?? 0n,
    params.dkmsKeyFormat ?? 0,
    params.piiEnabled ?? false,
  ]);
}
```

### Decode Response

Handles both simulation (`actualOutput` empty) and settled results:

```typescript
import { decodeAbiParameters } from 'viem';
import type { Hex } from 'viem';

type HTTPResult =
  | { mode: 'simulation'; simmedInput: Hex }
  | {
      mode: 'settled';
      statusCode: number;
      headerKeys: string[];
      headerValues: string[];
      body: Hex;
      errorMessage: string;
    };

function decodeHTTPResponse(raw: Hex): HTTPResult {
  const [simmedInput, actualOutput] = decodeAbiParameters(
    [{ type: 'bytes' }, { type: 'bytes' }],
    raw,
  );

  if ((actualOutput as Hex) === '0x') {
    return { mode: 'simulation', simmedInput: simmedInput as Hex };
  }

  const [statusCode, headerKeys, headerValues, body, errorMessage] =
    decodeAbiParameters(HTTP_RESPONSE_ABI, actualOutput as Hex);

  return {
    mode: 'settled',
    statusCode: Number(statusCode),
    headerKeys: headerKeys as string[],
    headerValues: headerValues as string[],
    body: body as Hex,
    errorMessage: errorMessage as string,
  };
}
```

### Parse Response Body

```typescript
function parseResponseBody(body: Hex): string {
  const bytes = Buffer.from((body as string).slice(2), 'hex');
  return new TextDecoder().decode(bytes);
}
```

### Submit Request

Wraps encoding + transaction submission so callers don't repeat fee fields:

```typescript
import type { WalletClient } from 'viem';

async function submitHTTPRequest(
  walletClient: WalletClient,
  params: HTTPRequestParams,
  gas?: bigint,
): Promise<Hex> {
  return walletClient.sendTransaction({
    to: HTTP_PRECOMPILE,
    data: encodeHTTPRequest(params),
    maxFeePerGas: 30_000_000_000n,
    maxPriorityFeePerGas: 2_000_000_000n,
    gas: gas ?? 2_000_000n,
  });
}
```

---

## 4. Making HTTP Requests

All examples below use the constants and helpers from sections 2–3.

### GET Request

```typescript
import { privateKeyToAccount } from 'viem/accounts';
import { createWalletClient, http } from 'viem';

const account = privateKeyToAccount(process.env.PRIVATE_KEY as `0x${string}`);
const walletClient = createWalletClient({ account, chain: ritualChain, transport: http() });

const hash = await submitHTTPRequest(walletClient, {
  executor: executorAddress,
  url: 'https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd',
  method: HTTP_METHOD.GET,
  headerKeys: ['Accept'],
  headerValues: ['application/json'],
});

const receipt = await publicClient.waitForTransactionReceipt({ hash });
```

### POST with JSON Body

```typescript
const hash = await submitHTTPRequest(walletClient, {
  executor: executorAddress,
  url: 'https://api.example.com/data',
  method: HTTP_METHOD.POST,
  headerKeys: ['Content-Type'],
  headerValues: ['application/json'],
  body: toHex(JSON.stringify({ query: 'latest block' })),
});
```

### Decoding the Result

After the transaction is settled, decode from the short-running async call output in the receipt:

```typescript
const result = decodeHTTPResponse(spcOutputHex);

if (result.mode === 'simulation') {
  console.log('Simulation only — no actual response yet');
} else {
  if (result.errorMessage) {
    console.error('Executor error:', result.errorMessage);
  } else if (result.statusCode >= 400) {
    console.error(`HTTP ${result.statusCode}:`, parseResponseBody(result.body));
  } else {
    const data = JSON.parse(parseResponseBody(result.body));
    console.log('Response:', data);
  }
}
```

---

## 5. Solidity Consumer Contract

A single contract that handles GET and POST requests with short-running async result decoding.

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

interface IRitualWallet {
    function deposit(uint256 lockDuration) external payable;
}

contract HTTPConsumer {
    address constant HTTP_PRECOMPILE = 0x0000000000000000000000000000000000000801;
    address constant RITUAL_WALLET = 0x532F0dF0896F353d8C3DD8cc134e8129DA2a3948;

    struct HTTPResponse {
        uint16 status;
        string[] headerKeys;
        string[] headerValues;
        bytes body;
        string errorMessage;
    }

    event ResponseReceived(uint16 status, bytes body);
    event RequestFailed(string error);

    function depositForFees() external payable {
        IRitualWallet(RITUAL_WALLET).deposit{value: msg.value}(5000);
    }

    function _makeHTTPCall(bytes memory input)
        internal
        returns (HTTPResponse memory)
    {
        (bool success, bytes memory rawOutput) = HTTP_PRECOMPILE.call(input);
        require(success, "Precompile call failed");
        (, bytes memory actualOutput) = abi.decode(rawOutput, (bytes, bytes));
        return abi.decode(actualOutput, (HTTPResponse));
    }

    function _emitResult(HTTPResponse memory resp)
        internal
        returns (uint16, bytes memory)
    {
        if (bytes(resp.errorMessage).length > 0) {
            emit RequestFailed(resp.errorMessage);
            return (0, bytes(""));
        }
        emit ResponseReceived(resp.status, resp.body);
        return (resp.status, resp.body);
    }

    function fetchGET(
        address executor,
        uint256 ttl,
        string calldata url
    ) external returns (uint16, bytes memory) {
        bytes memory input = abi.encode(
            executor, new bytes[](0), ttl, new bytes[](0), bytes(""),
            url, uint8(1),
            new string[](0), new string[](0), bytes(""),
            uint256(0), uint8(0), false
        );
        return _emitResult(_makeHTTPCall(input));
    }

    function fetchPOST(
        address executor,
        uint256 ttl,
        string calldata url,
        string calldata jsonBody
    ) external returns (uint16, bytes memory) {
        string[] memory hk = new string[](1);
        string[] memory hv = new string[](1);
        hk[0] = "Content-Type";
        hv[0] = "application/json";

        bytes memory input = abi.encode(
            executor, new bytes[](0), ttl, new bytes[](0), bytes(""),
            url, uint8(2),
            hk, hv, bytes(jsonBody),
            uint256(0), uint8(0), false
        );
        return _emitResult(_makeHTTPCall(input));
    }
}
```

---

## 6. Secrets and Response Encryption (Separate Concepts)

These are different features and should be modeled separately.
For end-to-end secret encryption/signing patterns, see `ritual-dapp-secrets`.

### 6.1 Secret Injection (request-side credentials)

Use this when you need API keys/tokens inside URL/headers/body without exposing plaintext on-chain.

```typescript
import { encrypt, ECIES_CONFIG } from 'eciesjs';
import { hexToBytes } from 'viem';

ECIES_CONFIG.symmetricNonceLength = 12; // see ritual-dapp-secrets

function encryptSecret(secretValue: string, executorPubKey: Hex): Hex {
  const pubKeyBytes = Buffer.from(executorPubKey.slice(2), 'hex');
  return toHex(encrypt(pubKeyBytes, Buffer.from(secretValue)));
}

const encryptedApiKey = encryptSecret('sk-live-abc123', executorPublicKey);

// Sign raw encrypted bytes (NOT hash). Executor verifies EIP-191 over raw bytes.
const signature = await walletClient.signMessage({
  message: { raw: hexToBytes(encryptedApiKey) },
});

const hash = await submitHTTPRequest(walletClient, {
  executor: executorAddress,
  url: 'https://api.openai.com/v1/models',
  method: HTTP_METHOD.GET,
  headerKeys: ['Authorization'],
  headerValues: ['Bearer API_KEY'],
  encryptedSecrets: [encryptedApiKey],
  secretSignatures: [signature],
});
```

What it does:
1. Decrypts secrets inside TEE.
2. Replaces templates in URL/headers/body.
3. Executes HTTP request with substituted values.

For policy controls (including redirect-related policy behavior), see `ritual-dapp-secrets`.

### 6.2 Response Encryption (`userPublicKey`)

Use this when you want the HTTP response encrypted before being returned from executor.


```typescript
const hash = await submitHTTPRequest(walletClient, {
  executor: executorAddress,
  url: 'https://api.example.com/private',
  method: HTTP_METHOD.GET,
  userPublicKey: myPublicKey, // 65-byte uncompressed key (0x04...)
});
```

---

## 7. JQ Post-Processing

Combine an HTTP call with the JQ precompile (`0x0803`) to filter JSON responses on-chain.

### Pattern: HTTP → JQ

```typescript
// Step 1: Submit the HTTP call (async — returns after settlement)
const hash = await submitHTTPRequest(walletClient, {
  executor: executorAddress,
  url: 'https://api.coingecko.com/api/v3/simple/price?ids=ethereum,bitcoin&vs_currencies=usd,eur',
  method: HTTP_METHOD.GET,
  headerKeys: ['Accept'],
  headerValues: ['application/json'],
});

// Step 2: After settlement, decode the HTTP body and pass to JQ precompile
// JQ is synchronous — usually a follow-up transaction after HTTP settlement
const JQ_PRECOMPILE = '0x0000000000000000000000000000000000000803' as const;
const jqFilter = '.ethereum.usd';
```

### Solidity: HTTP + JQ

```solidity
contract HTTPWithJQ {
    address constant HTTP_PRECOMPILE = 0x0000000000000000000000000000000000000801;
    address constant JQ_PRECOMPILE   = 0x0000000000000000000000000000000000000803;

    function fetch(
        address executor,
        string calldata url
    ) external returns (bytes memory body) {
        bytes memory input = abi.encode(
            executor, new bytes[](0), uint256(100),
            new bytes[](0), bytes(""),
            url, uint8(1),
            new string[](0), new string[](0), bytes(""),
            uint256(0), uint8(0), false
        );
        (bool ok, bytes memory rawOutput) = HTTP_PRECOMPILE.call(input);
        require(ok, "HTTP call failed");
        (, bytes memory actualOutput) = abi.decode(rawOutput, (bytes, bytes));
        (, , , body, ) = abi.decode(actualOutput, (uint16, string[], string[], bytes, string));
    }
}
```

---

## 8. dKMS Paths (x402 Payment Flows)

dKMS fields are optional and mostly relevant for x402 payment-required endpoints, not ordinary HTTP GET/POST.
For complete dKMS and payment flows, see `ritual-dapp-x402` and `ritual-dapp-precompiles` (DKMS Key precompile reference).

### 8.1 When dKMS is used in HTTP calls

- Set `dkmsKeyIndex > 0` and/or non-default `dkmsKeyFormat`.
- Executor treats the request as dKMS payment mode for x402 settlement.
- If dKMS mode is requested but dKMS manager is unavailable, request fails (no secret-based fallback in that branch).

### 8.2 dKMS request example

```typescript
const hash = await submitHTTPRequest(walletClient, {
  executor: executorAddress,
  url: 'https://api.example.com/paywalled-resource',
  method: HTTP_METHOD.GET,
  dkmsKeyIndex: 1n,
  dkmsKeyFormat: 1, // use actual chain-supported format for your deployment
  ttl: 100n,
});
```

### 8.3 Legacy secrets-based x402 path (without dKMS)

If dKMS fields are unset, executor may settle x402 using payment secrets from `encryptedSecrets` (legacy path).

---

## 9. Common Use Cases

All examples use the `encodeHTTPRequest` helper from section 3.

### Price Feed Oracle

```typescript
async function fetchTokenPrice(tokenId: string) {
  return submitHTTPRequest(walletClient, {
    executor: executorAddress,
    url: `https://api.coingecko.com/api/v3/simple/price?ids=${tokenId}&vs_currencies=usd`,
    method: HTTP_METHOD.GET,
    headerKeys: ['Accept'],
    headerValues: ['application/json'],
    ttl: 50n,
  });
}
```

### Webhook Trigger

```typescript
async function triggerSlackWebhook(payload: Record<string, unknown>) {
  return submitHTTPRequest(walletClient, {
    executor: executorAddress,
    url: 'https://hooks.slack.com/services/SLACK_TOKEN',
    method: HTTP_METHOD.POST,
    headerKeys: ['Content-Type'],
    headerValues: ['application/json'],
    body: toHex(JSON.stringify(payload)),
    encryptedSecrets: [encryptedSlackToken],
    secretSignatures: [slackTokenSignature],
    ttl: 50n,
  });
}
```

### Authenticated API Verification

```typescript
async function verifyEtherscanBalance(contractAddress: string) {
  return submitHTTPRequest(walletClient, {
    executor: executorAddress,
    url: `https://api.etherscan.io/api?module=account&action=balance&address=${contractAddress}&apikey=ETHERSCAN_KEY`,
    method: HTTP_METHOD.GET,
    encryptedSecrets: [encryptedEtherscanKey],
    secretSignatures: [etherscanKeySignature],
    ttl: 100n,
  });
}
```

### API Aggregation (Multiple Sources)

Each HTTP call is a separate transaction (one short-running async call per tx). Use `Promise.all` to submit in parallel:

```typescript
async function aggregatePrices(urls: string[]) {
  return Promise.all(
    urls.map((url) =>
      submitHTTPRequest(walletClient, {
        executor: executorAddress,
        url,
        method: HTTP_METHOD.GET,
        ttl: 100n,
      })
    )
  );
}
```

> **Note:** Parallel submission from the same sender may hit the one-async-per-sender-per-block limit. Use different sender accounts or submit sequentially with receipt confirmation between calls.

---

## 10. Error Handling

### Handling Responses

```typescript
function handleHTTPResult(raw: Hex) {
  const result = decodeHTTPResponse(raw);

  if (result.mode === 'simulation') {
    console.log('Simulation — no response yet. Decode from settled receipt.');
    return;
  }

  if (result.errorMessage) {
    console.error('Executor/chain error:', result.errorMessage);
    return;
  }

  if (result.statusCode >= 400) {
    console.error(`HTTP ${result.statusCode}:`, parseResponseBody(result.body));
    return;
  }

  const data = JSON.parse(parseResponseBody(result.body));
  console.log('Success:', data);
}
```

### Error Categories

| Category | Signal | Common Causes | Recovery |
|----------|--------|---------------|----------|
| Chain error | `errorMessage` set | Insufficient deposit, executor offline, TTL expired | Retry with higher deposit/TTL |
| HTTP 4xx | `statusCode` 400–499 | Bad URL, auth failure, rate limit | Fix params or wait |
| HTTP 5xx | `statusCode` 500–599 | API server error | Retry with backoff |
| Timeout | `errorMessage: "timeout"` | API too slow, low TTL | Increase TTL |
| Encoding | Transaction reverts | Malformed ABI encoding | Check request structure |
| Tx rejected | RPC error -32602 | Invalid method (0), zero TTL, bad URL scheme, zero executor | Fix request fields |
| Tx type | RPC error -32003 | Legacy (Type-0) transaction rejected by your RPC | Submit with EIP-1559 fee fields |

### Retry Pattern

```typescript
async function httpCallWithRetry(url: string, maxRetries = 3) {
  for (let attempt = 0; attempt < maxRetries; attempt++) {
    try {
      return await submitHTTPRequest(walletClient, {
        executor: executorAddress,
        url,
        method: HTTP_METHOD.GET,
        ttl: BigInt(100 + attempt * 50),
      });
    } catch (error) {
      if ((error as Error).message.includes('No executors found')) throw error;
      if (attempt === maxRetries - 1) throw error;
      await new Promise((r) => setTimeout(r, 1000 * 2 ** attempt));
    }
  }
}
```

### Side Notes

**IP-blocked APIs:** The TEE executor makes all HTTP requests from cloud provider IPs. APIs that block datacenter ranges (e.g., Reddit) return 403. Use authenticated API endpoints or contact the provider for IP whitelisting. The executor cannot use proxies or rotate IPs.

**Accept-Encoding: gzip:** The executor's HTTP client automatically sends `Accept-Encoding: gzip` on all requests and decompresses gzip responses before ABI-encoding them. You receive decompressed bytes. You cannot suppress this header.

**URL scheme requirement:** Only `http://` and `https://` URLs are accepted. Other schemes are rejected at the RPC layer.

---

## 11. Fee & Deposit Guide

### Fee Formula

```
executor_fee = BASE_FEE + (input_bytes × INPUT_RATE) + (estimated_output_bytes × OUTPUT_RATE)

Where (from chain source):
  BASE_FEE    = 2,500,000,000,000 wei  (0.0000025 RITUAL)
  INPUT_RATE  = 350,000,000 wei/byte    (0.35 gwei/byte)
  OUTPUT_RATE = 350,000,000 wei/byte    (0.35 gwei/byte)
```

The fee is deducted from your `RitualWallet` balance, not from the transaction's gas payment.

### Gas Constants

The EVM gas for the precompile call itself:

```
gas = 33,000 + (input_bytes × 16) + (output_bytes × 16)
```

A `gas: 2_000_000n` limit is sufficient for all standard HTTP calls.

### Output Size Limits

> **Version-sensitive note:** Some network versions use a higher runtime output cap (for execution) than fee-estimation cap (for deposit sizing). Plan deposits conservatively for large responses.

### Deposit Workflow

See **Preflight Step 2** (section 1) for the full deposit code. Use the `RITUAL_WALLET_ABI` defined there.

---

## 12. Frontend: useHTTPCall React Hook

Uses `encodeHTTPRequest` and `HTTP_METHOD` from section 2–3.

```typescript
import { useState, useCallback } from 'react';
import { useAccount, usePublicClient, useWalletClient } from 'wagmi';
import type { Address, Hex } from 'viem';

type HTTPCallState =
  | { status: 'idle' }
  | { status: 'submitting' }
  | { status: 'pending'; txHash: Hex }
  | { status: 'settled'; txHash: Hex }
  | { status: 'error'; error: string };

interface UseHTTPCallOptions {
  executor: Address;
  ttl?: bigint;
  gasLimit?: bigint;
}

export function useHTTPCall(options: UseHTTPCallOptions) {
  const [state, setState] = useState<HTTPCallState>({ status: 'idle' });
  const { address } = useAccount();
  const publicClient = usePublicClient();
  const { data: walletClient } = useWalletClient();

  const execute = useCallback(
    async (
      url: string,
      method: keyof typeof HTTP_METHOD = 'GET',
      headers: Record<string, string> = {},
      body: Hex = '0x',
    ) => {
      if (!walletClient || !address) {
        setState({ status: 'error', error: 'Wallet not connected' });
        return;
      }

      if (!options.executor || options.executor === '0x0000000000000000000000000000000000000000') {
        setState({ status: 'error', error: 'Executor address required — query TEEServiceRegistry first' });
        return;
      }

      setState({ status: 'submitting' });

      try {
        const hash = await walletClient.sendTransaction({
          to: HTTP_PRECOMPILE,
          data: encodeHTTPRequest({
            executor: options.executor,
            url,
            method: HTTP_METHOD[method],
            headerKeys: Object.keys(headers),
            headerValues: Object.values(headers),
            body,
            ttl: options.ttl,
          }),
          gas: options.gasLimit ?? 2_000_000n,
          maxFeePerGas: 30_000_000_000n,
          maxPriorityFeePerGas: 2_000_000_000n,
        });

        setState({ status: 'pending', txHash: hash });
        const receipt = await publicClient!.waitForTransactionReceipt({ hash });

        if (receipt.status === 'success') {
          setState({ status: 'settled', txHash: hash });
        } else {
          setState({ status: 'error', error: 'Transaction reverted' });
        }
      } catch (err) {
        setState({ status: 'error', error: (err as Error).message });
      }
    },
    [walletClient, address, publicClient, options],
  );

  const reset = useCallback(() => setState({ status: 'idle' }), []);

  return { state, execute, reset };
}
```

### Usage

```tsx
function PriceFetcher({ executor }: { executor: Address }) {
  const { state, execute, reset } = useHTTPCall({ executor, ttl: 100n });

  return (
    <div>
      <button
        onClick={() =>
          execute('https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd')
        }
        disabled={state.status === 'submitting' || state.status === 'pending'}
      >
        {state.status === 'submitting'
          ? 'Submitting...'
          : state.status === 'pending'
          ? 'Waiting for result...'
          : 'Fetch ETH Price'}
      </button>

      {state.status === 'pending' && <p>Tx: {state.txHash.slice(0, 10)}...</p>}
      {state.status === 'settled' && <p>Done! Tx: {state.txHash.slice(0, 10)}...</p>}
      {state.status === 'error' && (
        <div>
          <p style={{ color: 'red' }}>{state.error}</p>
          <button onClick={reset}>Try Again</button>
        </div>
      )}
    </div>
  );
}
```

---

## 13. Complete End-to-End Example

Brings together executor lookup, deposit, secret encryption, request submission, and response decoding.

```typescript
import {
  createPublicClient, createWalletClient, http, defineChain,
  parseEther, toHex, hexToBytes,
} from 'viem';
import { privateKeyToAccount } from 'viem/accounts';
import { encrypt, ECIES_CONFIG } from 'eciesjs';
import type { Hex, Address } from 'viem';

ECIES_CONFIG.symmetricNonceLength = 12; // see ritual-dapp-secrets

async function main() {
  const ritualChain = defineChain({
    id: 1979,
    name: 'Ritual',
    nativeCurrency: { name: 'RITUAL', symbol: 'RITUAL', decimals: 18 },
    rpcUrls: { default: { http: ['https://rpc.ritualfoundation.org'] } },
  });

  const account = privateKeyToAccount(process.env.PRIVATE_KEY as `0x${string}`);
  const publicClient = createPublicClient({ chain: ritualChain, transport: http() });
  const walletClient = createWalletClient({ account, chain: ritualChain, transport: http() });

  // 1. Find executor (see section 1 for full TEE_SERVICE_REGISTRY_ABI)
  const services = await publicClient.readContract({
    address: '0x9644e8562cE0Fe12b4deeC4163c064A8862Bf47F',
    abi: TEE_SERVICE_REGISTRY_ABI,
    functionName: 'getServicesByCapability',
    args: [0, true],
  });
  if (services.length === 0) throw new Error('No HTTP executors available');

  const executorAddress = services[0].node.teeAddress;
  const executorPublicKey = services[0].node.publicKey as Hex;

  // 2. Deposit fees
  const RITUAL_WALLET = '0x532F0dF0896F353d8C3DD8cc134e8129DA2a3948' as const;
  const depositHash = await walletClient.writeContract({
    address: RITUAL_WALLET,
    abi: [{ inputs: [{ name: 'lockDuration', type: 'uint256' }], name: 'deposit', outputs: [], stateMutability: 'payable', type: 'function' }],
    functionName: 'deposit',
    args: [5000n],
    value: parseEther('0.01'),
  });
  await publicClient.waitForTransactionReceipt({ hash: depositHash });

  // 3. Encrypt API key
  function encryptSecret(secret: string, pubKey: Hex): Hex {
    return toHex(encrypt(Buffer.from(pubKey.slice(2), 'hex'), Buffer.from(secret)));
  }

  const encryptedKey = encryptSecret(process.env.API_KEY!, executorPublicKey);
  const sig = await walletClient.signMessage({ message: { raw: hexToBytes(encryptedKey) } });

  // 4. Submit HTTP request with secrets
  const hash = await submitHTTPRequest(walletClient, {
    executor: executorAddress,
    url: 'https://pro-api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd&x_cg_pro_api_key=API_KEY',
    method: HTTP_METHOD.GET,
    encryptedSecrets: [encryptedKey],
    secretSignatures: [sig],
    ttl: 100n,
  });

  console.log('Submitted:', hash);
  const receipt = await publicClient.waitForTransactionReceipt({ hash });
  console.log('Status:', receipt.status);
}

main().catch(console.error);
```

---

## Quick Reference

| Item | Value |
|------|-------|
| Precompile address | `0x0000000000000000000000000000000000000801` |
| RitualWallet | `0x532F0dF0896F353d8C3DD8cc134e8129DA2a3948` |
| TEEServiceRegistry | `0x9644e8562cE0Fe12b4deeC4163c064A8862Bf47F` |
| Chain ID | 1979 |
| Transaction submission | Use EIP-1559 fee fields (`maxFeePerGas`, `maxPriorityFeePerGas`) |
| Executor fee (base) | 0.0000025 RITUAL (2.5e12 wei) |
| Executor fee (per byte) | 0.35 gwei/byte input + 0.35 gwei/byte output |
| Gas formula | 33,000 + (input_bytes × 16) + (output_bytes × 16) |
| Recommended gas limit | 2,000,000 |
| Default TTL | 100 blocks |
| Max TTL | 500 blocks (configurable) |
| Output cap behavior | Deployment/version-sensitive; verify on target network |
| Secret template | `SECRET_NAME` (plain string replacement in URL/headers/body) |
| Submit transaction | `sendTransaction({ to: HTTP_PRECOMPILE, data: encoded, maxFeePerGas, maxPriorityFeePerGas })` |
| Async limit | 1 short-running async call per tx, 1 async commitment per sender per block |

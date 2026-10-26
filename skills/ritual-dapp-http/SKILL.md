---
name: ritual-dapp-http
description: HTTP call precompile patterns for Ritual dApps. Use when building dApps that fetch external data, call APIs, hydrate public or encrypted JSON from DA, route public or encrypted outputs, or stream upstream SSE.
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
- **One short-running async call per transaction.** You cannot make two async precompile calls in one tx. Batch multiple HTTP needs into a single request (e.g., JSON-RPC batch). You CAN combine one HTTP call with synchronous precompiles (JQ) in the same tx.
- **Current network policy: one async commitment per sender per block.** If you submit two async transactions in the same block, only the first is included. Wait for receipt before sending the next.
- **Use EIP-1559 fee fields in all examples.** Submit with `maxFeePerGas` and `maxPriorityFeePerGas`. If a legacy tx fails with `transaction type not supported`, switch to Type-2 fields.

**Priority path for dApp agents (recommended order):**
1. Plain HTTP (`0x0801`) GET/POST.
2. RITHTTP1 when the request needs DA hydration, post-hydration secrets, contract projection, storage fan-out, or selected SSE. For encrypted DA, per-pipe encryption, or private streams, read both RITHTTP1 references.
3. HTTP result + JQ filter (`0x0803`) only for legacy calls that need deterministic extraction.
4. Secret injection (request credentials).
5. Response encryption (`userPublicKey`).
6. dKMS payment path (x402 flows only).

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

Query the `TEEServiceRegistry` for executors with `HTTP_CALL` capability. The `teeAddress` is what you pass as the `executor` field. The `executorSecretsAuthPublicKey` is needed if you encrypt secrets.

```typescript
import { createPublicClient, http, defineChain } from 'viem';
import type { Address, Hex } from 'viem';

const ritualChain = defineChain({
  id: 784,
  name: 'Ritual',
  nativeCurrency: { name: 'RITUAL', symbol: 'RITUAL', decimals: 18 },
  rpcUrls: { default: { http: [process.env.RITUAL_RPC_URL || 'https://rpc.ritualfoundation.org'] } },
});

const publicClient = createPublicClient({ chain: ritualChain, transport: http() });

const TEE_SERVICE_REGISTRY = '0xf4495DC72143D44A93AB0ecE4d6D63a216b27839' as const;
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
          { name: 'executorSecretsAuthPublicKey', type: 'bytes' },
          { name: 'endpoint', type: 'string' }, // infra metadata only; not part of HTTPCallRequest payload
          { name: 'mTlsSpkiHash', type: 'bytes32' },
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
const executorPublicKey: Hex = services[0].node.executorSecretsAuthPublicKey as Hex;
```

**Important:**
- Only `executor` (address) is part of the HTTP precompile request payload.
- The registry `endpoint` field is infrastructure metadata and is **not** encoded into `HTTPCallRequest`.

### Step 2: Deposit into RitualWallet

The executor charges a fee deducted from your `RitualWallet` balance. Deposit before your first call.

```typescript
import { parseEther, formatEther } from 'viem';

const RITUAL_WALLET = '0xF04076756d8129Baec46Dc0F1c526Baec490C393' as const;
const RITUAL_WALLET_ABI = [
  { inputs: [{ name: 'account', type: 'address' }], name: 'availableBalance', outputs: [{ type: 'uint256' }], stateMutability: 'view', type: 'function' },
  { inputs: [], name: 'deposit', outputs: [], stateMutability: 'payable', type: 'function' },
] as const;

const balance = await publicClient.readContract({
  address: RITUAL_WALLET,
  abi: RITUAL_WALLET_ABI,
  functionName: 'availableBalance',
  args: [account.address],
});

if (balance < parseEther('0.02')) {
  const hash = await walletClient.writeContract({
    address: RITUAL_WALLET,
    abi: RITUAL_WALLET_ABI,
    functionName: 'deposit',
    args: [],
    value: parseEther('0.05'),
  });
  await publicClient.waitForTransactionReceipt({ hash });
}
```

**How much to deposit:** Keep at least ~0.02 RITUAL of `availableBalance` per call: admission reserves `BASE_FEE` (0.01 RIT, `1e16` wei) plus 0.35 gwei × (input bytes + 5,120 worst-case output bytes) plus the commitment/inclusion fees, so exactly 0.01 is rejected; the `0.05` deposit above is a bootstrap example. Real usage depends on payload/response sizes and endpoint behavior.

### Step 3: TTL Rules

The `ttl` field sets how many blocks the executor has to fulfill the request.

- **Must be > 0.** Zero TTL is rejected at the RPC layer.
- **Must be ≤ 500 blocks** (default `MAX_TTL_BLOCKS`, configurable per network). The RPC rejects higher values.
- Typical value: `100n` (a few minutes on Ritual Chain).

### Step 4: Understand Async Output

The Solidity precompile CALL return is wrapped as `(bytes simmedInput, bytes actualOutput)`. RPC receipt `spcCalls[i].output` already contains the bare `actualOutput`; do not unwrap it again.

- **During `eth_call` simulation:** `actualOutput` is empty (`0x`). This is expected — the executor hasn't run yet.
- **In a settled transaction receipt (inline path, default):** when `output_storage_ref` is empty, `actualOutput` contains the full HTTP response ABI (the 5-field `HTTP_RESPONSE_ABI` below).
- **In a settled transaction receipt (DA-output path):** when the request sets a non-empty `output_storage_ref`, the executor uploads the (ECIES-encrypted) ABI-encoded `HTTPCallResponse` off-chain and `actualOutput` is instead a **DA result envelope** `(bool has_error, string output_uri, bytes32 output_content_hash, uint64 output_size_bytes, string error_message)`. The consumer must decode the envelope, fetch the bytes from `output_uri`, verify the stored hash and size, ABI-decode the downloaded bytes as a single `bytes` value to extract the ciphertext, ECIES-decrypt it with the user private key, and ABI-decode the plaintext `HTTPCallResponse`.
- **For a Solidity CALL return**, decode the envelope first. **For receipt `spcCalls[i].output`**, decode the response directly.
- **RITHTTP1 is a third inner-result shape.** When `body` starts with `RITHTTP1`, keep the legacy outer `output_storage_ref` empty and decode settled `actualOutput` as the self-describing `RITOUT1` result. Do not try the legacy inline or DA-result decoder first.

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

### Request ABI (16 fields)

```typescript
const HTTP_REQUEST_ABI = [
  { type: 'address' },   // executor — from TEEServiceRegistry.node.teeAddress
  { type: 'address' },   // sponsor — RitualWallet account whose balance/escrow backs this async job (must be non-zero)
  { type: 'address[]' }, // secretOwners — one non-zero owner per encrypted blob (parallel to encryptedSecrets/secretSignatures; all empty when [])
  { type: 'bytes[]' },   // encryptedSecrets — ECIES-encrypted secret blobs (or [])
  { type: 'uint256' },   // ttl — blocks until expiry (1–500)
  { type: 'bytes[]' },   // secretSignatures — EIP-191 owner signatures over the domain-separated secret authorization payload (not raw bytes), one per blob (or [])
  { type: 'bytes' },     // userPublicKey — for encrypted responses (or 0x)
  { type: 'string' },    // url — target URL (https:// required; supports SECRET_NAME templates)
  { type: 'uint8' },     // method — HTTP method code (1–7, see table above)
  { type: 'string[]' },  // headerKeys — request header names
  { type: 'string[]' },  // headerValues — request header values (must match headerKeys length)
  { type: 'bytes' },     // body — request body (0x for bodyless methods)
  { type: 'uint256' },   // dkmsKeyIndex — dKMS key derivation index (0 = not using dKMS)
  { type: 'uint8' },     // dkmsKeyFormat — dKMS key format (0 = default)
  { type: 'bool' },      // piiEnabled (independent executor-side service flag)
  { type: 'tuple', components: [{ type: 'string' }, { type: 'string' }, { type: 'string' }] }, // output_storage_ref — DA output ref (platform, path, keyRef); ['','',''] = inline response
] as const;
```

This skill uses the single canonical 16-field HTTP request layout shown above. Decoders read the top-level field count and accept ONLY 16 fields.
`output_storage_ref` is a `StorageRef` tuple `(platform, path, keyRef)`: `['','','']` returns the response inline (default), and a non-empty value routes the response off-chain as a DA result envelope (see below) and requires a valid 65-byte `userPublicKey` (`0x04` prefix). The RPC rejects a **partial ref** (`PartialStorageRef`): the tuple must be either fully empty or have **both** `platform` and `path` set (`keyRef` is optional; a `keyRef`-only or single-field tuple is rejected). Supported platforms: `gcs`, `hf`, `pinata` (plus `['','','']` for inline). Platform is enforced by the executor, not the RPC: any value other than `gcs`, `hf`, `pinata` is not a fallback to inline — the executor returns a DA error result (`hasError=true`, `errorMessage` containing `unsupported storage platform for client creation: <platform>`) and the call still settles at the normal byte-based executor fee (`BASE_FEE` + input bytes + the error envelope's bytes).
`piiEnabled` is independent of both secret injection (`encryptedSecrets` + `secretSignatures`) and response encryption (`userPublicKey`).

### RITHTTP1 body extension

RITHTTP1 keeps this exact 16-field ABI and places a versioned envelope only in field 11, `body`. Use it to splice GCS/Hugging Face/Pinata JSON into any JSON node, expand `http:*` secrets after hydration, select a small contract result, fan out selected response fragments to storage, or relay upstream SSE.

Read [`references/rithttp1.md`](references/rithttp1.md) before encoding one. It contains the `RITHTTP1`/`RITOUT1` layouts, a complete OpenAI-compatible DA-slot request, storage and secret alias rules, bounds, held-response behavior, and the compatibility gate.

Also read [`references/rithttp1-private-io.md`](references/rithttp1-private-io.md) when any input artifact, buffered sink, or SSE stream must be private. It defines the multi-recipient input artifact, the four-field output-pipe schema, RITPIPE1 bindings and stream commitments, executor and user key roles, and the integrity work an untrusted application relay cannot perform for the user.

For RITHTTP1, set `piiEnabled=false` and `output_storage_ref=['','','']`. The envelope's `outputs` explicitly route independent CONTRACT, STREAM and DA selections; selectors receive strings, so use `fromjson?` before JSON field lookup. Output privacy/encoding are per pipe. RITOUT1 encoding 4 returns indexed pipe results; inspect each success even when another pipe makes the aggregate result an error. Legacy bodies remain valid and keep every behavior documented below.

### Private I/O decision path

| Requirement | Use |
|---|---|
| Executor alone must read a DA input | Encrypt the artifact to the verified executor recipient key |
| User also needs to recover that input | Add the user recipient key to the same artifact |
| A user reads selected collected output | Set that CONTRACT/DA pipe's `recipientPublicKey` to the verified user key |
| Outputs have different recipients or public metadata | Set each pipe's recipient key independently; empty bytes explicitly mean plaintext |
| User receives a private stream before callback | Add a STREAM pipe with its recipient key, set `STREAM_RESPONSE` for upstream SSE, and verify its settled frame commitment before accepting content |

When a relay submits on a user's behalf, encrypt large request fields as separate input artifacts, bind their ciphertext hashes and lengths in the signed request, and verify the route and executor key before upload. Use Long HTTP with `AWAIT_RESPONSE` for a held call, then verify the submitted transaction and `RITOUT1` settlement through an independent chain view.

### Response ABI (5 fields) — inline path (default)

Applies only when `output_storage_ref` is empty (the default). `actualOutput` decodes directly as:

```typescript
const HTTP_RESPONSE_ABI = [
  { type: 'uint16' },    // statusCode — HTTP status (200, 404, etc.)
  { type: 'string[]' },  // headerKeys — response header names
  { type: 'string[]' },  // headerValues — response header values
  { type: 'bytes' },     // body — response body bytes
  { type: 'string' },    // errorMessage — empty on success; set on executor/chain errors
] as const;
```

### DA Result Envelope (5 fields) — DA-output path

Applies when the request sets a non-empty `output_storage_ref`. The executor uploads `abi.encode(ciphertext)`, where the ECIES ciphertext encrypts the ABI-encoded `HTTPCallResponse` (the 5-field layout above), off-chain, and `actualOutput` decodes as this envelope instead:

```typescript
const DA_RESULT_ABI = [
  { type: 'bool' },      // hasError — true if the executor could not produce/store the response
  { type: 'string' },    // outputUri — where the stored bytes live (e.g. gs://..., hf://...)
  { type: 'bytes32' },   // outputContentHash — sha256 of the stored encoded bytes (verify after fetch)
  { type: 'uint64' },    // outputSizeBytes — size of the stored encoded bytes
  { type: 'string' },    // errorMessage — set when hasError is true
] as const;
```

To consume DA output: decode `actualOutput` with `DA_RESULT_ABI`, fetch the bytes from `outputUri`, verify their sha256 and length against `outputContentHash` and `outputSizeBytes`, ABI-decode the stored object as a single `bytes` value (`decodeAbiParameters([{ type: 'bytes' }], toHex(storedBytes))[0]`), ECIES-decrypt that ciphertext with the user private key, then decode the plaintext as `HTTP_RESPONSE_ABI`. DA output is fail-closed: it requires a valid 65-byte `userPublicKey` (uncompressed, `0x04` prefix).

---

## 3. Encode & Decode Helpers

Use these throughout your codebase instead of repeating the ABI arrays.

### Encode Request

```typescript
import { encodeAbiParameters, toHex } from 'viem';
import type { Address, Hex } from 'viem';

interface HTTPRequestParams {
  executor: Address;
  sponsor: Address;
  secretOwners?: Address[];
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
  outputStorageRef?: [string, string, string];
}

function encodeHTTPRequest(params: HTTPRequestParams): Hex {
  return encodeAbiParameters(HTTP_REQUEST_ABI, [
    params.executor,
    params.sponsor,
    params.secretOwners ?? [],
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
    params.outputStorageRef ?? ['', '', ''],
  ]);
}
```

### Decode Response

Decode receipt `spcCalls[i].output` directly. Pass `'call-return'` explicitly only when decoding the wrapped Solidity CALL return, including a simulation with empty `actualOutput`:

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

function decodeHTTPResponse(
  raw: Hex,
  source: 'receipt' | 'call-return' = 'receipt',
): HTTPResult {
  let simmedInput: Hex = '0x';
  let actualOutput: Hex = raw;
  if (source === 'call-return') {
    [simmedInput, actualOutput] = decodeAbiParameters(
      [{ type: 'bytes' }, { type: 'bytes' }],
      raw,
    );
  }

  if ((actualOutput as Hex) === '0x') {
    return { mode: 'simulation', simmedInput: simmedInput as Hex };
  }

  // This helper handles the inline path only (output_storage_ref empty).
  // If the request set a non-empty output_storage_ref, actualOutput is the DA
  // result envelope (decode with DA_RESULT_ABI, fetch+verify, ABI-unpack the
  // ciphertext bytes, then ECIES-decrypt the off-chain HTTPCallResponse) — not the inline 5-field response below.
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

Wraps encoding + transaction submission so callers don't repeat fee fields. Supply a wallet client with its account and selected chain configured:

```typescript
import type { WalletClient } from 'viem';

async function submitHTTPRequest(
  walletClient: WalletClient,
  params: HTTPRequestParams,
  gas?: bigint,
): Promise<Hex> {
  if (!walletClient.account) throw new Error('Wallet client must have an account configured');
  return walletClient.sendTransaction({
    account: walletClient.account,
    chain: walletClient.chain,
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
  sponsor: account.address, // RitualWallet account backing async fees (often the caller itself; must be non-zero)
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
  sponsor: account.address, // RitualWallet account backing async fees (often the caller itself; must be non-zero)
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
    function deposit() external payable;
}

// DA output reference appended to the HTTP request; empty ("","","") = inline response.
struct StorageRef {
    string platform;
    string path;
    string keyRef;
}

contract HTTPConsumer {
    address constant HTTP_PRECOMPILE = 0x0000000000000000000000000000000000000801;
    address constant RITUAL_WALLET = 0xF04076756d8129Baec46Dc0F1c526Baec490C393;

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
        IRitualWallet(RITUAL_WALLET).deposit{value: msg.value}();
    }

    function _makeHTTPCall(bytes memory input)
        internal
        returns (HTTPResponse memory)
    {
        (bool success, bytes memory rawOutput) = HTTP_PRECOMPILE.call(input);
        require(success, "Precompile call failed");
        (, bytes memory actualOutput) = abi.decode(rawOutput, (bytes, bytes));
        // Inline-output path only: when output_storage_ref is set, actualOutput is the
        // DA result envelope (bool,string,bytes32,uint64,string) — not an HTTPResponse.
        HTTPResponse memory response;
        (response.status, response.headerKeys, response.headerValues, response.body, response.errorMessage) =
            abi.decode(actualOutput, (uint16, string[], string[], bytes, string));
        return response;
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
        address sponsor,
        uint256 ttl,
        string calldata url
    ) external returns (uint16, bytes memory) {
        bytes memory input = abi.encode(
            executor, sponsor, new address[](0), new bytes[](0), ttl, new bytes[](0), bytes(""),
            url, uint8(1),
            new string[](0), new string[](0), bytes(""),
            uint256(0), uint8(0), false,
            StorageRef("", "", "")
        );
        return _emitResult(_makeHTTPCall(input));
    }

    function fetchPOST(
        address executor,
        address sponsor,
        uint256 ttl,
        string calldata url,
        string calldata jsonBody
    ) external returns (uint16, bytes memory) {
        string[] memory hk = new string[](1);
        string[] memory hv = new string[](1);
        hk[0] = "Content-Type";
        hv[0] = "application/json";

        bytes memory input = abi.encode(
            executor, sponsor, new address[](0), new bytes[](0), ttl, new bytes[](0), bytes(""),
            url, uint8(2),
            hk, hv, bytes(jsonBody),
            uint256(0), uint8(0), false,
            StorageRef("", "", "")
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
import { toHex, hexToBytes, concat, toBytes, pad, keccak256, stringToBytes, getAddress } from 'viem';

ECIES_CONFIG.symmetricNonceLength = 12; // see ritual-dapp-secrets

// Encrypt the owner-bound envelope, NOT the bare value. The executor json-parses the
// decrypted bytes and rejects any blob whose secret_owner != the secret_owners[i] you
// declare in the request (see ritual-dapp-secrets buildSecretEnvelope; executor-go
// secretEnvelope in internal/utils/ecies.go: {version, secret_owner, secrets}).
function encryptSecret(key: string, value: string, owner: Address, executorPubKey: Hex): Hex {
  const envelope = JSON.stringify({ secret_owner: getAddress(owner), secrets: { [key]: value }, version: 1 });
  const pubKeyBytes = Buffer.from(executorPubKey.slice(2), 'hex');
  return toHex(encrypt(pubKeyBytes, Buffer.from(envelope)));
}

const ownerAddress = account.address; // the secret owner whose signature authorizes this blob
const encryptedApiKey = encryptSecret('API_KEY', 'sk-live-abc123', ownerAddress, executorPublicKey);

// Sign the domain-separated secret-authorization payload (NOT the raw encrypted bytes).
// The executor verifies EIP-191 over THIS payload and matches the signer to secret_owners[i].
// Layout: domain || uint16(len(useContext)) || useContext || uint256(chainId)
//         || executor(20) || owner(20) || keccak256(encryptedSecrets)
const SECRET_AUTHORIZATION_DOMAIN = 'RITUAL_SECRET_AUTHORIZATION_V1';
const HTTP_USE_CONTEXT = 'precompile:0x0000000000000000000000000000000000000801';

function buildSecretAuthorizationPayload(
  chainId: bigint,
  useContext: string,
  executor: Address,
  owner: Address,
  encryptedSecrets: Hex,
): Uint8Array {
  const ctxBytes = stringToBytes(useContext);
  const ctxLen = new Uint8Array([(ctxBytes.length >> 8) & 0xff, ctxBytes.length & 0xff]);
  return concat([
    stringToBytes(SECRET_AUTHORIZATION_DOMAIN),
    ctxLen,
    ctxBytes,
    pad(toBytes(chainId), { size: 32 }),
    hexToBytes(executor),
    hexToBytes(owner),
    keccak256(hexToBytes(encryptedSecrets), 'bytes'),
  ]);
}

const payload = buildSecretAuthorizationPayload(
  BigInt(ritualChain.id),
  HTTP_USE_CONTEXT,
  executorAddress,
  ownerAddress,
  encryptedApiKey,
);
const signature = await walletClient.signMessage({ message: { raw: payload } });

const hash = await submitHTTPRequest(walletClient, {
  executor: executorAddress,
  sponsor: account.address, // RitualWallet account backing async fees (often the caller itself; must be non-zero)
  url: 'https://api.openai.com/v1/models',
  method: HTTP_METHOD.GET,
  headerKeys: ['Authorization'],
  headerValues: ['Bearer API_KEY'],
  secretOwners: [ownerAddress],
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
  sponsor: account.address, // RitualWallet account backing async fees (often the caller itself; must be non-zero)
  url: 'https://api.example.com/private',
  method: HTTP_METHOD.GET,
  userPublicKey: myPublicKey, // 65-byte uncompressed key (0x04...)
});
```

---

## 7. JQ Post-Processing

Combine an HTTP call with the JQ precompile (`0x0803`) to filter JSON responses on-chain. Check the [JQ query compatibility notes](../ritual-dapp-precompiles/SKILL.md#query-compatibility-and-silent-failures) before choosing filters: some operations return empty output without reverting.

### Pattern: HTTP → JQ

```typescript
// Step 1: Submit the HTTP call (async — returns after settlement)
const hash = await submitHTTPRequest(walletClient, {
  executor: executorAddress,
  sponsor: account.address, // RitualWallet account backing async fees (often the caller itself; must be non-zero)
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

    // DA output reference appended to the HTTP request; empty ("","","") = inline response.
    struct StorageRef {
        string platform;
        string path;
        string keyRef;
    }

    function fetch(
        address executor,
        address sponsor,
        string calldata url
    ) external returns (bytes memory body) {
        bytes memory input = abi.encode(
            executor, sponsor, new address[](0), new bytes[](0), uint256(100),
            new bytes[](0), bytes(""),
            url, uint8(1),
            new string[](0), new string[](0), bytes(""),
            uint256(0), uint8(0), false,
            StorageRef("", "", "")
        );
        (bool ok, bytes memory rawOutput) = HTTP_PRECOMPILE.call(input);
        require(ok, "HTTP call failed");
        (, bytes memory actualOutput) = abi.decode(rawOutput, (bytes, bytes));
        // Inline-output path only: this 5-field decode is valid when output_storage_ref is empty.
        // For DA-output requests actualOutput is the DA result envelope (bool,string,bytes32,uint64,string).
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
  sponsor: account.address, // RitualWallet account backing async fees (often the caller itself; must be non-zero)
  url: 'https://api.example.com/paywalled-resource',
  method: HTTP_METHOD.GET,
  dkmsKeyIndex: 1n,
  dkmsKeyFormat: 1, // 1 = secp256k1 (the supported format)
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
    sponsor: account.address, // RitualWallet account backing async fees (often the caller itself; must be non-zero)
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
    sponsor: account.address, // RitualWallet account backing async fees (often the caller itself; must be non-zero)
    url: 'https://hooks.slack.com/services/SLACK_TOKEN',
    method: HTTP_METHOD.POST,
    headerKeys: ['Content-Type'],
    headerValues: ['application/json'],
    body: toHex(JSON.stringify(payload)),
    secretOwners: [slackTokenOwner], // non-zero owner, one per blob (parallel to encryptedSecrets/secretSignatures)
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
    sponsor: account.address, // RitualWallet account backing async fees (often the caller itself; must be non-zero)
    url: `https://api.etherscan.io/api?module=account&action=balance&address=${contractAddress}&apikey=ETHERSCAN_KEY`,
    method: HTTP_METHOD.GET,
    secretOwners: [etherscanKeyOwner], // non-zero owner, one per blob (parallel to encryptedSecrets/secretSignatures)
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
        sponsor: account.address, // RitualWallet account backing async fees (often the caller itself; must be non-zero)
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
        sponsor: account.address, // RitualWallet account backing async fees (often the caller itself; must be non-zero)
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
  BASE_FEE    = 10,000,000,000,000,000 wei  (0.01 RITUAL)
  INPUT_RATE  = 350,000,000 wei/byte    (0.35 gwei/byte)
  OUTPUT_RATE = 350,000,000 wei/byte    (0.35 gwei/byte)

Wallet admission reserves the worst case (HTTP_CALL_MAX_OUTPUT_BYTES = 5,120 output bytes); settlement charges actual bytes.
```

The fee is deducted from your `RitualWallet` balance, not from the transaction's gas payment.

### Gas Constants

The EVM gas for the precompile call itself:

```
gas = 33,000 + (input_bytes × 16) + (output_bytes × 16)
```

A `gas: 2_000_000n` limit is sufficient for all standard HTTP calls.

### Output Size Limits

> Size deposits against the fee-estimation cap (5 KiB, `HTTP_CALL_MAX_OUTPUT_BYTES`); the runtime execution cap can differ per deployment, so plan deposits conservatively for large responses.

> **DA upload cap:** When an HTTP response is stored via DA (`output_storage_ref` set), the executor rejects encoded outputs larger than `HTTPDAMaxOutputBytes = 10 * 1024 * 1024` (10 MiB) before upload, failing with `"HTTP response size %d exceeds executor DA upload cap %d"`. If you expect responses near this ceiling, keep them under 10 MiB or chunk the request.

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
  sponsor: Address;
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
            sponsor: options.sponsor,
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
function PriceFetcher({ executor, sponsor }: { executor: Address; sponsor: Address }) {
  const { state, execute, reset } = useHTTPCall({ executor, sponsor, ttl: 100n });

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
  parseEther, toHex, hexToBytes, concat, toBytes, pad, keccak256, stringToBytes, getAddress,
} from 'viem';
import { privateKeyToAccount } from 'viem/accounts';
import { encrypt, ECIES_CONFIG } from 'eciesjs';
import type { Hex, Address } from 'viem';

ECIES_CONFIG.symmetricNonceLength = 12; // see ritual-dapp-secrets
// buildSecretAuthorizationPayload is defined in section 6.1 (signs the domain-separated secret-authorization payload).

async function main() {
  const ritualChain = defineChain({
    id: 784,
    name: 'Ritual',
    nativeCurrency: { name: 'RITUAL', symbol: 'RITUAL', decimals: 18 },
    rpcUrls: { default: { http: ['https://rpc.ritualfoundation.org'] } },
  });

  const account = privateKeyToAccount(process.env.PRIVATE_KEY as `0x${string}`);
  const publicClient = createPublicClient({ chain: ritualChain, transport: http() });
  const walletClient = createWalletClient({ account, chain: ritualChain, transport: http() });

  // 1. Find executor (see section 1 for full TEE_SERVICE_REGISTRY_ABI)
  const services = await publicClient.readContract({
    address: '0xf4495DC72143D44A93AB0ecE4d6D63a216b27839',
    abi: TEE_SERVICE_REGISTRY_ABI,
    functionName: 'getServicesByCapability',
    args: [0, true],
  });
  if (services.length === 0) throw new Error('No HTTP executors available');

  const executorAddress = services[0].node.teeAddress;
  const executorPublicKey = services[0].node.executorSecretsAuthPublicKey as Hex;

  // 2. Deposit fees
  const RITUAL_WALLET = '0xF04076756d8129Baec46Dc0F1c526Baec490C393' as const;
  const depositHash = await walletClient.writeContract({
    address: RITUAL_WALLET,
    abi: [{ inputs: [], name: 'deposit', outputs: [], stateMutability: 'payable', type: 'function' }],
    functionName: 'deposit',
    args: [],
    value: parseEther('0.05'),
  });
  await publicClient.waitForTransactionReceipt({ hash: depositHash });

  // 3. Encrypt API key
  // Encrypt the owner-bound envelope, NOT the bare value. The executor json-parses the
  // decrypted bytes and rejects any blob whose secret_owner != the secret_owners[i] you
  // declare in the request (executor-go secretEnvelope in internal/utils/ecies.go:
  // {version, secret_owner, secrets}). secret_owner must equal ownerAddress below.
  function encryptSecret(key: string, value: string, owner: Address, pubKey: Hex): Hex {
    const envelope = JSON.stringify({ secret_owner: getAddress(owner), secrets: { [key]: value }, version: 1 });
    return toHex(encrypt(Buffer.from(pubKey.slice(2), 'hex'), Buffer.from(envelope)));
  }

  const encryptedKey = encryptSecret('API_KEY', process.env.API_KEY!, account.address, executorPublicKey);

  // Sign the domain-separated secret-authorization payload (NOT the raw encrypted bytes):
  // domain('RITUAL_SECRET_AUTHORIZATION_V1') || uint16(len(ctx)) || ctx || uint256(chainId)
  //   || executor(20) || owner(20) || keccak256(encryptedKey)
  // ctx = 'precompile:0x0000000000000000000000000000000000000801' (the HTTP precompile use-context).
  // The executor verifies EIP-191 over this payload and matches the signer to secret_owners[i].
  const ownerAddress = account.address;
  const sigPayload = buildSecretAuthorizationPayload(
    BigInt(ritualChain.id),
    'precompile:0x0000000000000000000000000000000000000801',
    executorAddress,
    ownerAddress,
    encryptedKey,
  );
  const sig = await walletClient.signMessage({ message: { raw: sigPayload } });

  // 4. Submit HTTP request with secrets
  const hash = await submitHTTPRequest(walletClient, {
    executor: executorAddress,
    sponsor: account.address, // RitualWallet account backing async fees (often the caller itself; must be non-zero)
    url: 'https://pro-api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd&x_cg_pro_api_key=API_KEY',
    method: HTTP_METHOD.GET,
    secretOwners: [ownerAddress],
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
| RitualWallet | `0xF04076756d8129Baec46Dc0F1c526Baec490C393` |
| TEEServiceRegistry | `0xf4495DC72143D44A93AB0ecE4d6D63a216b27839` |
| Chain ID | 784 |
| Transaction submission | Use EIP-1559 fee fields (`maxFeePerGas`, `maxPriorityFeePerGas`) |
| Executor fee (base) | 0.01 RITUAL (1e16 wei) |
| Executor fee (per byte) | 0.35 gwei/byte input + 0.35 gwei/byte output |
| Gas formula | 33,000 + (input_bytes × 16) + (output_bytes × 16) |
| Recommended gas limit | 2,000,000 |
| Default TTL | 100 blocks |
| Max TTL | 500 blocks (configurable) |
| Output cap behavior | Deployment/version-sensitive; verify on target network |
| Secret template | `SECRET_NAME` (plain string replacement in URL/headers/body) |
| Submit transaction | `sendTransaction({ to: HTTP_PRECOMPILE, data: encoded, maxFeePerGas, maxPriorityFeePerGas })` |
| Async limit | 1 short-running async call per tx, 1 async commitment per sender per block |

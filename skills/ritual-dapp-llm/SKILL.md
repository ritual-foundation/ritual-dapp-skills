---
name: ritual-dapp-llm
description: LLM inference patterns for Ritual dApps. Use when building dApps with LLM text generation, conversation history (GCS, HuggingFace, or Pinata), and streaming.
---

# LLM Inference — Ritual dApp Patterns

## Overview

The LLM precompile (`0x0802`) enables on-chain AI inference via TEE-verified executors. For current production usage, pin model selection to `deepseek-ai/DeepSeek-V4-Flash-0731`. Conversation history is stored as plaintext JSONL on the DA provider (GCS, HuggingFace, or Pinata) — see `ritual-dapp-da` for StorageRef format and credential encoding.

> **Execution Model: Short-running async.** LLM Call (0x0802) is async. The builder simulates your tx (fresh simulation) and creates a commitment, the executor performs inference off-chain, and the builder re-executes your deferred tx with the settled output injected in `spcCalls` (fulfilled replay). You do not register a callback function; you read settled output from the transaction receipt. See `ritual-dapp-overview` for the full transaction lifecycle.
>
> **At most one short-running async call per transaction.** You cannot make two async precompile calls in one transaction. You can still combine one async call with synchronous precompiles (JQ, etc.).

**Precompile address**: `0x0000000000000000000000000000000000000802`
**Chain ID**: 784 (Ritual Chain)
**Transaction type**: Short-running async (commitment → executor processes → your tx + settlement in same block)

### How It Works

```
┌──────────┐   call           ┌──────────────┐     inference     ┌─────────────┐
│  User Tx │ ──────────────▶ │  Precompile  │ ───────────────▶  │  LLM Model  │
│          │                 │   0x0802     │                   │  (in TEE)   │
└──────────┘                 └──────────────┘                   └─────────────┘
     │                             │                                  │
     │ commitment on-chain         │  executor runs inference         │ tokens
     │                             │◀─────────────────────────────────│
     │                             │                                  
     │ completion settled          │
     │◀────────────────────────────│
```

For streaming, a separate SSE service delivers tokens in real-time while the on-chain settlement happens asynchronously.

### Native LLM vs OpenAI-compatible HTTP

Use the native LLM precompile for registered Ritual models, its typed chat ABI, conversation JSONL lifecycle, tool calls, and standardized stream events. Use HTTP/Long HTTP with RITHTTP1 when the target is an arbitrary OpenAI-compatible endpoint and you need a large DA-backed `messages` value, private chat history or tools, post-hydration API secrets, selected output fan-out, a held response, or provider-native SSE. That route remains an HTTP call and does not inherit the LLM precompile's registry, pricing, response ABI, or token schema. Read [`../ritual-dapp-http/references/rithttp1.md`](../ritual-dapp-http/references/rithttp1.md) and, for private chat, [`../ritual-dapp-http/references/rithttp1-private-io.md`](../ritual-dapp-http/references/rithttp1-private-io.md).

### Execution Prerequisites (Early)

- **Registry + capability:** select executors from `TEEServiceRegistry` using LLM capability (`Capability.LLM = 1`).
- **What to use from registry:** use executor address (`teeAddress`) and `executorSecretsAuthPublicKey`.
- **What not to use:** do **not** read/use the registry `endpoint` field in this dapp flow.
- **Wallet funding:** deposit in `RitualWallet` before inference. If the account sponsoring fees (the ABI `sponsor` field) is DIFFERENT from the caller that invokes the precompile (e.g. a user EOA sponsoring a separate consumer contract), the sponsor must first call `RitualWallet.approve(caller, amount)` (e.g. `MAX_ALLOWANCE = 2**256-1`); otherwise the reservation reverts on the allowance check. When you self-sponsor (`sponsor == caller`, e.g. a direct EOA precompile call or a consumer contract that sets `sponsor = address(this)`), the allowance check is skipped and a deposit alone is sufficient.
- **Model policy:** for current production, pin to `deepseek-ai/DeepSeek-V4-Flash-0731`.

---

## ABI Context (Read First)

Before any example, lock these in:

- Always call precompile `0x0802` with the full **32-field** ABI tuple. Submitting any other field count returns RPC `-32602 invalid async payload` and the tx never lands. See "Error Reference" for the full surface.
- For current production, use **`deepseek-ai/DeepSeek-V4-Flash-0731`** only. In reasoning mode it emits a `<think>...</think>` chain-of-thought, which has two practical consequences:
  - Set `maxCompletionTokens` to **at least 4096**. The `<think>` block typically consumes 500–1500 tokens before the final answer is emitted; smaller caps risk returning empty `content` with `finish_reason: "length"`. 4096 is the recommended baseline for any substantive reply on this model.
  - Set `ttl` to **at least 60 blocks** (300 is a safe default). Reasoning inference can take 10–40 seconds wall-clock; the default `30` blocks risks expiration.
- `convoHistory` is a **StorageRef tuple**. See **`ritual-dapp-da`** for the full StorageRef contract — supported platforms (`gcs`, `hf`, `pinata`), path conventions per platform, credential JSON formats, the meaning of an empty `('', '', '')` tuple, and end-to-end DA debugging. Do not improvise from this skill alone — DA has its own surface area and `ritual-dapp-da` is the source of truth.
- Conversation history is stored as **plaintext JSONL** — not DKMS-encrypted (unlike agent precompiles).
- `piiEnabled` enables PII redaction mode and has extra requirements.
- `userPublicKey` can stay `0x` unless your request flow explicitly needs user-key encryption behavior.

The full request/response ABI layouts are listed in the "Request ABI Layout" and "Response ABI Layout" sections below.

### Three different "limits" — do not confuse them

This is the single most common source of mysterious LLM call failures on Ritual. There are three distinct caps and they fail independently:

| Cap | Where it lives | What it controls | What happens when you hit it |
|-----|---------------|------------------|--------------------|
| `max_completion_tokens` (ABI field 12, `int256`) | Your precompile input | **Output** generation budget only — caps the number of tokens the model is allowed to *produce*, not the input prompt size. Sent through to the upstream model as OpenAI-style `max_completion_tokens`. | The model stops generating early; you get a successful response with `finish_reason: "length"`. Not an error. |
| `ttl` (ABI field 4, `uint256`) | Your precompile input | **On-chain** wait budget — the executor must produce a result within `ttl` blocks of the commitment, otherwise the tx expires. | `Request expired` error in the response envelope. |
| Upstream **context window** (a.k.a. `max_seq_len`) | The **model**, registered on chain in `ModelPricingRegistry` and *separately* configured on whatever inference endpoint the executor actually talks to | Total prompt + completion tokens the upstream model will accept. Example: `deepseek-ai/DeepSeek-V4-Flash-0731` is registered with `max_seq_length: 1048576`. | The upstream call returns a **non-200 HTTP error**; the precompile envelope comes back with `has_error=true` and a freeform `error_message` string like `HTTP request failed with status 400: ... context length exceeded ...`. The precompile execution itself is still considered "successful" at the chain layer (still pays the `LLM_ERROR_EXECUTOR_FEE_WEI = 1×10¹⁶ wei` (0.01 RIT) error fee). |


> **Output size cap:** the ABI-encoded LLM output the executor settles on-chain is capped at 50 KiB (`LLM_CALL_PHASE1_MAX_OUTPUT_BYTES`); a larger settlement is a `SettlementConstraintViolation` and the block is rejected, so bound `max_completion_tokens` for very long completions.

**The executor does NOT preflight token counts.** Oversized prompts only fail when the upstream model rejects them — the executor doesn't count tokens before sending the call. You cannot rely on `max_completion_tokens` to protect you from context-window overflow; it is a separate cap.

### Always treat the precompile envelope as "may have failed even if the tx settled"

The chain considers an LLM precompile execution **successful** as long as the executor returned an ABI-encoded response — even if the response carries an error. Inside that envelope:

```
(bool has_error, bytes completion_data, bytes model_metadata, string error_message, (string, string, string) updated_convo_history)
```

When the upstream model rejects your prompt, returns invalid JSON, errors out for any other reason, or the executor itself fails to reach the model:

- `has_error = true`
- `completion_data` is empty
- `error_message` is a **freeform string** describing the failure (e.g. `HTTP request failed with status 400: ...`, `Failed to parse response JSON: ...`, `Model 'X' is not available. Available models: [...]`, `Streaming is requested but not enabled in executor configuration`, etc.). There is **no structured error code enum** — only the string. Pattern-match defensively, do not assume a fixed taxonomy.

**Consumer-contract requirement: always decode `has_error` first, never call into `completion_data` until you have verified `has_error == false`.** The Solidity consumer pattern in Section 7 shows this. If your contract assumes `completion_data` is always JSON conforming to your `response_format` schema and decodes it without checking `has_error`, you will revert (or worse, parse garbage) on the first upstream failure. Typical failure path: the upstream model errors on a context-window overflow, the executor returns `has_error=true` with a freeform error string, and a contract that assumes a clean JSON object blows up parsing it on-chain.

The Section 5 "Response Format — Structured Output" path (`response_format` with `json_schema`) is **best-effort**. The executor passes your schema through to the upstream model, but does not locally re-validate the model's output against the schema. If the model returns invalid JSON despite being asked for JSON mode, you will see that invalid JSON in `completion_data`, not as `has_error=true`. So even with structured-output mode, your decoder must handle:
1. `has_error == true` (upstream rejected the request entirely).
2. `has_error == false` but `completion_data` contains text that doesn't parse as your expected schema (model deviated despite the schema).

For (2), wrap your on-chain or off-chain JSON parse in a try/except (off-chain) or a minimum-viable-shape check (on-chain) and fall back to "model returned malformed output, retry or abort", rather than reverting.

---

## 1. Direct Precompile Usage (Recommended)

> **Build order:** Get the backend call working first (encode → send → decode response) before building any frontend. Verify you can send a transaction and decode the result via script/API before adding UI, streaming, or encryption layers.

### Simple Inference

```typescript
import { defineChain, createWalletClient, http, encodeAbiParameters, parseAbiParameters } from 'viem';
import { privateKeyToAccount } from 'viem/accounts';
import type { Address } from 'viem';

const ritualChain = defineChain({
  id: 784,
  name: 'Ritual',
  nativeCurrency: { name: 'RITUAL', symbol: 'RITUAL', decimals: 18 },
  rpcUrls: { default: { http: [process.env.RITUAL_RPC_URL!] } },
});

const account = privateKeyToAccount(process.env.PRIVATE_KEY! as `0x${string}`);
const walletClient = createWalletClient({
  account,
  chain: ritualChain,
  transport: http(),
});

const LLM_PRECOMPILE = '0x0000000000000000000000000000000000000802' as const;

const executorAddress: Address = '0x...'; // TEE executor address
const sponsorAddress: Address = account.address; // RitualWallet account backing async fees (sponsor); here the sponsor is also the caller, so only a deposit is required — no approve needed

// Simple inference with minimal parameters
const encoded = encodeAbiParameters(
  parseAbiParameters([
    'address, address, address[], bytes[], uint256, bytes[], bytes,',
    'string, string, int256, string, bool, int256, string, string,',
    'uint256, bool, int256, string, bytes, int256, string, string, bool,',
    'int256, bytes, bytes, int256, int256, string, bool,',
    '(string,string,string)',
  ].join('')),
  [
    executorAddress,
    sponsorAddress,         // sponsor: RitualWallet account backing this job (often your own address)
    [],                     // secretOwners: address[] — one owner per encryptedSecrets blob (parallel arrays)
    [],                     // encryptedSecrets
    300n,                   // ttl: blocks until expiry (max 500; increase if requests time out)
    [],                     // secretSignatures
    '0x',                   // userPublicKey
    JSON.stringify([
      { role: 'system', content: 'You are a helpful DeFi assistant.' },
      { role: 'user', content: 'Explain impermanent loss in one paragraph.' },
    ]),
    'deepseek-ai/DeepSeek-V4-Flash-0731',
    0n, '', false, -1n, '', '',
    1n, true, 0n, 'medium', '0x', -1n, 'auto', '',
    false,                   // stream
    700n, '0x', '0x', -1n, 1000n, '',
    false,                   // piiEnabled
    ['gcs', 'convos/my-session.jsonl', 'GCS_CREDS'], // convoHistory: REQUIRED — GCS credentials must be in encryptedSecrets under key_ref
  ],
);

const hash = await walletClient.sendTransaction({
  to: LLM_PRECOMPILE,
  data: encoded,
  gas: 3_000_000n,
});

console.log('Transaction hash:', hash);
```

### Full Inference with Advanced Options

```typescript
import { encodeAbiParameters, parseAbiParameters } from 'viem';
import type { Address } from 'viem';

const executorAddress: Address = '0x...';
const sponsorAddress: Address = '0x...'; // RitualWallet account backing async fees (sponsor)

// Encode request with full control using raw ABI encoding
const messagesJson = JSON.stringify([
  { role: 'system', content: 'You are a crypto analyst.' },
  { role: 'user', content: 'What are the top DeFi trends for 2026?' },
]);

const encoded = encodeAbiParameters(
  parseAbiParameters([
    'address, address, address[], bytes[], uint256, bytes[], bytes,',
    'string, string, int256, string, bool, int256, string, string,',
    'uint256, bool, int256, string, bytes, int256, string, string, bool,',
    'int256, bytes, bytes, int256, int256, string, bool,',
    '(string,string,string)',
  ].join('')),
  [
    executorAddress,        // executor
    sponsorAddress,         // sponsor: RitualWallet account backing async fees
    [],                     // secretOwners: address[] — one owner per encryptedSecrets blob (parallel arrays)
    [],                     // encryptedSecrets
    300n,                   // ttl: blocks until expiry (max 500; increase if requests time out)
    [],                     // secretSignatures
    '0x',                   // userPublicKey
    messagesJson,           // messagesJson
    'deepseek-ai/DeepSeek-V4-Flash-0731', // model
    100n,                   // frequencyPenalty (0.1 × 1000)
    '',                     // logitBiasJson
    false,                  // logprobs
    4096n,                  // maxCompletionTokens (>=4096 — reasoning headroom, see ABI Context)
    '',                     // metadataJson
    '',                     // modalitiesJson
    1n,                     // n
    true,                   // parallelToolCalls
    100n,                   // presencePenalty (0.1 × 1000)
    'medium',               // reasoningEffort
    '0x',                   // responseFormatData
    -1n,                    // seed (null)
    'auto',                 // serviceTier
    '',                     // stopJson
    false,                  // stream
    700n,                   // temperature (0.7 × 1000)
    '0x',                   // toolChoiceData
    '0x',                   // toolsData
    -1n,                    // topLogprobs (null)
    900n,                   // topP (0.9 × 1000)
    '',                     // user
    false,                  // piiEnabled
    ['gcs', 'convos/my-session.jsonl', 'GCS_CREDS'], // convoHistory: REQUIRED — GCS credentials must be in encryptedSecrets under key_ref
  ],
);

// Submit directly to the LLM precompile
const LLM_PRECOMPILE = '0x0000000000000000000000000000000000000802' as const;

const hash = await walletClient.sendTransaction({
  to: LLM_PRECOMPILE,
  data: encoded,
  gas: 5_000_000n,
});
```

### With RitualWallet Deposit

```typescript
import { parseEther } from 'viem';

const RITUAL_WALLET = '0xF04076756d8129Baec46Dc0F1c526Baec490C393' as const;
const LLM_PRECOMPILE = '0x0000000000000000000000000000000000000802' as const;

// Step 1: Deposit RITUAL to cover fees (credited to availableBalance immediately — no lock)
const depositHash = await walletClient.writeContract({
  address: RITUAL_WALLET,
  abi: [{
    name: 'deposit',
    type: 'function',
    stateMutability: 'payable',
    inputs: [],
    outputs: [],
  }] as const,
  functionName: 'deposit',
  args: [],
  // Must cover the worst-case escrow for the model (see "Worst-case escrow vs. actual fee"):
  // DeepSeek-V4-Flash-0731 reserves ~2.26 RIT per in-flight call, so 0.02 RIT would revert at submission.
  value: parseEther('0.5'),
});

// Step 2: Submit the LLM inference directly to the precompile
const encoded = encodeAbiParameters(
  parseAbiParameters([
    'address, address, address[], bytes[], uint256, bytes[], bytes,',
    'string, string, int256, string, bool, int256, string, string,',
    'uint256, bool, int256, string, bytes, int256, string, string, bool,',
    'int256, bytes, bytes, int256, int256, string, bool,',
    '(string,string,string)',
  ].join('')),
  [
    executorAddress,
    sponsorAddress,         // sponsor: RitualWallet account backing async fees
    [], [], 300n, [], '0x',  // secretOwners, encryptedSecrets, ttl, secretSignatures, userPublicKey
    JSON.stringify([
      { role: 'user', content: 'Summarize the latest crypto news' },
    ]),
    'deepseek-ai/DeepSeek-V4-Flash-0731',
    0n, '', false, 1024n, '', '',
    1n, true, 0n, 'medium', '0x', -1n, 'auto', '',
    false,                   // stream
    700n, '0x', '0x', -1n, 1000n, '',
    false,                   // piiEnabled
    ['gcs', 'convos/my-session.jsonl', 'GCS_CREDS'], // convoHistory: REQUIRED — GCS credentials must be in encryptedSecrets under key_ref
  ],
);

const hash = await walletClient.sendTransaction({
  to: LLM_PRECOMPILE,
  data: encoded,
  gas: 3_000_000n,
});
```

---

## 2. Raw ABI Encoding (Low-Level)

### Building and Encoding a Request

```typescript
import { encodeAbiParameters, parseAbiParameters } from 'viem';
import type { Address, Hex } from 'viem';

const executor: Address = '0x...';
const sponsor: Address = '0x...'; // RitualWallet account backing async fees (sponsor)

const messagesJson = JSON.stringify([
  { role: 'system', content: 'You are a helpful assistant.' },
  { role: 'user', content: 'What is Ritual Chain?' },
]);

// Encode for on-chain submission using raw ABI encoding
const encoded: Hex = encodeAbiParameters(
  parseAbiParameters([
    'address, address, address[], bytes[], uint256, bytes[], bytes,',
    'string, string, int256, string, bool, int256, string, string,',
    'uint256, bool, int256, string, bytes, int256, string, string, bool,',
    'int256, bytes, bytes, int256, int256, string, bool,',
    '(string,string,string)',
  ].join('')),
  [
    executor,               // executor
    sponsor,                // sponsor: RitualWallet account backing async fees
    [],                     // secretOwners: address[] — one owner per encryptedSecrets blob (parallel arrays)
    [],                     // encryptedSecrets
    300n,                   // ttl: blocks until expiry (max 500; increase if requests time out)
    [],                     // secretSignatures
    '0x',                   // userPublicKey
    messagesJson,           // messagesJson
    'deepseek-ai/DeepSeek-V4-Flash-0731', // model
    0n,                     // frequencyPenalty
    '',                     // logitBiasJson
    false,                  // logprobs
    4096n,                  // maxCompletionTokens (>=4096 — reasoning headroom, see ABI Context)
    '',                     // metadataJson
    '',                     // modalitiesJson
    1n,                     // n
    true,                   // parallelToolCalls
    0n,                     // presencePenalty
    'medium',               // reasoningEffort
    '0x',                   // responseFormatData
    -1n,                    // seed (null)
    'auto',                 // serviceTier
    '',                     // stopJson
    false,                  // stream
    700n,                   // temperature (0.7 × 1000)
    '0x',                   // toolChoiceData
    '0x',                   // toolsData
    -1n,                    // topLogprobs (null)
    1000n,                  // topP (1.0 × 1000)
    '',                     // user
    false,                  // piiEnabled
    ['gcs', 'convos/my-session.jsonl', 'GCS_CREDS'], // convoHistory: REQUIRED — GCS credentials must be in encryptedSecrets under key_ref
  ],
);
```

### Decoding a Response

```typescript
import { decodeAbiParameters, parseAbiParameters } from 'viem';

// Decode the top-level response envelope
const [hasError, completionData, modelMetadataBytes, errorMessage] =
  decodeAbiParameters(
    parseAbiParameters('bool, bytes, bytes, string, (string,string,string)'),
    resultHex,
  );

if (hasError) {
  console.error('LLM error:', errorMessage);
  return;
}

// completionData is ABI-encoded (not JSON). Top-level CompletionData structure:
// (string id, string object, uint256 created, string model,
//  string systemFingerprint, string serviceTier,
//  uint256 choicesCount, bytes[] choicesData, bytes usageData)
const [id, obj, created, model, , , choicesCount, choicesData, usageData] =
  decodeAbiParameters(
    parseAbiParameters('string, string, uint256, string, string, string, uint256, bytes[], bytes'),
    completionData,
  );

// usageData: (uint256 promptTokens, uint256 completionTokens, uint256 totalTokens, uint256 cachedTokens)
// usageData is normally 4 words; a 3-word payload (cachedTokens omitted) is also valid — decode
// length-aware. cachedTokens = prefix-cache hits, billed at the registry cached discount;
// consensus clamps it to <= promptTokens.
const usageBytes = (usageData.length - 2) / 2;
const usageWords = (usageBytes >= 128
  ? decodeAbiParameters(parseAbiParameters('uint256, uint256, uint256, uint256'), usageData)
  : decodeAbiParameters(parseAbiParameters('uint256, uint256, uint256'), usageData)) as readonly bigint[];
const [promptTokens, completionTokens, totalTokens] = usageWords;
const cachedTokens = usageWords[3] ?? 0n;

// Each choicesData element: (uint256 index, string finishReason, bytes messageData)
// messageData: (string role, string content, string refusal, uint256 toolCallsCount, bytes[] toolCallsData)
if (choicesCount > 0n && choicesData.length > 0) {
  const [, finishReason, messageData] =
    decodeAbiParameters(parseAbiParameters('uint256, string, bytes'), choicesData[0]);
  const [role, content] =
    decodeAbiParameters(parseAbiParameters('string, string, string, uint256, bytes[]'), messageData);
  console.log('Model:', model);
  console.log('Content:', content);
  console.log('Finish reason:', finishReason);
  console.log('Usage:', { prompt: promptTokens, completion: completionTokens, total: totalTokens, cached: cachedTokens });
}

// modelMetadataBytes: (string model, uint256 paramCount, string datatype, uint256 thetaScaled, uint256 maxSeqLen)
if (modelMetadataBytes.length > 2) {
  const [, paramCount, datatype, , maxSeqLen] =
    decodeAbiParameters(
      parseAbiParameters('string, uint256, string, uint256, uint256'),
      modelMetadataBytes,
    );
  console.log('Parameters:', paramCount);
  console.log('Datatype:', datatype);
  console.log('Max seq len:', maxSeqLen);
}
```

### Extracting the Result from a Receipt

The LLM result lives in the `PrecompileCalled(address,bytes,bytes)` event emitted during settlement. The async envelope wraps the output as `(bytes simmedInput, bytes actualOutput)` — unwrap to get the actual response bytes.

```typescript
import { decodeAbiParameters, parseAbiParameters, keccak256, toHex } from 'viem';
import type { Hex, TransactionReceipt } from 'viem';

const PRECOMPILE_CALLED_TOPIC = keccak256(toHex('PrecompileCalled(address,bytes,bytes)'));
const LLM = '0x0000000000000000000000000000000000000802';

function extractLLMResult(receipt: TransactionReceipt): Hex | null {
  for (const log of receipt.logs) {
    if (log.topics[0] !== PRECOMPILE_CALLED_TOPIC) continue;

    const [addr, , output] = decodeAbiParameters(
      parseAbiParameters('address, bytes, bytes'),
      log.data,
    );
    if ((addr as string).toLowerCase() !== LLM) continue;

    // Unwrap async envelope: (bytes simmedInput, bytes actualOutput)
    try {
      const [, actual] = decodeAbiParameters(parseAbiParameters('bytes, bytes'), output as Hex);
      return actual as Hex;
    } catch {
      return output as Hex; // already unwrapped
    }
  }
  return null; // no result yet — tx may still be in commitment phase
}
```

> If `extractLLMResult` returns `null`, the transaction is still in the commitment phase. The fulfilled replay (which re-executes your deferred tx with the result injected) has not been mined yet. Poll the receipt or wait for a few blocks.

### Request ABI Layout

```
EXECUTOR_REQUEST_ABI (base fields):
  executor            address    — TEE executor address
  sponsor             address    — RitualWallet account whose balance/escrow backs the job (may differ from msg.sender; must be non-zero)
  secretOwners        address[]  — one non-zero owner address per encrypted secret blob (parallel to encryptedSecrets/secretSignatures; all three must have equal length, and all empty together when there are no secrets)
  encryptedSecrets    bytes[]    — ECIES-encrypted secret blobs
  ttl                 uint256    — blocks until expiry
  secretSignatures    bytes[]    — per-secret signature over the LLM-precompile secret-authorization preimage (use_context `precompile:0x0000000000000000000000000000000000000802`), binding domain/chainId/executor/owner/keccak256(encryptedSecrets) — NOT a plain signature over the ciphertext. A signature minted with the HTTP context (0x0801) will NOT validate for an LLM (0x0802) request.
  userPublicKey       bytes      — leave `0x` unless required by your chosen user-key encryption flow

LLM_CALL_REQUEST_ABI (extends executor):
  messagesJson        string     — JSON-encoded message array
  model               string     — model identifier
  frequencyPenalty    int256     — scaled ×1000
  logitBiasJson       string     — JSON logit bias map
  logprobs            bool       — return log probabilities
  maxCompletionTokens int256     — max output tokens (-1 = null)
  metadataJson        string     — JSON metadata
  modalitiesJson      string     — JSON modalities array
  n                   uint256    — number of completions
  parallelToolCalls   bool       — allow parallel tool execution
  presencePenalty     int256     — scaled ×1000
  reasoningEffort     string     — "low" | "medium" | "high"
  responseFormatData  bytes      — ABI-encoded response format
  seed                int256     — deterministic seed (-1 = null)
  serviceTier         string     — "auto" | "default"
  stopJson            string     — stop sequences
  stream              bool       — enable streaming
  temperature         int256     — scaled ×1000 (700 = 0.7)
  toolChoiceData      bytes      — ABI-encoded tool choice
  toolsData           bytes      — ABI-encoded tools array
  topLogprobs         int256     — top log probs count (-1 = null)
  topP                int256     — scaled ×1000
  user                string     — user identifier
  piiEnabled          bool       — enable PII redaction/restoration flow (incompatible with stream=true). See `ritual-dapp-secrets` for details.
  convoHistory        (string,string,string) — StorageRef: platform ('gcs'|'hf'|'pinata'), path (JSONL object path), key_ref (secret key name in encryptedSecrets). See `ritual-dapp-da` for credential formats.
                      key_ref lookup expects a string value in decrypted secrets (not nested JSON object)
```

### Response ABI Layout

```
LLM_CALL_RESPONSE_ABI:
  hasError             bool                   — true if inference failed
  completionData       bytes                  — ABI-encoded CompletionData (not JSON; requires nested ABI decode, see Section 2)
  modelMetadata        bytes                  — ABI-encoded: (string model, uint256 paramCount, string datatype, uint256 thetaScaled, uint256 maxSeqLen)
  errorMessage         string                 — error description (empty on success)
  updatedConvoHistory  (string,string,string) — updated DA storage ref (platform, path, key_ref)
```

---

## 3. Message Encoding

Messages follow the OpenAI chat format, JSON-encoded on-chain.

### Message Types

```typescript
interface LLMMessage {
  role: 'system' | 'user' | 'assistant' | 'tool';
  content: string;
  tool_call_id?: string;
  tool_calls?: { id: string; type: string; function: { name: string; arguments: string } }[];
}

// System message — sets behavior
const systemMsg: LLMMessage = {
  role: 'system',
  content: 'You are a DeFi analyst specializing in yield strategies.',
};

// User message — the prompt
const userMsg: LLMMessage = {
  role: 'user',
  content: 'Compare Aave vs Compound lending rates.',
};

// Assistant message — for multi-turn context
const assistantMsg: LLMMessage = {
  role: 'assistant',
  content: 'Based on current data, Aave offers higher rates for ETH...',
};

// Tool result message — returning tool execution output
const toolMsg: LLMMessage = {
  role: 'tool',
  content: JSON.stringify({ eth_apy: '3.2%', usdc_apy: '5.1%' }),
  tool_call_id: 'call_abc123',
};
```

### Multi-Turn Conversation

```typescript
import { encodeAbiParameters, parseAbiParameters } from 'viem';

const messages: LLMMessage[] = [
  { role: 'system', content: 'You are a blockchain expert.' },
  { role: 'user', content: 'What is a rollup?' },
  { role: 'assistant', content: 'A rollup is a layer-2 scaling solution...' },
  { role: 'user', content: 'How does that differ from a sidechain?' },
];

const encoded = encodeAbiParameters(
  parseAbiParameters([
    'address, address, address[], bytes[], uint256, bytes[], bytes,',
    'string, string, int256, string, bool, int256, string, string,',
    'uint256, bool, int256, string, bytes, int256, string, string, bool,',
    'int256, bytes, bytes, int256, int256, string, bool,',
    '(string,string,string)',
  ].join('')),
  [
    executor, sponsor, [], [], 300n, [], '0x',  // secretOwners, encryptedSecrets, ttl, secretSignatures, userPublicKey
    JSON.stringify(messages),
    'deepseek-ai/DeepSeek-V4-Flash-0731',
    0n, '', false, -1n, '', '',
    1n, true, 0n, 'medium', '0x', -1n, 'auto', '',
    false,                   // stream
    500n, '0x', '0x', -1n, 1000n, '',
    false,                   // piiEnabled
    ['gcs', 'convos/my-session.jsonl', 'GCS_CREDS'], // convoHistory: REQUIRED — GCS credentials must be in encryptedSecrets under key_ref
  ],
);
```

---

## 4. End-to-End Baseline Flow

Get this path working first:

1. Select a valid executor from `TEEServiceRegistry` using `Capability.LLM (1)`.
2. Pin model to `deepseek-ai/DeepSeek-V4-Flash-0731`.
3. Deposit in `RitualWallet` before sending inference calls.
4. Encode the 32-field request correctly.
5. Send transaction to `0x0802`.
6. Wait for async settlement and read `spcCalls`.
7. Decode response ABI and handle `hasError`.

---

## 5. Response Format — Structured Output

Force the LLM to return JSON conforming to a specific schema.

```typescript
import { encodeAbiParameters, parseAbiParameters } from 'viem';

interface ResponseFormat {
  type: 'json_schema';
  json_schema: {
    name: string;
    description: string;
    json_schema: Record<string, unknown>;
    strict: boolean;
  };
}

const responseFormat: ResponseFormat = {
  type: 'json_schema',
  json_schema: {
    name: 'token_analysis',
    description: 'Analysis of a cryptocurrency token',
    json_schema: {
      type: 'object',
      properties: {
        symbol: { type: 'string' },
        sentiment: { type: 'string', enum: ['bullish', 'bearish', 'neutral'] },
        confidence: { type: 'number', minimum: 0, maximum: 1 },
        summary: { type: 'string', maxLength: 500 },
        risks: {
          type: 'array',
          items: { type: 'string' },
          maxItems: 5,
        },
      },
      required: ['symbol', 'sentiment', 'confidence', 'summary'],
    },
    strict: true,
  },
};

// responseFormatData: nested ABI encoding.
// JsonSchema inner encoding: (string name, string description, string schemaJson, string strict)
// strict is encoded as string: "none" | "true" | "false"
// ResponseFormat outer encoding: (string type, bytes jsonSchemaData)
const jsonSchemaData = encodeAbiParameters(
  parseAbiParameters('string, string, string, string'),
  [
    responseFormat.json_schema.name,
    responseFormat.json_schema.description ?? '',
    JSON.stringify(responseFormat.json_schema.json_schema),
    responseFormat.json_schema.strict === null ? 'none'
      : responseFormat.json_schema.strict ? 'true' : 'false',
  ],
);
const responseFormatData = encodeAbiParameters(
  parseAbiParameters('string, bytes'),
  [responseFormat.type, jsonSchemaData],
);

const encoded = encodeAbiParameters(
  parseAbiParameters([
    'address, address, address[], bytes[], uint256, bytes[], bytes,',
    'string, string, int256, string, bool, int256, string, string,',
    'uint256, bool, int256, string, bytes, int256, string, string, bool,',
    'int256, bytes, bytes, int256, int256, string, bool,',
    '(string,string,string)',
  ].join('')),
  [
    executor, sponsor, [], [], 300n, [], '0x',  // secretOwners, encryptedSecrets, ttl, secretSignatures, userPublicKey
    JSON.stringify([
      { role: 'user', content: 'Analyze ETH as an investment for Q1 2026.' },
    ]),
    'deepseek-ai/DeepSeek-V4-Flash-0731',
    0n, '', false, -1n, '', '',
    1n, true, 0n, 'medium',
    responseFormatData,     // responseFormatData
    -1n, 'auto', '',
    false,                   // stream
    300n, '0x', '0x', -1n, 1000n, '',
    false,                   // piiEnabled
    ['gcs', 'convos/my-session.jsonl', 'GCS_CREDS'], // convoHistory: REQUIRED — GCS credentials must be in encryptedSecrets under key_ref
  ],
);

// Response will be valid JSON matching the schema:
// {
//   "symbol": "ETH",
//   "sentiment": "bullish",
//   "confidence": 0.72,
//   "summary": "Ethereum continues to show strength...",
//   "risks": ["Regulatory uncertainty", "L2 competition"]
// }
```

---

## 6. Streaming LLM with SSE

For real-time token delivery, use the Ritual streaming service. The on-chain transaction initiates the request; an SSE connection delivers tokens as they're generated.

This section documents the native LLM stream schema. RITHTTP1 uses the same authenticated streaming service endpoint but emits base64 RITPIPE1 records/ciphertexts for selected payloads. Decode and bind the record before consuming UTF8 text or selected provider JSON. The executor passes `[DONE]` to selectors; `fromjson?` omits it. Do not reuse the native LLM token parser or assume raw provider events are forwarded.

### EIP-712 Stream Request Signing

Stream authentication uses EIP-712 typed data signatures to prove the requester authorized the stream.

```typescript
import { defineChain, createWalletClient, http } from 'viem';
import { privateKeyToAccount } from 'viem/accounts';

const ritualChain = defineChain({
  id: 784,
  name: 'Ritual',
  nativeCurrency: { name: 'RITUAL', symbol: 'RITUAL', decimals: 18 },
  rpcUrls: { default: { http: [process.env.RITUAL_RPC_URL!] } },
});

const account = privateKeyToAccount(process.env.PRIVATE_KEY! as `0x${string}`);
const walletClient = createWalletClient({
  account,
  chain: ritualChain,
  transport: http(process.env.RITUAL_RPC_URL!),
});

// EIP-712 domain for Ritual Streaming
const domain = {
  name: 'Ritual Streaming Service',
  version: '1',
  chainId: 784,
} as const;

// Stream request type
const types = {
  StreamRequest: [
    { name: 'txHash', type: 'bytes32' },
    { name: 'timestamp', type: 'uint256' },
  ],
} as const;

// Sign a stream request after submitting the on-chain tx
async function signStreamRequest(txHash: `0x${string}`) {
  const timestamp = BigInt(Math.floor(Date.now() / 1000));

  const signature = await walletClient.signTypedData({
    domain,
    types,
    primaryType: 'StreamRequest',
    message: {
      txHash,
      timestamp,
    },
  });

  return { signature, timestamp };
}
```

### SSE Stream Client

```typescript
interface StreamEvent {
  token?: string;    // token text (present on each chunk)
  done?: boolean;    // true on final event
}

class RitualStreamClient {
  constructor(
    private streamingServiceUrl: string
  ) {}

  /**
   * Stream tokens from the streaming service using authenticated SSE.
   *
   * Endpoint: GET /v1/stream/{txHash}
   * Auth: Authorization: Bearer {signature}, X-Timestamp: {timestamp}
   * Termination: `data: [DONE]` line signals end of stream
   *
   * NOTE: Cannot use browser EventSource because it doesn't support custom headers.
   * Use fetch() with ReadableStream or a library like eventsource-parser.
   */
  async connect(
    txHash: `0x${string}`,
    signature: `0x${string}`,
    timestamp: bigint,
    onToken: (token: string) => void,
    onDone?: () => void,
  ): Promise<string> {
    const url = `${this.streamingServiceUrl}/v1/stream/${txHash}`;

    const response = await fetch(url, {
      headers: {
        'Accept': 'text/event-stream',
        'Authorization': `Bearer ${signature}`,
        'X-Timestamp': timestamp.toString(),
      },
    });

    if (response.status === 401) {
      throw new Error('Authentication failed (401). Is AUTH_ENABLED=true on streaming service?');
    }
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${await response.text()}`);
    }

    const reader = response.body!.getReader();
    const decoder = new TextDecoder();
    let fullText = '';
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop()!; // keep incomplete line

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed || !trimmed.startsWith('data: ')) continue;
        const data = trimmed.slice(6);

        if (data === '[DONE]') {
          onDone?.();
          return fullText;
        }

        try {
          const event: StreamEvent = JSON.parse(data);
          if (event.token) {
            fullText += event.token;
            onToken(event.token);
          }
          if (event.done) {
            onDone?.();
            return fullText;
          }
        } catch { /* skip non-JSON lines */ }
      }
    }

    throw new Error('Stream ended before a completion event');
  }
}
```

### Complete Streaming Example

End-to-end flow: submit on-chain tx, sign stream request, connect SSE, render tokens.

```typescript
import { defineChain, createWalletClient, http } from 'viem';
import { privateKeyToAccount } from 'viem/accounts';

const ritualChain = defineChain({
  id: 784,
  name: 'Ritual',
  nativeCurrency: { name: 'RITUAL', symbol: 'RITUAL', decimals: 18 },
  rpcUrls: { default: { http: [process.env.RITUAL_RPC_URL!] } },
});

const LLM_PRECOMPILE = '0x0000000000000000000000000000000000000802' as const;

async function streamLLM(prompt: string) {
  const account = privateKeyToAccount(process.env.PRIVATE_KEY! as `0x${string}`);
  const walletClient = createWalletClient({
    account,
    chain: ritualChain,
    transport: http(),
  });

  // 1. Submit the on-chain LLM request directly to the precompile
  const encoded = encodeAbiParameters(
    parseAbiParameters([
      'address, address, address[], bytes[], uint256, bytes[], bytes,',
      'string, string, int256, string, bool, int256, string, string,',
      'uint256, bool, int256, string, bytes, int256, string, string, bool,',
      'int256, bytes, bytes, int256, int256, string, bool,',
      '(string,string,string)',
    ].join('')),
    [
      executorAddress,
      sponsorAddress,        // sponsor: RitualWallet account backing async fees
      [], [], 60n, [], '0x',  // secretOwners, encryptedSecrets, ttl, secretSignatures, userPublicKey
      JSON.stringify([{ role: 'user', content: prompt }]),
      'deepseek-ai/DeepSeek-V4-Flash-0731',
      0n, '', false, 2048n, '', '',
      1n, true, 0n, 'medium', '0x', -1n, 'auto', '',
      true,                    // stream — MUST be true for streaming
      700n, '0x', '0x', -1n, 1000n, '',
      false,                   // piiEnabled (PII + streaming is incompatible)
      ['gcs', 'convos/my-session.jsonl', 'GCS_CREDS'], // convoHistory: REQUIRED — GCS credentials must be in encryptedSecrets under key_ref
    ],
  );

  const hash = await walletClient.sendTransaction({
    to: LLM_PRECOMPILE,
    data: encoded,
    gas: 3_000_000n,
  });

  console.log('On-chain tx:', hash);

  // 2. Sign the stream request (EIP-712)
  const { signature, timestamp } = await signStreamRequest(hash);

  // 3. Connect to SSE stream
  const streamClient = new RitualStreamClient('https://streaming.ritualfoundation.org');

  const fullText = await streamClient.connect(
    hash, signature, timestamp,
    (token) => process.stdout.write(token), // typewriter effect
    () => console.log('\n\nStream complete.'),
  );

  return fullText;
}

streamLLM('Write a short story about a decentralized AI.').catch(console.error);
```

### Streaming Gotchas

| Issue | Behavior | Mitigation |
|-------|----------|------------|
| `stream=false` + SSE connect | SSE hangs silently forever (200 OK, zero events) | Always verify `stream: true` in ABI before connecting |
| TX not yet on-chain | 401 `"transaction not found"` | Wait for tx receipt before opening SSE |
| Signature expired | 401 after 5 minutes from timestamp | Generate fresh signature on reconnect |
| Timestamp clock skew | 401 if >60s in future | Keep timestamp within ±60s of server time |
| Slow consumer | Tokens silently dropped (executor-configured channel buffer, typically 100 tokens) | Process events immediately; detect gaps via `index` field |
| Stream TTL expired | Empty phantom stream (hangs forever) | Connect within 5 min of stream completion |
| Reconnection | Replay buffer: last 100 tokens only | Long responses (500+ tokens) lose early tokens on reconnect |
| HTTPS only | HTTP → TLS handshake error, no redirect | Use `https://`; in dev set `NODE_TLS_REJECT_UNAUTHORIZED=0` |
| Executor no streaming | On-chain error settles, SSE hangs | Not all executors support streaming; no pre-flight check available |
| `verifyingContract` in domain | Silent auth failure | EIP-712 domain is `(name, version, chainId)` only — no `verifyingContract` |

> Streaming is purely additive — the on-chain result always arrives regardless of SSE status. If the streaming service is down, you still get the final response via `PrecompileCalled` event.

---

## 7. Solidity Consumer Contract

Result is injected by the builder into the SPC mechanism (fulfilled replay) — there is **no callback**.

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract LLMConsumer {
    struct StorageRef {
        string platform;
        string path;
        string keyRef;
    }

    address constant LLM_PRECOMPILE = 0x0000000000000000000000000000000000000802;
    address constant RITUAL_WALLET  = 0xF04076756d8129Baec46Dc0F1c526Baec490C393;

    event InferenceCompleted(string model, bool hasError);

    function depositForFees() external payable {
        (bool ok,) = RITUAL_WALLET.call{value: msg.value}(
            abi.encodeWithSignature("deposit()")
        );
        require(ok, "Deposit failed");
        // Funds land in availableBalance immediately. Because this contract is both the
        // caller and the sponsor (sponsor == caller), no allowance is required. Only when a
        // DIFFERENT account sponsors a separate caller must that sponsor call
        // approve(caller, amount) first.
    }

    function requestInference(
        address executor,
        string calldata messagesJson,
        string calldata model,
        int256 temperature,
        int256 maxTokens
    ) external returns (bool hasError, bytes memory completionData) {
        bytes memory input = abi.encode(
            executor,
            address(this),    // sponsor: RitualWallet account backing async fees (this contract deposited)
            new address[](0), // secretOwners: one non-zero owner per encryptedSecrets blob (parallel arrays; empty here)
            new bytes[](0),   // encryptedSecrets (encrypted secrets payload for your flow)
            uint256(300),     // ttl
            new bytes[](0),   // secretSignatures
            bytes(""),        // userPublicKey
            messagesJson,        // JSON messages
            model,
            int256(0),           // frequencyPenalty
            "",                  // logitBiasJson
            false,               // logprobs
            maxTokens,           // maxCompletionTokens
            "",                  // metadataJson
            "",                  // modalitiesJson
            uint256(1),          // n
            true,                // parallelToolCalls
            int256(0),           // presencePenalty
            "medium",            // reasoningEffort
            bytes(""),           // responseFormatData
            int256(-1),          // seed (null)
            "auto",              // serviceTier
            "",                  // stopJson
            bool(false),         // stream
            temperature,         // temperature (scaled ×1000)
            bytes(""),           // toolChoiceData
            bytes(""),           // toolsData
            int256(-1),          // topLogprobs (null)
            int256(1000),        // topP (1.0 × 1000)
            "",                  // user
            bool(false),         // piiEnabled
            StorageRef("gcs", "convos/my-session.jsonl", "GCS_CREDS")
        );

        // Short-running async envelope: (bytes simmedInput, bytes actualOutput).
        // actualOutput is the ABI response bytes from precompile settlement.
        // GCS stores conversation history off-chain; updatedConvoHistory in actualOutput
        // contains the storage reference tuple, not raw JSONL history content.
        (bool success, bytes memory result) = LLM_PRECOMPILE.call(input);
        require(success, "Precompile call failed");
        (, bytes memory actualOutput) = abi.decode(result, (bytes, bytes));

        bytes memory modelMeta;
        string memory errorMsg;
        (hasError, completionData, modelMeta, errorMsg, ) =
            abi.decode(actualOutput, (bool, bytes, bytes, string, StorageRef));

        emit InferenceCompleted(model, hasError);
    }
}
```

> `completionData` is ABI-encoded — decode it off-chain with the TypeScript helpers, or write a Solidity helper for on-chain parsing.

---

## 8. PII Mode (Optional)

Use this only if you need redaction/restoration of sensitive user data.

PII requirements:
- Set `piiEnabled=true`
- Provide PII-specific encrypted secret material for redaction workflow
- `userPublicKey` must be 65 bytes (uncompressed, 0x04 prefix)
- Keep `stream=false` (PII + streaming is incompatible)

PII mode is a redaction workflow toggle — separate from `secretSignatures` or `userPublicKey` wiring. See `ritual-dapp-secrets` for encryption details.

Minimal parameter shape:

```typescript
// ...same 32-field tuple...
[
  executor,
  sponsor,            // sponsor: RitualWallet account backing async fees
  secretOwners,       // address[] — one non-zero owner per encryptedSecrets blob (parallel array, equal length)
  encryptedSecrets,   // includes pii prompt secret material
  300n,
  /* keep remaining base executor fields exactly as in your baseline request */,
  messagesJson,
  'deepseek-ai/DeepSeek-V4-Flash-0731',
  // ...
  false,              // stream
  // ...
  true,               // piiEnabled
  ['gcs', 'convos/my-session.jsonl', 'GCS_CREDS'],
]
```

### Separate: user-key encryption and signature fields

`userPublicKey` and `secretSignatures` are part of user-key encryption/signing flows.
Treat those as separate from PII redaction mode.
For all encryption setup (ECIES nonce length, key selection, signing), follow `ritual-dapp-secrets`.

---

## 9. Fee Estimation

LLM fees come from async settlement logic + RitualWallet charging.

### Fee Structure

Current fee formula — a linear, cache-aware per-model rate card (`llm_compute_fee_wei`):

```text
cached = min(cached_prompt_tokens, prompt_tokens)
fresh  = prompt_tokens - cached

executor_fee_wei = llmBaseFeeWei
                 + llmFeeWeiPerInputToken  * fresh
                 + llmFeeWeiPerInputToken  * cached * llmCachedInputDiscountBps / 10_000
                 + llmFeeWeiPerOutputToken * completion_tokens
```

All four rates (`llmBaseFeeWei`, `llmFeeWeiPerInputToken`, `llmFeeWeiPerOutputToken`, `llmCachedInputDiscountBps`) are per-model values read from `ModelPricingRegistry` (`getModel(name)` fields). The fee is linear in tokens; `paramsB` and `theta` do not enter it. `cached_prompt_tokens` is the 4th word of the executor's usage payload (see Section 2) and is clamped to `<= prompt_tokens` by consensus. A model whose `llmFeeWeiPerInputToken == 0` has no LLM pricing and the job is rejected.

Current rate cards (genesis `models.json`; `llm_cached_input_discount_bps = 1000` = cached tokens pay 10%):
- `deepseek-ai/DeepSeek-V4-Flash-0731`: base 5e11 wei, input 1.0792e12 wei/token, output 2.1584e12 wei/token. `maxSeqLen` 1,048,576 — read `getModel(name).maxSeqLen` from the registry before sizing escrow.
- `LLM_ERROR_EXECUTOR_FEE_WEI = 10_000_000_000_000_000` (0.01 RIT) when response has `hasError=true`

Rates change only via the owner-only `setLlmPricing(string modelName, uint256 baseFeeWei, uint256 feeWeiPerInputToken, uint256 feeWeiPerOutputToken, uint256 cachedInputDiscountBps)` (`cachedInputDiscountBps <= 10_000`, emits `LlmPricingSet`).

Important sad path:
- If model pricing cannot be resolved from `ModelPricingRegistry` (model missing, or `llmFeeWeiPerInputToken == 0`), transaction handling can be skipped by builder logic (not a normal in-contract revert path).

### Worst-case escrow vs. actual fee

The chain reserves a **worst-case escrow** at submission time, computed against the model's `maxSeqLen` from `ModelPricingRegistry`, not against your `maxCompletionTokens`. The escrowed amount moves from `availableBalance` into `reservedBalance`. Actual settlement charges only the realized usage, refunding the difference back to `availableBalance`.

Worst-case escrow = `max(llmBaseFeeWei + llmFeeWeiPerOutputToken × maxSeqLen, 1e16 wei)` — the whole `maxSeqLen` is charged as completion, since output is the highest per-token rate, and the estimate is floored at `HTTP_EXECUTOR_BASE_FEE_WEI` (1e16 wei = 0.01 RIT). For `deepseek-ai/DeepSeek-V4-Flash-0731` (maxSeqLen=1,048,576, output 2.1584e12 wei/token) the worst-case escrow is ~2.26e18 wei, i.e. **~2.26 RIT per in-flight call**. A realistic 30-prompt / 220-completion call settles for ~5.1e14 wei (~0.0005 RIT); a 30/4096 call settles for ~8.9e15 wei (~0.009 RIT).

Practical implications:
- A 0.1 RIT deposit covers ~0 in-flight DeepSeek-V4-Flash-0731 calls — submission will revert with insufficient deposit. Deposit at least 2.5 RIT before your first call, and ~2.3 RIT per additional concurrent in-flight call.
- For agents that submit many sequential (non-concurrent) calls, 0.5 RIT typically lasts hundreds of completed calls because the escrow reservation is released back to `availableBalance` after each settles.
- Monitor both `RitualWallet.availableBalance(yourAddress)` and `RitualWallet.reservedBalance(yourAddress)` — not available alone. At submission the worst-case escrow moves from `availableBalance` into `reservedBalance` (available drops, total unchanged); at settlement the realized cost is debited from the reservation and the remainder is refunded back to `availableBalance`. To observe actual spend/refunds, compare total (`availableBalance + reservedBalance`) before vs after; watching only `availableBalance` will mistake the in-flight escrow move for a payment. Settlement refunds usually appear in the same block as your tx; concurrent submissions need separate escrow ceilings.

### Depositing Fees

```typescript
import { parseEther } from 'viem';

const RITUAL_WALLET = '0xF04076756d8129Baec46Dc0F1c526Baec490C393' as const;

// Deposit enough for several LLM calls (credited to availableBalance immediately — no lock)
await walletClient.writeContract({
  address: RITUAL_WALLET,
  abi: [{
    name: 'deposit',
    type: 'function',
    stateMutability: 'payable',
    inputs: [],
    outputs: [],
  }] as const,
  functionName: 'deposit',
  args: [],
  value: parseEther('2.5'),  // 2.5 RIT covers ~1 in-flight DeepSeek-V4-Flash-0731 call (escrow ~2.26 RIT) plus headroom; sequential calls reuse the deposit as escrow refunds
});
```

### Recommended Gas Limits

| Operation | Gas Limit |
|-----------|-----------|
| Simple inference (short prompt) | 3,000,000 |
| Full inference (long context) | 5,000,000 |
| Structured output | 3,000,000 |

---

## 10. Frontend: useStreamingLLM Hook

A React hook that submits the on-chain transaction and streams tokens in real-time with a typewriter effect.

```typescript
import { useState, useCallback, useRef } from 'react';
import { useAccount, useWalletClient } from 'wagmi';
import type { Hex } from 'viem';

interface StreamingState {
  status: 'idle' | 'submitting' | 'signing' | 'streaming' | 'done' | 'error';
  txHash?: Hex;
  text: string;
  tokens: number;
  error?: string;
}

interface UseStreamingLLMOptions {
  executor: Hex;
  encryptedSecrets: Hex[]; // include encrypted blob that contains GCS_CREDS
  secretOwners?: Hex[];    // one non-zero owner address per encryptedSecrets blob (parallel array, equal length)
  secretSignatures?: Hex[]; // one secret-authorization signature per encryptedSecrets blob (parallel array, equal length)
  convoPath?: string;
  convoKeyRef?: string;
  model?: string;
  temperature?: number;
  maxTokens?: number;
  streamingServiceUrl?: string;
}

export function useStreamingLLM(options: UseStreamingLLMOptions) {
  const [state, setState] = useState<StreamingState>({
    status: 'idle',
    text: '',
    tokens: 0,
  });
  const abortControllerRef = useRef<AbortController | null>(null);
  const { address } = useAccount();
  const { data: walletClient } = useWalletClient();

  const {
    executor,
    encryptedSecrets,
    secretOwners = [],
    secretSignatures = [],
    convoPath = 'convos/my-session.jsonl',
    convoKeyRef = 'GCS_CREDS',
    model = 'deepseek-ai/DeepSeek-V4-Flash-0731',
    temperature = 0.7,
    maxTokens = 4096, // >=4096 default reasoning headroom; see ABI Context
    streamingServiceUrl = 'https://streaming.ritualfoundation.org',
  } = options;

  const submit = useCallback(
    async (prompt: string, systemPrompt?: string) => {
      if (!walletClient || !address) {
        setState((s) => ({ ...s, status: 'error', error: 'Wallet not connected' }));
        return;
      }
      if (!encryptedSecrets.length) {
        setState((s) => ({
          ...s,
          status: 'error',
          error: 'encryptedSecrets is required for GCS convo history',
        }));
        return;
      }

      setState({ status: 'submitting', text: '', tokens: 0 });
      let abortController: AbortController | null = null;

      try {
        const messages = [];
        if (systemPrompt) messages.push({ role: 'system', content: systemPrompt });
        messages.push({ role: 'user', content: prompt });

        // Submit on-chain transaction directly to the precompile
        const LLM_PRECOMPILE = '0x0000000000000000000000000000000000000802' as const;
        const { encodeAbiParameters, parseAbiParameters } = await import('viem');

        const encoded = encodeAbiParameters(
          parseAbiParameters([
            'address, address, address[], bytes[], uint256, bytes[], bytes,',
            'string, string, int256, string, bool, int256, string, string,',
            'uint256, bool, int256, string, bytes, int256, string, string, bool,',
            'int256, bytes, bytes, int256, int256, string, bool,',
            '(string,string,string)',
          ].join('')),
          [
            executor, // TEE executor address — must be a real registered executor (see Section 11)
            address,  // sponsor: RitualWallet account backing async fees (connected wallet)
            secretOwners, encryptedSecrets, 300n, secretSignatures, '0x', // secretOwners/secretSignatures must be parallel to encryptedSecrets (one non-zero owner + one sig per blob; equal length)
            JSON.stringify(messages),
            model,
            0n, '', false, BigInt(maxTokens), '', '',
            1n, true, 0n, 'medium', '0x', -1n, 'auto', '',
            true,                    // stream — MUST be true for streaming
            BigInt(Math.round(temperature * 1000)),
            '0x', '0x', -1n, 1000n, '',
            false,                   // piiEnabled (PII + streaming is incompatible)
            ['gcs', convoPath, convoKeyRef], // REQUIRED default path for persistent sessions
          ],
        );

        const hash = await walletClient.sendTransaction({
          to: LLM_PRECOMPILE,
          data: encoded,
          gas: 3_000_000n,
        });

        setState((s) => ({ ...s, status: 'signing', txHash: hash }));

        // Sign EIP-712 stream request
        const timestamp = BigInt(Math.floor(Date.now() / 1000));
        const signature = await walletClient.signTypedData({
          domain: { name: 'Ritual Streaming Service', version: '1', chainId: 784 },
          types: {
            StreamRequest: [
              { name: 'txHash', type: 'bytes32' },
              { name: 'timestamp', type: 'uint256' },
            ],
          },
          primaryType: 'StreamRequest',
          message: { txHash: hash, timestamp },
        });

        setState((s) => ({ ...s, status: 'streaming' }));

        // Connect SSE — uses path param + auth headers (NOT query params)
        // NOTE: Cannot use EventSource because it doesn't support custom headers.
        abortController = new AbortController();
        abortControllerRef.current = abortController;

        const sseResponse = await fetch(
          `${streamingServiceUrl}/v1/stream/${hash}`,
          {
            headers: {
              'Accept': 'text/event-stream',
              'Authorization': `Bearer ${signature}`,
              'X-Timestamp': timestamp.toString(),
            },
            signal: abortController.signal,
          },
        );

        if (!sseResponse.ok) {
          throw new Error(`Stream HTTP ${sseResponse.status}`);
        }

        const reader = sseResponse.body!.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        const processStream = async () => {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop()!;

            for (const line of lines) {
              const trimmed = line.trim();
              if (!trimmed || !trimmed.startsWith('data: ')) continue;
              const data = trimmed.slice(6);

              if (data === '[DONE]') {
                setState((s) => ({ ...s, status: 'done' }));
                return;
              }

              try {
                const event = JSON.parse(data);
                if (event.token) {
                  setState((s) => ({
                    ...s,
                    text: s.text + event.token,
                    tokens: s.tokens + 1,
                  }));
                }
                if (event.done) {
                  setState((s) => ({ ...s, status: 'done' }));
                  return;
                }
              } catch { /* skip non-JSON lines */ }
            }
          }
          throw new Error('Stream ended before a completion event');
        };

        await processStream();
      } catch (err) {
        if (abortController?.signal.aborted) return;
        setState((s) => ({
          ...s,
          status: 'error',
          error: (err as Error).message,
        }));
      }
    },
    [
      walletClient,
      address,
      executor,
      encryptedSecrets,
      secretOwners,
      secretSignatures,
      convoPath,
      convoKeyRef,
      model,
      temperature,
      maxTokens,
      streamingServiceUrl,
    ]
  );

  const stop = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
      setState((s) => ({ ...s, status: 'done' }));
    }
  }, []);

  const reset = useCallback(() => {
    stop();
    setState({ status: 'idle', text: '', tokens: 0 });
  }, [stop]);

  return { state, submit, stop, reset };
}
```

### Frontend Usage Notes

Use any UI wrapper you want, but keep frontend logic thin:

- reuse a shared ABI builder instead of re-encoding the full tuple in multiple components
- pass `executor`, `encryptedSecrets`, and GCS convo fields (`convoPath`, `convoKeyRef`) into the hook
- surface `status`, `error`, and `txHash` clearly for retries/debugging
- keep cancel/reset controls (`stop`, `reset`) in the UX


---

## 11. Model Selection

For current production, use **`deepseek-ai/DeepSeek-V4-Flash-0731` only**. If your agent picks any other model name, treat it as a sad path and fail fast in app logic.
From `TEEServiceRegistry` responses, use `teeAddress` and `executorSecretsAuthPublicKey` for this dapp flow. Do not use the registry `endpoint` field here.

`ModelPricingRegistry` (`0xd190Aa03c401ef5CEcE00927b522974c0f330b97`) is for pricing metadata. It does not prove executor liveness. Confirm executors via `TEEServiceRegistry.getServicesByCapability(1, true)`.

### Checking Available Executors

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
const CAPABILITY_LLM = 1; // LLM capability enum value

const services = await publicClient.readContract({
  address: TEE_SERVICE_REGISTRY,
  abi: [{
    name: 'getServicesByCapability',
    type: 'function',
    stateMutability: 'view',
    inputs: [{ name: 'capability', type: 'uint8' }, { name: 'checkValidity', type: 'bool' }],
    outputs: [{
      name: 'services',
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
  args: [CAPABILITY_LLM, true],
});

for (const service of services) {
  console.log('Executor:', service.node.teeAddress);
  console.log('Valid:', service.isValid);
  console.log('Public Key:', service.node.executorSecretsAuthPublicKey);
  // service.node.endpoint exists in the struct but is NOT used by dApp code.
}
```

> The `endpoint` field is present in the on-chain registry struct (required for ABI decoding) but is **not relevant to dApp developers**. It is an internal infrastructure value used by the node operator. Your dApp only needs `teeAddress` (pass as the executor in the precompile call) and `executorSecretsAuthPublicKey` (for ECIES secret encryption). Do not read, validate, or connect to the endpoint.

---

## 12. Model Discovery & Pricing

### Model Registry

Use registry lookups for pricing metadata and sanity checks, then still pin your call model to `deepseek-ai/DeepSeek-V4-Flash-0731`.

**ModelPricingRegistry** (`0xd190Aa03c401ef5CEcE00927b522974c0f330b97`):

```typescript
// Discover available models
const models = await publicClient.readContract({
  address: '0xd190Aa03c401ef5CEcE00927b522974c0f330b97',
  abi: [{
    name: 'getAllModels',
    type: 'function',
    inputs: [],
    outputs: [{ type: 'string[]' }],
    stateMutability: 'view'
  }],
  functionName: 'getAllModels',
});

// Check if a specific model exists
const exists = await publicClient.readContract({
  address: '0xd190Aa03c401ef5CEcE00927b522974c0f330b97',
  abi: [{
    name: 'modelExists',
    type: 'function',
    inputs: [{ name: 'modelName', type: 'string' }],
    outputs: [{ type: 'bool' }],
    stateMutability: 'view'
  }],
  functionName: 'modelExists',
  args: ['deepseek-ai/DeepSeek-V4-Flash-0731'], // enumerate hosted models with getAllModels()
});
```

#### ModelInfo Struct

`getModel(string modelName)` returns a `ModelInfo` struct with 17 fields (any ABI tuple you use to decode `getModel`/`getAllModelsWithInfo` must include the 4 trailing `uint256` LLM rate-card components):

```solidity
struct ModelInfo {
    uint256 paramsB;                  // Model size in billions × 1e18
    uint256 theta;                    // Theta multiplier × 1e18
    uint256 maxSeqLen;                // Maximum sequence length
    bool exists;                      // Distinguishes zero-value from missing
    uint256 imageFeeWeiPerPixel;      // Per-pixel image generation fee (wei)
    uint256 imageMinFeeWei;           // Minimum image fee (wei)
    uint256 imageStepsBaseline;       // Baseline diffusion steps for image
    uint256 audioFeeWeiPerSecond;     // Per-second audio fee (wei)
    uint256 audioMinFeeWei;           // Minimum audio fee (wei)
    uint256 videoBaseFeeWei;          // Base fee for video (wei)
    uint256 videoFeeWeiPerPixelSecond;// Per-pixel-second video fee (wei)
    uint256 videoStepsBaseline;       // Baseline diffusion steps for video
    uint256 videoFpsBaseline;         // Baseline FPS for video pricing
    uint256 llmBaseFeeWei;            // Per-request LLM base fee (wei)
    uint256 llmFeeWeiPerInputToken;   // Fresh prompt token rate (wei)
    uint256 llmFeeWeiPerOutputToken;  // Completion token rate (wei)
    uint256 llmCachedInputDiscountBps;// Cached prompt tokens pay this fraction (bps, 1000 = 10%)
}
```

For text LLM pricing, the relevant fields are `llmBaseFeeWei`, `llmFeeWeiPerInputToken`, `llmFeeWeiPerOutputToken`, and `llmCachedInputDiscountBps` (plus `maxSeqLen`, which sets the worst-case escrow ceiling). `paramsB` and `theta` do not enter the LLM fee. A model with `llmFeeWeiPerInputToken == 0` has no LLM pricing and LLM jobs against it are rejected. Image/audio/video fields apply to multimodal models.

### Pricing

Use the exact formula in Section 9 for fee calculations and budgeting. This section focuses on model discovery; Section 9 is the pricing source of truth.

### Gas Considerations

The LLM precompile (0x0802) is a **short-running async precompile** — there is no callback. Results appear in the transaction receipt's `spcCalls` field. Standard gas guidance:
- Default: 3,000,000 gas is typically sufficient
- The actual LLM inference cost is handled off-chain by the executor and charged via RitualWallet, not via EVM gas

---

## 13. Error Reference

> Failure handling has three paths: (1) tx settles and the response envelope has `has_error=true` (executor returned a structured error — most common); (2) tx settles, `has_error=false`, but `completion_data` contains text that doesn't conform to your expected schema (model deviated despite `response_format`); (3) tx is skipped/dropped before usable settlement output (builder/pool sad path). Your agent must handle all three.

The error string returned in `error_message` is **freeform** — there is no structured error code enum. The strings below are representative substrings, not exact match values; pattern-match loosely.

| Likely substring of `error_message` | Cause | Fix |
|-------|-------|-----|
| `HTTP request failed with status 400`, contains `context length`, `maximum context`, `max_tokens`, or `prompt is too long` | Prompt + completion budget exceeds the model's registered `max_seq_len` — read it from `getModel(name)`. The executor does **not** preflight token counts; this only surfaces from the upstream endpoint. | Reduce prompt size, lower `max_completion_tokens`, or summarize tool/conversation history before sending. **`max_completion_tokens` will not protect you** — it caps output only. |
| `insufficient wallet balance` | RitualWallet has not been funded sufficiently for executor + commitment + inclusion fees | Deposit more via `ritualWallet.deposit()`. See `ritual-dapp-wallet`. |
| `Request expired: emission block X > (commit block + TTL)` | TTL too low, commitment expired before executor processed | Increase TTL (300–500) |
| `Model 'X' is not available. Available models: [...]` | Model name not registered on the chosen executor | Pin model to `deepseek-ai/DeepSeek-V4-Flash-0731` for current production, or pick a different executor that supports your model |
| Model name not in `ModelPricingRegistry` | Tx is rejected at RPC validation before being mined | Use only registered models |
| Tx hash broadcast but no receipt/settlement output | Builder/pool sad path (skip/drop) | Retry with the registry model only, real executor, adequate TTL/deposit; then inspect next tx |
| `Failed to parse response JSON` | Upstream returned a non-JSON HTTP body | Pin to a healthy executor; check executor logs |
| `GCS preflight failed` | Bad GCS credentials — checked before inference | Verify `service_account_json` and `bucket` in encrypted secrets |
| Tx drops when `encryptedSecrets` is non-empty | Decrypted secrets payload shape mismatch | Use string-valued secrets; for `GCS_CREDS`, the value must be a JSON string blob |
| `GCS convo history upload failed` | Upload error after inference completed | Check bucket permissions and network connectivity |
| Tx revert | ABI encoding mismatch or address(0) executor | Verify 32-field ABI layout; use a real registered executor address |
| RPC `-32602 invalid async payload: ... ethabi decode failed: Invalid data` | Chain pre-validates async precompile inputs at submission time by ABI-decoding into the canonical `LLMCallRequest`. The tx never enters the mempool — `eth_getTransactionByHash` returns null. Almost always a field-count mismatch. | Encode all 32 fields including `secret_owners` (2), `pii_enabled` (30) and `convo_history` (31). For `convo_history` semantics (including the no-history case), see `ritual-dapp-da`. Field layout in Section 1. |
| `has_error=false` but `completion_data` content doesn't parse as expected JSON | Model deviated from the schema you supplied via `response_format` | Treat structured output as best-effort; wrap your decode in try/except and fall back to retry-or-abort. The executor does not locally validate the model's output against your schema. |
| Empty `content` with `usage.completion_tokens` equal to `max_completion_tokens` and `finish_reason` of `"length"` | Reasoning-budget exhaustion. In reasoning mode the model emits a `<think>...</think>` chain-of-thought; with a small `max_completion_tokens` cap, the model burns the entire budget reasoning and never emits final-content tokens. The empty bytes on chain accurately reflect what vLLM returned. The on-chain `ChatMessage` ABI does not carry `reasoning_content`, so reasoning text is dropped at the encoding boundary even when present upstream. | Raise `max_completion_tokens` to at least 4096 (the recommended baseline for this model). Discriminator: re-run at 4096; if `content` populates and `finish_reason` flips to `stop`, the cause is confirmed. |
| No `PrecompileCalled` in logs | Commitment phase, not settlement | Wait for the settlement tx |
| `sender locked` | Pending async tx for this address | Wait for current tx to settle. One pending async call per address. |
| `encrypted_secrets required when pii_enabled=true` | PII without secrets | Encrypt PII prompt into secrets with executor's public key |
| `PII redaction requested but PII service is not available` | Executor lacks PII sidecar | Try a different executor |
| PII + streaming | Incompatible | Set `stream: false` when `piiEnabled: true` |
| `Streaming is requested but not enabled` | Executor config | Not all executors support streaming — try a different one |
| SSE silent hang | `stream=false` in ABI but SSE connected | Verify `stream: true` in the request encoding |
| Stream 401 | Bad EIP-712 signature | Domain must be `'Ritual Streaming Service'` (no `verifyingContract`), signer must be tx sender |

---

## Quick Reference

| Item | Value |
|------|-------|
| Precompile | `0x0000000000000000000000000000000000000802` |
| RitualWallet | `0xF04076756d8129Baec46Dc0F1c526Baec490C393` |
| TEEServiceRegistry | `0xf4495DC72143D44A93AB0ecE4d6D63a216b27839` |
| ModelPricingRegistry | `0xd190Aa03c401ef5CEcE00927b522974c0f330b97` |
| Chain ID | 784 |
| Gas limit | 3,000,000 (actual ~60K; inference is off-chain) |
| TTL | 300 blocks (~105s at ~350ms block-time baseline) |
| Temperature | ×1000 (700 = 0.7) |
| Null sentinel | -1 (optional int fields) |
| Live model | `deepseek-ai/DeepSeek-V4-Flash-0731` (1M context) |
| Stream auth | `Authorization: Bearer {sig}` + `X-Timestamp` → `/v1/stream/{txHash}` |
| EIP-712 domain | `{ name: 'Ritual Streaming Service', version: '1', chainId: 784 }` |
| Message format | OpenAI chat (JSON-encoded) |
| Stream signature expiry | 5 minutes (60s future tolerance) |
| Convo history DA | StorageRef `(platform, path, key_ref)` — supports `gcs` (default), `hf`, `pinata`. Stored as plaintext JSONL. See `ritual-dapp-da`. |
| GCS convo history | Default for production agents: `('gcs', path, key_ref)` with credentials in `encryptedSecrets` |
| ECIES nonce length (`eciesjs`) | `ECIES_CONFIG.symmetricNonceLength = 12` |
| Encryption/secrets | See `ritual-dapp-secrets` for ECIES encryption and secret handling |
| Arbitrary OpenAI-compatible HTTP | RITHTTP1 in `ritual-dapp-http`: DA-backed JSON, held responses, selected SSE, jq projection/fan-out |

---

## 14. Tool / Function Calling

Use this after your baseline inference flow is stable. Keep both `toolsData` and `toolChoiceData` as `0x` until you need tool calling.

```typescript
const toolsData = '0x' as Hex;
const toolChoiceData = '0x' as Hex;
// Pass these in the appropriate positions of the 32-field ABI tuple.
// See Section 1 for the full field layout.
```

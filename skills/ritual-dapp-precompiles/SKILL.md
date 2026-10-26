---
name: ritual-dapp-precompiles
description: Complete Ritual precompile ABI reference. Use when encoding/decoding precompile calls, understanding request/response formats, or debugging precompile interactions.
---

# Ritual Precompile ABI Reference

This file is the ABI reference — field layouts, types, and output formats. For complete contract patterns (deposit, executor selection, callback handling, testing), see `ritual-dapp-contracts`. For wallet deposits and fund flows, see `ritual-dapp-wallet`.

> Agent launches use application-owned consumers that forward the canonical envelopes below. See `ritual-dapp-agents` and the self-contained examples for identity, sponsorship, secrets and callback setup.

## Address Map

| Precompile | Address | Fields | Execution Model |
|---|---|---|---|
| HTTP Call | `0x0801` | 16 | Short-running async |
| LLM Call | `0x0802` | 32 | Short-running async |
| JQ | `0x0803` | 3 | Synchronous |
| Long-Running HTTP | `0x0805` | 38 | Long-running async |
| ZK Long-Running | `0x0806` | 16 | Long-running async |
| FHE Inference | `0x0807` | 21 | Long-running async |
| Sovereign Agent | `0x080C` | 13 (envelope; 16-field V1 payload) | Long-running async |
| Image Call | `0x0818` | 20 | Long-running async |
| Audio Call | `0x0819` | 20 | Long-running async |
| Video Call | `0x081A` | 20 | Long-running async |
| DKMS Key | `0x081B` | 10 | Short-running async |
| Persistent Agent | `0x0820` | 13 (envelope; 21-field V1 payload) | Long-running async |
| Ed25519 | `0x0009` | 3 | Synchronous |
| SECP256R1 | `0x0100` | 3 | Synchronous |
| TX Hash | `0x0830` | 0 | Synchronous |

**Synchronous**: inline execution, no executor, no limits on calls per tx.
**Short-running async**: One per tx. Builder simulates (fresh simulation), executor processes in TEE, builder re-executes deferred tx with result injected (fulfilled replay). Result in receipt `spcCalls`.
**Long-running async**: Phase 1 mined immediately (returns task ID). Phase 2 delivers result via callback from AsyncDelivery (`0x508f57AE70967Da28AE0Ab6b95532878c4D0F440`).

```typescript
const PRECOMPILES = {
  HTTP_CALL: '0x0000000000000000000000000000000000000801',
  LLM: '0x0000000000000000000000000000000000000802',
  JQ: '0x0000000000000000000000000000000000000803',
  LONG_RUNNING_HTTP: '0x0000000000000000000000000000000000000805',
  ZK_TWO_PHASE: '0x0000000000000000000000000000000000000806',
  FHE_CALL: '0x0000000000000000000000000000000000000807',
  SOVEREIGN_AGENT: '0x000000000000000000000000000000000000080C', // submit through your consumer (ritual-dapp-agents)
  IMAGE_CALL: '0x0000000000000000000000000000000000000818',
  AUDIO_CALL: '0x0000000000000000000000000000000000000819',
  VIDEO_CALL: '0x000000000000000000000000000000000000081A',
  DKMS_KEY: '0x000000000000000000000000000000000000081B',
  PERSISTENT_AGENT: '0x0000000000000000000000000000000000000820', // submit through your consumer (ritual-dapp-agents)
  ED25519: '0x0000000000000000000000000000000000000009',
  SECP256R1: '0x0000000000000000000000000000000000000100',
  TX_HASH: '0x0000000000000000000000000000000000000830',
} as const;
```

---

## Output Unwrapping

The Solidity CALL return from an async precompile is `abi.encode(bytes simmedInput, bytes actualOutput)`. Unwrap that CALL return to get the real result:

```solidity
(, bytes memory actualOutput) = abi.decode(rawOutput, (bytes, bytes));
```

In `eth_call` simulation, `actualOutput` may be empty (`0x`). This is expected — decode the settled receipt for final data.

The `spcCalls` field is a Ritual extension to the transaction receipt:

```typescript
const receipt = await publicClient.waitForTransactionReceipt({ hash });
const spcCalls = (receipt as any).spcCalls;
```

Each `spcCalls[i].output` is already the bare executor result. Decode it with the precompile's response ABI; do not apply the CALL-return `(bytes,bytes)` unwrap to a receipt output.

---

## Base Executor Fields (7 fields)

All executor-based precompiles start with these fields (exception: the agent precompiles `0x080C`/`0x0820`, which use the 13-field `AgentAsyncEnvelope` instead — see their sections):

| Index | Type | Field | Description |
|---|---|---|---|
| 0 | `address` | executor | TEE executor address |
| 1 | `address` | sponsor | RitualWallet account backing the job (MUST be non-zero). Extraction is per-precompile (`sponsor_for_precompile`): non-agent precompiles read ABI field 1 (input[44..64]); agent families (`0x080C`/`0x0820`) get sponsor from a strict `AgentAsyncEnvelope` decode (envelope field 1), and admission (`AsyncJobTracker._validateProtocolInput`) additionally requires the decoded executor/sponsor/ttl to match the job's executor, reserve sponsor, and ttl — malformed agent input is rejected at admission instead of being silently read at a fixed offset |
| 2 | `address[]` | secretOwners | Explicit owner address per encrypted secret blob (parallel to encryptedSecrets/secretSignatures; each owner non-zero) |
| 3 | `bytes[]` | encryptedSecrets | ECIES-encrypted owner-bound secret envelopes |
| 4 | `uint256` | ttl | Blocks until expiry |
| 5 | `bytes[]` | secretSignatures | Owner EIP-191 signatures over each blob's domain-separated authorization payload (`RITUAL_SECRET_AUTHORIZATION_V1 \|\| uint16(len(useContext)) \|\| useContext \|\| uint256(chainId) \|\| executor \|\| owner \|\| keccak256(encryptedSecrets)`); signer must equal `secretOwners[i]` |
| 6 | `bytes` | userPublicKey | User's ECIES public key (empty = no output encryption) |

`secretOwners`, `encryptedSecrets`, and `secretSignatures` must have identical length and be all empty together when there are no secrets; each owner must be non-zero. The signature binds the OWNER (not the caller/delegate) — caller/delegate authorization is enforced downstream by `SecretsAccessControl`.

Each `encryptedSecrets[i]` decrypts to an owner-bound JSON envelope `{version:1, secret_owner, secrets}` (not a bare map); the executor rejects `version != 1` or an envelope owner that does not match the request's `secretOwners[i]`. Secrets use plain string replacement — the executor reads the inner `.secrets` key-value map and replaces matching key strings wherever they appear in URLs, headers, and body.

---

## HTTP Call (0x0801) — 16 fields

| Index | Type | Field |
|---|---|---|
| 0-6 | — | Base executor fields |
| 7 | `string` | url |
| 8 | `uint8` | method (GET=1, POST=2, PUT=3, DELETE=4, PATCH=5, HEAD=6, OPTIONS=7) |
| 9 | `string[]` | headersKeys |
| 10 | `string[]` | headersValues |
| 11 | `bytes` | body |
| 12 | `uint256` | dkmsKeyIndex (0 = not using dKMS) |
| 13 | `uint8` | dkmsKeyFormat |
| 14 | `bool` | piiEnabled |
| 15 | `(string,string,string)` | outputStorageRef (DA output ref; empty tuple = inline). See `ritual-dapp-da`. |

**Output (inline, when `outputStorageRef` is empty)**: `(uint16 statusCode, string[] headerKeys, string[] headerValues, bytes body, string errorMessage)`

**Output (DA, when `outputStorageRef` is set)**: the executor uploads the (encrypted) ABI-encoded `HTTPCallResponse` off-chain and `actualOutput` becomes a DA result envelope `(bool hasError, string outputUri, bytes32 outputContentHash, uint64 outputSizeBytes, string errorMessage)`. Decode the envelope, fetch the bytes from `outputUri`, verify against `outputContentHash`, then decrypt with the user private key to recover the inline `HTTPCallResponse`. DA output is fail-closed: it requires a valid 65-byte `userPublicKey` with `0x04` prefix. See `ritual-dapp-da`.

**RITHTTP1 extension (same 16 fields)**: field 11 may be `"RITHTTP1" || abi.encode(uint32 options, bytes jsonTemplate, InputRef[], OutputPipe[])`. Each pipe has kind, string selector, encoding, recipient key and inline DA destination. Only options 1 (AWAIT_RESPONSE) and 8 (STREAM_RESPONSE) exist; this four-field revision rejects older RITHTTP1 schemas. Normal output completion uses RITOUT1 encoding 4 with indexed per-pipe results. In RITHTTP1 mode field 15 is empty, `piiEnabled=false`, and output starts with `RITOUT1`. See the [base](../ritual-dapp-http/references/rithttp1.md) and [private-I/O](../ritual-dapp-http/references/rithttp1-private-io.md) references.

### Quick Encode

```typescript
// HTTP GET — all 16 fields
const encoded = encodeAbiParameters(
  [{type:'address'},{type:'address'},{type:'address[]'},{type:'bytes[]'},{type:'uint256'},{type:'bytes[]'},{type:'bytes'},
   {type:'string'},{type:'uint8'},{type:'string[]'},{type:'string[]'},{type:'bytes'},
   {type:'uint256'},{type:'uint8'},{type:'bool'},
   {type:'tuple', components:[{type:'string'},{type:'string'},{type:'string'}]}],
  [executor, sponsor, [], [], 100n, [], '0x', url, 1, [], [], '0x', 0n, 0, false, ['','','']]
);
```

```solidity
// Solidity — decode output after unwrapping (simmedInput, actualOutput) pair
// This 5-field decode applies ONLY when outputStorageRef was empty (inline output).
(, bytes memory out) = abi.decode(rawOutput, (bytes, bytes));
(uint16 status, , , bytes memory body, string memory err) =
    abi.decode(out, (uint16, string[], string[], bytes, string));
// When outputStorageRef was set, `out` is instead the DA result envelope
// (bool hasError, string outputUri, bytes32 outputContentHash, uint64 outputSizeBytes, string errorMessage);
// fetch + verify + decrypt off-chain to recover the inline HTTPCallResponse. See `ritual-dapp-da`.
```

Rough deposit: budget above 0.01 RIT — 0.01 RIT (`HTTP_EXECUTOR_BASE_FEE_WEI`) is only the fixed base floor; a real call also pays 0.35 gwei/byte in + 0.35 gwei/byte out on top.

---

## LLM Call (0x0802) — 32 fields

| Index | Type | Field | Notes |
|---|---|---|---|
| 0-6 | — | Base executor fields | |
| 7 | `string` | messagesJson | `[{role, content}]` |
| 8 | `string` | model | e.g. `deepseek-ai/DeepSeek-V4-Flash-0731` (text, 284B total / 13B active MoE, 1M ctx); enumerate with `getAllModels()` |
| 9 | `int256` | frequencyPenalty | ×1000 |
| 10 | `string` | logitBiasJson | |
| 11 | `bool` | logprobs | |
| 12 | `int256` | maxCompletionTokens | -1 = null |
| 13 | `string` | metadataJson | |
| 14 | `string` | modalitiesJson | |
| 15 | `uint256` | n | |
| 16 | `bool` | parallelToolCalls | ABI placeholder (always true) |
| 17 | `int256` | presencePenalty | ×1000 |
| 18 | `string` | reasoningEffort | "low"/"medium"/"high" |
| 19 | `bytes` | responseFormatData | |
| 20 | `int256` | seed | -1 = null |
| 21 | `string` | serviceTier | |
| 22 | `string` | stopJson | |
| 23 | `bool` | stream | |
| 24 | `int256` | temperature | ×1000 |
| 25 | `bytes` | toolChoiceData | ABI placeholder (always 0x) |
| 26 | `bytes` | toolsData | ABI placeholder (always 0x) |
| 27 | `int256` | topLogprobs | -1 = null |
| 28 | `int256` | topP | ×1000 |
| 29 | `string` | user | |
| 30 | `bool` | piiEnabled | |
| 31 | `(string,string,string)` | convoHistory | (platform, path, keyRef) StorageRef for DA-backed multi-turn history; `('','','')` if unused. See `ritual-dapp-da`. |

**Output**: `(bool hasError, bytes completionData, bytes modelMetadata, string errorMessage, (string,string,string) updatedConvoHistory)`

### Quick Encode

```typescript
// LLM — all 32 fields
const encoded = encodeAbiParameters(
  parseAbiParameters([
    'address, address, address[], bytes[], uint256, bytes[], bytes,',
    'string, string, int256, string, bool, int256, string, string,',
    'uint256, bool, int256, string, bytes, int256, string, string, bool,',
    'int256, bytes, bytes, int256, int256, string, bool,',
    '(string,string,string)',
  ].join('')),
  [
    executor, sponsor, [], [], 300n, [], '0x',
    JSON.stringify([{role:'user', content: prompt}]),
    model,
    0n, '', false, 4096n, '', '',           // freq, logitBias, logprobs, maxTokens, meta, modalities  -- >=4096 reasoning headroom; see ritual-dapp-llm
    1n, true, 0n, 'medium', '0x', -1n,     // n, parallel, presence, reasoning, respFmt, seed
    'auto', '',                              // serviceTier, stop
    false,                                   // stream
    700n,                                    // temperature (0.7)
    '0x', '0x',                             // toolChoice, tools
    -1n, 1000n, '',                         // topLogprobs, topP, user
    false,                                   // piiEnabled
    ['gcs', 'convos/my-session.jsonl', 'GCS_CREDS'], // convoHistory
  ]
);
```

Deposit: model-dependent — the reserve is the worst-case rate-card escrow; see `ritual-dapp-llm` §Fees for the formula and current numbers.

---

## Long-Running HTTP (0x0805) — 38 fields

| Index | Type | Field |
|---|---|---|
| 0-6 | — | Base executor fields |
| 7 | `uint64` | pollIntervalBlocks |
| 8 | `uint64` | maxPollBlock (Phase 2 deadline offset) |
| 9 | `string` | taskIdMarker |
| 10 | `address` | deliveryTarget |
| 11 | `bytes4` | deliverySelector |
| 12 | `uint256` | deliveryGasLimit |
| 13 | `uint256` | deliveryMaxFeePerGas |
| 14 | `uint256` | deliveryMaxPriorityFeePerGas |
| 15 | `uint256` | deliveryValue |
| 16 | `string` | url |
| 17 | `uint8` | method |
| 18 | `string[]` | headersKeys |
| 19 | `string[]` | headersValues |
| 20 | `bytes` | body |
| 21 | `string` | taskIdJsonPath |
| 22 | `string` | pollUrl |
| 23 | `uint8` | pollMethod |
| 24 | `string[]` | pollHeadersKeys |
| 25 | `string[]` | pollHeadersValues |
| 26 | `bytes` | pollBody |
| 27 | `string` | statusJsonPath |
| 28 | `string` | resultUrl |
| 29 | `uint8` | resultMethod |
| 30 | `string[]` | resultHeadersKeys |
| 31 | `string[]` | resultHeadersValues |
| 32 | `bytes` | resultBody |
| 33 | `string` | resultJsonPath |
| 34 | `uint256` | dkmsKeyIndex |
| 35 | `uint8` | dkmsKeyFormat |
| 36 | `bool` | piiEnabled |
| 37 | `(string,string,string)` | outputStorageRef (StorageRef: platform, path, keyRef; see `ritual-dapp-da`) |

**Phase 1 output**: `(string taskId)`
**Phase 2 callback**: `function onLongRunningResult(bytes32 jobId, bytes calldata result) external`

RITHTTP1 does not alter these 38 fields. Without `AWAIT_RESPONSE`, it hydrates the initial request and retains task-ID polling. With `AWAIT_RESPONSE`, Phase 1 settles before one held upstream request and the callback receives `RITOUT1`; poll/result request fields are ignored placeholders, `maxPollBlock` is the deadline, and `resultJsonPath` must be `.`. Long SSE additionally sets `STREAM_RESPONSE`. See [`../ritual-dapp-http/references/rithttp1.md`](../ritual-dapp-http/references/rithttp1.md).

---

## ZK Long-Running (0x0806) — 16 fields

Note: ZK extends ExecutorRequest directly, NOT the LongRunningRequest base. Different delivery field layout.

| Index | Type | Field |
|---|---|---|
| 0-6 | — | Base executor fields |
| 7 | `bool` | inputEncrypted |
| 8 | `uint64` | maxProofBlock (Phase 2 deadline offset) |
| 9 | `address` | deliveryTarget |
| 10 | `bytes4` | deliverySelector |
| 11 | `uint256` | deliveryGasLimit |
| 12 | `uint256` | deliveryMaxFeePerGas |
| 13 | `uint256` | deliveryMaxPriorityFeePerGas |
| 14 | `uint256` | deliveryValue |
| 15 | `bytes` | operationInput |

**Phase 1 output**: `bytes32` job commitment hash
**Phase 2 callback**: `function onZKResultDelivered(bytes32 jobId, bytes calldata result) external`

---

## FHE Inference (0x0807) — 21 fields

| Index | Type | Field |
|---|---|---|
| 0-6 | — | Base executor fields |
| 7 | `string` | model |
| 8 | `bytes` | encryptedInput |
| 9 | `bytes` | encryptedInputRef |
| 10 | `bytes` | evkReference |
| 11 | `uint8` | numLayers |
| 12 | `uint64` | maxInferenceBlock (Phase 2 deadline offset) |
| 13 | `address` | deliveryTarget |
| 14 | `bytes4` | deliverySelector |
| 15 | `uint256` | deliveryGasLimit |
| 16 | `uint256` | deliveryMaxFeePerGas |
| 17 | `uint256` | deliveryMaxPriorityFeePerGas |
| 18 | `uint256` | deliveryValue |
| 19 | `(string,string,string)` | inputStorageRef (StorageRef tuple) |
| 20 | `(string,string,string)` | outputStorageRef (StorageRef tuple) |

**Capacity (fail-closed)**: Phase 1 can be rejected at capacity. The executor bounds outstanding jobs (pending + active, incl. the one serially executing) by `FHE_MAX_OUTSTANDING_JOBS` (default 2); over the limit `RegisterFHEJob` errors and the handler returns an error result `FHE capacity unavailable: ...`. A dApp calling 0x0807 must handle a capacity-rejection error result.

**Fees**: FHE has its own two-phase schedule — Phase 1 settlement `FHE_PHASE1_SETTLEMENT_FEE_WEI` = 0.10 RIT; Phase 2 = `FHE_PHASE2_EXECUTOR_FEE_WEI` = 0.11 RIT, a fixed fee for every successful delivery (reserved in full at Phase 1); output size does not affect it. These are chain constants — confirm against the deployed async-fees configuration. On a DA-error delivery Phase 2 charges the flat `DA_ERROR_PHASE2_FEE_WEI` = 0.01 RIT instead.

---

## Sovereign Agent (0x080C) — 13-field envelope + 16-field V1 payload (direct consumer input)

Does NOT extend the `ExecutorRequest` base. The chain-visible request is the canonical flat 13-field `AgentAsyncEnvelope` (`AGENT_ASYNC_ENVELOPE_FIELD_COUNT = 13`, flat `abi.encode` — NOT a tuple), shared with Persistent Agent (0x0820). Agent-specific fields (prompt, model, skills, refs) are opaque executor-interpreted bytes in `executorPayload`. Encode this input and submit it through your own sovereign consumer (`ritual-dapp-agents`).

**AgentAsyncEnvelope (13 flat fields)**:

| Index | Type | Field |
|---|---|---|
| 0 | `address` | executor |
| 1 | `address` | sponsor (funded RitualWallet account; approve the consumer when different from caller) |
| 2 | `uint64` | ttl |
| 3 | `uint64` | phase2Ttl (carries the old maxPollBlock deadline role) |
| 4 | `bool` | callbackEnabled (true for the example sovereign consumer) |
| 5 | `address` | callbackTarget (the deployed consumer) |
| 6 | `bytes4` | callbackSelector |
| 7 | `uint64` | callbackGasLimit |
| 8 | `uint128` | callbackMaxFeePerGas |
| 9 | `uint128` | callbackMaxPriorityFeePerGas |
| 10 | `uint256` | callbackValue (MUST be 0 — executor rejects: "sovereign agent callback value is not supported") |
| 11 | `bytes32` | applicationContext |
| 12 | `bytes` | executorPayload (opaque; V1 layout below) |

Decode is strict everywhere (Solidity library, Rust codec, Go handlerutil, Python ritual_common): re-encoding the decoded envelope must be byte-exact equal to the input, and callback validation is all-or-nothing (enabled ⇒ target/selector/gasLimit non-zero and priority fee ≤ max fee; disabled ⇒ EVERY callback field zero).

**Sovereign V1 executorPayload (16 fields)** — "expected 16 sovereign agent V1 payload fields"; version != 1 rejected:

| Index | Type | Field |
|---|---|---|
| 0 | `uint8` | version (MUST be 1) |
| 1 | `address[]` | secretOwners |
| 2 | `bytes[]` | encryptedSecrets |
| 3 | `bytes[]` | secretSignatures |
| 4 | `bytes` | userPublicKey |
| 5 | `uint16` | cliType (ABI enum 0=claude_code, 1=codex, 2=aider, 3=mcp, 4=openclaw, 5=crush, 6=zeroclaw) |
| 6 | `string` | prompt |
| 7 | `(string,string,string)` | convoHistory (platform, path, keyRef) |
| 8 | `(string,string,string)` | output |
| 9 | `(string,string,string)[]` | skills |
| 10 | `(string,string,string)` | systemPrompt |
| 11 | `string` | model |
| 12 | `string[]` | tools |
| 13 | `uint16` | maxTurns |
| 14 | `uint32` | maxTokens |
| 15 | `string` | rpcUrls |

The agent envelope has no polling fields; delivery rides the envelope's mandatory callback fields.

---

## Image Call (0x0818) — 20 fields

| Index | Type | Field |
|---|---|---|
| 0-6 | — | Base executor fields |
| 7-15 | — | Polling + delivery config (same as Long-Running HTTP 7-15) |
| 16 | `string` | model |
| 17 | `(uint8,bytes,string,bytes32,uint32,uint32,bool)[]` | inputs (ModalInput array) |
| 18 | `(uint8,uint32,uint32,uint32,bool,uint16,uint16,uint32,uint8,string)` | output (OutputConfig) |
| 19 | `(string,string,string)` | outputStorageRef — StorageRef: (platform, path, keyRef). See `ritual-dapp-da`. |

**ModalInput**: `(inputType, data, uri, contentHash, param1, param2, encrypted)` — inputType: 0=TEXT, 1=IMAGE, 2=AUDIO, 3=VIDEO
**OutputConfig**: `(outputType, maxWidth, maxHeight, maxParam3, encryptOutput, numInferenceSteps, guidanceScaleX100, seed, fps, negativePrompt)`
**StorageRef**: `(platform, path, keyRef)` — platform is `'gcs'`, `'hf'`, or `'pinata'`. Credentials in `encryptedSecrets` keyed by `keyRef`. See `ritual-dapp-da`.

For IMAGE: outputType=1, maxParam1=width, maxParam2=height.

**Phase 2 result (Image)**: `(bool hasError, bytes completionData, string outputUri, bytes32 outputContentHash, bool outputEncrypted, uint32 outputSizeBytes, uint32 outputWidth, uint32 outputHeight, string errorMessage)`

---

## Audio Call (0x0819) — 20 fields

Same ABI structure as Image Call (field 19 is `outputStorageRef` StorageRef tuple). For AUDIO: outputType=2, maxParam1=maxDurationMs, negativePrompt repurposed as voice parameter.

**Phase 2 result (Audio)**: `(bool hasError, bytes completionData, string outputUri, bytes32 outputContentHash, bool outputEncrypted, uint32 outputSizeBytes, uint32 outputDurationMs, string errorMessage)`

---

## Video Call (0x081A) — 20 fields

Same ABI structure as Image Call (field 19 is `outputStorageRef` StorageRef tuple). For VIDEO: outputType=3, maxParam1=width, maxParam2=height, maxParam3=maxDurationMs, fps used.

**Phase 2 result (Video)**: `(bool hasError, bytes completionData, string outputUri, bytes32 outputContentHash, bool outputEncrypted, uint64 outputSizeBytes, uint32 outputWidth, uint32 outputHeight, uint32 outputDurationMs, string errorMessage)`

---

## DKMS Key (0x081B) — 10 fields

| Index | Type | Field |
|---|---|---|
| 0-6 | — | Base executor fields (sponsor at index 1, explicit non-zero RitualWallet account backing the job) |
| 7 | `address` | owner |
| 8 | `uint256` | keyIndex |
| 9 | `uint8` | keyFormat |

In x402 dKMS flows the key `owner` is the PrecompileConsumer/ScheduledConsumer (the consumer contract sender of the async job), with the agent passed as `sponsor`. Each agent gets a stable per-agent key index via `get_agent_dkms_key_index(base, agentIndex) = base * 10_000 + agentIndex` to avoid shared payment keys.

**Plaintext result ABI:** `(address paymentAddress, bytes daPublicKey)`. The DA key is an uncompressed 65-byte secp256k1 public key. Payment and DA keys use different derivation domains; do not derive `paymentAddress` from `daPublicKey`. With a nonempty user output key the complete result is encrypted, so decrypt before ABI decoding.

The [standalone DKMS example](../../examples/dkms/README.md) includes the complete ten-field encoder, two-field decoder, explicit funding/deployment inputs and exact-origin/commitment receipt correlation. It calls `0x081B` directly from its EOA and requires no factory, traffic generator or private SDK. Its default plaintext output contains public address/key material only.

---

## Persistent Agent (0x0820) — 13-field envelope + 21-field V1 payload (direct consumer input)

Does NOT extend the `ExecutorRequest` base. The chain-visible request is the canonical flat 13-field `AgentAsyncEnvelope` shared with Sovereign Agent (0x080C) — see that section for the envelope layout and the strict byte-exact re-encode + all-or-nothing callback validation. Persistent-specific requirements:

- Callbacks MAY be disabled (fire-and-forget launch/revival); the direct example enables callbacks and targets its own consumer.
- `applicationContext` MUST equal `keccak256(abi.encode(uint256 agentId, uint64 revision))` — enforced at Go decode+handler, the Solidity consumer, DKMS bootstrap, and Python encode/decode.
- `phase2Ttl` is the Phase 2 deadline offset.

Persistent-specific fields (provider, model, refs, agentRuntime, agentId) live in the opaque `executorPayload`. Encode this input and submit it through your own persistent consumer (`ritual-dapp-agents`).

**Persistent V1 executorPayload (21 fields)** — "expected 21 persistent agent V1 payload fields"; version != 1 rejected; canonical re-pack equality required:

| Index | Type | Field |
|---|---|---|
| 0 | `uint8` | version (MUST be 1) |
| 1 | `address[]` | secretOwners |
| 2 | `bytes[]` | encryptedSecrets |
| 3 | `bytes[]` | secretSignatures |
| 4 | `bytes` | userPublicKey |
| 5 | `uint8` | provider (0=anthropic, 1=openai, 2=gemini, 3=xai, 4=openrouter) |
| 6 | `string` | model |
| 7 | `string` | llmApiKeyRef |
| 8 | `(string,string,string)` | daConfig |
| 9 | `(string,string,string)` | soulRef |
| 10 | `(string,string,string)` | agentsRef |
| 11 | `(string,string,string)` | userRef |
| 12 | `(string,string,string)` | memoryRef |
| 13 | `(string,string,string)` | identityRef |
| 14 | `(string,string,string)` | toolsRef |
| 15 | `(string,string,string)` | openclawConfigRef |
| 16 | `string` | restoreFromCid |
| 17 | `string` | rpcUrls |
| 18 | `uint16` | agentRuntime (0=ZeroClaw, 1=OpenClaw, 2=Hermes; use 0 or 2 for new agents) |
| 19 | `uint256` | agentId (chain-issued; MUST be positive) |
| 20 | `uint64` | revision |

Delivery, executor, and TTL fields live in the envelope. The StorageRef JSON key is `keyRef`.

`agentId` is the chain-issued persistent-agent identity. The EOA owner must allocate it in a prior committed transaction with `AgentIdentityRegistry.allocateAgentId(owner)`, then grant the deployed consumer operator authority using `setAgentOperator(agentId, consumer, true)`. Encode the same id and revision in the payload and `applicationContext = keccak256(abi.encode(agentId, revision))`. The executor validates identity and operator authorization against committed chain state.

StorageRef tuple: `(platform, path, keyRef)` — all strings.

---

## JQ (0x0803) — Synchronous

```solidity
(string query, string inputData, uint8 outputType)
```

| outputType | Return Type | Notes |
|---|---|---|
| 0 | `int256` | |
| 1 | `uint256` | |
| 2 | `string` | Most common |
| 3 | `bool` | |
| 4 | `address` | |
| 5-9 | Array variants | int256[], uint256[], string[], bool[], address[] |

String output (type 2) has a double-indirection wrapper. Use this decoder:

```solidity
function _decodeJQString(bytes memory raw) internal pure returns (string memory) {
    require(raw.length >= 96, "JQ output too short");
    uint256 strLen;
    assembly { strLen := mload(add(raw, 96)) }
    bytes memory result = new bytes(strLen);
    for (uint256 i = 0; i < strLen; i++) {
        result[i] = raw[96 + i];
    }
    return string(result);
}
```

Wrong `outputType` returns `ok=true` with zero-length output — it does NOT revert.

### Query compatibility and silent failures

The following observations are recorded in [issue #62](https://github.com/ritual-foundation/ritual-dapp-skills-internal/issues/62). Treat them as known query limitations when choosing filters; this is not an exhaustive JQ language support matrix.

| Query/operation | Observed behavior |
|---|---|
| `.count | tostring` and other `tostring` use | Empty/null output without an error |
| `@json` and `@csv` formatting | Empty/null output without an error |
| `[.items[].field]` with `outputType=2` | Empty/null output; type 2 expects a string, not an array |
| String concatenation involving `tostring` | Empty/null output without an error |
| `map(.field) | join(", ")` | Worked as a string-producing alternative |
| `length` with `outputType=1` | Worked as a uint256 result |
| Simple `.field` access | Worked with a matching output type |
| Pipe chains such as `.data.children | length` | Worked |

For scalar extraction/counting, prefer the working forms above. To join existing string fields, use `map(.field) | join(", ")` rather than converting values with `tostring`. Array results require a matching array output type (5–9); the reported failure with type 2 does not establish that array construction fails for every output type.

Check both the low-level call success and nonempty, correctly shaped return data before decoding. A successful call alone does not prove that the query produced a usable value. Handle empty output explicitly as a query/type failure; do not silently turn it into zero, an empty string, or an application verdict.


---

## Ed25519 (0x0009) — Synchronous

```solidity
// Input:  abi.encode(bytes pubkey, bytes message, bytes signature)
// Output: abi.encode(uint256 isValid)  — 1 or 0
// Gas:    2,000

bytes memory input = abi.encode(pubkey, message, signature);  // all three are type bytes
(bool ok, bytes memory result) = address(0x0009).staticcall(input);
if (!ok || result.length == 0) revert("ed25519 failed");
bool isValid = abi.decode(result, (uint256)) == 1;
```

All three fields are ABI type `bytes` (dynamic). `pubkey` is 32 bytes, `signature` is 64 bytes (R || S). See `ritual-dapp-ed25519` for complete Solidity and TypeScript examples.

---

## SECP256R1 / P-256 (0x0100) — Synchronous

```solidity
// Input:  abi.encode(bytes pubkey, bytes message, bytes signature)
// Output: abi.encode(uint256 isValid)  — 1 or 0
// Gas:    3,450

bytes memory input = abi.encode(pubkey, message, signature);  // all three are type bytes
(bool ok, bytes memory result) = address(0x0100).staticcall(input);
if (!ok || result.length == 0) revert("secp256r1 failed");
bool isValid = abi.decode(result, (uint256)) == 1;
```

All three fields are ABI type `bytes` (dynamic). `pubkey` accepts 33 bytes (compressed) or 65 bytes (uncompressed, `0x04 || x || y`). `signature` is 64 bytes (`r || s`). `message` is the raw message — the precompile hashes it with SHA-256 internally. See `ritual-dapp-passkey` for complete patterns including TxPasskey (type `0x77`) and WebAuthn flows.

---

## TX Hash (0x0830) — Synchronous

No input. Returns `bytes32` of the current transaction hash. Used internally by the Scheduler.

---

## HTTP Method Codes

| Method | Code |
|---|---|
| GET | 1 |
| POST | 2 |
| PUT | 3 |
| DELETE | 4 |
| PATCH | 5 |
| HEAD | 6 |
| OPTIONS | 7 |

---

## Long-Running Delivery Config

All long-running async precompiles (except ZK, which has its own layout, and the agent precompiles) share fields 7-15 for polling and delivery (indices shifted +1 from the 7-field base). The agent precompiles (0x080C, 0x0820) do NOT use this layout — their delivery config rides the 13-field `AgentAsyncEnvelope`'s callback* fields (`uint64` callbackGasLimit, `uint128` fee fields, `uint256` callbackValue), with the Phase 2 deadline on `phase2Ttl`:

| Index | Type | Field |
|---|---|---|
| 7 | `uint64` | pollIntervalBlocks |
| 8 | `uint64` | maxPollBlock (Phase 2 deadline offset from settlement block) |
| 9 | `string` | taskIdMarker (substituted in poll/result URLs) |
| 10 | `address` | deliveryTarget |
| 11 | `bytes4` | deliverySelector |
| 12 | `uint256` | deliveryGasLimit |
| 13 | `uint256` | deliveryMaxFeePerGas |
| 14 | `uint256` | deliveryMaxPriorityFeePerGas |
| 15 | `uint256` | deliveryValue |

All Phase 2 callbacks have signature: `function onResult(bytes32 jobId, bytes calldata result) external`
`msg.sender` is always `0x508f57AE70967Da28AE0Ab6b95532878c4D0F440` (AsyncDelivery).

---

## System Contracts

```typescript
const SYSTEM = {
  RITUAL_WALLET: '0xF04076756d8129Baec46Dc0F1c526Baec490C393',
  SCHEDULER: '0x4E0abeE2233D73E66382b45244F7459B34E1490E',
  ASYNC_JOB_TRACKER: '0xf00385449fD961925A0B125F5f30b29B682D4bFb',
  ASYNC_DELIVERY: '0x508f57AE70967Da28AE0Ab6b95532878c4D0F440',
  TEE_SERVICE_REGISTRY: '0xf4495DC72143D44A93AB0ecE4d6D63a216b27839',
  SECRETS_ACCESS_CONTROL: '0x0cEae62e2082829226eF5821Bb662483Db17A71F',
  MODEL_PRICING_REGISTRY: '0xd190Aa03c401ef5CEcE00927b522974c0f330b97',
} as const;
```

## Capability Enum

| Capability | Value | Precompile |
|---|---|---|
| HTTP_CALL | 0 | 0x0801 |
| LLM | 1 | 0x0802 |
| WORMHOLE_QUERY | 2 | — |
| STREAMING | 3 | SSE relay |
| VLLM_PROXY | 4 | vLLM proxy |
| ZK_CALL | 5 | 0x0806 |
| DKMS | 6 | 0x081B |
| IMAGE_CALL | 7 | 0x0818 |
| AUDIO_CALL | 8 | 0x0819 |
| VIDEO_CALL | 9 | 0x081A |
| FHE | 10 | 0x0807 |

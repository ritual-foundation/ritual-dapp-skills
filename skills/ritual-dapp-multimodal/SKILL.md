---
name: ritual-dapp-multimodal
description: Image, audio, and video generation for Ritual dApps. Use when building dApps with AI multimodal creation capabilities.
---

# Multimodal Generation — Ritual dApp Patterns

## Overview

Ritual Chain provides three multimodal generation precompiles — Image (`0x0818`), Audio (`0x0819`), and Video (`0x081A`) — that enable on-chain AI multimodal creation. Each follows an async two-phase model: Phase 1 submits the generation request and returns a task ID; Phase 2 delivers the generated output URI and metadata via callback. Generated content is stored externally (HuggingFace, GCS) with content hashes verified on-chain.

**Precompile addresses**:
| Modality | Address |
|----------|---------|
| Image | `0x0000000000000000000000000000000000000818` |
| Audio | `0x0000000000000000000000000000000000000819` |
| Video | `0x000000000000000000000000000000000000081A` |

**Chain ID**: 1979 (Ritual Chain)
**Transaction type**: Async two-phase (submit → generate → callback)

### How It Works

```
Phase 1: Submit
┌──────────┐   .call()        ┌──────────────┐     queue job      ┌─────────────┐
│  User Tx │ ───────────────▶ │  Precompile  │ ────────────────▶  │  AI Model   │
│          │                  │  0x0818/19/1A │                   │  (in TEE)   │
└──────────┘                  └──────────────┘                    └─────────────┘
     │                              │                                    │
     │  taskId returned             │  executor generates content          │
     │◀─────────────────────────────│                                    │

Phase 2: Deliver
┌─────────────┐   callback     ┌──────────────────┐
│  Executor   │ ─────────────▶ │  Consumer        │
│             │  URI + hash    │  .onMediaReady() │
└─────────────┘                └──────────────────┘
```

---

## 1. Submitting Multimodal Requests via Raw `encodeAbiParameters`

Use raw `encodeAbiParameters` from viem to build multimodal precompile inputs. The encoded bytes are sent via `.call()` from your Solidity contract; the TypeScript side only needs to prepare the calldata.

### Image Generation

```typescript
import {
  createPublicClient, createWalletClient, defineChain, http,
  encodeAbiParameters, parseEther,
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

const RITUAL_WALLET = '0x532F0dF0896F353d8C3DD8cc134e8129DA2a3948' as const;
const IMAGE_PRECOMPILE = '0x0000000000000000000000000000000000000818' as const;

// Deposit to RitualWallet for fees
// Recommended minimum: 5000 blocks (~29 minutes at Ritual's ~350ms conservative block-time baseline).
// For development, 100_000 blocks (~9.7 hours) avoids lock-expiry during iteration.
await walletClient.writeContract({
  address: RITUAL_WALLET,
  abi: [{ name: 'deposit', type: 'function', stateMutability: 'payable',
    inputs: [{ name: 'lockDuration', type: 'uint256' }], outputs: [] }] as const,
  functionName: 'deposit',
  args: [100_000n],   // 100k blocks ≈ 9.7 hours. Use large values for development — lock only extends, never shortens.
  value: parseEther('0.15'),  // ~0.15 RITUAL per IMAGE request
});

// Submit image generation via your consumer contract
const hash = await walletClient.writeContract({
  address: consumerContractAddress,
  abi: mediaConsumerAbi,
  functionName: 'requestImage',
  args: [
    executorAddress,       // executor
    60n,                   // ttl
    'A mystical forest at sunset, oil painting style',
    'black-forest-labs/FLUX.2-klein-4B',
    1024,                  // width
    1024,                  // height
    ['gcs', 'images/model', 'GCS_CREDS'], // outputStorageRef
    encryptedSecrets,      // encrypted storage credentials
  ],
  gas: 800_000n,
});

console.log('Image generation submitted:', hash);
```

### Audio Generation

```typescript
const hash = await walletClient.writeContract({
  address: consumerContractAddress,
  abi: mediaConsumerAbi,
  functionName: 'requestAudio',
  args: [
    executorAddress,
    120n,                  // ttl
    'A calm ambient piano melody, lo-fi beats',
    'LiquidAI/LFM2.5-Audio-1.5B',
    10_000,                // maxDurationMs
    ['gcs', 'images/model', 'GCS_CREDS'], // outputStorageRef
    encryptedSecrets,      // encrypted storage credentials
  ],
  gas: 800_000n,
});
```

### Video Generation

```typescript
const hash = await walletClient.writeContract({
  address: consumerContractAddress,
  abi: mediaConsumerAbi,
  functionName: 'requestVideo',
  args: [
    executorAddress,
    300n,                  // ttl — video gen takes longer
    'A serene lake with mountains reflected in still water, cinematic',
    'Wan-AI/Wan2.2-T2V-A14B-Diffusers',
    1280,                  // width
    720,                   // height
    3_000,                 // durationMs (see “Wan T2V / cached DiT” below)
    ['gcs', 'images/model', 'GCS_CREDS'], // outputStorageRef
    encryptedSecrets,      // encrypted storage credentials
  ],
  gas: 800_000n,
});
```

### Wan T2V / cached DiT (duration and resolution)

The video backend pre-warms a **cached DiT** (diffusion transformer) for a single fixed shape. Requesting a different duration or resolution can invalidate that cache, causing the job to hang or fail on-chain settlement.

**What this means for your dApp:**

- The `width`, `height`, and `durationMs` parameters are part of the ABI but are **currently clamped by the proxy** to match the backend's cached shape. Regardless of what values you pass, the backend will produce video at its fixed shape.
- The response `duration_ms` reflects what the backend **actually produced**, not what you requested.

---

## 2. Low-Level Encoding/Decoding with viem

### Encoding a MultiModal Request

```typescript
import { encodeAbiParameters, type Address, type Hex } from 'viem';

const executor: Address = '0x...';

const textInputData = new TextEncoder().encode(
  'Cyberpunk cityscape at night, neon reflections'
);

// IMPORTANT: Use tuple types for inputs (ModalInput[]) and output (OutputConfig).
// Flat scalar encoding (20 fields) will fail at the executor's decoder.
const encoded = encodeAbiParameters(
  [
    { type: 'address' },   // executor
    { type: 'bytes[]' },   // encryptedSecrets
    { type: 'uint256' },   // ttl
    { type: 'bytes[]' },   // secretSignatures
    { type: 'bytes' },     // userPublicKey
    { type: 'uint64' },    // pollIntervalBlocks
    { type: 'uint64' },    // maxPollBlock
    { type: 'string' },    // taskIdMarker
    { type: 'address' },   // deliveryTarget
    { type: 'bytes4' },    // deliverySelector
    { type: 'uint256' },   // deliveryGasLimit
    { type: 'uint256' },   // deliveryMaxFeePerGas
    { type: 'uint256' },   // deliveryMaxPriorityFeePerGas
    { type: 'uint256' },   // deliveryValue
    { type: 'string' },    // model
    { type: 'tuple[]', components: [                          // ModalInput[]
      { name: 'inputType', type: 'uint8' },
      { name: 'data', type: 'bytes' },
      { name: 'uri', type: 'string' },
      { name: 'contentHash', type: 'bytes32' },
      { name: 'param1', type: 'uint32' },
      { name: 'param2', type: 'uint32' },
      { name: 'encrypted', type: 'bool' },
    ]},
    { type: 'tuple', components: [                            // OutputConfig
      { name: 'outputType', type: 'uint8' },
      { name: 'maxParam1', type: 'uint32' },
      { name: 'maxParam2', type: 'uint32' },
      { name: 'maxParam3', type: 'uint32' },
      { name: 'encryptOutput', type: 'bool' },
      { name: 'numInferenceSteps', type: 'uint16' },
      { name: 'guidanceScaleX100', type: 'uint16' },
      { name: 'seed', type: 'uint32' },
      { name: 'fps', type: 'uint8' },
      { name: 'negativePrompt', type: 'string' },
    ]},
    { type: 'tuple', components: [{ type: 'string' }, { type: 'string' }, { type: 'string' }] }, // outputStorageRef
    { type: 'bytes[]' },   // encryptedSecrets
  ],
  [
    executor,
    [],                          // no encrypted secrets
    60n,                         // ttl
    [],                          // no signatures
    '0x',                        // no private output
    5n,                          // pollIntervalBlocks
    1000n,                       // maxPollBlock
    'IMAGE_TASK_ID',             // taskIdMarker — keep non-empty
    consumerAddress,             // deliveryTarget
    callbackSelector,            // deliverySelector — selector for your callback signature (bytes32,bytes)
    500_000n,                    // deliveryGasLimit
    1_000_000_000n,              // deliveryMaxFeePerGas
    100_000_000n,                // deliveryMaxPriorityFeePerGas
    0n,                          // deliveryValue
    'black-forest-labs/FLUX.2-klein-4B',
    [{ inputType: 0, data: `0x${Buffer.from(textInputData).toString('hex')}`, uri: '',
       contentHash: '0x0000000000000000000000000000000000000000000000000000000000000000',
       param1: 0, param2: 0, encrypted: false }],
    { outputType: 1, maxParam1: 1024, maxParam2: 1024, maxParam3: 0,
      encryptOutput: false, numInferenceSteps: 0, guidanceScaleX100: 0,
      seed: 0, fps: 0, negativePrompt: '' },
    outputStorageRef,            // StorageRef tuple: ['gcs', 'images/model', 'GCS_CREDS']
    encryptedSecrets,            // ECIES-encrypted JSON containing GCS_CREDS
  ]
);
```

### Decoding Phase 1 Response

Phase 1 returns a task ID that can be used to poll for status.

```typescript
import { decodeAbiParameters } from 'viem';

const [taskId] = decodeAbiParameters(
  [{ type: 'string' }],
  resultHex
);
console.log('Task ID:', taskId);
```

### Decoding Phase 2 Responses

Each modality has a specific response ABI. Use `decodeAbiParameters` with the matching tuple.

```typescript
import { decodeAbiParameters, type Hex } from 'viem';

// Image response
const imageFields = decodeAbiParameters(
  [
    { type: 'bool' },    // hasError
    { type: 'bytes' },   // completionData
    { type: 'string' },  // outputUri
    { type: 'bytes32' }, // outputContentHash
    { type: 'bool' },    // outputEncrypted
    { type: 'uint32' },  // outputSizeBytes
    { type: 'uint32' },  // outputWidth
    { type: 'uint32' },  // outputHeight
    { type: 'string' },  // errorMessage
  ],
  responseHex
);
const [hasError, , outputUri, contentHash, encrypted, sizeBytes, width, height, errorMsg] = imageFields;
console.log('Image URI:', outputUri);
console.log('Dimensions:', width, '×', height);
console.log('Size:', sizeBytes, 'bytes');
console.log('Content hash:', contentHash);
console.log('Encrypted:', encrypted);

// Audio response
const audioFields = decodeAbiParameters(
  [
    { type: 'bool' }, { type: 'bytes' }, { type: 'string' },
    { type: 'bytes32' }, { type: 'bool' }, { type: 'uint32' },
    { type: 'uint32' },  // outputDurationMs
    { type: 'string' },
  ],
  audioResponseHex
);
console.log('Audio URI:', audioFields[2]);
console.log('Duration:', audioFields[6], 'ms');

// Video response
const videoFields = decodeAbiParameters(
  [
    { type: 'bool' }, { type: 'bytes' }, { type: 'string' },
    { type: 'bytes32' }, { type: 'bool' }, { type: 'uint64' },
    { type: 'uint32' }, { type: 'uint32' },
    { type: 'uint32' },  // outputDurationMs
    { type: 'string' },
  ],
  videoResponseHex
);
console.log('Video URI:', videoFields[2]);
console.log('Dimensions:', videoFields[6], '×', videoFields[7]);
console.log('Duration:', videoFields[8], 'ms');
```

---

## 3. Request ABI Layout

```
MULTIMODAL_REQUEST_ABI (extends EXECUTOR_REQUEST_ABI):
  pollIntervalBlocks        uint64    — blocks between status polls
  maxPollBlock              uint64    — max block to poll until
  taskIdMarker              string    — marker for task ID extraction
  deliveryTarget            address   — contract to receive callback
  deliverySelector          bytes4    — callback function selector
  deliveryGasLimit          uint256   — gas limit for callback
  deliveryMaxFeePerGas      uint256   — max fee for callback
  deliveryMaxPriorityFeePerGas uint256 — priority fee for callback
  deliveryValue             uint256   — RITUAL value for callback

  model                     string    — model identifier
  inputs                    tuple[]   — input array:
    inputType               uint8     — 0=TEXT, 1=IMAGE, 2=AUDIO, 3=VIDEO
    data                    bytes     — raw input data
    uri                     string    — URI reference for input
    contentHash             bytes32   — SHA-256 of input data
    param1                  uint32    — modality-specific param
    param2                  uint32    — modality-specific param
    encrypted               bool      — whether input is encrypted

  output                    tuple     — output config (10 fields):
    outputType              uint8     — 0=TEXT, 1=IMAGE, 2=AUDIO, 3=VIDEO
    maxParam1               uint32    — image: width, audio: maxDurationMs, video: width
    maxParam2               uint32    — image: height, video: height
    maxParam3               uint32    — video: durationMs
    encryptOutput           bool      — encrypt the generated output
    numInferenceSteps       uint16    — diffusion steps (0 = model default)
    guidanceScaleX100       uint16    — guidance scale x 100 (0 = model default)
    seed                    uint32    — RNG seed (0 = random)
    fps                     uint8     — frames per second (video only)
    negativePrompt          string    — negative prompt text

  outputStorageRef          (string,string,string) — StorageRef: (platform, path, keyRef). See `ritual-dapp-da`.
  encryptedSecrets          bytes[]   — ECIES-encrypted JSON with storage credentials keyed by keyRef
```

### Response ABI by Modality

**Image Response**:
```
hasError            bool      — true if generation failed
completionData      bytes     — raw completion data
outputUri           string    — URI to generated image
outputContentHash   bytes32   — SHA-256 of output file
outputEncrypted     bool      — whether output is encrypted
outputSizeBytes     uint32    — file size in bytes
outputWidth         uint32    — image width in pixels
outputHeight        uint32    — image height in pixels
errorMessage        string    — error details (empty on success)
```

**Audio Response**:
```
hasError            bool
completionData      bytes
outputUri           string    — URI to generated audio
outputContentHash   bytes32
outputEncrypted     bool
outputSizeBytes     uint32
outputDurationMs    uint32    — audio duration in milliseconds
errorMessage        string
```

**Video Response**:
```
hasError            bool
completionData      bytes
outputUri           string    — URI to generated video
outputContentHash   bytes32
outputEncrypted     bool
outputSizeBytes     uint64    — file size (uint64 for large videos)
outputWidth         uint32
outputHeight        uint32
outputDurationMs    uint32    — video duration in milliseconds
errorMessage        string
```

---

## 4. Storage Configuration

Generated content is stored on external providers via a `StorageRef` tuple in the request ABI. You provide storage credentials inside `encryptedSecrets`, encrypted to the executor's ECIES public key.

All three providers — GCS, HuggingFace, and Pinata — work for image, audio, and video. See `ritual-dapp-da` for full StorageRef format, credential encoding, and debugging.

> **⚠ CRITICAL — ECIES nonce length**: You MUST set `ECIES_CONFIG.symmetricNonceLength = 12` before calling `encrypt()`. The default is 16. Mismatched nonce length means the executor cannot decrypt your storage credentials — the callback never arrives.
>
> **Callback never arrived? Checklist:**
> 1. Is `outputStorageRef` non-empty? `['', '', '']` means no storage — the executor cannot upload output.
> 2. Does `keyRef` in your StorageRef match a key in the decrypted `encryptedSecrets` JSON?
> 3. Is `ECIES_CONFIG.symmetricNonceLength` = 12? (wrong nonce → decryption failure)
> 4. Is the RitualWallet lock still active? `lockUntil` must be > `current block + ttl`. Locks expire fast — 5,000 blocks ~ 29 min on Ritual's ~350ms baseline. Use 100,000+ for development. See `ritual-dapp-block-time` for conversion formulas and measurement preflight.
> 5. Is the precompile input using **tuple-based encoding** (with `ModalInput[]`, `OutputConfig`, and `StorageRef` tuples)? Flat scalar encoding will fail at the executor's decoder.

### Storage Credentials

| Platform | `platform` value | `keyRef` credential format | Notes |
|----------|------------------|---------------------------|-------|
| GCS | `'gcs'` | JSON: `{"service_account_json": "<SA JSON>", "bucket": "<bucket>"}` | Use full SA key JSON, not a path or OAuth token |
| HuggingFace | `'hf'` | Plain HF access token string | Path format: `org/repo/file` |
| Pinata (IPFS) | `'pinata'` | JSON: `{"jwt": "<JWT>", "gateway_url": "<gateway URL>"}` | Returns CID after upload |

```typescript
import { encrypt, ECIES_CONFIG } from 'eciesjs';

ECIES_CONFIG.symmetricNonceLength = 12;  // MUST be set before any encrypt()

// outputStorageRef: (platform, path, keyRef)
const outputStorageRef = ['gcs', `images/${model}`, 'GCS_CREDS'];

// encryptedSecrets: JSON with credential keyed by keyRef
const secretsJson = JSON.stringify({
  GCS_CREDS: JSON.stringify({
    service_account_json: process.env.GCS_SA_KEY!,
    bucket: process.env.GCS_BUCKET!,
  }),
});

const encryptedSecrets = `0x${encrypt(
  executorPublicKey.slice(2),
  Buffer.from(secretsJson),
).toString('hex')}` as `0x${string}`;
```

### Executor Discovery

Before creating `encryptedSecrets`, fetch the executor's public key from the TEEServiceRegistry:

```typescript
import { createPublicClient, http } from 'viem';

const TEE_SERVICE_REGISTRY = '0x9644e8562cE0Fe12b4deeC4163c064A8862Bf47F' as const;
const IMAGE_CAPABILITY = 7;  // Capability enum: 7 = IMAGE_CALL

// Use the (uint8, bool) overload — capability enum + active-only flag
const services = await publicClient.readContract({
  address: TEE_SERVICE_REGISTRY,
  abi: [{
    name: 'getServicesByCapability',
    type: 'function',
    stateMutability: 'view',
    inputs: [{ name: 'capability', type: 'uint8' }, { name: 'activeOnly', type: 'bool' }],
    outputs: [{ type: 'tuple[]', components: [
      { name: 'teeAddress', type: 'address' },
      { name: 'publicKey', type: 'bytes' },
      // ... other fields
    ]}],
  }] as const,
  functionName: 'getServicesByCapability',
  args: [IMAGE_CAPABILITY, true],
});

const executor = services[0];
const executorAddress = executor.teeAddress;
// executor.publicKey is already a 0x-prefixed hex string from viem — use it directly.
// Do NOT use Buffer.from(hexString) which interprets hex chars as UTF-8 and garbles the key.
const executorPublicKey = executor.publicKey as `0x${string}`;

// You don't need the executor's endpoint — routing is handled internally.
// Only teeAddress (for ABI) and publicKey (for secret encryption) are needed.
```

### Models

| Modality | Model | outputType |
|----------|-------|------------|
| Image | `black-forest-labs/FLUX.2-klein-4B` | 1 |
| Audio | `LiquidAI/LFM2.5-Audio-1.5B` | 2 |
| Video | `Wan-AI/Wan2.2-T2V-A14B-Diffusers` | 3 |

The current chain supports exactly these three models. Hard-code these model IDs.

### Output URI Handling

The executor uploads generated content and returns a platform-specific URI (`gs://`, `hf://`, or an IPFS CID). For GCS, browsers **cannot** fetch `gs://` directly — convert to HTTPS before displaying:

```typescript
function gsUriToHttps(uri: string): string {
  // gs://bucket-name/path/to/file.png
  // → https://storage.googleapis.com/bucket-name/path/to/file.png
  if (uri.startsWith('gs://')) {
    return uri.replace('gs://', 'https://storage.googleapis.com/');
  }
  return uri;
}

// Usage in React:
const displayUri = gsUriToHttps(imageUri);
// <img src={displayUri} />
```

### Binding Credentials to Your Contract (SecretsAccessControl)

> **⚠ Security Warning — Credentials are replayable without access control**: `encryptedSecrets` bytes are public on-chain. Anyone can copy them from your transaction and reuse them in a different contract to upload to *your* storage bucket. The executor does not verify the caller by default.
>
> To prevent this, use `SecretsAccessControl` (`0xf9BF1BC8A3e79B9EBeD0fa2Db70D0513fecE32FD`) to bind the encrypted credentials to your specific contract address. The executor will then verify the delegation before decrypting. See `ritual-dapp-secrets` for the full delegation pattern.

```typescript
import { keccak256, toBytes } from 'viem';

const SECRETS_AC = '0xf9BF1BC8A3e79B9EBeD0fa2Db70D0513fecE32FD' as const;

// After encrypting storage credentials, compute the hash
const secretsHash = keccak256(toBytes(encryptedSecrets));

// Grant your consumer contract permission to use these credentials
// expiresAt is a block number — set to current block + some duration
const currentBlock = await publicClient.getBlockNumber();
const expiresAt = currentBlock + 50_000n; // ~4.9 hours at ~350ms/block
const emptyPolicy = {
  allowedDestinations: [],
  allowedMethods: [],
  allowedPaths: [],
  allowedQueryParams: [],
  allowedHeaders: [],
  secretLocation: '',
  bodyFormat: '',
};

await walletClient.writeContract({
  address: SECRETS_AC,
  abi: [{
    name: 'grantAccess',
    type: 'function',
    stateMutability: 'nonpayable',
    inputs: [
      { name: 'delegate', type: 'address' },
      { name: 'secretsHash', type: 'bytes32' },
      { name: 'expiresAt', type: 'uint256' },
      { name: 'policy', type: 'tuple', components: [
        { name: 'allowedDestinations', type: 'string[]' },
        { name: 'allowedMethods', type: 'string[]' },
        { name: 'allowedPaths', type: 'string[]' },
        { name: 'allowedQueryParams', type: 'string[]' },
        { name: 'allowedHeaders', type: 'string[]' },
        { name: 'secretLocation', type: 'string' },
        { name: 'bodyFormat', type: 'string' },
      ]},
    ],
    outputs: [],
  }] as const,
  functionName: 'grantAccess',
  args: [consumerContractAddress, secretsHash, expiresAt, emptyPolicy],
});

// Now only consumerContractAddress can use these credentials
// The executor verifies checkAccess(you, consumerContract, secretsHash) before decrypting
```

To revoke access (e.g., rotate credentials):

```typescript
await walletClient.writeContract({
  address: SECRETS_AC,
  abi: [{
    name: 'revokeAccess',
    type: 'function',
    stateMutability: 'nonpayable',
    inputs: [
      { name: 'delegate', type: 'address' },
      { name: 'secretsHash', type: 'bytes32' },
    ],
    outputs: [],
  }] as const,
  functionName: 'revokeAccess',
  args: [consumerContractAddress, secretsHash],
});
```

See the `ritual-dapp-secrets` skill for the full delegation pattern including Solidity-side verification.

### Storage Flow

```
1. Fetch executor address + public key from TEEServiceRegistry (capability 7)
2. Build outputStorageRef: ('gcs', 'images/<model>', 'GCS_CREDS')
3. Build secretsJson: {"GCS_CREDS": "{"service_account_json":..., "bucket":...}"}
4. Set ECIES_CONFIG.symmetricNonceLength = 12
5. ECIES-encrypt secretsJson with executor's public key → encryptedSecrets
6. secretsHash = keccak256(encryptedSecrets)
7. SecretsAccessControl.grantAccess(consumerContract, secretsHash, expiresAt, policy)
8. Include outputStorageRef + encryptedSecrets in request ABI
9. TEE executor verifies checkAccess(you, consumerContract, secretsHash)
10. Executor decrypts credentials, generates content, uploads to storage → URI
11. Callback delivers URI to contract
12. Convert gs:// to https:// before displaying in browser (GCS only)
```

---

## 5. Solidity: MediaConsumer Contract

A contract handling image, audio, and video generation with callbacks.

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

interface IRitualWallet {
    function deposit(uint256 lockDuration) external payable;
}

contract MediaConsumer {
    address constant IMAGE_PRECOMPILE = 0x0000000000000000000000000000000000000818;
    address constant AUDIO_PRECOMPILE = 0x0000000000000000000000000000000000000819;
    address constant VIDEO_PRECOMPILE = 0x000000000000000000000000000000000000081A;
    address constant RITUAL_WALLET    = 0x532F0dF0896F353d8C3DD8cc134e8129DA2a3948;
    address constant ASYNC_DELIVERY_SENDER = 0x5A16214fF555848411544b005f7Ac063742f39F6;
    address constant TX_HASH_PRECOMPILE = address(0x0830);

    modifier onlyAsyncSystem() {
        require(msg.sender == ASYNC_DELIVERY_SENDER, "unauthorized callback");
        _;
    }

    /// @dev Input type for multimodal precompiles (ModalInput tuple)
    struct ModalInput {
        uint8 inputType;    // 0=TEXT, 1=IMAGE, 2=AUDIO, 3=VIDEO
        bytes data;
        string uri;
        bytes32 contentHash;
        uint32 param1;
        uint32 param2;
        bool encrypted;
    }

    /// @dev Output configuration for multimodal precompiles (OutputConfig tuple)
    struct OutputConfig {
        uint8 outputType;           // 1=IMAGE, 2=AUDIO, 3=VIDEO
        uint32 maxParam1;           // image: width, audio: maxDurationMs, video: width
        uint32 maxParam2;           // image: height, video: height
        uint32 maxParam3;           // video: durationMs
        bool encryptOutput;
        uint16 numInferenceSteps;
        uint16 guidanceScaleX100;
        uint32 seed;
        uint8 fps;
        string negativePrompt;
    }

    struct MediaResult {
        string uri;
        bytes32 contentHash;
        uint256 timestamp;
        bool encrypted;
    }

    mapping(bytes32 => MediaResult) public results;
    mapping(bytes32 => bool) public pendingJobs;
    bytes32[] public resultIds;

    event ImageRequested(bytes32 indexed taskId);
    event AudioRequested(bytes32 indexed taskId);
    event VideoRequested(bytes32 indexed taskId);
    event MediaReady(bytes32 indexed taskId, string uri);
    event MediaFailed(bytes32 indexed taskId, string error);

    function depositForFees() external payable {
        // Recommended minimum: 5000 blocks (~29 min at ~350ms/block).
        // Use 100_000+ in development to avoid lock-expiry during iteration.
        IRitualWallet(RITUAL_WALLET).deposit{value: msg.value}(100_000);
    }

    /// @notice Request image generation
    /// @dev Each sender can only have ONE async tx in flight at a time.
    ///      Two concurrent image requests MUST come from different EOAs.
    function requestImage(
        address executor,
        uint256 ttl,
        string calldata prompt,
        string calldata model,
        uint32 width,
        uint32 height,
        StorageRef calldata outputStorageRef,
        bytes[] calldata encryptedSecrets
    ) external {
        bytes32 jobId = _trackCurrentJob();
        bytes memory input = _buildMultiModalInput(
            executor, ttl, prompt, model,
            width, height, 0,  // no duration for images
            outputStorageRef,
            encryptedSecrets,
            "IMAGE_TASK_ID",
            this.onImageReady.selector,
            1  // outputType: IMAGE
        );

        // Use .call() not staticcall — async precompiles require a state-mutating call
        (bool ok,) = IMAGE_PRECOMPILE.call(input);
        require(ok, "Image precompile call failed");

        emit ImageRequested(jobId);
    }

    /// @notice Request audio generation
    /// @dev Same async TX constraints as requestImage — see that function's docs.
    function requestAudio(
        address executor,
        uint256 ttl,
        string calldata prompt,
        string calldata model,
        uint32 maxDurationMs,
        StorageRef calldata outputStorageRef,
        bytes[] calldata encryptedSecrets
    ) external {
        bytes32 jobId = _trackCurrentJob();
        bytes memory input = _buildMultiModalInput(
            executor, ttl, prompt, model,
            maxDurationMs, 0, 0,
            outputStorageRef,
            encryptedSecrets,
            "AUDIO_TASK_ID",
            this.onAudioReady.selector,
            2  // outputType: AUDIO
        );

        (bool ok,) = AUDIO_PRECOMPILE.call(input);
        require(ok, "Audio precompile call failed");

        emit AudioRequested(jobId);
    }

    /// @notice Request video generation
    /// @dev Same async TX constraints as requestImage — see that function's docs.
    function requestVideo(
        address executor,
        uint256 ttl,
        string calldata prompt,
        string calldata model,
        uint32 width,
        uint32 height,
        uint32 durationMs,
        StorageRef calldata outputStorageRef,
        bytes[] calldata encryptedSecrets
    ) external {
        bytes32 jobId = _trackCurrentJob();
        bytes memory input = _buildMultiModalInput(
            executor, ttl, prompt, model,
            width, height, durationMs,
            outputStorageRef,
            encryptedSecrets,
            "VIDEO_TASK_ID",
            this.onVideoReady.selector,
            3  // outputType: VIDEO
        );

        (bool ok,) = VIDEO_PRECOMPILE.call(input);
        require(ok, "Video precompile call failed");

        emit VideoRequested(jobId);
    }

    /// @notice Phase 2 callback for image results
    /// @dev Callback signature must be (bytes32 jobId, bytes calldata responseData).
    ///      Function name is arbitrary as long as deliverySelector matches.
    ///      The AsyncDelivery system calls: target.call(abi.encodeWithSelector(selector, jobId, result))
    ///      Both parameters are required. Registering a single-param selector will never match.
    function onImageReady(bytes32 jobId, bytes calldata responseData) external onlyAsyncSystem {
        _consumePendingJob(jobId);
        (
            bool hasError,
            ,
            string memory outputUri,
            bytes32 contentHash,
            bool encrypted,
            ,
            ,
            ,
            string memory errorMsg
        ) = abi.decode(
            responseData,
            (bool, bytes, string, bytes32, bool, uint32, uint32, uint32, string)
        );

        bytes32 taskId = jobId;

        if (hasError) {
            emit MediaFailed(taskId, errorMsg);
            return;
        }

        results[taskId] = MediaResult({
            uri: outputUri,
            contentHash: contentHash,
            timestamp: block.timestamp,
            encrypted: encrypted
        });
        resultIds.push(taskId);

        emit MediaReady(taskId, outputUri);
    }

    /// @notice Phase 2 callback for audio results
    function onAudioReady(bytes32 jobId, bytes calldata responseData) external onlyAsyncSystem {
        _consumePendingJob(jobId);
        (
            bool hasError,
            ,
            string memory outputUri,
            bytes32 contentHash,
            bool encrypted,
            ,
            ,
            string memory errorMsg
        ) = abi.decode(
            responseData,
            (bool, bytes, string, bytes32, bool, uint32, uint32, string)
        );

        bytes32 taskId = jobId;

        if (hasError) {
            emit MediaFailed(taskId, errorMsg);
            return;
        }

        results[taskId] = MediaResult({
            uri: outputUri,
            contentHash: contentHash,
            timestamp: block.timestamp,
            encrypted: encrypted
        });
        resultIds.push(taskId);

        emit MediaReady(taskId, outputUri);
    }

    /// @notice Phase 2 callback for video results
    function onVideoReady(bytes32 jobId, bytes calldata responseData) external onlyAsyncSystem {
        _consumePendingJob(jobId);
        (
            bool hasError,
            ,
            string memory outputUri,
            bytes32 contentHash,
            bool encrypted,
            ,
            ,
            ,
            ,
            string memory errorMsg
        ) = abi.decode(
            responseData,
            (bool, bytes, string, bytes32, bool, uint64, uint32, uint32, uint32, string)
        );

        bytes32 taskId = jobId;

        if (hasError) {
            emit MediaFailed(taskId, errorMsg);
            return;
        }

        results[taskId] = MediaResult({
            uri: outputUri,
            contentHash: contentHash,
            timestamp: block.timestamp,
            encrypted: encrypted
        });
        resultIds.push(taskId);

        emit MediaReady(taskId, outputUri);
    }

    function _trackCurrentJob() private returns (bytes32 jobId) {
        (bool ok, bytes memory output) = TX_HASH_PRECOMPILE.staticcall("");
        require(ok && output.length == 32, "tx hash unavailable");
        jobId = abi.decode(output, (bytes32));
        require(!pendingJobs[jobId], "job already pending");
        pendingJobs[jobId] = true;
    }

    function _consumePendingJob(bytes32 jobId) private {
        require(pendingJobs[jobId], "unknown or fulfilled job");
        delete pendingJobs[jobId];
    }

    /// @dev Builds the ABI-encoded input for multimodal precompiles.
    ///      The executor expects exactly 18 ABI fields where fields 15-17 are
    ///      ModalInput[] (tuple[]), OutputConfig (tuple), and StorageRef (tuple).
    function _buildMultiModalInput(
        address executor,
        uint256 ttl,
        string calldata prompt,
        string calldata model,
        uint32 param1,
        uint32 param2,
        uint32 param3,
        StorageRef calldata outputStorageRef,
        bytes[] calldata encryptedSecrets,
        string memory taskMarker,
        bytes4 callbackSelector,
        uint8 outputType
    ) private view returns (bytes memory) {
        ModalInput[] memory inputs = new ModalInput[](1);
        inputs[0] = ModalInput({
            inputType: 0,       // TEXT
            data: bytes(prompt),
            uri: "",
            contentHash: bytes32(0),
            param1: 0,
            param2: 0,
            encrypted: false
        });

        OutputConfig memory output = OutputConfig({
            outputType: outputType,
            maxParam1: param1,
            maxParam2: param2,
            maxParam3: param3,
            encryptOutput: false,
            numInferenceSteps: 0,
            guidanceScaleX100: 0,
            seed: 0,
            fps: 0,
            negativePrompt: ""
        });

        return abi.encode(
            executor,
            encryptedSecrets,   // ECIES-encrypted JSON with storage creds
            ttl,
            new bytes[](0),     // secretSignatures
            bytes(""),          // userPublicKey
            uint64(5),          // pollIntervalBlocks
            uint64(1000),       // maxPollBlock
            taskMarker,         // taskIdMarker — per-modality, must NOT be empty
            address(this),      // deliveryTarget
            callbackSelector,   // per-modality callback selector
            uint256(500_000),   // deliveryGasLimit
            uint256(1e9),       // deliveryMaxFeePerGas
            uint256(1e8),       // deliveryMaxPriorityFeePerGas
            uint256(0),         // deliveryValue
            model,
            inputs,             // ModalInput[] — tuple array, NOT flat bytes
            output,             // OutputConfig — tuple, NOT flat scalars
            outputStorageRef    // StorageRef: (platform, path, keyRef)
        );
    }

    function getResultCount() external view returns (uint256) {
        return resultIds.length;
    }
}
```

---

## 6. Async Constraints

> **Read this section before writing any contract that calls a multimodal precompile.** These constraints are specific to Ritual's async precompile model and differ from normal Solidity development.

### Two-phase async model

Multimodal precompiles are two-phase async: your submit transaction is mined normally (Phase 1), and the result is delivered via a callback in a separate transaction (Phase 2). State writes in the submit function persist normally — you can set mappings, increment counters, and emit events alongside the precompile call.

```solidity
function requestImage(uint256 id, bytes calldata encPayment) external {
    jobOwner[id] = msg.sender;
    jobPending[id] = true;
    emit ImageRequested(id, msg.sender);
    (bool ok, ) = IMAGE_PRECOMPILE.call(input);
    if (!ok) revert PrecompileCallFailed();
}
```

### One async tx per sender at a time

Ritual locks a sender address while its async job is in flight. **A sender cannot submit any other transaction until the job completes (~1–5 min).** This means:

- Two `requestImage` calls cannot come from the same EOA.
- If your app needs image generation for two players, use **two different wallets**.
- The sender lock applies to the **EOA** (transaction signer), not the contract.

```typescript
// ❌ WRONG — same wallet for both requests
await playerWallet.writeContract({ functionName: 'requestImage1', ... });
await playerWallet.writeContract({ functionName: 'requestImage2', ... }); // will fail

// ✅ CORRECT — different wallets
await wallet1.writeContract({ functionName: 'requestImage1', ... });
await wallet2.writeContract({ functionName: 'requestImage2', ... }); // different sender
```

### Transactions appear to hang — that's normal

Your wallet will show the image-request tx as "pending" for 1–5 minutes. The nonce increments immediately (the original tx is consumed), but the async job runs in the background. Do not retry or replace the transaction. The result arrives via the callback when the executor finishes.

### Compiler: `via_ir = true` required for large ABI encoding

If your contract uses `abi.encode(...)` with many parameters (as in `_buildMultiModalInput`), the Solidity compiler may hit "stack too deep". Add `via_ir = true` to your `foundry.toml`:

```toml
[profile.default]
via_ir = true
```

---

## 7. Polling for Results

Multimodal generation is asynchronous. After Phase 1, poll for the task status before Phase 2 delivery.

### Polling Pattern

```typescript
import type { PublicClient } from 'viem';

async function waitForMedia(
  publicClient: PublicClient,
  txHash: `0x${string}`,
  maxWaitMs = 300_000,  // 5 minutes
  pollIntervalMs = 10_000
) {
  const startTime = Date.now();

  while (Date.now() - startTime < maxWaitMs) {
    const receipt = await publicClient.getTransactionReceipt({
      hash: txHash,
    });

    if (receipt.status === 'success') {
      const logs = receipt.logs.filter(
        (log) => log.topics[0] === '0x...' // MediaReady event topic
      );

      if (logs.length > 0) {
        return { status: 'ready', logs };
      }
    }

    await new Promise((r) => setTimeout(r, pollIntervalMs));
  }

  return { status: 'timeout' };
}
```

### Event-Based Listening

```typescript
import { parseAbiItem } from 'viem';

const unwatch = publicClient.watchEvent({
  address: consumerContractAddress,
  event: parseAbiItem('event MediaReady(bytes32 indexed taskId, string uri)'),
  onLogs: (logs) => {
    for (const log of logs) {
      console.log('Multimodal ready!', {
        taskId: log.args.taskId,
        uri: log.args.uri,
      });
    }
  },
});
```

---

## 8. Frontend: Multimodal Display Components

### useMediaGeneration Hook

```typescript
import { useState, useCallback } from 'react';
import { useAccount, usePublicClient, useWalletClient } from 'wagmi';
import type { Address, Hex } from 'viem';

type MediaType = 'image' | 'audio' | 'video';

interface MediaGenState {
  status: 'idle' | 'submitting' | 'generating' | 'ready' | 'error';
  txHash?: Hex;
  mediaUri?: string;
  mediaType?: MediaType;
  error?: string;
}

export function useMediaGeneration() {
  const [state, setState] = useState<MediaGenState>({ status: 'idle' });
  const { address } = useAccount();
  const publicClient = usePublicClient();
  const { data: walletClient } = useWalletClient();

  const generate = useCallback(
    async (params: {
      consumerContract: Address;
      mediaType: MediaType;
      prompt: string;
      model: string;
      width?: number;
      height?: number;
      durationMs?: number;
    }) => {
      if (!walletClient || !address) {
        setState({ status: 'error', error: 'Wallet not connected' });
        return;
      }

      setState({ status: 'submitting', mediaType: params.mediaType });

      try {
        const functionName = params.mediaType === 'image'
          ? 'requestImage'
          : params.mediaType === 'audio'
          ? 'requestAudio'
          : 'requestVideo';

        const hash = await walletClient.writeContract({
          address: params.consumerContract,
          abi: mediaConsumerAbi,
          functionName,
          args: [/* ... args based on media type */],
          gas: 1_000_000n,
        });

        setState((s) => ({ ...s, status: 'generating', txHash: hash }));

        // Poll for completion...
        const receipt = await publicClient!.waitForTransactionReceipt({ hash });

        if (receipt.status === 'success') {
          setState((s) => ({ ...s, status: 'generating' }));
        }
      } catch (err) {
        setState({ status: 'error', error: (err as Error).message });
      }
    },
    [walletClient, address, publicClient]
  );

  const reset = useCallback(() => setState({ status: 'idle' }), []);

  return { state, generate, reset };
}
```

### Multimodal Gallery Component

```tsx
function MediaGallery({ items }: { items: Array<{ uri: string; type: 'image' | 'audio' | 'video'; timestamp: number }> }) {
  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fill, minmax(280, 1fr))',
      gap: 16,
      padding: 16,
    }}>
      {items.map((item, i) => (
        <div key={i} style={{
          background: '#1a1a2e',
          borderRadius: 12,
          overflow: 'hidden',
        }}>
          {item.type === 'image' && (
            <img
              src={item.uri}
              alt={`Generated #${i}`}
              style={{ width: '100%', height: 280, objectFit: 'cover' }}
              loading="lazy"
            />
          )}

          {item.type === 'audio' && (
            <div style={{ padding: 16 }}>
              <audio controls src={item.uri} style={{ width: '100%' }} />
            </div>
          )}

          {item.type === 'video' && (
            <video
              src={item.uri}
              controls
              style={{ width: '100%', height: 280, objectFit: 'cover' }}
            />
          )}

          <div style={{ padding: 12, fontSize: 12, color: '#888' }}>
            {new Date(item.timestamp * 1000).toLocaleString()}
          </div>
        </div>
      ))}
    </div>
  );
}
```

### Generation Form

```tsx
function MediaGenerationForm() {
  const [prompt, setPrompt] = useState('');
  const [mediaType, setMediaType] = useState<'image' | 'audio' | 'video'>('image');
  const { state, generate, reset } = useMediaGeneration();

  const isActive = state.status === 'submitting' || state.status === 'generating';

  return (
    <div style={{ maxWidth: 640, margin: '0 auto', fontFamily: 'system-ui' }}>
      <h2>AI Multimodal Generator</h2>

      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        {(['image', 'audio', 'video'] as const).map((type) => (
          <button
            key={type}
            onClick={() => setMediaType(type)}
            style={{
              padding: '8px 16px',
              borderRadius: 8,
              background: mediaType === type ? '#6c63ff' : '#2a2a3e',
              color: '#fff',
              border: 'none',
              cursor: 'pointer',
            }}
          >
            {type.charAt(0).toUpperCase() + type.slice(1)}
          </button>
        ))}
      </div>

      <textarea
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        placeholder={`Describe the ${mediaType} to generate...`}
        rows={3}
        disabled={isActive}
        style={{ width: '100%', padding: 12, borderRadius: 8 }}
      />

      <button
        onClick={() => generate({
          consumerContract: '0x...' as `0x${string}`,
          mediaType,
          prompt,
          model: mediaType === 'image'
            ? 'black-forest-labs/FLUX.2-klein-4B'
            : mediaType === 'audio'
            ? 'LiquidAI/LFM2.5-Audio-1.5B'
            : 'Wan-AI/Wan2.2-T2V-A14B-Diffusers',
        })}
        disabled={isActive || !prompt.trim()}
        style={{ marginTop: 8, padding: '10px 24px', borderRadius: 8 }}
      >
        {state.status === 'submitting' ? 'Submitting...' :
         state.status === 'generating' ? `Generating ${mediaType}...` :
         `Generate ${mediaType.charAt(0).toUpperCase() + mediaType.slice(1)}`}
      </button>

      {state.status === 'generating' && (
        <div style={{ marginTop: 16, textAlign: 'center' }}>
          <p>Generating — this may take 30s to several minutes</p>
          {state.txHash && (
            <p style={{ fontSize: 12, color: '#888' }}>
              Tx: {state.txHash.slice(0, 18)}...
            </p>
          )}
        </div>
      )}

      {state.status === 'ready' && state.mediaUri && (
        <div style={{ marginTop: 16 }}>
          {state.mediaType === 'image' && (
            <img src={state.mediaUri} alt="Generated" style={{ maxWidth: '100%', borderRadius: 8 }} />
          )}
          {state.mediaType === 'audio' && (
            <audio controls src={state.mediaUri} style={{ width: '100%' }} />
          )}
          {state.mediaType === 'video' && (
            <video controls src={state.mediaUri} style={{ maxWidth: '100%', borderRadius: 8 }} />
          )}
          <button onClick={reset} style={{ marginTop: 8 }}>Generate Another</button>
        </div>
      )}

      {state.status === 'error' && (
        <div style={{ marginTop: 16, color: '#ff6b6b' }}>
          <p>{state.error}</p>
          <button onClick={reset}>Try Again</button>
        </div>
      )}
    </div>
  );
}
```

---

## 9. Cost Considerations

Multimodal generation is significantly more expensive than text-based precompiles due to GPU computation and storage costs.

### Cost Components

```
Total Cost = BASE_FEE + COMPUTE_FEE + STORAGE_FEE

Where:
  BASE_FEE     = precompile base fee (~5e12 wei)
  COMPUTE_FEE  = GPU time × model rate (varies by model/executor)
  STORAGE_FEE  = output_size × storage rate (depends on provider)
```

### Recommended Deposits by Modality

| Modality | Min Deposit | Recommended | Generation Time |
|-----------|------------|-------------|-----------------|
| Image (1024×1024) | 0.02 RITUAL | 0.05 RITUAL | 10-60s |
| Image (512×512) | 0.01 RITUAL | 0.03 RITUAL | 5-30s |
| Audio (10s) | 0.03 RITUAL | 0.08 RITUAL | 15-90s |
| Audio (30s) | 0.05 RITUAL | 0.12 RITUAL | 30-180s |
| Video (5s, 720p) | 0.10 RITUAL | 0.25 RITUAL | 60-300s |
| Video (10s, 1080p) | 0.20 RITUAL | 0.50 RITUAL | 120-600s |

### TTL Recommendations

| Modality | Min TTL | Recommended TTL |
|-----------|---------|-----------------|
| Image | 60 blocks | 120 blocks |
| Audio | 120 blocks | 300 blocks |
| Video | 300 blocks | 600 blocks |

---

## 10. Error Handling

### Response Error Checking

```typescript
import { decodeAbiParameters } from 'viem';

function handleImageResult(responseHex: `0x${string}`) {
  const [hasError, , outputUri, outputContentHash, , outputSizeBytes, outputWidth, outputHeight, errorMessage] =
    decodeAbiParameters(
      [
        { type: 'bool' }, { type: 'bytes' }, { type: 'string' },
        { type: 'bytes32' }, { type: 'bool' }, { type: 'uint32' },
        { type: 'uint32' }, { type: 'uint32' }, { type: 'string' },
      ],
      responseHex
    );

  if (hasError) {
    console.error('Generation failed:', errorMessage);

    if (errorMessage.includes('model_not_found')) {
      console.error('Model not available — check executor capabilities');
    } else if (errorMessage.includes('storage_error')) {
      console.error('Storage upload failed — check storage credentials');
    } else if (errorMessage.includes('timeout')) {
      console.error('Generation timed out — increase TTL');
    }
    return null;
  }

  if (outputContentHash === '0x' + '0'.repeat(64)) {
    console.warn('No content hash — cannot verify integrity');
  }

  return {
    uri: outputUri,
    width: outputWidth,
    height: outputHeight,
    size: outputSizeBytes,
  };
}
```

### Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `No services found for multimodal capability` | No IMAGE/AUDIO/VIDEO services registered | Use `getServicesByCapability(7, true)` to find active services |
| `model_not_found` | Model not supported on current chain | Hard-code one of: `black-forest-labs/FLUX.2-klein-4B`, `LiquidAI/LFM2.5-Audio-1.5B`, `Wan-AI/Wan2.2-T2V-A14B-Diffusers` |
| `storage_error` | Failed to upload to storage provider | Check `encryptedSecrets` encoding and `outputStorageRef` format; ensure ECIES nonce length = 12. See `ritual-dapp-da` for credential formats. |
| `insufficient deposit` | Not enough RITUAL for generation + storage | Increase deposit; ~0.15 RITUAL per IMAGE request |
| `insufficient lock duration` | `lockDuration` too short — lock already expired or doesn't cover `commit_block + ttl` | Advisory minimum is `5000`; use `100_000n` in development to reduce expiry risk |
| `sender locked due to existing async transaction` | Same sender trying to submit a second async tx | Use a different EOA for each concurrent image request |
| `timeout` | Generation exceeded TTL | Increase TTL (video especially needs high TTL) |
| `prompt is required` | Empty or whitespace-only prompt | Provide a non-empty prompt string |
| Callback never received | Wrong callback signature in `deliverySelector` | Ensure callback signature is `(bytes32 jobId, bytes calldata responseData)` |
| Storage credentials replayed by third party | `encryptedSecrets` is public on-chain and not caller-bound | Use `SecretsAccessControl.grantAccess(consumerContract, secretsHash, expiry)` to bind credentials to your contract |
| No `MediaReady`/`MediaFailed` event within timeout | Storage credentials are malformed or cannot be decrypted/validated | Treat as storage-auth failure candidate; recheck credential JSON format per `ritual-dapp-da` |
| `grantAccess` reverts with no data | Incorrect call shape/arguments | Verify 4-arg signature `grantAccess(delegate, secretsHash, expiresAt, policy)` and policy tuple fields before assuming network issue |
| TX mines but callback never arrives | Invalid `encryptedSecrets` or empty `outputStorageRef` — credential format mismatch or ECIES decryption failure causes silent Phase 2 failure | See debugging checklist below and `ritual-dapp-da` |
| TX accepted but never mined (nonce unchanged) | Base-field validation failure — executor address zero, TTL out of bounds, or insufficient RitualWallet balance/lock | Check executor address, TTL, and wallet deposit |

### Debugging: TX Mines But Callback Never Arrives

This is the most common failure mode for multimodal precompiles. Phase 1 succeeds (TX mines, nonce increments) but the Phase 2 callback never arrives — the executor fails silently during content generation or delivery.

**Note:** If the TX truly never mines (nonce unchanged), the issue is likely in the base fields validated at commitment time: executor address, TTL bounds, or RitualWallet balance/lock. Storage credential issues do **not** cause TX drops — they cause silent Phase 2 failures.

**Checklist:**

1. **Check nonce before and after:** `eth_getTransactionCount(address, 'latest')`. If nonce didn't change, the issue is base-field validation (see items 2-3). If nonce incremented, the issue is Phase 2 (see items 4-10).
2. **Check RitualWallet lock:** `lockUntil(address)` must be > current block + TTL. If expired, deposit with a longer `lockDuration`.
3. **Check RitualWallet balance:** `balanceOf(address)` must cover the generation fee (~0.14 RITUAL for IMAGE). The balance check is against the **EOA** that signs the TX, not the calling contract (see Section 6 and ritual-dapp-wallet skill).
4. **Verify `outputStorageRef`:** Must be a non-empty `(platform, path, keyRef)` tuple. `['', '', '']` means no storage — executor cannot upload.
5. **Verify credential format matches platform:** GCS needs `{"service_account_json":..., "bucket":...}` JSON; HF needs a plain token string; Pinata needs `{"jwt":..., "gateway_url":...}` JSON. See `ritual-dapp-da` for details.
6. **Verify ECIES config:** `ECIES_CONFIG.symmetricNonceLength` must be `12` before calling `encrypt()`.
7. **Verify executor public key:** Fetch fresh from `TEEServiceRegistry.getService(executorAddress).node.publicKey`.
8. **Executor endpoint is irrelevant to dApp developers.** Executor routing is handled internally. You only need `teeAddress` and `publicKey` from the registry.
9. **Verify model selection:** The current chain supports only `black-forest-labs/FLUX.2-klein-4B`, `LiquidAI/LFM2.5-Audio-1.5B`, and `Wan-AI/Wan2.2-T2V-A14B-Diffusers`.
10. **Use `eth_call` as preflight only:** Validate payload shape and immediate revert/decode issues before sending a signed transaction.

---

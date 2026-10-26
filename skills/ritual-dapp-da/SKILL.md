---
name: ritual-dapp-da
description: Data Availability (storage) patterns for Ritual dApps. Use when any precompile stores or retrieves external data — multimodal outputs, conversation history, agent state, FHE ciphertexts, or artifact files.
---

# Data Availability (Storage) — Ritual dApp Patterns

## Overview

Several Ritual precompiles read from or write to external storage during execution. The chain itself does not store large blobs — generated images, conversation history, FHE ciphertexts, and agent artifacts all live off-chain on storage providers (GCS, HuggingFace, Pinata). The executor handles all storage I/O inside the TEE.

This skill covers the shared DA patterns. For precompile-specific ABI fields and usage, see the corresponding skill (`ritual-dapp-multimodal`, `ritual-dapp-llm`, `ritual-dapp-agents`).

## Read This First

- Use `StorageRef` everywhere DA appears: `(platform, path, keyRef)`.
- Put storage credentials in `encryptedSecrets`; `keyRef` links a DA field to its credential.
- Handle `hasError` on result decode paths (callbacks and settled async outputs).
- Keep this skill as the shared DA source; use precompile-specific skills only for ABI specifics.

## When to Use

- "How do I set `outputStorageRef` for image/audio/video?"
- "How should I format GCS/HF/Pinata credentials in `encryptedSecrets`?"
- "How do I debug DA failures when callbacks do not arrive?"
- "How does agent DA encryption with DKMS work?"
- "How do I splice a large JSON file into an HTTP body or fan response fields out to several stores?"

### Which Precompiles Use DA?

| Precompile | Address | DA Fields | Read/Write | Skill |
|---|---|---|---|---|
| Image Call | `0x0818` | `outputStorageRef` (field 19) | Write (upload generated image) | `ritual-dapp-multimodal` |
| Audio Call | `0x0819` | `outputStorageRef` (field 19) | Write (upload generated audio) | `ritual-dapp-multimodal` |
| Video Call | `0x081A` | `outputStorageRef` (field 19) | Write (upload generated video) | `ritual-dapp-multimodal` |
| FHE | `0x0807` | `inputStorageRef` (field 19), `outputStorageRef` (field 20) | Read + Write (ciphertext I/O) | `ritual-dapp-precompiles` |
| LLM Call | `0x0802` | `convoHistory` (field 31) | Read + Write (conversation JSONL, **plaintext**) | `ritual-dapp-llm` |
| HTTP Call | `0x0801` | legacy `outputStorageRef`; RITHTTP1 `InputRef[]` + `OutputPipe[]` inside `body` | Read public/encrypted JSON + write selected public/encrypted artifacts | `ritual-dapp-http` |
| Long-Running HTTP | `0x0805` | legacy `outputStorageRef`; RITHTTP1 `InputRef[]` + `OutputPipe[]` inside `body` | Read public/encrypted JSON + write independently collected artifacts alongside live selected frames | `ritual-dapp-longrunning` |
| Sovereign Agent | `0x080C` | inside the 16-field V1 `executorPayload` (envelope field 12): `convoHistory` (payload 7), `output` (payload 8), `skills[]` (payload 9), `systemPrompt` (payload 10) | Read + Write (**DKMS-encrypted**) | `ritual-dapp-agents` |
| Persistent Agent | `0x0820` | inside the 21-field V1 `executorPayload` (envelope field 12): `daConfig` (payload 8), `soulRef` (payload 9), `agentsRef` (payload 10), `userRef` (payload 11), `memoryRef` (payload 12), `identityRef` (payload 13), `toolsRef` (payload 14), `openclawConfigRef` (payload 15) | Read + Write (**DKMS-encrypted**) | `ritual-dapp-agents` |

> **HTTP / Long-Running HTTP DA output.** For both HTTP precompiles, `outputStorageRef` is the trailing `StorageRef` field. An all-empty tuple (`['', '', '']`) means "return the response inline" (unchanged behavior); a populated tuple makes the executor store the response off-chain. The reth RPC validator rejects a **partial** ref (`PartialStorageRef`): the tuple must be either fully empty or have **both** `platform` AND `path` non-empty (`keyRef` stays optional for public/no-auth storage). Unlike multimodal/LLM DA (plaintext), the stored HTTP payload is **ECIES-encrypted to the caller's `userPublicKey`** — see [Output URI Handling](#output-uri-handling).

> **RITHTTP1 uses StorageRef differently.** A RITHTTP1 request leaves the legacy outer ref empty. Its inner refs require a non-empty path plus a `storage:*` key alias and return indexed per-pipe results in RITOUT1 encoding 4. An input ref may point to a plaintext JSON value or a multi-recipient encrypted artifact; its digest always covers the exact stored bytes, ciphertext when encrypted. Every output has its own optional ECIES recipient. DA collects selected bytes and encrypts once; it is not a ciphertext-frame archive. STREAM commits length-prefixed transmitted frames separately. Both outer and inner refs accept `gcs`, `hf`, and `pinata`. Read [`../ritual-dapp-http/references/rithttp1.md`](../ritual-dapp-http/references/rithttp1.md) and [`../ritual-dapp-http/references/rithttp1-private-io.md`](../ritual-dapp-http/references/rithttp1-private-io.md).

---

## 1. StorageRef — The Universal Storage Pointer

Every DA field uses the same type: a `StorageRef` tuple of three strings.

```typescript
// ABI type: (string, string, string)
type StorageRef = [
  string,  // platform  — storage provider identifier
  string,  // path      — platform-specific object path
  string,  // keyRef    — placeholder name in encryptedSecrets for credentials
];
```

**How `keyRef` works:** `keyRef` points to the credential value inside `encryptedSecrets`. For example, if `keyRef = 'GCS_CREDS'`, then `encryptedSecrets` should include a `GCS_CREDS` entry with GCS credentials in the expected format.

RITHTTP1 deliberately namespaces reusable credentials as `storage:gcs`, `storage:hf`, or `storage:pinata`. The credential lives once in the ordinary encrypted secrets map; any number of thin input/output refs can repeat only that alias and a path.

**Empty ref:** `['', '', '']` means "no storage reference" — the executor skips this field.

### Encoding in TypeScript

```typescript
import { encodeAbiParameters } from 'viem';

// StorageRef is encoded as a tuple of three strings
const storageRef = ['gcs', 'outputs/image.png', 'GCS_CREDS'];

// In the full precompile ABI, use the tuple type:
// { type: 'tuple', components: [
//   { name: 'platform', type: 'string' },
//   { name: 'path', type: 'string' },
//   { name: 'keyRef', type: 'string' },
// ]}

// Or with parseAbiParameters shorthand:
// '(string,string,string)'
```

### Encoding in Solidity

```solidity
// StorageRef value passed as one tuple field in a larger precompile payload
StorageRef memory outRef = StorageRef({
    platform: "gcs",
    path: "outputs/image.png",
    keyRef: "GCS_CREDS"
});

// Example: include outRef in your full abi.encode payload
bytes memory input = abi.encode(
    // ... other fields ...
    outRef
);
```

---

## 2. Supported Platforms

| Platform | `platform` value | `path` format | `keyRef` value | Auth Required |
|---|---|---|---|---|
| Google Cloud Storage | `'gcs'` | Object path within bucket (bucket is in credential JSON) | Key name in `encryptedSecrets` holding `{service_account_json, bucket}` JSON | Yes |
| HuggingFace | `'hf'` | `org/repo/path/to/file` (slash-separated, first two segments are repo ID) | Key name holding HF access token string | Yes |
| Pinata (IPFS) | `'pinata'` | CID (empty for first upload, CID for subsequent) | Key name holding `{jwt, gateway_url}` JSON | Yes |

### GCS Path Format

The path is an object key within the GCS bucket. The bucket name is specified inside the credential JSON (the `bucket` field), not in the StorageRef path.

```typescript
// GCS StorageRef — object path only, bucket is in credentials
const gcsRef: StorageRef = ['gcs', 'multimodal/outputs/image_001.png', 'GCS_CREDS'];

// The GCS_CREDS value in encryptedSecrets must be a JSON string with two fields:
// '{"service_account_json":"{\"type\":\"service_account\",...}","bucket":"my-bucket"}'
//
// service_account_json: the full GCP service account key file JSON (stringified)
// bucket: the GCS bucket name
```

### HuggingFace Path Format

Slash-separated: the first two segments are the HF repo ID, the rest is the file path within the repo.

```typescript
// org/repo/path/to/file — first two segments = repo ID, rest = file path
const hfRef: StorageRef = ['hf', 'my-org/agent-data/configs/SOUL.md', 'HF_TOKEN'];
// repo ID = "my-org/agent-data", file path = "configs/SOUL.md"

// Repo-root ref (no file subpath) — use for listing/downloading entire repo
const hfRepoRef: StorageRef = ['hf', 'my-org/agent-configs', 'HF_TOKEN'];
```

### Pinata (IPFS) Path Format

Pinata is append-only (content-addressed). Each upload returns a new CID. For the first upload, pass an empty path. For subsequent uploads, pass the CID from the previous response.

```typescript
// First call — empty path, CID returned after upload
const pinataFirst: StorageRef = ['pinata', '', 'DA_PINATA_JWT'];

// Subsequent call — pass CID from previous response
const pinataNext: StorageRef = ['pinata', 'QmXyzAbc123...', 'DA_PINATA_JWT'];
```

### Inline

Content is embedded directly in the path field. No storage I/O occurs — the executor reads the path string as the content. Read-only (never uploaded to).

```typescript
const inlineRef: StorageRef = ['inline', 'You are a helpful DeFi agent.', ''];
```

---

## 3. Providing Storage Credentials

Storage credentials are delivered inside `encryptedSecrets`, encrypted with the executor's ECIES public key. The `keyRef` field in each `StorageRef` tells the executor which key in the decrypted secrets map holds the credential.

### Credential Format by Platform

| Platform | Credential Format | Example `encryptedSecrets` JSON |
|---|---|---|
| GCS | JSON object with `service_account_json` and `bucket` | `{"GCS_CREDS": "{\"service_account_json\":\"{\\\"type\\\":\\\"service_account\\\",...}\",\"bucket\":\"my-bucket\"}"}` |
| HuggingFace | HF access token string (plain, not JSON) | `{"HF_TOKEN": "hf_abc123..."}` |
| Pinata | JSON object with `jwt` and `gateway_url` | `{"PINATA_CREDS": "{\"jwt\":\"eyJ...\",\"gateway_url\":\"https://my-gateway.mypinata.cloud/ipfs\"}"}` |

### Encrypting Credentials

```typescript
import { encrypt, ECIES_CONFIG } from 'eciesjs';
import { encodeAbiParameters, hexToBytes, bytesToHex } from 'viem';

// MANDATORY: 12-byte nonce for Ritual ECIES
ECIES_CONFIG.symmetricNonceLength = 12;

// Combine storage credentials with any other secrets (e.g., LLM API key)
const gcsServiceAccountJson = process.env.GCS_DA_SERVICE_ACCOUNT_JSON!;
const gcsBucket = process.env.GCS_DA_BUCKET!;

const secrets = {
  ANTHROPIC_API_KEY: 'sk-ant-...',
  GCS_CREDS: JSON.stringify({
    service_account_json: gcsServiceAccountJson,
    bucket: gcsBucket,
  }),
};

// The executor rejects a bare secrets map. Wrap it in the owner-bound
// envelope {version:1, secret_owner:<checksumAddress>, secrets:{...}} before encrypting.
// On decrypt the executor zips encrypted_secrets with the explicit secret_owners[]
// base field and rejects the blob if version != 1 or the envelope owner != secret_owners[i].
// secretOwner is the EOA/contract that owns these secrets (checksummed).
const secretsJson = JSON.stringify({
  version: 1,
  secret_owner: secretOwner,
  secrets,
});

// Encrypt to executor's public key (from TEEServiceRegistry)
const encryptedBuffer = encrypt(executorPublicKey.slice(2), Buffer.from(secretsJson));
const encryptedSecrets = [`0x${Buffer.from(encryptedBuffer).toString('hex')}` as `0x${string}`];
```

> **ECIES nonce length = 12.** Both `eciesjs` (TypeScript) and `eciespy` (Python) default to 16-byte nonces. The executor uses 12. Mismatched nonce length causes silent decryption failure — the transaction mines but DA operations fail with no error message. Set `ECIES_CONFIG.symmetricNonceLength = 12` (TypeScript) or `ECIES_CONFIG.symmetric_nonce_length = 12` (Python) before any `encrypt()` call.

### Executor Discovery for Public Key

```typescript
import { createPublicClient, http, defineChain } from 'viem';

const ritualChain = defineChain({
  id: 784,
  name: 'Ritual Chain',
  nativeCurrency: { name: 'RITUAL', symbol: 'RITUAL', decimals: 18 },
  rpcUrls: { default: { http: [process.env.RITUAL_RPC_URL!] } },
});
const publicClient = createPublicClient({ chain: ritualChain, transport: http() });

const TEE_SERVICE_REGISTRY = '0xf4495DC72143D44A93AB0ecE4d6D63a216b27839' as const;

// Use the capability for your precompile:
// 0 = HTTP_CALL (agents), 1 = LLM, 7 = IMAGE_CALL (multimodal)
const services = await publicClient.readContract({
  address: TEE_SERVICE_REGISTRY,
  abi: [{
    name: 'getServicesByCapability',
    type: 'function',
    stateMutability: 'view',
    inputs: [{ name: 'capability', type: 'uint8' }, { name: 'activeOnly', type: 'bool' }],
    outputs: [{ type: 'tuple[]', components: [
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
    ]}],
  }] as const,
  functionName: 'getServicesByCapability',
  args: [7, true],  // 7 = IMAGE_CALL capability
});

const executor = services[0];
const executorAddress = executor.node.teeAddress;
const executorPublicKey = executor.node.executorSecretsAuthPublicKey as `0x${string}`;
```

### Binding Credentials with SecretsAccessControl

Storage credentials in `encryptedSecrets` are visible on-chain (as ciphertext). Anyone can copy and replay them. To prevent unauthorized reuse, bind credentials to your contract using `SecretsAccessControl`:

```typescript
import { keccak256, toBytes } from 'viem';

const SECRETS_AC = '0x0cEae62e2082829226eF5821Bb662483Db17A71F' as const;
const secretsHash = keccak256(toBytes(encryptedSecrets[0]));
const currentBlock = await publicClient.getBlockNumber();

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
  args: [
    consumerContractAddress,
    secretsHash,
    currentBlock + 50_000n,
    { allowedDestinations: [], allowedMethods: [], allowedPaths: [],
      allowedQueryParams: [], allowedHeaders: [], secretLocation: '', bodyFormat: '' },
  ],
});
```

See `ritual-dapp-secrets` for the full delegation pattern.

---

## 4. DA Lifecycle (Builder View)

From an app-builder perspective, DA follows a simple lifecycle:

1. **Prepare request inputs**
   - Set one or more `StorageRef` values.
   - Include matching credentials in `encryptedSecrets`.
   - Ensure the sponsor's RitualWallet `availableBalance` (and `allowance(sponsor, caller)` if sponsored) covers the async reserve.

2. **Submit the precompile call**
   - The request is accepted on-chain.
   - Processing continues asynchronously for long-running precompiles.

3. **Receive success result**
   - You receive a URI / updated storage reference through the normal result channel:
     - callback for long-running precompiles
     - settled receipt output for short-running async precompiles

4. **Or receive an error result**
   - DA failures come back as structured results with `hasError=true` and an `errorMessage`.
   - You can surface this error directly in your app UX.

### Output URI Handling

Multimodal executors upload to GCS and return `gs://` URIs. Browsers cannot fetch `gs://` directly — convert to HTTPS before displaying:

```typescript
function gsUriToHttps(uri: string): string {
  if (uri.startsWith('gs://')) {
    return uri.replace('gs://', 'https://storage.googleapis.com/');
  }
  return uri;
}
```

### HTTP DA Output (Result Envelope)

This subsection describes the **legacy outer** `outputStorageRef`. RITHTTP1 instead returns `RITOUT1` encoding 4 with indexed CONTRACT/STREAM/DA results in `contractOutput` and an empty outer receipts array; see the canonical RITHTTP1 reference. Never populate both routing mechanisms.

When an HTTP / Long-Running HTTP call sets `outputStorageRef`, the executor uploads the (ECIES-encrypted) ABI-encoded `HTTPCallResponse` off-chain and the precompile `actualOutput` becomes a **DA result envelope** instead of the inline `HTTPCallResponse`:

```typescript
// DA result envelope ABI: (bool, string, bytes32, uint64, string)
const DA_RESULT_ABI = [
  { type: 'bool' },    // has_error
  { type: 'string' },  // output_uri          — where the encrypted response is stored
  { type: 'bytes32' }, // output_content_hash — sha256 of the stored bytes
  { type: 'uint64' },  // output_size_bytes   — length of the stored bytes
  { type: 'string' },  // error_message
] as const;
```

To consume it, the dApp must: (1) decode the envelope, (2) fetch the bytes from `output_uri`, (3) verify they hash (sha256) to `output_content_hash` and match `output_size_bytes`, then (4) ABI-decode the stored object as a single `bytes` value to extract the ECIES ciphertext, (5) decrypt that ciphertext with the **USER private key**, and (6) decode the plaintext as the flat five-field `HTTPCallResponse` (the response is ECIES-encrypted to `userPublicKey`, unlike multimodal/LLM which store plaintext). HTTP DA output is **fail-closed**: it requires a valid 65-byte `userPublicKey` with a `0x04` prefix, otherwise the executor returns an error envelope. The Python end-to-end helper uses the matching `DA_RESULT_ABI = ['bool', 'string', 'bytes32', 'uint64', 'string']`.

---

## 5. DA Error Handling

When storage operations fail (bad credentials, upload failure, network/provider issues), the request still resolves on-chain with a structured error result instead of hanging silently.

### What You Should Expect

1. The result payload includes `hasError=true`.
2. `errorMessage` explains the failure reason.
3. DA-related failures on the Image, Audio, Video, and FHE paths settle Phase 2 with a **constant error fee**: `10,000,000,000,000,000 wei` (0.01 RIT, `DA_ERROR_PHASE2_FEE_WEI`). A failed multimodal call therefore costs its Phase 1 fee (0.01 RIT image/audio, 0.10 RIT video, 0.10 RIT FHE) plus the 0.01 RIT DA error fee. HTTP and LLM DA failures are priced by their own lanes.
4. Your app should treat `hasError=true` as a terminal state and surface the message to users.

### DA Errors Apply To

| Precompile | Common DA failure points |
|---|---|
| Image (0x0818) | Credential validation failure, output upload failure |
| Audio (0x0819) | Credential validation failure, output upload failure |
| Video (0x081A) | Credential validation failure, output upload failure |
| FHE (0x0807) | Input/output storage credential failure, output upload failure |
| LLM (0x0802) | Convo-history credential failure, convo-history upload failure |
| HTTP (0x0801) / Long-Running HTTP (0x0805) | Missing/invalid `userPublicKey` (fail-closed), output storage credential failure, output upload failure, response exceeds the executor DA upload cap |

When `hasError=true` on the Image, Audio, Video, or FHE path, Phase 2 deducts the constant `DA_ERROR_PHASE2_FEE_WEI` (10,000,000,000,000,000 wei / 0.01 RIT) from escrow instead of the generation price; the total cost of a failed call is the Phase 1 fee (0.01 RIT image/audio, 0.10 RIT video, 0.10 RIT FHE) plus this 0.01 RIT error fee. HTTP (0x0801/0x0805) and LLM (0x0802) DA failures are priced by their own lanes, not by this constant.

> **HTTP DA upload size cap.** An HTTP response uploaded via DA is capped at `HTTPDAMaxOutputBytes = 10 * 1024 * 1024` (10 MiB). The executor rejects encoded outputs above this cap **before** uploading with `HTTP response size %d exceeds executor DA upload cap %d`. Keep DA-backed HTTP responses under 10 MiB.

### Handling DA Errors in Your Callback

```typescript
// In your Phase 2 callback (e.g., onImageReady):
function onImageReady(jobId: `0x${string}`, responseData: `0x${string}`) {
  const [hasError, , outputUri, , , , , , errorMessage] = decodeAbiParameters(
    [
      { type: 'bool' }, { type: 'bytes' }, { type: 'string' },
      { type: 'bytes32' }, { type: 'bool' }, { type: 'uint32' },
      { type: 'uint32' }, { type: 'uint32' }, { type: 'string' },
    ],
    responseData,
  );

  if (hasError) {
    // DA error — errorMessage contains the reason
    // Common messages:
    //   "Failed to decrypt secrets: ..."
    //   "Failed to create storage client: ..."
    //   "Storage credentials invalid: ..."
    //   "Phase 2 processing failed after N retries: ..."
    console.error('DA error:', errorMessage);
    return;
  }

  // Success — use outputUri
}
```

```solidity
// Solidity callback
address constant ASYNC_DELIVERY = 0x508f57AE70967Da28AE0Ab6b95532878c4D0F440;

function onImageReady(bytes32 jobId, bytes calldata responseData) external {
    require(msg.sender == ASYNC_DELIVERY, "unauthorized callback sender");
    (bool hasError, , , , , , , , string memory errorMsg) = abi.decode(
        responseData,
        (bool, bytes, string, bytes32, bool, uint32, uint32, uint32, string)
    );

    if (hasError) {
        emit MediaFailed(jobId, errorMsg);
        return;
    }

    // Process success...
}
```

### Two Common Error Timing Patterns

**Before generation completes**
- Typically credential or access issues.
- You receive `hasError=true` without a usable output URI.

**After generation but before persistence**
- Generation succeeded, but writing output to storage failed.
- You still receive `hasError=true`, and should ask users to retry.

---

## 6. DKMS — Agent DA Encryption (Agent Precompiles Only)

Agent precompiles (Sovereign Agent, Persistent Agent) use DKMS (Decentralized Key Management) to derive an encryption key inside the TEE. All **agent** DA content is encrypted at rest. The two precompiles key the derivation differently: **Sovereign Agent** derives a **per-sender** key bound to the sender's Ethereum address; **Persistent Agent** derives a key keyed by the **chain-issued `agentId`** (an agent-scoped DKMS root, not the sender address). For a persistent agent the executor first looks the `agentId` up in `AgentIdentityRegistry` and authorizes the request — the sender must be the on-chain owner or an owner-approved operator (`isAgentOperator`) — before deriving the agentId-keyed key.

> **LLM, multimodal (image/audio/video), and FHE precompiles store output in plaintext.** Only Sovereign Agent and Persistent Agent use DKMS-derived encryption. LLM conversation history, generated images, audio, video, and FHE ciphertexts are written directly to the storage provider without an additional encryption layer.

### How DKMS DA Encryption Works

1. The executor derives a **secp256k1 keypair** from DKMS. For **sovereign agents** the keypair is bound to the sender's Ethereum address; for **persistent agents** it is derived from an agent-scoped DKMS root keyed by the chain-issued `agentId` (the sender must first pass the `AgentIdentityRegistry` owner-or-approved-operator check).
2. **Uploads**: executor ECIES-encrypts content with the derived public key before writing to storage.
3. **Downloads**: executor ECIES-decrypts content with the derived private key after reading from storage.
4. The keypair is **principal-bound, not executor-bound** — agent state is portable across executors. For sovereign agents the principal is the sender; for persistent agents it is the `agentId` itself, so whichever authorized sender (owner or approved operator) submits the request reaches the same key.

### Encrypted Inputs with `dkms_encrypted:` Prefix

Skills and system prompts for agents can be pre-encrypted to the agent's DA public key. This keeps agent instructions private on the storage provider.

To use this pattern:

1. Get the agent's DA public key from the DKMS precompile (`0x081B`).
2. ECIES-encrypt the content with that public key.
3. Upload the ciphertext to HF/GCS/Pinata.
4. Set `keyRef` to `dkms_encrypted:<credential>` on the StorageRef.

```typescript
const systemPrompt: StorageRef = [
  'hf',
  'my-org/workspace/system.encrypted.md',
  'dkms_encrypted:HF_TOKEN',  // prefix tells executor to DKMS-decrypt after download
];
```

> **Two different encryption targets.** `encryptedSecrets` is encrypted to the **executor's** public key (from `TEEServiceRegistry.node.executorSecretsAuthPublicKey`). `dkms_encrypted:` content is encrypted to the **agent's** DA public key (from DKMS precompile 0x081B). These are different keys for different purposes.

See `ritual-dapp-agents` for the full DKMS agent pattern.

---

## 7. Debugging DA Failures

### Symptom: TX Mines But Callback Never Arrives (Multimodal)

This is the most common DA failure. Phase 1 succeeds but the Phase 2 callback never comes.

**Checklist:**

1. **Is `outputStorageRef` non-empty?** An empty `['', '', '']` means no storage configured — the executor cannot upload the output.
2. **Is `keyRef` correct?** Must match a key in the decrypted `encryptedSecrets` JSON exactly.
3. **Is the credential format correct?** GCS expects a JSON payload containing both `service_account_json` and `bucket`. HF expects a token string. Pinata expects a JSON payload containing `jwt` and `gateway_url`.
4. **Is `ECIES_CONFIG.symmetricNonceLength` = 12?** Wrong nonce length = executor cannot decrypt secrets = silent failure.
5. **Is the executor public key current?** Fetch fresh from `TEEServiceRegistry.getServicesByCapability()`.
6. **Does the sponsor's RitualWallet have enough available balance?** The commitment validator reserves the required execution escrow up front, so `availableBalance(sponsor)` must cover that reserve. For long-running HTTP (`0x0805`), include Phase 1 HTTP fee, worst-case Phase 2 polling escrow (`FEE_PER_POLL_BLOCK_WEI * (ttl + maxPollBlock)`), worst-case output payload fee, and callback gas/value. There is no lock/`lockUntil` anymore. If the call is sponsored (sponsor != caller), `allowance(sponsor, caller)` must also be >= that reserve.

### Symptom: Callback Arrives with `hasError=true`

The executor detected a DA problem and settled with an error. Read the `errorMessage` field:

| Error Message Pattern | Cause | Fix |
|---|---|---|
| `Failed to decrypt secrets: ...` | ECIES decryption failed | Check nonce length (12), public key correctness |
| `Failed to create storage client: ...` | Credential format invalid for platform | Check credential JSON format per platform table above |
| `Storage credentials invalid: ...` | Credentials are well-formed but rejected by the storage provider | Check SA permissions, token expiry, bucket existence |
| `Phase 2 processing failed after N retries: ...` | Upload succeeded partially or network issues | Retry with fresh credentials; check storage provider status |

### Symptom: Agent DA Content Not Persisting

For Sovereign/Persistent agents:

1. **Check that DA credentials are in `encryptedSecrets`.** Agent DA requires credentials alongside the LLM API key.
2. **Check `convoHistory` and `output` StorageRefs are non-empty.** Empty refs = no persistence between calls.
3. **For Pinata: pass the CID from the previous response.** Pinata is content-addressed — you must chain CIDs across calls.
4. **All agent DA content is ECIES-encrypted at rest.** You cannot read it directly from the storage provider — it is ciphertext.

---

## Quick Reference

| Item | Value |
|---|---|
| StorageRef type | `(string platform, string path, string keyRef)` |
| Supported platforms | `gcs`, `hf`, `pinata`, `inline` |
| Credential delivery | Via `encryptedSecrets` (ECIES-encrypted to executor public key) |
| ECIES nonce length | **12** (both TypeScript and Python default to 16 — must override) |
| DA error fee | 10,000,000,000,000,000 wei = 0.01 RIT (constant `DA_ERROR_PHASE2_FEE_WEI`, applies to Image/Audio/Video/FHE) |
| DA error detection | `hasError` field in response payload |
| DKMS DA encryption | Content encrypted at rest (agents only). Sovereign = per-sender derived key; Persistent = key keyed by chain-issued `agentId` (sender must be the `AgentIdentityRegistry` owner or an approved operator) |
| TEEServiceRegistry | `0xf4495DC72143D44A93AB0ecE4d6D63a216b27839` |
| SecretsAccessControl | `0x0cEae62e2082829226eF5821Bb662483Db17A71F` |
| RitualWallet | `0xF04076756d8129Baec46Dc0F1c526Baec490C393` |

---
name: ritual-dapp-secrets
description: Secret management and private outputs for Ritual dApps. Use when handling encrypted secrets, private execution results, or delegated access control.
version: 1.0.0
---

# Secret Management, Private I/O & Delegation

For persistent Hermes, an encrypted named secret does **not** automatically become
an arbitrary environment variable. Read [runtime secret bindings and Jev](../ritual-dapp-agents/references/hermes-tools-and-secrets.md)
before promising custom tool credentials or configuration-based injection.


Encrypt secrets for executor-side injection, receive private execution outputs, and manage delegated access control for shared secrets on Ritual Chain.

> For storage credential formats (GCS, HuggingFace, Pinata) used in `encryptedSecrets`, see `ritual-dapp-da`.

## Read This First

Core path in this skill: encrypt `encryptedSecrets` to an executor public key, use template substitution, optionally set `userPublicKey` for encrypted outputs, and use delegation via `SecretsAccessControl`.

Template substitution runs whenever `encryptedSecrets` is non-empty.

RITHTTP1 adds structured aliases without changing encryption, ownership, delegation, or signatures. Put reusable storage credentials under `storage:*` and injected HTTP values under `http:*` in the same owner-bound secrets map. After DA hydration, the executor expands `{"$ritual_secret":"http:alias"}` whole-value nodes and `{{ritual.secret:http:alias}}` string markers, including markers that came from downloaded JSON. Encrypted DA artifacts are a separate content-encryption layer; see [`../ritual-dapp-http/references/rithttp1-private-io.md`](../ritual-dapp-http/references/rithttp1-private-io.md).

### The four identities must stay separate

| Identity | Meaning | Authorization role |
|---|---|---|
| Secret owner | Address named in `secretOwners[i]`, encoded inside the decrypted owner-bound envelope, and recovered from `signatures[i]` | Owns the ciphertext and is the only address that can create its on-chain grant because `grantAccess` stores `msg.sender` as owner |
| Delegate | Immediate EVM caller of the async precompile (`job.SenderAddress`) | Must be the owner or have `checkAccess(owner, delegate, secretsHash)` permission |
| Sponsor | RitualWallet account paying/reserving the async fee | Needs balance and, when different from the caller, wallet allowance; it does not receive secret access by paying |
| Executor | Selected TEE address whose public key encrypted the blob | Bound into the owner's signature so authorization cannot be replayed to another executor |

`tx.origin`, the end user who called a router, and a Scheduler callback sender are not automatically the delegate. The consuming router/manager contract is the delegate when it is the contract that calls the precompile.

Every non-empty encrypted blob uses parallel array entries across `secretOwners`, `encryptedSecrets`, and `signatures`. The owner signs:

```text
RITUAL_SECRET_AUTHORIZATION_V1
|| uint16(useContext.length) || useContext
|| uint256(chainId) || executor || owner || keccak256(ciphertext)
```

The executor then decrypts `{version:1, secret_owner, secrets}` and requires the envelope owner to equal the explicit calldata owner. This prevents a ciphertext from being copied and relabeled.

For the optional `piiEnabled` behavior, see **Optional PII Redaction (`piiEnabled`)** near the end of this document.

## When to Use

- "How do I pass API keys securely to a precompile?"
- "I want to encrypt my execution output so only I can read it"
- "How do I share secrets with a contract or another user?"
- "Set up delegated access for my DAO's API keys"
- "Build a form that encrypts secrets client-side"
- Any dApp using secret API keys, private results, or delegated credentials

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Secrets Architecture                        │
│                                                                 │
│  ┌──────────────┐    ECIES encrypt    ┌──────────────────────┐  │
│  │ User Secrets │ ──────────────────→ │ Encrypted Secrets    │  │
│  │ (API keys)   │  (executor pubkey)  │ (on-chain, opaque)   │  │
│  └──────────────┘                     └──────────┬───────────┘  │
│                                                  │              │
│                          ┌───────────────────────┘              │
│                          ▼                                      │
│  ┌──────────────────────────────────────────────┐               │
│  │           TEE Executor (in enclave)          │               │
│  │                                              │               │
│  │  1. Decrypt secrets with private key         │               │
│  │  2. Substitute secret key names              │               │
│  │  3. Execute request with real values         │               │
│  │  4. Optionally encrypt output with user key  │               │
│  └──────────────────────────────────────────────┘               │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │            SecretsAccessControl Contract                 │   │
│  │  Address: 0x0cEae62e2082829226eF5821Bb662483Db17A71F    │   │
│  │                                                          │   │
│  │  grantAccess(delegate, secretsHash, expiresAt, policy)    │   │
│  │  revokeAccess(delegate, secretsHash)                     │   │
│  │  checkAccess(owner, delegate, secretsHash)               │   │
│  │    → (bool hasAccess, SecretsAccessPolicy policy)        │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## viem Setup

```typescript
import { defineChain, createPublicClient, createWalletClient, http, keccak256, toBytes } from 'viem';
import { privateKeyToAccount } from 'viem/accounts';
import { encrypt, decrypt, PrivateKey, ECIES_CONFIG } from 'eciesjs';

// MANDATORY: use 12-byte nonce for Ritual encrypted secrets. Do NOT use 16.
ECIES_CONFIG.symmetricNonceLength = 12;

const ritualChain = defineChain({
  id: 784,
  name: 'Ritual',
  nativeCurrency: { name: 'RITUAL', symbol: 'RITUAL', decimals: 18 },
  rpcUrls: { default: { http: [process.env.RITUAL_RPC_URL!] } },
});

const account = privateKeyToAccount(process.env.PRIVATE_KEY! as `0x${string}`);
const publicClient = createPublicClient({ chain: ritualChain, transport: http() });
const walletClient = createWalletClient({ account, chain: ritualChain, transport: http() });
```

## ECIES Nonce Length (MANDATORY: 12)

Ritual encrypted-secret payloads require a 12-byte AES-GCM nonce. Some client libraries default to 16, so you must explicitly set 12 before any secret encryption.

If you use 16, requests can fail because encrypted secret payload format will not match Ritual expectations.

If you use `eciesjs`, set:

```typescript
import { ECIES_CONFIG } from 'eciesjs';
ECIES_CONFIG.symmetricNonceLength = 12;
```

## Secret Encryption

Secrets are encrypted using ECIES (Elliptic Curve Integrated Encryption Scheme) to the executor's public key. Only the TEE executor can decrypt them inside its secure enclave.

### Encrypt Secrets (One Canonical Flow)

```typescript
import { createPublicClient, http, defineChain, keccak256, toBytes } from 'viem';
import type { Address, Hex } from 'viem';
import { encrypt } from 'eciesjs';

const ritualChain = defineChain({
  id: 784,
  name: 'Ritual',
  nativeCurrency: { name: 'RITUAL', symbol: 'RITUAL', decimals: 18 },
  rpcUrls: { default: { http: [process.env.RITUAL_RPC_URL!] } },
});
const publicClient = createPublicClient({ chain: ritualChain, transport: http() });

const TEE_SERVICE_REGISTRY = '0xf4495DC72143D44A93AB0ecE4d6D63a216b27839' as const;
const CAPABILITY_HTTP = 0;

// Option A (discover): pick a valid executor by capability
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
  args: [CAPABILITY_HTTP, true],
});
if (services.length === 0) throw new Error('No active executors found');
const selected = services[0];

// Option B (already selected): set these directly instead of discovery
const executorAddress: Address = selected.node.teeAddress;
const executorPublicKey: Hex = selected.node.executorSecretsAuthPublicKey as Hex;

// Endpoint note: `node.endpoint` is NOT used for encryption/delegation.
// Secrets path uses executor address + executor public key.

// The plaintext is an owner-bound envelope, NOT a bare secrets map. The executor
// rejects any blob whose envelope owner does not match the secret_owners[i] you
// declare in the request. The envelope mirrors ritual-common build_secret_envelope:
// {version:1, secret_owner:<checksum>, secrets:{...}}. The executor json-parses the
// decrypted bytes, so exact key ordering is not required for correctness; the version
// and owner-match checks are what matter.
import { getAddress } from 'viem';

function buildSecretEnvelope(secretOwner: Address, secrets: Record<string, string>): string {
  return JSON.stringify({
    secret_owner: getAddress(secretOwner),   // EIP-55 checksummed owner address
    secrets,
    version: 1,
  });
}

const ownerAddress = account.address;        // the address that owns/signs this blob
const secretsJson = buildSecretEnvelope(ownerAddress, {
  API_KEY: 'sk-my-openai-key-here',
  WEBHOOK_SECRET: 'whsec_abc123',
});
const encryptedBuffer = encrypt(executorPublicKey.slice(2), Buffer.from(secretsJson));
const encryptedSecrets: Hex[] = [`0x${Buffer.from(encryptedBuffer).toString('hex')}`];
// Pass secret_owners=[ownerAddress] in the request; it must equal the envelope owner.
const secretsHash: Hex = keccak256(toBytes(encryptedSecrets[0]));
```

### Decrypt Secrets (for Testing / Executor-Side)

```typescript
import { hexToBytes } from 'viem';
import { decrypt } from 'eciesjs';

// Decrypt using your private key
const encryptedBytes = hexToBytes(encryptedSecrets[0]);
const decryptedBuffer = decrypt(
  process.env.PRIVATE_KEY!.slice(2),  // raw hex private key
  Buffer.from(encryptedBytes),
);
const envelope = JSON.parse(Buffer.from(decryptedBuffer).toString('utf-8'));
// Returns the owner-bound envelope, NOT a flat map:
//   { version: 1, secret_owner: '0x...', secrets: { API_KEY: 'sk-my-openai-key-here', WEBHOOK_SECRET: 'whsec_abc123' } }
// Verify version === 1 and secret_owner === the expected owner, then read .secrets:
if (envelope.version !== 1) throw new Error('Unsupported secret envelope version');
// (executor-side) require getAddress(envelope.secret_owner) === getAddress(expectedOwner)
const decrypted = envelope.secrets;
// decrypted = { API_KEY: 'sk-my-openai-key-here', WEBHOOK_SECRET: 'whsec_abc123' }

// Decrypt with a specific private key
const specificKey = '0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
const decryptedWithKey = JSON.parse(
  Buffer.from(decrypt(specificKey.slice(2), Buffer.from(hexToBytes(encryptedSecrets[0])))).toString('utf-8'),
).secrets;
```

## Secret Template Substitution

Executors perform template substitution by direct key-name replacement using the keys inside the envelope's inner `secrets` object. If your decrypted envelope is `{ "version": 1, "secret_owner": "0x...", "secrets": { "API_KEY": "sk-..." } }`, every literal `API_KEY` (a key of `.secrets`) substring in relevant request fields is replaced with `sk-...`.

Substitution is triggered by non-empty `encryptedSecrets` (not by `piiEnabled`).

Use distinctive secret keys (`OPENAI_API_KEY_PROD`) to avoid accidental substring collisions.

### RITHTTP1 post-hydration secrets

Legacy HTTP requests keep the direct key-name replacement documented below. A body prefixed with `RITHTTP1` uses a bounded structured pipeline instead:

1. decrypt the same owner-bound blobs and enforce the same owner/delegate/signature policy;
2. resolve and digest-check DA inputs through `storage:*` aliases;
3. splice the downloaded JSON values into exact `$ritual_da` nodes;
4. resolve `http:*` secret nodes and string markers across the hydrated document.

DA expansion is not recursive and secret values are terminal. RITHTTP1 does not support legacy PII mode, so set `piiEnabled=false`. This does not weaken secret privacy: the executor still decrypts inside its normal TEE flow, and credentials never enter the compact JSON template or StorageRef paths.

### RITHTTP1 encrypted DA artifacts

Do not conflate the two encrypted inputs:

| Input | Contains | Encryption and authorization |
|---|---|---|
| `encryptedSecrets` | Storage credentials, provider keys, injected values | Owner-bound envelope encrypted to the executor, plus owner signature and delegate policy |
| Encrypted DA artifact | Request content such as messages or tools | Random AES-GCM content DEK wrapped to 1–8 recipient keys; `InputRef` commits the ciphertext SHA-256 |

Both are needed when private request content lives in authenticated storage: `encryptedSecrets` lets the executor fetch the object and call the provider, while the artifact keeps content opaque to storage and non-recipient relays. The executor recipient key is required; a user recipient is optional for recovery. Verify the selected executor key from chain state before encrypting.

Output privacy is chosen explicitly on each `OutputPipe.recipientPublicKey`; empty bytes mean plaintext, including on CONTRACT. The outer user key does not encrypt pipes. See the private-I/O reference for RITPIPE1 bindings and separate stream/DA verification.

### Shared HTTP ABI (reuse in examples)

```typescript
import { parseAbiParameters } from 'viem';

const HTTP_CALL_ABI = parseAbiParameters([
  'address, address, address[], bytes[], uint256, bytes[], bytes,',
  'string, uint8, string[], string[], bytes, uint256, uint8, bool,',
  '(string, string, string)',
].join(''));
```

### In HTTP Headers

```typescript
import { toHex, encodeAbiParameters } from 'viem';
import type { Address } from 'viem';
import { encrypt } from 'eciesjs';

// 1. Encrypt your API key (wrapped in the owner-bound envelope) with the executor's public key.
//    See buildSecretEnvelope / buildSecretAuthorizationPayload under "Signature Format" below.
const secretJson = buildSecretEnvelope(account.address, { API_KEY: 'sk-live-abc123def456' });
const encryptedBuffer = encrypt(executorPublicKey.slice(2), Buffer.from(secretJson));
const encryptedSecrets = [`0x${Buffer.from(encryptedBuffer).toString('hex')}` as `0x${string}`];
// Sign the domain-separated authorization payload (NOT the raw ciphertext), as the OWNER.
const HTTP_USE_CONTEXT = 'precompile:0x0000000000000000000000000000000000000801';
const signature = await walletClient.signMessage({
  account: account.address,
  message: { raw: buildSecretAuthorizationPayload(784n, HTTP_USE_CONTEXT, executorAddress, account.address, encryptedSecrets[0]) },
});

// 2. Build HTTP request with template in headers using raw ABI encoding
const encoded = encodeAbiParameters(HTTP_CALL_ABI, [
  executorAddress as Address,                      // executor
  account.address as Address,                      // sponsor (RitualWallet account backing payment)
  [account.address] as Address[],                  // secretOwners (one non-zero owner per blob, parallel to encryptedSecrets)
  encryptedSecrets,                                // encryptedSecrets
  100n,                                            // ttl
  [signature],                                     // secretSignatures (one per blob)
  '0x',                                            // userPublicKey
  'https://api.openai.com/v1/chat/completions',   // url
  2,                                               // method (POST)
  ['Content-Type', 'Authorization'],               // headersKeys
  ['application/json', 'Bearer API_KEY'],          // headersValues — template substitution
  toHex(new TextEncoder().encode(JSON.stringify({
    model: 'gpt-4',
    messages: [{ role: 'user', content: 'Hello' }],
  }))),
  0n,                                              // dkmsKeyIndex (0 = not using dKMS)
  0,                                               // dkmsKeyFormat
  false,                                           // piiEnabled (independent from substitution)
  ['', '', ''],                                    // outputStorageRef (empty = inline output)
]);

// The executor decrypts API_KEY and replaces every literal API_KEY match
```

### In URL

```typescript
const encoded = encodeAbiParameters(HTTP_CALL_ABI, [
  executorAddress,
  account.address,                                  // sponsor
  [account.address],                                // secretOwners (parallel to encryptedSecrets)
  encryptedSecrets,
  100n,
  [signature],
  '0x',
  'https://api.example.com/data?key=API_KEY',      // Template in URL
  1,                                                // GET
  [], [],                                           // no extra headers
  '0x',                                // no body
  0n,                                               // dkmsKeyIndex
  0,                                                // dkmsKeyFormat
  false,                                            // piiEnabled (optional, unrelated)
  ['', '', ''],                                     // outputStorageRef (empty = inline output)
]);
```

### In Request Body

```typescript
import { toHex } from 'viem';

const encoded = encodeAbiParameters(HTTP_CALL_ABI, [
  executorAddress,
  account.address,                                  // sponsor
  [account.address],                                // secretOwners (parallel to encryptedSecrets)
  encryptedSecrets,
  100n,
  [signature],
  '0x',
  'https://api.example.com/webhook',
  2,                                               // POST
  ['Content-Type'], ['application/json'],
  toHex(new TextEncoder().encode(JSON.stringify({
    token: 'WEBHOOK_TOKEN',        // Template in body
    secret: 'WEBHOOK_SECRET',      // Multiple templates supported
    data: { message: 'Hello from Ritual' },
  }))),
  0n,                                               // dkmsKeyIndex
  0,                                                // dkmsKeyFormat
  false,                                            // piiEnabled (optional, unrelated)
  ['', '', ''],                                     // outputStorageRef (empty = inline output)
]);
```

### Multiple Secrets in One Request

```typescript
import { toHex } from 'viem';

import { encrypt } from 'eciesjs';

// Encrypt all secrets into a single owner-bound blob
const secretJson = buildSecretEnvelope(account.address, {
  OPENAI_KEY: 'sk-...',
  PINECONE_KEY: 'pc-...',
  CUSTOM_HEADER: 'my-value',
});
const encryptedBuffer = encrypt(executorPublicKey.slice(2), Buffer.from(secretJson));
const encryptedSecrets = [`0x${Buffer.from(encryptedBuffer).toString('hex')}` as `0x${string}`];
const HTTP_USE_CONTEXT = 'precompile:0x0000000000000000000000000000000000000801';
const signature = await walletClient.signMessage({
  account: account.address,
  message: { raw: buildSecretAuthorizationPayload(784n, HTTP_USE_CONTEXT, executorAddress, account.address, encryptedSecrets[0]) },
});

const encoded = encodeAbiParameters(HTTP_CALL_ABI, [
  executorAddress,
  account.address,                               // sponsor
  [account.address],                             // secretOwners (parallel to encryptedSecrets)
  encryptedSecrets,
  100n,
  [signature],
  '0x',
  'https://my-api.com/enrich',
  2,                                             // POST
  ['Authorization', 'X-Pinecone-Api-Key', 'X-Custom'],
  ['Bearer OPENAI_KEY', 'PINECONE_KEY', 'CUSTOM_HEADER'],
  toHex(new TextEncoder().encode(JSON.stringify({ query: 'Find similar documents' }))),
  0n,                                            // dkmsKeyIndex
  0,                                             // dkmsKeyFormat
  false,                                         // piiEnabled (optional, unrelated)
  ['', '', ''],                                  // outputStorageRef (empty = inline output)
]);
```

### Signature Format

The signature is NOT over the raw encrypted blob. Each blob's signature is an EIP-191
`personal_sign` over a **domain-separated authorization payload**, and the signer must be
the secret **owner** — the address placed in the new `secret_owners[i]` ABI slot. One
signature per blob. The payload is byte-identical to ritual-common `create_secret_signature` /
ritual-common `build_secret_authorization_payload` and Go `ReconstructSecretAuthorizationPreimage`.

Payload byte layout:
```
RITUAL_SECRET_AUTHORIZATION_V1            (domain, ASCII bytes, no length prefix)
|| uint16(len(use_context))               (big-endian, 2 bytes)
|| utf8(use_context)                      (per-precompile context string)
|| uint256(chain_id)                      (32 bytes, big-endian)
|| executor                              (20 bytes)
|| owner                                 (20 bytes, == secret_owners[i])
|| keccak256(encrypted_secrets[i])        (32 bytes)
```

`use_context` for the HTTP precompile is the exact string
`precompile:0x0000000000000000000000000000000000000801`. Per-precompile contexts prevent a
signature for one precompile from being replayed on another.

```typescript
import { getAddress, keccak256, concat, toBytes, numberToBytes } from 'viem';

// Owner-bound envelope mirroring ritual-common build_secret_envelope ({version:1,
// secret_owner, secrets}). The executor json-parses the decrypted bytes, so it is the
// version/owner-match that matter, not exact key ordering.
function buildSecretEnvelope(secretOwner: Address, secrets: Record<string, string>): string {
  return JSON.stringify({ secret_owner: getAddress(secretOwner), secrets, version: 1 });
}

// Domain-separated authorization payload that the OWNER personal-signs.
function buildSecretAuthorizationPayload(
  chainId: bigint,
  useContext: string,
  executor: Address,
  owner: Address,
  encryptedBlob: `0x${string}`,
): Uint8Array {
  const ctx = new TextEncoder().encode(useContext);
  return concat([
    new TextEncoder().encode('RITUAL_SECRET_AUTHORIZATION_V1'),
    numberToBytes(ctx.length, { size: 2 }),       // uint16 big-endian length
    ctx,
    numberToBytes(chainId, { size: 32 }),         // uint256 big-endian chain id
    toBytes(getAddress(executor)),                // 20 bytes
    toBytes(getAddress(owner)),                   // 20 bytes
    toBytes(keccak256(encryptedBlob)),            // 32 bytes
  ]);
}

// The executor expects EIP-191 personal_sign format over that payload.
const HTTP_USE_CONTEXT = 'precompile:0x0000000000000000000000000000000000000801';
const payload = buildSecretAuthorizationPayload(784n, HTTP_USE_CONTEXT, executorAddress, ownerAddress, encryptedSecretBytes);
const signature = await walletClient.signMessage({
  account: ownerAddress,                          // signer MUST be the secret owner
  message: { raw: payload },                      // sign the payload, NOT the raw ciphertext
});
// Returns 65-byte signature [R(32) || S(32) || V(1)]

// The executor recovers the signer over the SAME payload:
// hash = keccak256("\x19Ethereum Signed Message:\n" + len + payload)
// signer = ecrecover(hash, v, r, s)
// Verifies signer === secret_owners[i] (the explicit per-blob owner). Caller/delegate
// authorization is a separate downstream check via SecretsAccessControl: checkAccess is
// evaluated as (secret_owners[i], delegate), where the delegate is the caller/sender
// (job.SenderAddress), not the payment sponsor.
```

Do NOT use `eth_sign` or manual hashing — `signMessage` already applies the EIP-191 prefix.

`secretOwners`, `encryptedSecrets` and `secretSignatures` must be strictly parallel — equal length, and all three empty together when there are no secrets. For each blob provide one non-zero owner address and one signature. The chain rejects the request (Rust `CodecError` "secret_owners, encrypted_secrets and secret_signature arrays must have same length" / Go `DecodeBaseRequestFields` error / Python `validate_secret_arrays`) if the three lengths differ; empty owners (zero address), empty blobs, or empty signatures at any populated index are also rejected.

### Secret Reference Format

Use secret key names directly (for example `API_KEY`, `WEBHOOK_TOKEN`, `OPENAI_API_KEY`).

There is no required `{{...}}` wrapper syntax for Ritual template substitution.

### Debugging Silent Failures

Secret template transactions can fail silently. Common causes:

1. **Empty `encryptedSecrets`**: If `encryptedSecrets` is empty, no substitution runs and your request sends literal placeholders.

2. **Signature mismatch**: The executor recovers the signer of each signature over the domain-separated authorization payload. If the recovered address doesn't match `secret_owners[i]` (the explicit per-blob owner), the blob is rejected. Caller/delegate authorization is a separate downstream check via `SecretsAccessControl` (`checkAccess(secret_owners[i], delegate)`, where the delegate is the caller/sender). Denied access returns HTTP 402 in the executor response (not a revert).

3. **Check the receipt for errors**: Executor errors appear in the settled transaction receipt, not as reverts:
```typescript
const receipt = await publicClient.waitForTransactionReceipt({ hash });
const spcCalls = (receipt as any).spcCalls;
if (spcCalls?.[0]) {
  const [statusCode, , , body, errorMessage] = decodeAbiParameters(
    [{ type: 'uint16' }, { type: 'string[]' }, { type: 'string[]' }, { type: 'bytes' }, { type: 'string' }],
    spcCalls[0].output
  );
  if (errorMessage) console.error('Executor error:', errorMessage);
  if (statusCode >= 400) console.error('HTTP error:', statusCode);
}
```

### Complete Example: Authenticated API Call with Secrets

```typescript
import { createWalletClient, createPublicClient, http, defineChain, encodeAbiParameters, decodeAbiParameters } from 'viem';
import type { Hex } from 'viem';
import { privateKeyToAccount } from 'viem/accounts';
import { encrypt } from 'eciesjs';

// 1. Encrypt an owner-bound secret envelope with executor's public key (ECIES).
//    buildSecretEnvelope wraps the map as {version:1, secret_owner, secrets} (canonical JSON).
const secretJson = buildSecretEnvelope(account.address, { API_KEY: 'sk-your-api-key' });
const encryptedBuffer = encrypt(executorPublicKey.slice(2), Buffer.from(secretJson));
const encryptedSecret = `0x${Buffer.from(encryptedBuffer).toString('hex')}` as `0x${string}`;

// 2. Sign the domain-separated authorization payload as the OWNER (not the raw blob).
//    The envelope owner and the secret_owners[i] passed below must agree.
const HTTP_USE_CONTEXT = 'precompile:0x0000000000000000000000000000000000000801';
const signature = await walletClient.signMessage({
  account,
  message: { raw: buildSecretAuthorizationPayload(784n, HTTP_USE_CONTEXT, executorAddress, account.address, encryptedSecret) },
});

// 3. Encode the precompile input (16 fields)
const input = encodeAbiParameters(
  [
    { type: 'address' }, { type: 'address' }, { type: 'address[]' }, { type: 'bytes[]' }, { type: 'uint256' },
    { type: 'bytes[]' }, { type: 'bytes' },
    { type: 'string' }, { type: 'uint8' }, { type: 'string[]' },
    { type: 'string[]' }, { type: 'bytes' }, { type: 'uint256' },
    { type: 'uint8' }, { type: 'bool' }, { type: 'tuple', components: [{ type: 'string' }, { type: 'string' }, { type: 'string' }] },
  ],
  [
    executorAddress,
    account.address,         // sponsor (RitualWallet account backing payment)
    [account.address],       // secretOwners (one owner per blob, parallel to encryptedSecrets)
    [encryptedSecret],       // encrypted secrets array
    100n,                     // TTL in blocks
    [signature],              // signatures array
    '0x',                     // userPublicKey (empty if no response encryption)
    'https://api.example.com/data',
    1,                        // GET
    ['Authorization'],
    ['Bearer API_KEY'],        // key-name placeholder
    '0x',                     // empty body for GET
    0n,                       // dkmsKeyIndex (0 = not using dKMS)
    0,                        // dkmsKeyFormat
    false,                    // piiEnabled (optional, unrelated)
    ['', '', ''],             // outputStorageRef (empty = inline output)
  ]
);

// 4. Submit transaction
const hash = await walletClient.sendTransaction({
  to: '0x0000000000000000000000000000000000000801',
  data: input,
  gas: 3_000_000n,
});

// 5. Wait for settlement and decode result
const receipt = await publicClient.waitForTransactionReceipt({ hash });
const spcCalls = (receipt as any).spcCalls;
const [statusCode, headerKeys, headerValues, body, errorMessage] = decodeAbiParameters(
  [{ type: 'uint16' }, { type: 'string[]' }, { type: 'string[]' }, { type: 'bytes' }, { type: 'string' }],
  spcCalls[0].output
);

const bodyText = new TextDecoder().decode(Buffer.from((body as string).slice(2), 'hex'));
console.log('Response:', JSON.parse(bodyText));
```

## Private Execution Outputs

Normally, precompile results are visible on-chain to anyone. Private outputs use an ephemeral keypair so only the requester can decrypt the result.

### How It Works

```
1. User generates ephemeral keypair (publicKey, privateKey)
2. User includes publicKey in the precompile request
3. Executor encrypts the output with user's publicKey
4. Encrypted output is stored/returned on-chain
5. Only the user (with privateKey) can decrypt the result
```

### Generate Ephemeral Keypair

```typescript
import { PrivateKey, PublicKey } from 'eciesjs';

function generateKeyPair(): { publicKey: `0x${string}`; privateKey: `0x${string}` } {
  const sk = new PrivateKey();
  const pk = sk.publicKey;

  return {
    publicKey: `0x${pk.toHex(false)}` as `0x${string}`,
    privateKey: `0x${sk.toHex()}` as `0x${string}`,
  };
}

const { publicKey: userPublicKey, privateKey: userPrivateKey } = generateKeyPair();
```

### Submit Request with Private Output

```typescript
import { encodeAbiParameters } from 'viem';

// Generate keypair for this request
const { publicKey: userPublicKey, privateKey: userPrivateKey } = generateKeyPair();

// Reuse HTTP_CALL_ABI from "Shared HTTP ABI" above

// Include userPublicKey so executor encrypts the response
const encoded = encodeAbiParameters(HTTP_CALL_ABI, [
  executorAddress,
  account.address, // sponsor (RitualWallet account backing payment)
  [],              // secretOwners (all three secret arrays empty together when no secrets)
  [],              // encryptedSecrets
  100n,            // ttl
  [],              // secretSignatures
  userPublicKey,   // Executor encrypts output with this key
  'https://api.example.com/sensitive-data',
  1,               // GET
  [], [],          // no extra headers
  '0x',
  0n,              // dkmsKeyIndex
  0,               // dkmsKeyFormat
  false,           // piiEnabled — set to true only for PII redaction
  ['', '', ''],    // outputStorageRef (empty = inline output)
]);

// ... submit to precompile

// Later, when result arrives:
// const encryptedResult = <result from chain>;
// const decrypted = decryptOutput(encryptedResult, userPrivateKey);
```

### Decrypt Private Output

```typescript
import { decrypt } from 'eciesjs';
import { hexToBytes, bytesToString, type Hex } from 'viem';

function decryptOutput(encryptedHex: Hex, privateKeyHex: string): string {
  const clean = privateKeyHex.startsWith('0x')
    ? privateKeyHex.slice(2)
    : privateKeyHex;

  const encryptedBytes = hexToBytes(encryptedHex);
  const decryptedBuffer = decrypt(clean, Buffer.from(encryptedBytes));

  return Buffer.from(decryptedBuffer).toString('utf-8');
}

// Usage after receiving encrypted response from chain
const plaintext = decryptOutput(encryptedResponseHex, userPrivateKey);
const data = JSON.parse(plaintext);
console.log('Private result:', data);
```

### Private Horoscope Pattern (End-to-End)

Based on the `private-horoscope` prototype — a complete flow where the user's horoscope is encrypted so only they can read it.

```typescript
import { encodeAbiParameters, decodeAbiParameters, hexToBytes, toHex } from 'viem';
import type { Hex } from 'viem';
import { PrivateKey, encrypt, decrypt } from 'eciesjs';

// Reuse HTTP_CALL_ABI from "Shared HTTP ABI" above

async function getPrivateHoroscope(zodiacSign: string) {
  // 1. Generate ephemeral keypair
  const sk = new PrivateKey();
  const userPublicKey = `0x${sk.publicKey.toHex(false)}` as Hex;
  const userPrivateKey = sk.toHex();

  // 2. Encrypt API key (owner-bound envelope) for the executor using ECIES
  const secretJson = buildSecretEnvelope(account.address, { HOROSCOPE_API_KEY: process.env.HOROSCOPE_API_KEY! });
  const encryptedBuffer = encrypt(
    (executorPublicKey as string).slice(2),
    Buffer.from(secretJson),
  );
  const encryptedSecrets = [`0x${Buffer.from(encryptedBuffer).toString('hex')}` as `0x${string}`];
  // Sign the domain-separated authorization payload as the OWNER.
  const HTTP_USE_CONTEXT = 'precompile:0x0000000000000000000000000000000000000801';
  const signature = await walletClient.signMessage({
    account: account.address,
    message: { raw: buildSecretAuthorizationPayload(784n, HTTP_USE_CONTEXT, executorAddress, account.address, encryptedSecrets[0]) },
  });

  // 3. Build request with both secrets AND private output key
  const encoded = encodeAbiParameters(HTTP_CALL_ABI, [
    executorAddress,
    account.address, // sponsor
    [account.address], // secretOwners (parallel to encryptedSecrets)
    encryptedSecrets,
    100n,
    [signature],
    userPublicKey,   // Output will be encrypted with this
    `https://api.horoscope.com/v1/daily?sign=${zodiacSign}`,
    1,               // GET
    ['Authorization'],
    ['Bearer HOROSCOPE_API_KEY'],
    '0x',
    0n,              // dkmsKeyIndex
    0,               // dkmsKeyFormat
    false,           // piiEnabled (optional, unrelated)
    ['', '', ''],    // outputStorageRef (empty = inline output)
  ]);

  // 4. Submit to precompile
  // ... submit transaction and wait for result

  // 5. Read actualOutput from this transaction's settled HTTP SPC receipt.
  // const [ciphertext] = decodeAbiParameters([{ type: 'bytes' }], actualOutput);
  // const plaintext = decrypt(userPrivateKey, hexToBytes(ciphertext));
  // const [, , , body, errorMessage] = decodeAbiParameters(
  //   [{ type: 'uint16' }, { type: 'string[]' }, { type: 'string[]' }, { type: 'bytes' }, { type: 'string' }],
  //   toHex(plaintext),
  // );
  // if (errorMessage) throw new Error(errorMessage);
  // return JSON.parse(new TextDecoder().decode(hexToBytes(body)));
}
```

## Delegated Secret Sharing

The SecretsAccessControl contract allows a secret owner to grant other addresses (delegates) permission to use their encrypted secrets. This enables patterns like:

- A DAO treasury granting a smart contract access to shared API keys
- A user delegating their secrets to a consumer contract for a limited time
- An organization sharing credentials across multiple contracts with expiration

### Contract Address

```
SecretsAccessControl: 0x0cEae62e2082829226eF5821Bb662483Db17A71F
```

### Grant Access

```typescript
import { createWalletClient, http, defineChain, keccak256, toBytes } from 'viem';
import { privateKeyToAccount } from 'viem/accounts';
import type { Address, Hex } from 'viem';
import { encrypt } from 'eciesjs';

const ritualChain = defineChain({
  id: 784,
  name: 'Ritual',
  nativeCurrency: { name: 'RITUAL', symbol: 'RITUAL', decimals: 18 },
  rpcUrls: { default: { http: [process.env.RITUAL_RPC_URL!] } },
});
const account = privateKeyToAccount(process.env.PRIVATE_KEY! as `0x${string}`);
const walletClient = createWalletClient({ account, chain: ritualChain, transport: http() });

const SECRETS_AC = '0x0cEae62e2082829226eF5821Bb662483Db17A71F' as const;
const contractAddress = '0x1111111111111111111111111111111111111111' as Address;

// Encrypt the owner-bound envelope and compute hash. secret_owner is the delegating
// owner; it must equal the secret_owners[i] presented at request time. The secretsHash
// is computed over the encrypted envelope ciphertext.
const secretJson = buildSecretEnvelope(account.address, { API_KEY: 'sk-my-key' });
const encryptedBuffer = encrypt(executorPublicKey.slice(2), Buffer.from(secretJson));
const encryptedHex = `0x${Buffer.from(encryptedBuffer).toString('hex')}` as Hex;
const secretsHash = keccak256(toBytes(encryptedHex));

// IMPORTANT: expiresAt is a BLOCK NUMBER, not a Unix timestamp.
// The contract checks block.number >= expiresAt.
const currentBlock = await publicClient.getBlockNumber();
const BLOCKS_PER_DAY = 246_858n; // ~24h at ~350ms block-time baseline
const expiresAt = currentBlock + BLOCKS_PER_DAY;

// Grant access on-chain with an empty policy (no restrictions)
// SecretsAccessPolicy fields: allowedDestinations, allowedMethods, allowedPaths,
//   allowedQueryParams, allowedHeaders, secretLocation, bodyFormat
// Pass empty arrays and empty strings for unrestricted access.
const emptyPolicy = {
  allowedDestinations: [],
  allowedMethods: [],
  allowedPaths: [],
  allowedQueryParams: [],
  allowedHeaders: [],
  secretLocation: '',
  bodyFormat: '',
};

const txHash = await walletClient.writeContract({
  address: SECRETS_AC,
  abi: [{
    name: 'grantAccess',
    type: 'function',
    stateMutability: 'nonpayable',
    inputs: [
      { name: 'delegate', type: 'address' },
      { name: 'secretsHash', type: 'bytes32' },
      { name: 'expiresAt', type: 'uint256' },
      {
        name: 'policy',
        type: 'tuple',
        components: [
          { name: 'allowedDestinations', type: 'string[]' },
          { name: 'allowedMethods', type: 'string[]' },
          { name: 'allowedPaths', type: 'string[]' },
          { name: 'allowedQueryParams', type: 'string[]' },
          { name: 'allowedHeaders', type: 'string[]' },
          { name: 'secretLocation', type: 'string' },
          { name: 'bodyFormat', type: 'string' },
        ],
      },
    ],
    outputs: [],
  }] as const,
  functionName: 'grantAccess',
  args: [contractAddress, secretsHash, expiresAt, emptyPolicy],
});

console.log('Access granted. Secrets hash:', secretsHash);
console.log('Transaction:', txHash);
```

### Grant Access with Pre-Computed Hash

If you've already encrypted and hashed your secrets:

```typescript
const emptyPolicy = {
  allowedDestinations: [],
  allowedMethods: [],
  allowedPaths: [],
  allowedQueryParams: [],
  allowedHeaders: [],
  secretLocation: '',
  bodyFormat: '',
};

const txHash = await walletClient.writeContract({
  address: SECRETS_AC,
  abi: [{
    name: 'grantAccess',
    type: 'function',
    stateMutability: 'nonpayable',
    inputs: [
      { name: 'delegate', type: 'address' },
      { name: 'secretsHash', type: 'bytes32' },
      { name: 'expiresAt', type: 'uint256' },
      {
        name: 'policy',
        type: 'tuple',
        components: [
          { name: 'allowedDestinations', type: 'string[]' },
          { name: 'allowedMethods', type: 'string[]' },
          { name: 'allowedPaths', type: 'string[]' },
          { name: 'allowedQueryParams', type: 'string[]' },
          { name: 'allowedHeaders', type: 'string[]' },
          { name: 'secretLocation', type: 'string' },
          { name: 'bodyFormat', type: 'string' },
        ],
      },
    ],
    outputs: [],
  }] as const,
  functionName: 'grantAccess',
  args: [contractAddress, secretsHash, expiresAt, emptyPolicy],
});
```

### Grant Access with Restrictive Policy

Restrict how your secrets can be used by filling in the `SecretsAccessPolicy` fields:

```typescript
const restrictivePolicy = {
  allowedDestinations: ['api.twitter.com'],           // Host allowlist (no scheme)
  allowedMethods: ['POST'],                           // Only POST requests
  allowedPaths: ['/2/tweets'],                        // Only the tweet endpoint
  allowedQueryParams: [],                             // No query param restrictions
  allowedHeaders: ['Content-Type', 'Authorization'],  // Only these headers
  secretLocation: 'header',                           // Secret injected into headers
  bodyFormat: 'json',                                 // Allowed values: json | xml | form
};

const txHash = await walletClient.writeContract({
  address: SECRETS_AC,
  abi: [{
    name: 'grantAccess',
    type: 'function',
    stateMutability: 'nonpayable',
    inputs: [
      { name: 'delegate', type: 'address' },
      { name: 'secretsHash', type: 'bytes32' },
      { name: 'expiresAt', type: 'uint256' },
      {
        name: 'policy',
        type: 'tuple',
        components: [
          { name: 'allowedDestinations', type: 'string[]' },
          { name: 'allowedMethods', type: 'string[]' },
          { name: 'allowedPaths', type: 'string[]' },
          { name: 'allowedQueryParams', type: 'string[]' },
          { name: 'allowedHeaders', type: 'string[]' },
          { name: 'secretLocation', type: 'string' },
          { name: 'bodyFormat', type: 'string' },
        ],
      },
    ],
    outputs: [],
  }] as const,
  functionName: 'grantAccess',
  args: [contractAddress, secretsHash, expiresAt, restrictivePolicy],
});
```

### Check Access

`checkAccess` returns both a boolean and the `SecretsAccessPolicy` associated with the grant:

```typescript
const SECRETS_AC = '0x0cEae62e2082829226eF5821Bb662483Db17A71F' as const;

const [hasAccess, policy] = await publicClient.readContract({
  address: SECRETS_AC,
  abi: [{
    name: 'checkAccess',
    type: 'function',
    stateMutability: 'view',
    inputs: [
      { name: 'owner', type: 'address' },
      { name: 'delegate', type: 'address' },
      { name: 'secretsHash', type: 'bytes32' },
    ],
    outputs: [
      { name: 'hasAccess', type: 'bool' },
      {
        name: 'policy',
        type: 'tuple',
        components: [
          { name: 'allowedDestinations', type: 'string[]' },
          { name: 'allowedMethods', type: 'string[]' },
          { name: 'allowedPaths', type: 'string[]' },
          { name: 'allowedQueryParams', type: 'string[]' },
          { name: 'allowedHeaders', type: 'string[]' },
          { name: 'secretLocation', type: 'string' },
          { name: 'bodyFormat', type: 'string' },
        ],
      },
    ],
  }] as const,
  functionName: 'checkAccess',
  args: [account.address, contractAddress, secretsHash],
});

console.log('Has access:', hasAccess);
console.log('Policy destinations:', policy.allowedDestinations);
```

### Revoke Access

```typescript
const txHash = await walletClient.writeContract({
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
  args: [contractAddress, secretsHash],
});

console.log('Access revoked:', txHash);
```

### Never-Expiring Access

Pass the max uint256 value for `expiresAt` if you intentionally want non-expiring access:

```typescript
const MAX_UINT256 =
  115792089237316195423570985008687907853269984665640564039457584007913129639935n;

const emptyPolicy = {
  allowedDestinations: [],
  allowedMethods: [],
  allowedPaths: [],
  allowedQueryParams: [],
  allowedHeaders: [],
  secretLocation: '',
  bodyFormat: '',
};

const hash = await walletClient.writeContract({
  address: SECRETS_AC,
  abi: [{
    name: 'grantAccess',
    type: 'function',
    stateMutability: 'nonpayable',
    inputs: [
      { name: 'delegate', type: 'address' },
      { name: 'secretsHash', type: 'bytes32' },
      { name: 'expiresAt', type: 'uint256' },
      {
        name: 'policy',
        type: 'tuple',
        components: [
          { name: 'allowedDestinations', type: 'string[]' },
          { name: 'allowedMethods', type: 'string[]' },
          { name: 'allowedPaths', type: 'string[]' },
          { name: 'allowedQueryParams', type: 'string[]' },
          { name: 'allowedHeaders', type: 'string[]' },
          { name: 'secretLocation', type: 'string' },
          { name: 'bodyFormat', type: 'string' },
        ],
      },
    ],
    outputs: [],
  }] as const,
  functionName: 'grantAccess',
  args: [contractAddress, secretsHash, MAX_UINT256, emptyPolicy], // never expires, no restrictions
});
```

### Using Delegated Secrets as a Delegate

The owner encrypts secrets (owner-bound envelope), grants you access via `grantAccess`, and shares the encrypted blob, their address, and their EIP-191 signature (over the domain-separated authorization payload) off-chain. Your transaction includes these in the precompile call — declaring the owner explicitly in `secretOwners`:

```typescript
// ownerEncryptedSecrets and ownerSignature are provided by the secret owner.
// ownerAddress is the secret owner's address, declared explicitly in secretOwners.
const encoded = encodeAbiParameters(HTTP_CALL_ABI, [
  executorAddress,
  account.address,           // sponsor (the delegate's RitualWallet account backing payment)
  [ownerAddress],            // secretOwners — the explicit per-blob owner(s), parallel to ownerEncryptedSecrets
  ownerEncryptedSecrets,     // the owner's encrypted blob (unchanged)
  100n,
  [ownerSignature],          // owner's EIP-191 signature over the authorization payload — REQUIRED for delegation
  '0x',
  'https://api.example.com/data',
  1,                         // GET
  ['Authorization'],
  ['Bearer API_KEY'],
  '0x',
  0n,                        // dkmsKeyIndex
  0,                         // dkmsKeyFormat
  false,                     // piiEnabled (optional, unrelated)
  ['', '', ''],              // outputStorageRef (empty = inline output)
]);

// sponsor = the RitualWallet payer (here, your EOA). It may be different from
// the delegate. For mediated calls, the consuming contract is the delegate
// because it is the immediate precompile caller; the payer may be another
// contract such as a sponsor vault.
// The executor:
//   1. Reads the owner from secretOwners[i] and verifies ownerSignature[i]
//      recovers to that owner over the domain-separated authorization payload
//   2. Calls checkAccess(secretOwners[i], delegate, secretsHash), where the
//      delegate is the caller/sender (not the payment sponsor)
//   3. If granted and not expired, proceeds with decryption
const hash = await walletClient.sendTransaction({
  to: '0x0000000000000000000000000000000000000801',
  data: encoded,
  gas: 3_000_000n,
});
```

### Delegation Workflow

```
  ┌────────────┐                ┌───────────────────────┐
  │ Secret     │  grantAccess   │ SecretsAccessControl  │
  │ Owner      │ ─────────────→ │ Contract              │
  │            │  (+policy)     │                       │
  │ (encrypts  │  revokeAccess  │ Stores:               │
  │  secrets,  │ ─────────────→ │ owner → delegate →    │
  │  sets      │                │ secretsHash → expiry  │
  │  expiry,   │                │ + SecretsAccessPolicy │
  │  policy)   │                └───────────┬───────────┘
  └────────────┘                            │
                                checkAccess │
                                            ▼
  ┌────────────────┐            ┌───────────────────────┐
  │ Consumer       │  uses      │ TEE Executor          │
  │ Contract       │ ─────────→ │                       │
  │ (delegate)     │  secrets   │ Verifies delegation   │
  │                │            │ before decrypting     │
  └────────────────┘            └───────────────────────┘
```

### End-to-End Role Topologies

| Topology | Secret owner | Delegate (immediate precompile caller) | Sponsor | Important consequence |
|---|---|---|---|---|
| User-owned secret through a router | Owner EOA | Router contract | Separate sponsor vault | An upstream buyer or caller does not gain secret access; the owner grants the router and signs each executor-bound blob |
| Scheduled manager request | Owner EOA | Manager contract | Manager contract | The Scheduler transports the typed callback, but the manager remains the delegate when it invokes the async precompile |

Do not implement an EOA-owned grant extension through a registry or manager contract. When that contract calls `grantAccess`, `msg.sender` is the contract, so the grant is written in the contract's owner namespace rather than the original EOA owner's namespace. The EOA owner must submit the re-grant.

## Solidity Contract with Secrets

### Consumer Contract Using Delegated Secrets

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

interface ISecretsAccessControl {
    struct SecretsAccessPolicy {
        string[] allowedDestinations;
        string[] allowedMethods;
        string[] allowedPaths;
        string[] allowedQueryParams;
        string[] allowedHeaders;
        string secretLocation;
        string bodyFormat;
    }

    function grantAccess(
        address delegate,
        bytes32 secretsHash,
        uint256 expiresAt,
        SecretsAccessPolicy calldata policy
    ) external;

    function revokeAccess(address delegate, bytes32 secretsHash) external;

    function checkAccess(
        address owner,
        address delegate,
        bytes32 secretsHash
    ) external view returns (bool hasAccess, SecretsAccessPolicy memory policy);
}

interface IRitualWallet {
    function availableBalance(address account) external view returns (uint256);
    function deposit() external payable;
}

contract SecretConsumer {
    ISecretsAccessControl public constant SECRETS_AC =
        ISecretsAccessControl(0x0cEae62e2082829226eF5821Bb662483Db17A71F);

    IRitualWallet public constant RITUAL_WALLET =
        IRitualWallet(0xF04076756d8129Baec46Dc0F1c526Baec490C393);

    address public constant HTTP_PRECOMPILE =
        0x0000000000000000000000000000000000000801;

    address public owner;
    bytes32 public secretsHash;

    event ResponseReceived(bytes actualOutput);
    event SecretHashUpdated(bytes32 oldHash, bytes32 newHash);

    modifier onlyOwner() {
        require(msg.sender == owner, "Not owner");
        _;
    }

    constructor(bytes32 _secretsHash) {
        owner = msg.sender;
        secretsHash = _secretsHash;
    }

    function verifySecretAccess() public view returns (bool) {
        (bool hasAccess,) = SECRETS_AC.checkAccess(
            owner,
            address(this),
            secretsHash
        );
        return hasAccess;
    }

    function makeSecretRequest(
        bytes calldata encodedRequest
    ) external onlyOwner {
        require(verifySecretAccess(), "No secret access");

        uint256 balance = RITUAL_WALLET.availableBalance(address(this));
        require(balance > 0, "Deposit required");

        (bool success, bytes memory result) = HTTP_PRECOMPILE.call(
            encodedRequest
        );
        require(success, "Precompile call failed");

        (, bytes memory actualOutput) = abi.decode(result, (bytes, bytes));
        emit ResponseReceived(actualOutput);
    }

    function updateSecretsHash(bytes32 _newHash) external onlyOwner {
        bytes32 oldHash = secretsHash;
        secretsHash = _newHash;
        emit SecretHashUpdated(oldHash, _newHash);
    }

    function deposit() external payable {
        RITUAL_WALLET.deposit{value: msg.value}();
    }

    receive() external payable {
        RITUAL_WALLET.deposit{value: msg.value}();
    }
}
```

### DAO Shared Secrets Contract

> **Warning: This pattern is broken as-written.** When `DAOSecretManager` calls `SECRETS_AC.grantAccess()`, `msg.sender` is the contract — not the admin EOA. The grant is stored under the contract's address. But the secret blob declares the admin EOA as its `secret_owners[i]`, and the executor verifies the EIP-191 signature (over the domain-separated authorization payload) recovers to that admin EOA, then calls `checkAccess(adminEOA, consumer, hash)` — which returns `false` because the grant is under the contract, not the admin EOA. Contracts cannot produce EIP-191 owner signatures, so this mismatch cannot be resolved. **Fix:** Have the admin EOA call `grantAccess` directly instead of through a contract intermediary.

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

interface ISecretsAccessControl {
    struct SecretsAccessPolicy {
        string[] allowedDestinations;
        string[] allowedMethods;
        string[] allowedPaths;
        string[] allowedQueryParams;
        string[] allowedHeaders;
        string secretLocation;
        string bodyFormat;
    }

    function grantAccess(
        address delegate,
        bytes32 secretsHash,
        uint256 expiresAt,
        SecretsAccessPolicy calldata policy
    ) external;

    function revokeAccess(address delegate, bytes32 secretsHash) external;

    function checkAccess(
        address owner,
        address delegate,
        bytes32 secretsHash
    ) external view returns (bool hasAccess, SecretsAccessPolicy memory policy);
}

contract DAOSecretManager {
    ISecretsAccessControl public constant SECRETS_AC =
        ISecretsAccessControl(0x0cEae62e2082829226eF5821Bb662483Db17A71F);

    address public admin;
    mapping(bytes32 => bool) public registeredSecrets;
    mapping(address => bool) public authorizedConsumers;

    event SecretRegistered(bytes32 indexed secretsHash);
    event ConsumerAuthorized(address indexed consumer);
    event ConsumerRevoked(address indexed consumer);

    modifier onlyAdmin() {
        require(msg.sender == admin, "Not admin");
        _;
    }

    constructor() {
        admin = msg.sender;
    }

    function registerSecret(bytes32 _secretsHash) external onlyAdmin {
        registeredSecrets[_secretsHash] = true;
        emit SecretRegistered(_secretsHash);
    }

    function authorizeConsumer(address consumer) external onlyAdmin {
        authorizedConsumers[consumer] = true;
        emit ConsumerAuthorized(consumer);
    }

    function revokeConsumer(address consumer) external onlyAdmin {
        authorizedConsumers[consumer] = false;
        emit ConsumerRevoked(consumer);
    }

    /// @notice Grant a consumer access to a secret with an empty (unrestricted) policy
    function grantConsumerAccess(
        address consumer,
        bytes32 _secretsHash,
        uint256 expiresAt
    ) external onlyAdmin {
        ISecretsAccessControl.SecretsAccessPolicy memory emptyPolicy;
        SECRETS_AC.grantAccess(consumer, _secretsHash, expiresAt, emptyPolicy);
    }

    function canConsumerUseSecret(
        address consumer,
        bytes32 secretsHash
    ) external view returns (bool) {
        if (!authorizedConsumers[consumer]) return false;
        if (!registeredSecrets[secretsHash]) return false;

        (bool hasAccess,) = SECRETS_AC.checkAccess(
            admin,
            consumer,
            secretsHash
        );

        return hasAccess;
    }
}
```

### Private Output Consumer

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract PrivateOutputConsumer {
    address public constant HTTP_PRECOMPILE =
        0x0000000000000000000000000000000000000801;

    event PrivateResultReady(address indexed requester, bytes encryptedResult);

    function submitPrivateRequest(bytes calldata encodedRequest) external {
        (bool success, bytes memory result) = HTTP_PRECOMPILE.call(encodedRequest);
        require(success, "Precompile call failed");

        // Short-running HTTP returns its settled output inline, without a callback.
        (, bytes memory actualOutput) = abi.decode(result, (bytes, bytes));
        bytes memory encryptedResult = abi.decode(actualOutput, (bytes));
        emit PrivateResultReady(msg.sender, encryptedResult);
    }
}
```


## Security Checklist

1. **Never put raw secrets in transactions** — always ECIES-encrypt to executor's public key. Use key-name placeholders (for example `API_KEY`), never literal values.
2. **ECIES nonce must be 12** — set `ECIES_CONFIG.symmetricNonceLength = 12` before any secret encryption. Do not use 16.
3. **Fetch executor public key from TEEServiceRegistry** — never hardcode it. Use `getServicesByCapability(0, true)` as shown in "Encrypt Secrets" section.
4. **`expiresAt` is a block number, not a timestamp** — use `currentBlock + 10_286n` (~1h) or `currentBlock + 246_858n` (~24h) at ~350ms baseline. Confirm with recent block measurements via `ritual-dapp-block-time`.
5. **Rotate secrets** by granting access with the new hash, then revoking the old hash in separate transactions.
6. **Generate fresh ephemeral keypairs** for each private output request — never reuse.
7. **Sign every encrypted blob with the owner's key** — a per-blob owner signature is REQUIRED for every non-empty encrypted blob (not only when the owner differs from the caller). The executor validates each signature against the explicitly declared `secret_owners[i]` (the owner), over the context-, chain-, executor-, owner-, and ciphertext-bound authorization payload — never against the sponsor or `tx.origin`.
8. **Grant the immediate precompile caller** — caller/delegate authorization is separate from payment. For mediated async calls the router/manager contract that invokes the precompile must hold the grant. A sponsor vault, buyer, scheduler, or upstream EOA does not need the grant unless it is itself the immediate precompile caller.
9. **The owner must submit its own grant** — `grantAccess` writes under `msg.sender`. A registry or manager contract cannot grant or extend an EOA's secret ownership on that EOA's behalf. Have the owner EOA submit the grant/re-grant transaction.


## Key Addresses

| Contract | Address |
|----------|---------|
| SecretsAccessControl | `0x0cEae62e2082829226eF5821Bb662483Db17A71F` |
| TEEServiceRegistry | `0xf4495DC72143D44A93AB0ecE4d6D63a216b27839` |
| RitualWallet | `0xF04076756d8129Baec46Dc0F1c526Baec490C393` |

## Quick Reference

```typescript
// Setup — viem + eciesjs
import { defineChain, createPublicClient, createWalletClient, http, keccak256, toBytes } from 'viem';
import { privateKeyToAccount } from 'viem/accounts';
import { encrypt, decrypt, ECIES_CONFIG } from 'eciesjs';

const SECRETS_AC = '0x0cEae62e2082829226eF5821Bb662483Db17A71F' as const;
const TEE_SERVICE_REGISTRY = '0xf4495DC72143D44A93AB0ecE4d6D63a216b27839' as const;

// Mandatory for Ritual encrypted-secret compatibility. Do NOT use 16.
ECIES_CONFIG.symmetricNonceLength = 12;

// Encrypt secrets: secretsJson must be the owner-bound envelope {version:1, secret_owner:<owner>, secrets:{...}}
//   (canonical JSON, sorted keys) → encrypt(executorPubKey, secretsJson) via eciesjs.
//   The request carries a parallel secret_owners address[] (one owner per blob) matching the envelope owner.
// Compute hash: keccak256(toBytes(encryptedHex))
// Signatures: one signature per encrypted blob over the domain-separated authorization payload
//   (RITUAL_SECRET_AUTHORIZATION_V1 || uint16(len(useContext)) || useContext || uint256(chainId) || executor || owner || keccak256(blob)),
//   personal-signed by the blob OWNER via signMessage({ message: { raw: payload } }). useContext is per-precompile,
//   e.g. 'precompile:0x0000000000000000000000000000000000000801' for HTTP. NOT a signature over the raw blob.
// Executor endpoint is not part of this flow; use executor address + public key only.

// Grant delegation: walletClient.writeContract on SECRETS_AC.grantAccess(delegate, hash, expiry, policy)
//   policy = { allowedDestinations: [], allowedMethods: [], allowedPaths: [],
//              allowedQueryParams: [], allowedHeaders: [], secretLocation: '', bodyFormat: '' }
//   Pass empty arrays/strings for unrestricted access.
// Check delegation: publicClient.readContract on SECRETS_AC.checkAccess(owner, delegate, hash)
//   Returns: [bool hasAccess, SecretsAccessPolicy policy]
// Revoke delegation: walletClient.writeContract on SECRETS_AC.revokeAccess(delegate, hash)

// Template substitution: use key names in URL, headers, or body (for example API_KEY)
// Executor decrypts and replaces matching key names at runtime
// piiEnabled is independent; keep false unless you explicitly need PII redaction
// RITHTTP1: keep false; use storage:* aliases for DA credentials and http:* aliases for injected values.
// Expansion occurs after the executor hydrates exact {"$ritual_da":N} JSON nodes.

// HTTP precompile ABI (16 fields):
// (address executor, address sponsor, address[] secretOwners, bytes[] encryptedSecrets, uint256 ttl,
//  bytes[] secretSignatures, bytes userPublicKey, string url, uint8 method, string[] headersKeys,
//  string[] headersValues, bytes body, uint256 dkmsKeyIndex, uint8 dkmsKeyFormat,
//  bool piiEnabled, (string,string,string) outputStorageRef)

// Private output: include userPublicKey in the ABI-encoded request
// Executor encrypts response with that key
```

## Optional PII Redaction (`piiEnabled`)

Use `piiEnabled=true` only when you explicitly want PII redaction. Otherwise keep it `false`.

- `piiEnabled=true` requires `encryptedSecrets` + `userPublicKey`.
- For LLM calls, PII + streaming is incompatible.
- This flag is independent from secret injection/template substitution.

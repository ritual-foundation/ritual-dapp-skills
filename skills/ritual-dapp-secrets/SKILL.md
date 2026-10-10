---
name: ritual-dapp-secrets
description: Secret management and private outputs for Ritual dApps. Use when handling encrypted secrets, private execution results, or delegated access control.
version: 1.0.0
---

# Secret Management, Private I/O & Delegation

Encrypt secrets for executor-side injection, receive private execution outputs, and manage delegated access control for shared secrets on Ritual Chain.

> For storage credential formats (GCS, HuggingFace, Pinata) used in `encryptedSecrets`, see `ritual-dapp-da`.

## Read This First

Core path in this skill: encrypt `encryptedSecrets` to an executor public key, use template substitution, optionally set `userPublicKey` for encrypted outputs, and use delegation via `SecretsAccessControl`.

Template substitution runs whenever `encryptedSecrets` is non-empty.

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
│  │  Address: 0xf9BF1BC8A3e79B9EBeD0fa2Db70D0513fecE32FD    │   │
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
  id: 1979,
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
  id: 1979,
  name: 'Ritual',
  nativeCurrency: { name: 'RITUAL', symbol: 'RITUAL', decimals: 18 },
  rpcUrls: { default: { http: [process.env.RITUAL_RPC_URL!] } },
});
const publicClient = createPublicClient({ chain: ritualChain, transport: http() });

const TEE_SERVICE_REGISTRY = '0x9644e8562cE0Fe12b4deeC4163c064A8862Bf47F' as const;
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
if (services.length === 0) throw new Error('No active executors found');
const selected = services[0];

// Option B (already selected): set these directly instead of discovery
const executorAddress: Address = selected.node.teeAddress;
const executorPublicKey: Hex = selected.node.publicKey as Hex;

// Endpoint note: `node.endpoint` is NOT used for encryption/delegation.
// Secrets path uses executor address + executor public key.

const secretsJson = JSON.stringify({
  API_KEY: 'sk-my-openai-key-here',
  WEBHOOK_SECRET: 'whsec_abc123',
});
const encryptedBuffer = encrypt(executorPublicKey.slice(2), Buffer.from(secretsJson));
const encryptedSecrets: Hex[] = [`0x${encryptedBuffer.toString('hex')}`];
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
const decrypted = JSON.parse(decryptedBuffer.toString('utf-8'));
// Returns: { API_KEY: 'sk-my-openai-key-here', WEBHOOK_SECRET: 'whsec_abc123' }

// Decrypt with a specific private key
const specificKey = '0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
const decryptedWithKey = JSON.parse(
  decrypt(specificKey.slice(2), Buffer.from(hexToBytes(encryptedSecrets[0]))).toString('utf-8'),
);
```

## Secret Template Substitution

Executors perform template substitution by direct key-name replacement. If your decrypted secrets JSON contains `{ "API_KEY": "sk-..." }`, every literal `API_KEY` substring in relevant request fields is replaced with `sk-...`.

Substitution is triggered by non-empty `encryptedSecrets` (not by `piiEnabled`).

Use distinctive secret keys (`OPENAI_API_KEY_PROD`) to avoid accidental substring collisions.

### Shared HTTP ABI (reuse in examples)

```typescript
import { parseAbiParameters } from 'viem';

const HTTP_CALL_ABI = parseAbiParameters([
  'address, bytes[], uint256, bytes[], bytes,',
  'string, uint8, string[], string[], bytes, uint256, uint8, bool',
].join(''));
```

### In HTTP Headers

```typescript
import { encodeAbiParameters } from 'viem';
import type { Address } from 'viem';
import { encrypt } from 'eciesjs';

// 1. Encrypt your API key with the executor's public key
const secretJson = JSON.stringify({ API_KEY: 'sk-live-abc123def456' });
const encryptedBuffer = encrypt(executorPublicKey.slice(2), Buffer.from(secretJson));
const encryptedSecrets = [`0x${encryptedBuffer.toString('hex')}` as `0x${string}`];
const signature = await walletClient.signMessage({
  account: account.address,
  message: { raw: encryptedSecrets[0] },
});

// 2. Build HTTP request with template in headers using raw ABI encoding
const encoded = encodeAbiParameters(HTTP_CALL_ABI, [
  executorAddress as Address,                      // executor
  encryptedSecrets,                                // encryptedSecrets
  100n,                                            // ttl
  [signature],                                     // secretSignatures (one per blob)
  '0x',                                            // userPublicKey
  'https://api.openai.com/v1/chat/completions',   // url
  2,                                               // method (POST)
  ['Content-Type', 'Authorization'],               // headersKeys
  ['application/json', 'Bearer API_KEY'],          // headersValues — template substitution
  new TextEncoder().encode(JSON.stringify({
    model: 'gpt-4',
    messages: [{ role: 'user', content: 'Hello' }],
  })),
  0n,                                              // dkmsKeyIndex (disabled)
  0,                                               // dkmsKeyFormat (disabled)
  false,                                           // piiEnabled (independent from substitution)
]);

// The executor decrypts API_KEY and replaces every literal API_KEY match
```

### In URL

```typescript
const encoded = encodeAbiParameters(HTTP_CALL_ABI, [
  executorAddress,
  encryptedSecrets,
  100n,
  [signature],
  '0x',
  'https://api.example.com/data?key=API_KEY',      // Template in URL
  1,                                                // GET
  [], [],                                           // no extra headers
  new Uint8Array(0),                                // no body
  0n,                                               // dkmsKeyIndex (disabled)
  0,                                                // dkmsKeyFormat (disabled)
  false,                                            // piiEnabled (optional, unrelated)
]);
```

### In Request Body

```typescript
const encoded = encodeAbiParameters(HTTP_CALL_ABI, [
  executorAddress,
  encryptedSecrets,
  100n,
  [signature],
  '0x',
  'https://api.example.com/webhook',
  2,                                               // POST
  ['Content-Type'], ['application/json'],
  new TextEncoder().encode(JSON.stringify({
    token: 'WEBHOOK_TOKEN',        // Template in body
    secret: 'WEBHOOK_SECRET',      // Multiple templates supported
    data: { message: 'Hello from Ritual' },
  })),
  0n,                                               // dkmsKeyIndex (disabled)
  0,                                                // dkmsKeyFormat (disabled)
  false,                                            // piiEnabled (optional, unrelated)
]);
```

### Multiple Secrets in One Request

```typescript
import { encrypt } from 'eciesjs';

// Encrypt all secrets into a single blob
const secretJson = JSON.stringify({
  OPENAI_KEY: 'sk-...',
  PINECONE_KEY: 'pc-...',
  CUSTOM_HEADER: 'my-value',
});
const encryptedBuffer = encrypt(executorPublicKey.slice(2), Buffer.from(secretJson));
const encryptedSecrets = [`0x${encryptedBuffer.toString('hex')}` as `0x${string}`];
const signature = await walletClient.signMessage({
  account: account.address,
  message: { raw: encryptedSecrets[0] },
});

const encoded = encodeAbiParameters(HTTP_CALL_ABI, [
  executorAddress,
  encryptedSecrets,
  100n,
  [signature],
  '0x',
  'https://my-api.com/enrich',
  2,                                             // POST
  ['Authorization', 'X-Pinecone-Api-Key', 'X-Custom'],
  ['Bearer OPENAI_KEY', 'PINECONE_KEY', 'CUSTOM_HEADER'],
  new TextEncoder().encode(JSON.stringify({ query: 'Find similar documents' })),
  0n,                                             // dkmsKeyIndex (disabled)
  0,                                              // dkmsKeyFormat (disabled)
  false,                                          // piiEnabled (optional, unrelated)
]);
```

### Signature Format

Sign each encrypted secret blob using viem's `signMessage` with raw bytes:

```typescript
// The executor expects EIP-191 personal_sign format
const signature = await walletClient.signMessage({
  account: userAddress,
  message: { raw: encryptedSecretBytes },  // Pass raw bytes, NOT the hash
});
// Returns 65-byte signature [R(32) || S(32) || V(1)]

// The executor recovers the signer address using:
// hash = keccak256("\x19Ethereum Signed Message:\n" + len + data)
// signer = ecrecover(hash, v, r, s)
// Verifies signer === tx.origin (or checks delegation via SecretsAccessControl)
```

Do NOT use `eth_sign` or manual hashing — `signMessage` already applies the EIP-191 prefix.

For non-empty `encryptedSecrets`, provide one signature per blob even when signer is also `tx.origin`.

### Secret Reference Format

Use secret key names directly (for example `API_KEY`, `WEBHOOK_TOKEN`, `OPENAI_API_KEY`).

There is no required `{{...}}` wrapper syntax for Ritual template substitution.

### Debugging Silent Failures

Secret template transactions can fail silently. Common causes:

1. **Empty `encryptedSecrets`**: If `encryptedSecrets` is empty, no substitution runs and your request sends literal placeholders.

2. **Signature mismatch**: The executor recovers the signer from each signature. If the recovered address doesn't match `tx.origin`, delegation is checked via `SecretsAccessControl`. Denied access returns HTTP 402 in the executor response (not a revert).

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

// 1. Encrypt a JSON secrets map with executor's public key (ECIES)
const secretJson = JSON.stringify({ API_KEY: 'sk-your-api-key' });
const encryptedBuffer = encrypt(executorPublicKey.slice(2), Buffer.from(secretJson));
const encryptedSecret = `0x${encryptedBuffer.toString('hex')}` as `0x${string}`;

// 2. Sign the encrypted blob
const signature = await walletClient.signMessage({
  account,
  message: { raw: encryptedSecret },
});

// 3. Encode the precompile input (13 fields)
const input = encodeAbiParameters(
  [
    { type: 'address' }, { type: 'bytes[]' }, { type: 'uint256' },
    { type: 'bytes[]' }, { type: 'bytes' },
    { type: 'string' }, { type: 'uint8' }, { type: 'string[]' },
    { type: 'string[]' }, { type: 'bytes' }, { type: 'uint256' },
    { type: 'uint8' }, { type: 'bool' },
  ],
  [
    executorAddress,
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
    publicKey: `0x${pk.toHex()}` as `0x${string}`,
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
  [],              // encryptedSecrets
  100n,            // ttl
  [],              // secretSignatures
  userPublicKey,   // Executor encrypts output with this key
  'https://api.example.com/sensitive-data',
  1,               // GET
  [], [],          // no extra headers
  new Uint8Array(0),
  0n,              // dkmsKeyIndex (disabled)
  0,               // dkmsKeyFormat (disabled)
  false,           // piiEnabled — set to true only for PII redaction
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

  return decryptedBuffer.toString('utf-8');
}

// Usage after receiving encrypted response from chain
const plaintext = decryptOutput(encryptedResponseHex, userPrivateKey);
const data = JSON.parse(plaintext);
console.log('Private result:', data);
```

### Private Horoscope Pattern (End-to-End)

Based on the `private-horoscope` prototype — a complete flow where the user's horoscope is encrypted so only they can read it.

```typescript
import { encodeAbiParameters } from 'viem';
import type { Hex } from 'viem';
import { PrivateKey, encrypt } from 'eciesjs';

// Reuse HTTP_CALL_ABI from "Shared HTTP ABI" above

async function getPrivateHoroscope(zodiacSign: string) {
  // 1. Generate ephemeral keypair
  const sk = new PrivateKey();
  const userPublicKey = `0x${sk.publicKey.toHex()}` as Hex;
  const userPrivateKey = sk.toHex();

  // 2. Encrypt API key for the executor using ECIES
  const secretJson = JSON.stringify({ HOROSCOPE_API_KEY: process.env.HOROSCOPE_API_KEY! });
  const encryptedBuffer = encrypt(
    (executorPublicKey as string).slice(2),
    Buffer.from(secretJson),
  );
  const encryptedSecrets = [`0x${encryptedBuffer.toString('hex')}` as `0x${string}`];
  const signature = await walletClient.signMessage({
    account: account.address,
    message: { raw: encryptedSecrets[0] },
  });

  // 3. Build request with both secrets AND private output key
  const encoded = encodeAbiParameters(HTTP_CALL_ABI, [
    executorAddress,
    encryptedSecrets,
    100n,
    [signature],
    userPublicKey,   // Output will be encrypted with this
    `https://api.horoscope.com/v1/daily?sign=${zodiacSign}`,
    1,               // GET
    ['Authorization'],
    ['Bearer HOROSCOPE_API_KEY'],
    new Uint8Array(0),
    0n,              // dkmsKeyIndex (disabled)
    0,               // dkmsKeyFormat (disabled)
    false,           // piiEnabled (optional, unrelated)
  ]);

  // 4. Submit to precompile
  // ... submit transaction and wait for result

  // 5. Decrypt the private result (only this user can do this)
  // const encryptedResult = await getJobResult(jobId);
  // const horoscope = decryptOutput(encryptedResult, userPrivateKey);
  // return JSON.parse(horoscope);
}
```

## Delegated Secret Sharing

The SecretsAccessControl contract allows a secret owner to grant other addresses (delegates) permission to use their encrypted secrets. This enables patterns like:

- A DAO treasury granting a smart contract access to shared API keys
- A user delegating their secrets to a consumer contract for a limited time
- An organization sharing credentials across multiple contracts with expiration

### Contract Address

```
SecretsAccessControl: 0xf9BF1BC8A3e79B9EBeD0fa2Db70D0513fecE32FD
```

### Grant Access

```typescript
import { createWalletClient, http, defineChain, keccak256, toBytes } from 'viem';
import { privateKeyToAccount } from 'viem/accounts';
import type { Address, Hex } from 'viem';
import { encrypt } from 'eciesjs';

const ritualChain = defineChain({
  id: 1979,
  name: 'Ritual',
  nativeCurrency: { name: 'RITUAL', symbol: 'RITUAL', decimals: 18 },
  rpcUrls: { default: { http: [process.env.RITUAL_RPC_URL!] } },
});
const account = privateKeyToAccount(process.env.PRIVATE_KEY! as `0x${string}`);
const walletClient = createWalletClient({ account, chain: ritualChain, transport: http() });

const SECRETS_AC = '0xf9BF1BC8A3e79B9EBeD0fa2Db70D0513fecE32FD' as const;
const contractAddress = '0x1111111111111111111111111111111111111111' as Address;

// Encrypt secrets and compute hash
const secretJson = JSON.stringify({ API_KEY: 'sk-my-key' });
const encryptedBuffer = encrypt(executorPublicKey.slice(2), Buffer.from(secretJson));
const encryptedHex = `0x${encryptedBuffer.toString('hex')}` as Hex;
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

`checkAccess` now returns both a boolean and the `SecretsAccessPolicy` associated with the grant:

```typescript
const SECRETS_AC = '0xf9BF1BC8A3e79B9EBeD0fa2Db70D0513fecE32FD' as const;

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

The owner encrypts secrets, grants you access via `grantAccess`, and shares the encrypted blob + their EIP-191 signature off-chain. Your transaction includes these in the precompile call:

```typescript
// ownerEncryptedSecrets and ownerSignature are provided by the secret owner
const encoded = encodeAbiParameters(HTTP_CALL_ABI, [
  executorAddress,
  ownerEncryptedSecrets,     // the owner's encrypted blob (unchanged)
  100n,
  [ownerSignature],          // owner's EIP-191 signature — REQUIRED for delegation
  '0x',
  'https://api.example.com/data',
  1,                         // GET
  ['Authorization'],
  ['Bearer API_KEY'],
  new Uint8Array(0),
  0n,                        // dkmsKeyIndex (disabled)
  0,                         // dkmsKeyFormat (disabled)
  false,                     // piiEnabled (optional, unrelated)
]);

// tx.origin = your address (the delegate)
// The executor:
//   1. Recovers signer from ownerSignature → ownerAddress
//   2. Calls checkAccess(ownerAddress, tx.origin, secretsHash)
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
    function balanceOf(address user) external view returns (uint256);
    function deposit(uint256 lockDuration) external payable;
}

contract SecretConsumer {
    ISecretsAccessControl public constant SECRETS_AC =
        ISecretsAccessControl(0xf9BF1BC8A3e79B9EBeD0fa2Db70D0513fecE32FD);

    IRitualWallet public constant RITUAL_WALLET =
        IRitualWallet(0x532F0dF0896F353d8C3DD8cc134e8129DA2a3948);

    address public constant HTTP_PRECOMPILE =
        0x0000000000000000000000000000000000000801;

    address public owner;
    bytes32 public secretsHash;

    event RequestSubmitted(bytes32 indexed jobId);
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

        uint256 balance = RITUAL_WALLET.balanceOf(address(this));
        require(balance > 0, "Deposit required");

        (bool success, bytes memory result) = HTTP_PRECOMPILE.call(
            encodedRequest
        );
        require(success, "Precompile call failed");

        emit RequestSubmitted(bytes32(result));
    }

    function updateSecretsHash(bytes32 _newHash) external onlyOwner {
        bytes32 oldHash = secretsHash;
        secretsHash = _newHash;
        emit SecretHashUpdated(oldHash, _newHash);
    }

    function deposit() external payable {
        RITUAL_WALLET.deposit{value: msg.value}(5000);
    }

    receive() external payable {
        RITUAL_WALLET.deposit{value: msg.value}(5000);
    }
}
```

### DAO Shared Secrets Contract

> **Warning: This pattern is broken as-written.** When `DAOSecretManager` calls `SECRETS_AC.grantAccess()`, `msg.sender` is the contract — not the admin EOA. The grant is stored under the contract's address. But the executor recovers the signer from the encrypted blob's EIP-191 signature (the admin EOA), and calls `checkAccess(adminEOA, consumer, hash)` — which returns `false` because the grant is under the contract. Contracts cannot produce EIP-191 signatures, so this mismatch cannot be resolved. **Fix:** Have the admin EOA call `grantAccess` directly instead of through a contract intermediary.

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
        ISecretsAccessControl(0xf9BF1BC8A3e79B9EBeD0fa2Db70D0513fecE32FD);

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
    address public constant ASYNC_DELIVERY_SENDER =
        0x5A16214fF555848411544b005f7Ac063742f39F6;
    // NOTE: 0xfA9E is tx.origin for settlement transactions.
    // msg.sender for callbacks is the AsyncDelivery proxy at the address above.

    struct PrivateRequest {
        address requester;
        bytes userPublicKey;
        uint256 timestamp;
    }

    mapping(bytes32 => PrivateRequest) public requests;

    event PrivateRequestSubmitted(
        bytes32 indexed jobId,
        address indexed requester
    );

    event PrivateResultReady(
        bytes32 indexed jobId,
        bytes encryptedResult
    );

    function submitPrivateRequest(
        bytes calldata encodedRequest,
        bytes calldata userPublicKey
    ) external {
        (bool success, bytes memory result) = HTTP_PRECOMPILE.call(
            encodedRequest
        );
        require(success, "Precompile call failed");

        bytes32 jobId = bytes32(result);
        requests[jobId] = PrivateRequest({
            requester: msg.sender,
            userPublicKey: userPublicKey,
            timestamp: block.timestamp
        });

        emit PrivateRequestSubmitted(jobId, msg.sender);
    }

    function handleCallback(
        bytes32 jobId,
        bytes calldata encryptedResult
    ) external {
        require(msg.sender == ASYNC_DELIVERY_SENDER, "Unauthorized callback");
        PrivateRequest memory req = requests[jobId];
        require(req.requester != address(0), "Unknown job");

        emit PrivateResultReady(jobId, encryptedResult);
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
7. **Sign encrypted blobs for delegated access** — omitting signatures when `tx.origin` ≠ secret owner causes silent 402 errors.


## Key Addresses

| Contract | Address |
|----------|---------|
| SecretsAccessControl | `0xf9BF1BC8A3e79B9EBeD0fa2Db70D0513fecE32FD` |
| TEEServiceRegistry | `0x9644e8562cE0Fe12b4deeC4163c064A8862Bf47F` |
| RitualWallet | `0x532F0dF0896F353d8C3DD8cc134e8129DA2a3948` |

## Quick Reference

```typescript
// Setup — viem + eciesjs
import { defineChain, createPublicClient, createWalletClient, http, keccak256, toBytes } from 'viem';
import { privateKeyToAccount } from 'viem/accounts';
import { encrypt, decrypt, ECIES_CONFIG } from 'eciesjs';

const SECRETS_AC = '0xf9BF1BC8A3e79B9EBeD0fa2Db70D0513fecE32FD' as const;
const TEE_SERVICE_REGISTRY = '0x9644e8562cE0Fe12b4deeC4163c064A8862Bf47F' as const;

// Mandatory for Ritual encrypted-secret compatibility. Do NOT use 16.
ECIES_CONFIG.symmetricNonceLength = 12;

// Encrypt secrets: encrypt(executorPubKey, secretsJson) via eciesjs
// Compute hash: keccak256(toBytes(encryptedHex))
// Signatures: one signature per encrypted blob over raw bytes via signMessage({ message: { raw: blob } })
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

// HTTP precompile ABI (13 fields):
// (address executor, bytes[] encryptedSecrets, uint256 ttl, bytes[] secretSignatures,
//  bytes userPublicKey, string url, uint8 method, string[] headersKeys,
//  string[] headersValues, bytes body, uint256 dkmsKeyIndex, uint8 dkmsKeyFormat,
//  bool piiEnabled)

// Private output: include userPublicKey in the ABI-encoded request
// Executor encrypts response with that key
```

## Optional PII Redaction (`piiEnabled`)

Use `piiEnabled=true` only when you explicitly want PII redaction. Otherwise keep it `false`.

- `piiEnabled=true` requires `encryptedSecrets` + `userPublicKey`.
- For LLM calls, PII + streaming is incompatible.
- This flag is independent from secret injection/template substitution.

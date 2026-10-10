---
name: ritual-dapp-passkey
description: Passkey (WebAuthn / P-256) authentication for Ritual dApps. Use when building dApps with passkey login, passwordless wallets, or SECP256R1 signature verification.
version: 1.0.0
---

# Passkey Authentication — Ritual dApp Patterns

## Overview

Ritual Chain has **native passkey support** at two levels:

1. **TxPasskey (type `0x77`)** — a native transaction type that accepts P-256/WebAuthn signatures directly, enabling passkey-signed EOA transactions without account abstraction.
2. **SECP256R1 precompile (`0x0100`)** — a synchronous native precompile for on-chain P-256 signature verification in smart contracts.

This enables passwordless wallets, biometric authentication, and hardware security key flows — all settled natively on Ritual Chain with no ERC-4337 overhead.

**Precompile address**: `0x0000000000000000000000000000000000000100`
**Chain ID**: 1979 (Ritual Chain)
**Transaction type**: Synchronous (native, single-block, gas-only)

### How It Works

```
Option A: TxPasskey Transaction (native, no smart contract needed)
┌──────────────┐  WebAuthn   ┌──────────────┐  type 0x77 tx  ┌───────────────┐
│  User Device │ ──────────▶ │  dApp Client │ ─────────────▶ │  Ritual Chain │
│  (biometric) │  sign       │  (browser)   │  P256/WebAuthn │  (native EVM) │
└──────────────┘             └──────────────┘                └───────────────┘

Option B: Precompile Verification (smart contract level)
┌──────────┐  staticcall(0x0100)  ┌──────────────┐   bool   ┌──────────────┐
│  User Tx │ ──────────────────▶  │  SECP256R1   │ ───────▶ │  Consumer    │
│          │  (pubkey,msg,sig)    │  Precompile  │  valid?  │  Contract    │
└──────────┘                     └──────────────┘          └──────────────┘
```

### Why Passkeys on Ritual?

- **Passwordless UX**: Users authenticate with Face ID, Touch ID, or hardware keys — no seed phrases
- **Native protocol support**: TxPasskey (`0x77`) means passkey-signed transactions are first-class; no wrapper contracts needed
- **Gas efficient**: 3,450 gas for P-256 verify, 5,000 gas for full WebAuthn — cheaper than ecrecover
- **No account abstraction required**: P-256 public keys map directly to Ethereum addresses via `keccak256(x || y)[12:32]`
- **Hardware-backed security**: Private keys never leave the device's secure enclave

---

## 1. Passkey Signature Types

TxPasskey transactions accept three signature types, encoded via a dedicated `sig_type` field appended to the signed RLP payload:

| Type Byte | Name | Flattened Signed Fields | Gas Adjustment | Use Case |
|-----------|------|-------------------------|----------------|----------|
| `0x00` | Secp256k1 | `sig_type, signature_rsv` | +0 | Standard ECDSA (backward compatible) |
| `0x01` | P256 | `sig_type, signature_rs, public_key_xy` | +3,450 | Raw passkey / hardware key |
| `0x02` | WebAuthn | `sig_type, signature_rs, public_key_xy, authenticator_data, client_data_json` | +5,000 | Browser WebAuthn API |

### Address Derivation from P256 Public Key

A P256 public key maps to an Ethereum address deterministically:

```
address = keccak256(publicKeyX || publicKeyY)[12:32]
```

This means each passkey has a unique, deterministic Ritual Chain address — no registration step needed.

```typescript
import { keccak256, getAddress, concat, toBytes } from 'viem';

function passKeyToAddress(publicKeyX: Uint8Array, publicKeyY: Uint8Array): `0x${string}` {
  const hash = keccak256(concat([publicKeyX, publicKeyY]));
  return getAddress(`0x${hash.slice(26)}`); // last 20 bytes
}
```

---

## 2. Frontend WebAuthn Integration

### Feature Detection

Always check for WebAuthn support before calling any passkey API:

```typescript
function isPasskeySupported(): boolean {
  return typeof window !== 'undefined' &&
    typeof window.PublicKeyCredential !== 'undefined' &&
    typeof window.PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable === 'function';
}

async function isPlatformAuthenticatorAvailable(): Promise<boolean> {
  if (!isPasskeySupported()) return false;
  return window.PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable();
}
```

### Error Handling for WebAuthn Calls

WebAuthn APIs throw specific errors. Handle them explicitly:

```typescript
async function safeWebAuthnCall<T>(fn: () => Promise<T>): Promise<{ result: T } | { error: string; code: string }> {
  try {
    return { result: await fn() };
  } catch (err) {
    if (err instanceof DOMException) {
      switch (err.name) {
        case 'NotAllowedError':
          return { error: 'User cancelled the biometric prompt or timed out.', code: 'CANCELLED' };
        case 'SecurityError':
          return { error: 'WebAuthn blocked — the RP ID does not match the current domain.', code: 'WRONG_DOMAIN' };
        case 'InvalidStateError':
          return { error: 'A credential with this ID already exists on this authenticator.', code: 'DUPLICATE' };
        case 'NotSupportedError':
          return { error: 'This browser or device does not support the requested authenticator type.', code: 'UNSUPPORTED' };
        default:
          return { error: `WebAuthn error: ${err.name} — ${err.message}`, code: 'UNKNOWN' };
      }
    }
    return { error: String(err), code: 'UNKNOWN' };
  }
}
```

### 2a. Create a Passkey (Registration)

```typescript
import { toHex } from 'viem';

// Create a new passkey credential bound to the user's device
async function createPasskey(username: string): Promise<{
  credentialId: string;
  publicKeyX: Uint8Array;
  publicKeyY: Uint8Array;
}> {
  const challenge = crypto.getRandomValues(new Uint8Array(32));

  const credential = await navigator.credentials.create({
    publicKey: {
      rp: { name: 'My Ritual dApp', id: window.location.hostname },
      user: {
        id: new TextEncoder().encode(username),
        name: username,
        displayName: username,
      },
      challenge,
      pubKeyCredParams: [
        { alg: -7, type: 'public-key' }, // ES256 = P-256 + SHA-256
      ],
      authenticatorSelection: {
        authenticatorAttachment: 'platform',  // device biometric
        residentKey: 'required',
        userVerification: 'required',
      },
      attestation: 'none',
    },
  }) as PublicKeyCredential;

  const attestation = credential.response as AuthenticatorAttestationResponse;

  // Extract uncompressed P-256 public key from COSE key in attestation
  const publicKeyBytes = extractP256PublicKey(attestation);

  const result = {
    credentialId: credential.id,
    publicKeyX: publicKeyBytes.slice(0, 32),
    publicKeyY: publicKeyBytes.slice(32, 64),
  };

  // Persist the public key for later login flows
  localStorage.setItem(`passkey:${credential.id}`, JSON.stringify({
    x: toHex(result.publicKeyX),
    y: toHex(result.publicKeyY),
  }));

  return result;
}

// Extract raw P-256 (x, y) from the attestation's COSE public key
function extractP256PublicKey(attestation: AuthenticatorAttestationResponse): Uint8Array {
  const publicKeyDer = new Uint8Array(attestation.getPublicKey()!);
  // SubjectPublicKeyInfo for P-256: last 65 bytes = 0x04 || x(32) || y(32)
  const uncompressed = publicKeyDer.slice(-65);
  if (uncompressed[0] !== 0x04) throw new Error('Expected uncompressed P-256 key');
  return uncompressed.slice(1); // 64 bytes: x || y
}
```

### 2b. Sign with Passkey (Authentication)

```typescript
import { toHex } from 'viem';

// Sign a transaction hash with the user's passkey
async function signWithPasskey(
  txHash: Uint8Array,
  credentialId: string
): Promise<{
  r: Uint8Array;
  s: Uint8Array;
  authenticatorData: Uint8Array;
  clientDataJSON: string;
}> {
  const assertion = await navigator.credentials.get({
    publicKey: {
      challenge: txHash,  // the EIP-191/EIP-712 hash to sign
      allowCredentials: [{
        id: base64UrlToBuffer(credentialId),
        type: 'public-key',
      }],
      userVerification: 'required',
    },
  }) as PublicKeyCredential;

  const response = assertion.response as AuthenticatorAssertionResponse;
  const signature = new Uint8Array(response.signature);

  // Parse DER-encoded ECDSA signature into (r, s) components
  const { r, s } = parseDerSignature(signature);

  return {
    r,
    s,
    authenticatorData: new Uint8Array(response.authenticatorData),
    clientDataJSON: new TextDecoder().decode(response.clientDataJSON),
  };
}

// Parse DER-encoded ECDSA signature → { r: 32 bytes, s: 32 bytes }
function parseDerSignature(der: Uint8Array): { r: Uint8Array; s: Uint8Array } {
  // DER: 0x30 <len> 0x02 <rLen> <r> 0x02 <sLen> <s>
  let offset = 2; // skip 0x30 + total length
  if (der[offset] !== 0x02) throw new Error('Invalid DER');
  offset++;
  const rLen = der[offset++];
  const rRaw = der.slice(offset, offset + rLen);
  offset += rLen;

  if (der[offset] !== 0x02) throw new Error('Invalid DER');
  offset++;
  const sLen = der[offset++];
  const sRaw = der.slice(offset, offset + sLen);

  // Pad/trim to exactly 32 bytes each
  const r = padTo32(rRaw);
  const s = padTo32(sRaw);

  return { r, s };
}

function padTo32(bytes: Uint8Array): Uint8Array {
  if (bytes.length === 32) return bytes;
  if (bytes.length === 33 && bytes[0] === 0x00) return bytes.slice(1); // strip leading zero
  if (bytes.length < 32) {
    const padded = new Uint8Array(32);
    padded.set(bytes, 32 - bytes.length);
    return padded;
  }
  throw new Error(`Unexpected integer length: ${bytes.length}`);
}

function base64UrlToBuffer(base64url: string): ArrayBuffer {
  const base64 = base64url.replace(/-/g, '+').replace(/_/g, '/');
  const padded = base64.padEnd(base64.length + (4 - base64.length % 4) % 4, '=');
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}
```

### 2c. Normalize High-S Signatures

P-256 ECDSA signatures are malleable — `(r, s)` and `(r, n-s)` are both valid. Ritual Chain enforces **low-s** (s must be ≤ n/2). Always normalize after signing:

```typescript
// P-256 curve order
const P256_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551n;
const P256_HALF_N = P256_N / 2n;

function normalizeS(s: Uint8Array): Uint8Array {
  const sBigInt = BigInt('0x' + Array.from(s).map(b => b.toString(16).padStart(2, '0')).join(''));
  if (sBigInt > P256_HALF_N) {
    const normalized = P256_N - sBigInt;
    const hex = normalized.toString(16).padStart(64, '0');
    return new Uint8Array(hex.match(/.{2}/g)!.map(b => parseInt(b, 16)));
  }
  return s;
}

// Use after signing:
const { r, s, authenticatorData, clientDataJSON } = await signWithPasskey(txHash, credentialId);
const normalizedS = normalizeS(s);
```

---

## 3. SECP256R1 Precompile — On-Chain Verification

### 3a. Production ABI (Ritual Sigver)

The production SECP256R1 precompile uses **ABI-encoded** input, NOT raw 160-byte concatenation:

```solidity
// Input: abi.encode(bytes pubkey, bytes message, bytes signature)
// Output: abi.encode(uint256 isValid) — 1 = valid, 0 = invalid

address constant SECP256R1_PRECOMPILE = address(0x100);

function verifyP256(
    bytes memory pubkey,     // 33 bytes (compressed) or 65 bytes (0x04 || x || y)
    bytes memory message,    // arbitrary length (raw message, NOT pre-hashed)
    bytes memory signature   // 64 bytes (r || s)
) internal view returns (bool) {
    bytes memory input = abi.encode(pubkey, message, signature);
    (bool success, bytes memory result) = SECP256R1_PRECOMPILE.staticcall(input);
    if (!success || result.length == 0) return false;
    return abi.decode(result, (uint256)) == 1;
}
```

**Key difference from RIP-7212**: The production precompile takes a **raw message** (internally hashed with SHA-256 by the precompile), NOT a pre-hashed message. The pubkey can be compressed (33 bytes) or uncompressed (65 bytes with `0x04` prefix).

### 3b. PrecompileConsumer Helper

The `PrecompileConsumer` base contract provides a convenience wrapper:

```solidity
import {PrecompileConsumer} from "ritual-sc/utils/PrecompileConsumer.sol";

contract PasskeyVerifier is PrecompileConsumer {
    mapping(address => bytes) public registeredKeys; // address → compressed pubkey

    function registerKey(bytes calldata compressedPubkey) external {
        require(compressedPubkey.length == 33, "Invalid compressed key");
        registeredKeys[msg.sender] = compressedPubkey;
    }

    function verifyAction(
        address user,
        bytes calldata message,
        bytes calldata signature
    ) external returns (bool) {
        bytes memory pubkey = registeredKeys[user];
        require(pubkey.length > 0, "No key registered");

        bytes memory input = abi.encode(pubkey, message, signature);
        bytes memory result = callSECP256R1SigVer(input);
        return abi.decode(result, (uint256)) == 1;
    }
}
```

### 3c. Using Solady P256 Library

Ritual's smart contract repo vendors Solady's `P256.sol` which wraps the RIP-7212 precompile at `0x0100` with malleability protection:

```solidity
import {P256} from "solady/utils/P256.sol";

contract PasskeyGate {
    struct PasskeyCredential {
        uint256 pubKeyX;
        uint256 pubKeyY;
    }

    mapping(address => PasskeyCredential) public credentials;

    function register(uint256 x, uint256 y) external {
        credentials[msg.sender] = PasskeyCredential(x, y);
    }

    function verify(bytes32 hash, bytes32 r, bytes32 s) external view returns (bool) {
        PasskeyCredential memory cred = credentials[msg.sender];
        // verifySignature enforces low-s (malleability protection)
        return P256.verifySignature(hash, uint256(r), uint256(s), cred.pubKeyX, cred.pubKeyY);
    }
}
```

**Note**: Solady's `P256.verifySignature` expects a **pre-hashed** message (bytes32), matching the RIP-7212 spec. If you need raw-message verification, use the ABI-encoded sigver precompile directly (Section 3a).

### 3d. Using Solady WebAuthn Library

For full WebAuthn assertion verification on-chain:

```solidity
import {WebAuthn} from "solady/utils/WebAuthn.sol";

contract WebAuthnVerifier {
    struct StoredCredential {
        uint256 pubKeyX;
        uint256 pubKeyY;
    }

    mapping(bytes32 => StoredCredential) public credentials; // credentialId → key

    function registerCredential(bytes32 credentialId, uint256 x, uint256 y) external {
        credentials[credentialId] = StoredCredential(x, y);
    }

    function verifyAssertion(
        bytes32 credentialId,
        bytes32 challenge,
        WebAuthn.WebAuthnAuth calldata auth
    ) external view returns (bool) {
        StoredCredential memory cred = credentials[credentialId];
        return WebAuthn.verify(
            abi.encodePacked(challenge), // expected challenge bytes
            true,                        // requireUserVerification
            auth,
            cred.pubKeyX,
            cred.pubKeyY
        );
    }
}
```

---

## 4. Frontend Integration with viem

### 4a. Verify Passkey Signature via Precompile

```typescript
import { createPublicClient, http, defineChain } from 'viem';
import { ritualChain } from '@/lib/chain'; // see section 1 of ritual-dapp-frontend

const publicClient = createPublicClient({ chain: ritualChain, transport: http() });

const SECP256R1_PRECOMPILE = '0x0000000000000000000000000000000000000100' as const;

// Verify a P-256 signature on-chain via eth_call (no gas cost, read-only)
async function verifyP256OnChain(
  pubkey: `0x${string}`,     // compressed (33B) or uncompressed (65B) hex
  message: `0x${string}`,    // raw message hex
  signature: `0x${string}`   // 64 bytes: r || s
): Promise<boolean> {
  const result = await publicClient.call({
    to: SECP256R1_PRECOMPILE,
    data: encodeAbiParameters(
      [{ type: 'bytes' }, { type: 'bytes' }, { type: 'bytes' }],
      [pubkey, message, signature]
    ),
  });

  if (!result.data || result.data === '0x') return false;
  const decoded = decodeAbiParameters([{ type: 'uint256' }], result.data);
  return decoded[0] === 1n;
}

import { encodeAbiParameters, decodeAbiParameters } from 'viem';
```

### 4b. Full Passkey Login Flow

```typescript
import { keccak256, concat, toHex, toBytes, getAddress } from 'viem';

async function passkeyLogin() {
  // 1. Request WebAuthn assertion
  const challenge = crypto.getRandomValues(new Uint8Array(32));
  const assertion = await navigator.credentials.get({
    publicKey: {
      challenge,
      userVerification: 'required',
    },
  }) as PublicKeyCredential;

  const response = assertion.response as AuthenticatorAssertionResponse;

  // 2. Extract signature components
  const { r, s } = parseDerSignature(new Uint8Array(response.signature));
  const normalizedS = normalizeS(s);

  // 3. Derive Ritual Chain address from stored public key
  //    (public key must be stored during registration)
  const storedKey = localStorage.getItem(`passkey:${assertion.id}`);
  if (!storedKey) throw new Error('Unknown credential — register first');
  const { x, y } = JSON.parse(storedKey);

  const address = getAddress(
    `0x${keccak256(concat([toBytes(x), toBytes(y)])).slice(26)}`
  );

  // 4. Verify signature on-chain (optional — the chain verifies TxPasskey natively)
  const pubkeyUncompressed = concat([toBytes('0x04'), toBytes(x), toBytes(y)]);
  const isValid = await verifyP256OnChain(
    toHex(pubkeyUncompressed),
    toHex(challenge),
    toHex(concat([r, normalizedS]))
  );

  return { address, isValid, credentialId: assertion.id };
}
```

---

## 5. Gas Costs

| Operation | Gas | Notes |
|-----------|-----|-------|
| SECP256R1 precompile (`0x0100`) | 3,450 | Flat fee, no per-byte cost |
| TxPasskey with P256 signature | +3,450 | Added to intrinsic gas |
| TxPasskey with WebAuthn signature | +5,000 | P256 + challenge parsing overhead |
| Ed25519 precompile (`0x0009`) | 2,000 | For comparison |
| ecrecover (secp256k1) | 3,000 | Standard Ethereum, for comparison |

The SECP256R1 precompile is **gas-only** — no RitualWallet deposit required. It runs natively in the EVM (not delegated to a sidecar executor), so there is no async lifecycle, no callback pattern, and no executor fees.

---

## 6. Solidity Patterns

### 6a. Passkey-Gated Access Control

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract PasskeyAccessControl {
    address constant SECP256R1 = address(0x100);

    struct P256Key {
        bytes32 x;
        bytes32 y;
    }

    mapping(address => P256Key) public authorizedKeys;

    event KeyRegistered(address indexed account, bytes32 x, bytes32 y);
    event ActionExecuted(address indexed account, bytes32 actionHash);

    function registerKey(bytes32 x, bytes32 y) external {
        authorizedKeys[msg.sender] = P256Key(x, y);
        emit KeyRegistered(msg.sender, x, y);
    }

    function executeWithPasskey(
        bytes calldata message,
        bytes calldata signature
    ) external {
        P256Key memory key = authorizedKeys[msg.sender];
        require(key.x != bytes32(0), "No key registered");

        // Build uncompressed pubkey: 0x04 || x || y
        bytes memory pubkey = abi.encodePacked(bytes1(0x04), key.x, key.y);
        bytes memory input = abi.encode(pubkey, message, signature);

        (bool success, bytes memory result) = SECP256R1.staticcall(input);
        require(success && result.length > 0, "Verification call failed");
        require(abi.decode(result, (uint256)) == 1, "Invalid passkey signature");

        emit ActionExecuted(msg.sender, keccak256(message));
    }
}
```

### 6b. Multisig with Mixed Key Types

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract HybridMultisig {
    address constant SECP256R1 = address(0x100);

    enum KeyType { ECDSA, P256 }

    struct Signer {
        KeyType keyType;
        bytes key;
    }

    Signer[] public signers;
    uint256 public threshold;
    bool private _locked;

    modifier nonReentrant() {
        require(!_locked, "Reentrancy");
        _locked = true;
        _;
        _locked = false;
    }

    constructor(Signer[] memory _signers, uint256 _threshold) {
        require(_threshold <= _signers.length, "Bad threshold");
        for (uint256 i = 0; i < _signers.length; i++) signers.push(_signers[i]);
        threshold = _threshold;
    }

    function execute(
        address target,
        bytes calldata data,
        bytes[] calldata signatures,
        bytes calldata message
    ) external nonReentrant {
        uint256 validCount = 0;
        bytes32 ethHash = keccak256(abi.encodePacked("\x19Ethereum Signed Message:\n", message));

        for (uint256 i = 0; i < signers.length && validCount < threshold; i++) {
            if (signatures[i].length == 0) continue;

            if (signers[i].keyType == KeyType.ECDSA) {
                address recovered = _recoverECDSA(ethHash, signatures[i]);
                if (recovered == address(bytes20(signers[i].key))) validCount++;
            } else {
                bytes memory pubkey = abi.encodePacked(bytes1(0x04), signers[i].key);
                bytes memory input = abi.encode(pubkey, message, signatures[i]);
                (bool ok, bytes memory result) = SECP256R1.staticcall(input);
                if (ok && result.length > 0 && abi.decode(result, (uint256)) == 1) validCount++;
            }
        }

        require(validCount >= threshold, "Not enough signatures");
        (bool success,) = target.call(data);
        require(success, "Execution failed");
    }

    function _recoverECDSA(bytes32 hash, bytes calldata sig) internal pure returns (address) {
        (bytes32 r, bytes32 s, uint8 v) = abi.decode(sig, (bytes32, bytes32, uint8));
        return ecrecover(hash, v, r, s);
    }
}
```

---

## 7. Testing

### 7a. Foundry Unit Test

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Test.sol";

contract PasskeyPrecompileTest is Test {
    address constant SECP256R1 = address(0x100);

    function test_validSignature() public {
        // Test vector from daimo-eth/p256-verifier (Wycheproof suite)
        bytes memory pubkey = hex"04...";   // 65-byte uncompressed key
        bytes memory message = hex"...";    // raw message
        bytes memory signature = hex"...";  // 64-byte r || s

        bytes memory input = abi.encode(pubkey, message, signature);
        (bool success, bytes memory result) = SECP256R1.staticcall(input);

        assertTrue(success, "staticcall failed");
        assertGt(result.length, 0, "empty result");
        assertEq(abi.decode(result, (uint256)), 1, "signature should be valid");
    }

    function test_invalidSignature_returnsZero() public {
        bytes memory pubkey = hex"04...";
        bytes memory message = hex"deadbeef";        // wrong message
        bytes memory signature = hex"...";

        bytes memory input = abi.encode(pubkey, message, signature);
        (bool success, bytes memory result) = SECP256R1.staticcall(input);

        assertTrue(success, "staticcall should not revert");
        if (result.length > 0) {
            assertEq(abi.decode(result, (uint256)), 0, "should return 0 for invalid sig");
        }
        // empty result also indicates failure
    }

    function test_gasUsage() public {
        bytes memory pubkey = hex"04...";
        bytes memory message = hex"...";
        bytes memory signature = hex"...";
        bytes memory input = abi.encode(pubkey, message, signature);

        uint256 gasBefore = gasleft();
        SECP256R1.staticcall(input);
        uint256 gasUsed = gasBefore - gasleft();

        // Expect ~3,450 gas for the precompile itself (plus call overhead)
        assertLt(gasUsed, 10_000, "Gas usage unexpectedly high");
    }
}
```

### 7b. TypeScript Integration Test

```typescript
import { describe, it, expect } from 'vitest';
import { createPublicClient, http, defineChain, encodeAbiParameters, decodeAbiParameters } from 'viem';

// Use ritualChain from @/lib/chain (Chain ID 1979, RPC: https://rpc.ritualfoundation.org)

describe('SECP256R1 Precompile', () => {
  const client = createPublicClient({ chain: ritualChain, transport: http() });
  const PRECOMPILE = '0x0000000000000000000000000000000000000100' as const;

  it('should verify a valid P-256 signature', async () => {
    // Replace with real test vectors
    const pubkey = '0x04...';   // uncompressed
    const message = '0x...';
    const signature = '0x...';  // r || s (64 bytes)

    const data = encodeAbiParameters(
      [{ type: 'bytes' }, { type: 'bytes' }, { type: 'bytes' }],
      [pubkey, message, signature]
    );

    const result = await client.call({ to: PRECOMPILE, data });
    const [isValid] = decodeAbiParameters([{ type: 'uint256' }], result.data!);
    expect(isValid).toBe(1n);
  });
});
```

---

## 8. Architecture Details

### TxPasskey Unsigned Signing Payload

```
0x77 || rlp([
  chain_id,
  nonce,
  max_priority_fee_per_gas,
  max_fee_per_gas,
  gas_limit,
  to,
  value,
  data,
  access_list
])
```

This is the exact payload used for the TxPasskey signing hash:

```
keccak256(0x77 || rlp([9 standard EIP-1559 fields]))
```

Important: the Ritual-specific async fields sometimes seen elsewhere in the protocol (`commitment_tx`, `settlement_tx`, `spc_calls`) are **not** part of the TxPasskey signing hash and are **not** appended to the signed `0x77` transaction payload. For TxPasskey client implementations, always hash and encode only the 9 standard EIP-1559 fields above.

### TxPasskey Signed Transaction Encoding

Signed transactions flatten the signature material directly into the outer RLP list. Do **not** pack the signature into one opaque blob, and do **not** wrap the signature fields in a nested sub-list.

```
Signed (Secp256k1): 0x77 || rlp([
  chain_id, nonce, max_priority_fee_per_gas, max_fee_per_gas,
  gas_limit, to, value, data, access_list,
  sig_type,      // 0x00
  signature_rsv  // 65 bytes: r || s || v
])

Signed (P256): 0x77 || rlp([
  chain_id, nonce, max_priority_fee_per_gas, max_fee_per_gas,
  gas_limit, to, value, data, access_list,
  sig_type,      // 0x01
  signature_rs,  // 64 bytes: r || s
  public_key_xy  // 64 bytes: x || y (no 0x04 prefix)
])

Signed (WebAuthn): 0x77 || rlp([
  chain_id, nonce, max_priority_fee_per_gas, max_fee_per_gas,
  gas_limit, to, value, data, access_list,
  sig_type,              // 0x02
  signature_rs,          // 64 bytes: r || s
  public_key_xy,         // 64 bytes: x || y (no 0x04 prefix)
  authenticator_data,    // variable-length bytes
  client_data_json       // raw UTF-8 bytes, variable length
])
```

Flattening rule: each signature item above is its own RLP element in the outer list. For example, WebAuthn is encoded as `[..., 0x02, signature_rs, public_key_xy, authenticator_data, client_data_json]`, not as `[..., 0x02 || signature_blob]` and not as `[..., [0x02, ...]]`.

### TypeScript: Encode a WebAuthn TxPasskey Transaction

```typescript
import { concatHex, keccak256, toHex, toRlp } from 'viem';

type TxPasskeyBase = {
  chainId: bigint;
  nonce: bigint;
  maxPriorityFeePerGas: bigint;
  maxFeePerGas: bigint;
  gasLimit: bigint;
  to: `0x${string}` | null;
  value: bigint;
  data: `0x${string}`;
  accessList: [];
};

type WebAuthnTxPasskeySignature = {
  sigType: 0x02;
  r: Uint8Array; // 32 bytes
  s: Uint8Array; // 32 bytes, already normalized to low-s
  x: Uint8Array; // 32 bytes
  y: Uint8Array; // 32 bytes
  authenticatorData: Uint8Array;
  clientDataJSON: string;
};

function join32ByteParts(a: Uint8Array, b: Uint8Array): `0x${string}` {
  if (a.length !== 32 || b.length !== 32) throw new Error('Expected 32-byte inputs');
  const combined = new Uint8Array(64);
  combined.set(a, 0);
  combined.set(b, 32);
  return toHex(combined);
}

function encodeTxPasskeySigningPayload(tx: TxPasskeyBase): `0x${string}` {
  return concatHex([
    '0x77',
    toRlp([
      tx.chainId,
      tx.nonce,
      tx.maxPriorityFeePerGas,
      tx.maxFeePerGas,
      tx.gasLimit,
      tx.to ?? '0x',
      tx.value,
      tx.data,
      tx.accessList,
    ]),
  ]);
}

function hashTxPasskeyForSigning(tx: TxPasskeyBase): `0x${string}` {
  return keccak256(encodeTxPasskeySigningPayload(tx));
}

function encodeSignedWebAuthnTxPasskey(
  tx: TxPasskeyBase,
  sig: WebAuthnTxPasskeySignature
): `0x${string}` {
  const signatureRs = join32ByteParts(sig.r, sig.s);
  const publicKeyXy = join32ByteParts(sig.x, sig.y);
  const clientDataJsonBytes = new TextEncoder().encode(sig.clientDataJSON);

  return concatHex([
    '0x77',
    toRlp([
      tx.chainId,
      tx.nonce,
      tx.maxPriorityFeePerGas,
      tx.maxFeePerGas,
      tx.gasLimit,
      tx.to ?? '0x',
      tx.value,
      tx.data,
      tx.accessList,
      sig.sigType,
      signatureRs,
      publicKeyXy,
      toHex(sig.authenticatorData),
      toHex(clientDataJsonBytes),
    ]),
  ]);
}

// The browser signs the 9-field hash only.
const signingHash = hashTxPasskeyForSigning(tx);

// Later, after navigator.credentials.get(...):
const rawTx = encodeSignedWebAuthnTxPasskey(tx, {
  sigType: 0x02,
  r,
  s: normalizeS(s),
  x,
  y,
  authenticatorData,
  clientDataJSON,
});
```

Implementation notes:

- `clientDataJSON` must be encoded as raw UTF-8 bytes inside the RLP list, not hex-decoded JSON and not base64.
- `public_key_xy` is exactly `x || y` with no uncompressed `0x04` prefix.
- `signature_rs` is exactly `r || s` after low-s normalization.
- If your encoder produces a nested signature structure, a single "signature blob", or includes Ritual async extension fields in the signable payload, the transaction will be rejected.

### Precompile Input/Output Summary

```
PRODUCTION PRECOMPILE (0x0100, Sigver):
  Input:  abi.encode(bytes pubkey, bytes message, bytes signature)
  Output: abi.encode(uint256 isValid)  // 1 or 0
  Gas:    3,450

  pubkey:    33 bytes (compressed, 0x02/0x03 prefix)
             or 65 bytes (uncompressed, 0x04 || x || y)
  message:   arbitrary bytes (raw, NOT pre-hashed — precompile hashes with SHA-256)
  signature: 64 bytes (r || s, each 32 bytes, big-endian)

SOLADY P256.sol WRAPPER (RIP-7212 format):
  Input:  hash(32) || r(32) || s(32) || x(32) || y(32) = 160 bytes
  Output: 0x01 (32 bytes, last byte = 1) on success, empty on failure
  Note:   expects PRE-HASHED message (bytes32)
```

### WebAuthn Verification Flow (on-chain)

```
1. Client sends: authenticatorData, clientDataJSON, signature (r,s), pubkey (x,y)
2. Contract verifies:
   a. authenticatorData flags: UP (user presence) must be set
   b. clientDataJSON.type === "webauthn.get"
   c. clientDataJSON.challenge === base64url(expected_challenge)
   d. hash = SHA-256(authenticatorData || SHA-256(clientDataJSON))
   e. P256.verify(hash, r, s, x, y) via 0x0100 precompile
```

---

## 9. End-to-End Onboarding Flow

The complete user journey from zero to passkey-controlled Ritual address:

```
1. User visits dApp
       │
       ▼
2. Feature detection — isPasskeySupported()?
       │ yes                    │ no
       ▼                        ▼
3. "Create Passkey" button     Fall back to MetaMask/injected wallet
       │
       ▼
4. Browser biometric prompt (Face ID / Touch ID / PIN)
       │
       ▼
5. Extract P-256 public key (x, y) from attestation
       │
       ▼
6. Derive Ritual address: keccak256(x || y)[12:32]
       │
       ▼
7. Store credential in localStorage (credentialId → {x, y})
       │
       ▼
8. Display address to user — "Your Ritual address is 0x..."
       │
       ▼
9. User funds address (faucet, bridge, or transfer from another wallet)
       │
       ▼
10. User can now sign TxPasskey (0x77) transactions with biometric
```

```typescript
async function onboardWithPasskey(username: string) {
  if (!await isPlatformAuthenticatorAvailable()) {
    throw new Error('Passkeys not supported — use a standard wallet');
  }

  const credential = await createPasskey(username);
  const address = passKeyToAddress(credential.publicKeyX, credential.publicKeyY);

  return {
    credentialId: credential.credentialId,
    address,
    needsFunding: true,
  };
}
```

---

## 10. Integration with Other Ritual Skills

### SECP256R1 is Synchronous — No useRitualWrite Needed

The SECP256R1 precompile at `0x0100` is synchronous — like Ed25519 (`0x0009`, see `ritual-dapp-ed25519`), JQ, and ONNX. It executes inline in a single block. This means you can verify signatures for free via `eth_call` without a transaction. It also means:

- `writeContractAsync` works normally for contracts that call SECP256R1
- No `useRitualWrite` bypass needed (the `eth_call` simulation succeeds)
- No RitualWallet deposit required (gas-only)
- No async lifecycle, no callbacks, no `spcCalls` in the receipt

**However:** if your contract calls BOTH SECP256R1 (for passkey verification) AND an async precompile (for HTTP/LLM), you must use `useRitualWrite` for the function that triggers the async call. The SECP256R1 part still works — it's the async precompile that breaks simulation.

### Passkey Addresses Still Need RitualWallet Deposits

A passkey-derived address is a standard EOA. If that address wants to call async precompiles (HTTP, LLM, Agent, etc.), it still needs:
1. RITUAL balance for gas
2. RitualWallet deposit for executor fees

The passkey controls the address. The deposit funds the precompile. These are independent concerns.

---

## 11. Application-Level Recovery (Not Native EOA Rotation)

A native TxPasskey address is derived from the P256 public key. Changing the key therefore produces a
different address; no registry contract can replace the key that validates transactions for the original
EOA. If a user loses every copy of that passkey, the native passkey-derived EOA is not recoverable.

Recovery must be designed before funds are deposited. Put assets and permissions behind a smart account or
application contract whose authorization logic reads a mutable passkey registry. A secondary secp256k1 key
can then rotate the key used by that contract. The following example is such an **application-level
registry**; it does not rotate a native TxPasskey EOA:

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @notice Application-level key registry for a contract-managed account.
/// @dev Updating this registry does not change a native TxPasskey EOA's key.
contract PasskeyRecoveryRegistry {
    address constant SECP256R1 = address(0x100);

    struct Account {
        bytes32 passkeyX;
        bytes32 passkeyY;
        address recoveryAddress;
        uint256 recoveryDelay;
        uint256 recoveryInitiatedAt;
        bytes32 pendingX;
        bytes32 pendingY;
    }

    mapping(address => Account) public accounts;

    event PasskeyRegistered(address indexed account, bytes32 x, bytes32 y);
    event RecoveryInitiated(address indexed account, uint256 executeAfter);
    event RecoveryCancelled(address indexed account);
    event PasskeyRotated(address indexed account, bytes32 newX, bytes32 newY);

    function register(bytes32 x, bytes32 y, address recoveryAddr, uint256 delay) external {
        accounts[msg.sender] = Account(x, y, recoveryAddr, delay, 0, 0, 0);
        emit PasskeyRegistered(msg.sender, x, y);
    }

    function initiateRecovery(address target, bytes32 newX, bytes32 newY) external {
        Account storage acct = accounts[target];
        require(msg.sender == acct.recoveryAddress, "Not recovery address");

        acct.recoveryInitiatedAt = block.timestamp;
        acct.pendingX = newX;
        acct.pendingY = newY;
        emit RecoveryInitiated(target, block.timestamp + acct.recoveryDelay);
    }

    function executeRecovery(address target) external {
        Account storage acct = accounts[target];
        require(acct.recoveryInitiatedAt > 0, "No recovery pending");
        require(block.timestamp >= acct.recoveryInitiatedAt + acct.recoveryDelay, "Delay not elapsed");

        acct.passkeyX = acct.pendingX;
        acct.passkeyY = acct.pendingY;
        acct.recoveryInitiatedAt = 0;
        emit PasskeyRotated(target, acct.pendingX, acct.pendingY);
    }

    function cancelRecovery() external {
        Account storage acct = accounts[msg.sender];
        require(acct.recoveryInitiatedAt > 0, "No recovery pending");
        acct.recoveryInitiatedAt = 0;
        emit RecoveryCancelled(msg.sender);
    }
}
```

The recovery address is a standard secp256k1 EOA (MetaMask or a hardware wallet). The delay gives the
legitimate owner time to cancel a malicious recovery attempt. To make the rotation effective, the smart
account or application must verify future actions against `accounts[account].passkeyX/passkeyY`; this
standalone registry only stores the policy.

Do not present this pattern as recovery for funds held directly by the passkey-derived EOA. For native EOA
funds, use passkey-provider device sync and backup procedures, or transfer funds into a recoverable smart
account while the original passkey is still available.

---

## 12. Dual-Auth Support

Most dApps need to support both traditional wallet users (MetaMask) and passkey users. Detect the available auth method and route accordingly:

```typescript
type AuthMethod = { type: 'wallet'; address: `0x${string}` } | { type: 'passkey'; address: `0x${string}`; credentialId: string };

async function detectAuthMethod(): Promise<'wallet' | 'passkey' | 'none'> {
  const hasWallet = typeof window !== 'undefined' && typeof window.ethereum !== 'undefined';
  const hasPasskey = await isPlatformAuthenticatorAvailable();

  if (hasPasskey && hasWallet) return 'passkey';
  if (hasPasskey) return 'passkey';
  if (hasWallet) return 'wallet';
  return 'none';
}

async function authenticate(): Promise<AuthMethod> {
  const method = await detectAuthMethod();

  if (method === 'passkey') {
    const { address, credentialId } = await passkeyLogin();
    return { type: 'passkey', address, credentialId };
  }

  if (method === 'wallet') {
    const [address] = await window.ethereum!.request({ method: 'eth_requestAccounts' });
    return { type: 'wallet', address: address as `0x${string}` };
  }

  throw new Error('No authentication method available');
}
```

When both are available, prefer passkeys — the UX is smoother (biometric vs. MetaMask popup). Allow users to switch methods via a settings toggle.

---

## Common Pitfalls

### Signature Malleability
The P-256 curve has order `n`. Both `(r, s)` and `(r, n-s)` are valid signatures. **Always normalize to low-s** (s ≤ n/2) before submitting. TxPasskey transactions with high-s will be rejected. The Solady `P256.verifySignature()` enforces this on-chain.

### Two Encoding Formats
The production precompile at `0x0100` uses **ABI-encoded `(bytes, bytes, bytes)`** with a raw (unhashed) message. Solady's `P256.sol` uses the **RIP-7212 raw 160-byte format** with a pre-hashed message. Do not mix them — if you use Solady, pass a `bytes32` hash; if you use the precompile directly, pass the raw message.

### TxPasskey RLP Is Flat
For signed `0x77` transactions, the signature pieces are flattened into the outer RLP list. Do not encode WebAuthn as a nested tuple/list, and do not prepend a type byte to a single signature blob. The signable hash is `keccak256(0x77 || rlp([9 EIP-1559 fields]))`, and the signed payload appends `sig_type` plus the signature fields as separate RLP items.

### Compressed vs Uncompressed Keys
The precompile accepts both. WebAuthn APIs return uncompressed keys (65 bytes, `0x04` prefix). If storing on-chain, prefer compressed (33 bytes) to save gas on storage.

### Empty Result = Failure
The precompile returns **empty bytes** (not a revert) on invalid input or failed verification. Always check `result.length > 0` before decoding.

### WebAuthn Challenge Encoding
The `clientDataJSON.challenge` field is **base64url-encoded** (no padding). When constructing expected challenges, use base64url encoding, not standard base64.

### Relying Party ID (Domain Mismatch)
The `rp.id` in `navigator.credentials.create()` must match the deployed domain. Credentials created on `localhost` will NOT work on `myapp.com` — they are bound to the RP ID at creation time. For development, create separate test credentials. For staging vs production, use the same domain or accept that credentials won't transfer.

### Browser Compatibility
WebAuthn is supported in all modern browsers (Chrome 67+, Firefox 60+, Safari 14+, Edge 79+). Mobile support: iOS 16+ (Face ID/Touch ID), Android 9+ (fingerprint). Always check `isPasskeySupported()` (see section 2) before attempting any passkey operation.

### Key Storage and Cross-Device Sync
P-256 private keys are created in the device's secure enclave. On modern platforms, passkeys may sync across devices via iCloud Keychain (Apple), Google Password Manager (Android/Chrome), or Windows Hello (Microsoft). This means the "key never leaves the device" guarantee is now "key never leaves the platform ecosystem." For high-security applications, set `authenticatorAttachment: 'cross-platform'` to require a hardware security key (YubiKey) that does not sync. For consumer applications, synced passkeys are desirable — they prevent device-loss lockout.

If the user loses all devices in their sync ecosystem, they lose access. Implement recovery mechanisms (see section 9 — Recovery Pattern).

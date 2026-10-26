---
name: ritual-dapp-ed25519
description: On-chain Ed25519 signature verification via native precompile. Use when verifying Solana signatures, SSH keys, or any Ed25519-signed data on-chain.
---

# Ed25519 Signature Verification — Ritual dApp Patterns

## Overview

The Ed25519 precompile (`0x0009`) verifies Ed25519 signatures on-chain in a single synchronous call. On other EVM chains, Ed25519 verification requires expensive Solidity libraries (100k+ gas). On Ritual, it's a native precompile (~2,000 gas).

**Precompile address**: `0x0000000000000000000000000000000000000009`
**Execution model**: Synchronous (result in same TX)
**Gas cost**: ~2,000 gas (vs 100,000+ for Solidity library implementations)

## ABI

```solidity
// Input:  abi.encode(bytes pubkey, bytes message, bytes signature)
// Output: abi.encode(uint256 isValid)  — 1 = valid, 0 = invalid
```

| Field | Type | Size | Description |
|-------|------|------|-------------|
| pubkey | bytes | 32 bytes | Ed25519 public key |
| message | bytes | arbitrary | The message that was signed |
| signature | bytes | 64 bytes (R \|\| S) | Ed25519 signature |

**Argument order matters:** `(pubkey, message, signature)`. Not `(message, signature, pubkey)`.

**All three fields are ABI type `bytes` (dynamic).** Do not use `bytes32` or any fixed-size type — the precompile decodes `(bytes, bytes, bytes)` and will silently fail on mismatched encoding.

**Return value:** `uint256` — `1` if the signature is valid, `0` if invalid. On malformed input or empty input, the precompile returns empty bytes (not a revert), so always check `result.length > 0` before decoding.

## Solidity: Verification

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract Ed25519Verifier {
    address constant ED25519 = 0x0000000000000000000000000000000000000009;

    error InvalidSignature();

    function verify(
        bytes calldata pubkey,
        bytes calldata message,
        bytes calldata signature
    ) external view returns (bool) {
        require(pubkey.length == 32, "pubkey must be 32 bytes");
        require(signature.length == 64, "signature must be 64 bytes");

        bytes memory input = abi.encode(pubkey, message, signature);
        (bool ok, bytes memory result) = ED25519.staticcall(input);
        if (!ok || result.length == 0) return false;

        return abi.decode(result, (uint256)) == 1;
    }

    function verifyOrRevert(
        bytes calldata pubkey,
        bytes calldata message,
        bytes calldata signature
    ) external view {
        require(pubkey.length == 32, "pubkey must be 32 bytes");
        require(signature.length == 64, "signature must be 64 bytes");

        bytes memory input = abi.encode(pubkey, message, signature);
        (bool ok, bytes memory result) = ED25519.staticcall(input);
        require(ok && result.length > 0, "precompile call failed");

        if (abi.decode(result, (uint256)) != 1) revert InvalidSignature();
    }
}
```

## TypeScript: Encoding and Calling

```typescript
import { encodeAbiParameters, decodeAbiParameters, createPublicClient, http } from 'viem';

const ED25519 = '0x0000000000000000000000000000000000000009';

function encodeEd25519Verify(
  pubkey: `0x${string}`,
  message: `0x${string}`,
  signature: `0x${string}`
): `0x${string}` {
  return encodeAbiParameters(
    [{ type: 'bytes' }, { type: 'bytes' }, { type: 'bytes' }],
    [pubkey, message, signature]
  );
}

// Verify via eth_call (no transaction needed, it's synchronous)
async function verifyEd25519(
  client: ReturnType<typeof createPublicClient>,
  pubkey: `0x${string}`,     // 32 bytes
  message: `0x${string}`,    // arbitrary length
  signature: `0x${string}`   // 64 bytes (R || S)
): Promise<boolean> {
  const data = encodeEd25519Verify(pubkey, message, signature);
  const result = await client.call({ to: ED25519, data });
  if (!result.data || result.data === '0x') return false;
  const [isValid] = decodeAbiParameters([{ type: 'uint256' }], result.data);
  return isValid === 1n;
}
```

## Use Cases

| Use Case | How It Works |
|----------|-------------|
| **Solana signature verification** | Solana uses Ed25519 for all signatures. Verify Solana-signed messages on Ritual to bridge trust between chains. |
| **SSH key verification** | SSH keys are often Ed25519. Verify that a message was signed by a specific SSH key on-chain. |
| **DKIM email verification** | Some DKIM signatures use Ed25519. Verify email authenticity on-chain. |
| **Tor/onion service identity** | Tor v3 onion addresses are Ed25519 public keys. Verify service identity on-chain. |
| **Cross-chain message verification** | Any chain or protocol using Ed25519 (Solana, NEAR, Cardano, Stellar) can have its signatures verified on Ritual. |

## Key Properties

- **Synchronous**: returns the result in the same call — no async lifecycle, no callbacks, no polling
- **Free to query**: call via `eth_call` to verify signatures without a transaction and without spending gas. Unlike async precompiles (HTTP, LLM), the result is real — not a placeholder. See the TypeScript example above.
- **Gas-only**: no RitualWallet deposit or executor fees. Just standard EVM gas (2,000 gas for the precompile itself)
- **No sender lock**: doesn't block or get blocked by async job locks on the same address
- **Composable**: can be combined with other synchronous precompiles (SECP256R1 at `0x0100`, JQ at `0x0803`) and short-running async precompiles in the same transaction. See `ritual-dapp-passkey` for the SECP256R1 equivalent and `ritual-dapp-precompiles` for the full address map.

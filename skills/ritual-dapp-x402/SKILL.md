---
name: ritual-dapp-x402
description: X402 micropayment and paid API access patterns for Ritual dApps. Use when building dApps that need automatic paid API access, micropayment flows, per-call payment for premium APIs, budget-controlled data access, shared credential management via dKMS, or metered on-chain API usage. Do NOT use for free/public API calls — use ritual-dapp-http instead.
version: 1.0.0
---

# X402 Micropayments — Paid API Access Patterns

X402 (named after HTTP 402 Payment Required) enables pay-per-call access to premium APIs through Ritual's HTTP precompile. Instead of managing API subscriptions off-chain, dApps submit encrypted payment credentials with an HTTP request. The TEE executor decrypts them, makes the paid call, and returns the result — all in a single on-chain transaction.

### Why X402?

- **No API key management**: Users don't need accounts with premium APIs — the dApp holds encrypted credentials
- **Pay-per-call**: Only pay for what you use, no subscriptions or upfront commitments
- **On-chain auditability**: Payment and data delivery are both on-chain events
- **Composable**: Combine with any precompile that needs external paid data
- **Privacy**: Payment credentials never appear on-chain (ECIES encrypted to TEE)

### Payment Flow

1. **Encrypt credentials**: User/dApp encrypts payment info (API key with billing, payment token) to the executor's ECIES public key
2. **Submit with HTTP request**: Encrypted payment blob is included as `encryptedSecrets` in the HTTP precompile call
3. **Executor decrypts**: Inside the TEE, the executor decrypts payment credentials
4. **String replacement**: Executor replaces `SECRET_NAME` placeholders in URL, headers, and body with decrypted values
5. **Make paid call**: Executor calls the premium API with real credentials
6. **Return result**: Result is settled on-chain in the same transaction; payment credentials are never exposed

## When to Use vs When NOT to Use

| Scenario | Skill |
|----------|-------|
| Premium API requiring payment credentials (API keys with billing, tokens) | **This skill (X402)** |
| Free/public APIs, open endpoints, no credentials needed | `ritual-dapp-http` |
| Passing secrets that aren't payment-related (auth tokens, config) | `ritual-dapp-secrets` |
| Premium API that takes >30s to respond | **This skill** + `ritual-dapp-longrunning` |
| Multiple users sharing one paid API key (DAO pattern) | **This skill** + `ritual-dapp-secrets` (dKMS) |

## Architecture

```
┌──────────────┐   encrypt creds    ┌──────────────┐   HTTP + payment   ┌──────────────┐
│  User / dApp │ ─────────────────▶ │  Precompile  │ ────────────────▶  │  Premium API │
│              │  (executor pubkey)  │   0x0801     │                    │  (paid)      │
└──────────────┘                    └──────────────┘                    └──────────────┘
                                          │
                       TEE executor:      │
                       1. Decrypt creds   │
                       2. Substitute      │
                          SECRET_NAME     │
                       3. Make paid call  │
                       4. Return result   │
                          on-chain        │
```

**Key property:** Payment credentials never appear on-chain. They are ECIES-encrypted to the executor's public key and only decrypted inside the TEE enclave.

## Skill Dependencies

This skill is a **composition layer**. It combines patterns from other skills with payment-specific concerns. Before using this skill, the agent should be familiar with:

- **`ritual-dapp-secrets`** — ECIES encryption, secret string replacement syntax, SecretsAccessControl. All credential encryption in X402 follows the patterns defined there.
- **`ritual-dapp-http`** — HTTP precompile (0x0801) encoding format, executor selection, ABI parameter layout. X402 uses the same encoding with encrypted secrets added.
- **`ritual-dapp-wallet`** — RitualWallet deposit flows. The sender's wallet must be funded before any X402 call.
- **`ritual-dapp-longrunning`** — For premium APIs with response times >30s, use 0x0805 instead of 0x0801.
- **`ritual-dapp-frontend`** — For building UI around X402 flows. Use `walletClient.request({ method: "eth_sendTransaction" })` with explicit `gas` hex field (never `useWriteContract` or `useSendTransaction` for async precompiles — both trigger EVM simulation which fails).

---

## Ritual X402 Interface: HTTP Precompile with Payment Credentials

X402 uses the **same HTTP precompile ABI** (`0x0801`) as a plain HTTP call. The difference is which parameter slots are populated. Here is the interface — the parameters marked **← X402** are what change:

### ABI Parameter Layout (0x0801)

| # | Type | Parameter | Plain HTTP | X402 (Paid) |
|---|------|-----------|-----------|-------------|
| 0 | `address` | executor | TEE executor address | Same |
| 1 | `bytes[]` | **encryptedSecrets** | `[]` (empty) | **← X402: `[encryptedHex]`** — ECIES-encrypted JSON containing payment credential keys |
| 2 | `uint256` | ttl | Blocks until timeout | Same |
| 3 | `bytes[]` | **secretSignatures** | `[]` (empty) | **← X402: `[signature]`** — ECDSA signature over each encrypted blob |
| 4 | `bytes` | userPublicKey | `'0x'` | `'0x'` (or user pubkey for encrypted responses) |
| 5 | `string` | url | Plain URL | **← X402: URL with `SECRET_NAME` placeholders** |
| 6 | `uint8` | method | HTTP method enum | Same |
| 7 | `string[]` | headerKeys | Header names | Same (may include credential headers) |
| 8 | `string[]` | headerValues | Header values | **← X402: values with secret placeholders** |
| 9 | `bytes` | body | Request body | **← X402: body with secret placeholders** |
| 10 | `uint256` | dkmsKeyIndex | `0` (disabled) | `0` (X402 does not use dKMS) |
| 11 | `uint8` | dkmsKeyFormat | `0` (disabled) | `0` (X402 does not use dKMS) |
| 12 | `bool` | piiEnabled | `false` | **← X402: set to `true`** — enables secret template substitution. See `ritual-dapp-secrets`. |

### How String Replacement Works

The executor decrypts the `encryptedSecrets` blob inside the TEE, producing a JSON object. Every `KEY_NAME` placeholder in the URL, headers, or body is replaced with the corresponding value from that JSON before the HTTP request is made.

```
Encrypted payload:   { "API_KEY": "sk-live-abc123", "BILLING_ID": "cust_xyz" }
                                  ↓ TEE decrypts ↓
URL before:          https://api.example.com/v1/data?key=API_KEY
URL after:           https://api.example.com/v1/data?key=sk-live-abc123

Header before:       Authorization: Bearer API_KEY
Header after:        Authorization: Bearer sk-live-abc123
```

**Rules:**
- Placeholder names are **case-sensitive** and must match JSON keys exactly
- Use `UPPER_SNAKE_CASE` for naming consistency
- Placeholders can appear in URL, header values, and body — not in header keys
- If a `KEY` has no match in the decrypted JSON, the executor returns `Secret template not found`

### Constructing the Encrypted Secrets

The encryption follows `ritual-dapp-secrets`. The X402-specific part is the **payload content** — billing/payment credentials:

```typescript
import { encrypt } from 'eciesjs';

// 1. Build the payload — keys MUST match placeholder names in URL/headers/body
const x402Payload = JSON.stringify({
  API_KEY: process.env.PREMIUM_API_KEY,
  BILLING_TOKEN: process.env.BILLING_TOKEN,
});

// 2. Encrypt to executor's pubkey (lookup via TEEServiceRegistry.getNodePublicKey)
const encrypted = encrypt(executorPublicKey.slice(2), Buffer.from(x402Payload));
const encryptedHex = `0x${Buffer.from(encrypted).toString('hex')}`;

// 3. Sign the encrypted blob
const signature = await account.signMessage({ message: { raw: encryptedHex } });

// 4. These go into ABI parameter slots 1 and 3:
//    encryptedSecrets: [encryptedHex]
//    secretSignatures: [signature]
```

The `executorPublicKey` comes from the TEE Service Registry at `0x9644e8562cE0Fe12b4deeC4163c064A8862Bf47F` via `getNodePublicKey(executorAddress)`. To find available executors, query `getServicesByCapability(0, true)` for HTTP_CALL-capable executors — see `ritual-dapp-http` section 10. See `ritual-dapp-secrets` for the full encryption flow.

**Multiple secrets:** The `encryptedSecrets` array can hold multiple blobs. Typically you encrypt a single JSON object with all credential keys and pass it as a single-element array. Multiple entries are for cases where different secrets are encrypted to different executor public keys (e.g., a multi-executor setup). For most X402 dApps, use `[encryptedHex]` (single element).

---

## End-to-End Build Sequence

When building an X402 dApp, follow this order:

1. **Fund the RitualWallet** — Deposit RITUAL to cover precompile execution fees. See `ritual-dapp-wallet`. Must happen before any X402 call.
2. **Select an executor** — Query `TEEServiceRegistry.getServicesByCapability(0, true)` to find executors with HTTP_CALL capability. See `ritual-dapp-http` section 10 for the full lookup pattern. Pick one and note its `teeAddress` (the executor address) and `publicKey` (for ECIES encryption).
3. **Encrypt credentials** — Build the JSON payload, encrypt with ECIES to the executor's public key, sign with your account (see "Constructing the Encrypted Secrets" above).
4. **Encode the HTTP precompile call** — Use the ABI parameter layout table above. Fill slots 1, 3, 5, 8, 9, and 12 with X402-specific values. Set slots 10–11 (dKMS) to zero.
5. **Send the transaction** — Call the consumer contract or send directly to `0x0801`. The result comes back **in the same transaction** via inline settlement (not a callback).
6. **Decode the response** — The precompile returns `(bytes, bytes)` where the second element decodes to `(uint16 status, string[] headerKeys, string[] headerValues, bytes body, string errorMessage)`. See `ritual-dapp-http` for the full decoding pattern.

### Response Format (Inline Settlement)

The HTTP precompile (0x0801) does **NOT** use callbacks. The result is settled inline in the same transaction — your contract receives it as the return value of `HTTP_PRECOMPILE.call(input)`:

```solidity
(bool success, bytes memory rawOutput) = HTTP_PRECOMPILE.call(input);
(, bytes memory actualOutput) = abi.decode(rawOutput, (bytes, bytes));
// actualOutput decodes to: (uint16 status, string[] headerKeys, string[] headerValues, bytes body, string errorMessage)
```

If the premium API returns an error (4xx, 5xx), the result still settles — you get the error status code and body. The executor fee is still consumed. The external API cost depends on whether the API's billing considers failed requests billable.

> **0x0805 (Long-Running HTTP) is different.** It uses a callback/delivery model via `AsyncDelivery`. If your X402 call uses 0x0805, the result is delivered to your contract via a callback function — see `ritual-dapp-longrunning`.

---

## What X402 Adds Beyond the Interface

On top of populating the precompile's secret slots, X402 introduces three concerns:

1. **Budget tracking at the contract level.** The consumer contract should enforce per-address spending limits so individual users can't drain a shared payment account.

2. **Credential rotation.** Payment tokens expire. The dApp must handle re-encryption when credentials are refreshed — this is an off-chain concern since decrypted values never leave the TEE.

3. **Cost awareness.** Unlike free API calls, X402 calls have external costs (the premium API's pricing) on top of executor fees. The contract should track estimated spend.

---

## Budget Management (Contract Pattern)

This is the primary X402-specific Solidity concern. The consumer contract should enforce per-address spending limits.

**Key design decisions the agent must make:**

| Decision | Options | Guidance |
|----------|---------|----------|
| Cost tracking | Fixed estimate per call vs oracle-based | Fixed estimate is simpler but inaccurate. Use a configurable `costPerCall` state variable that the owner can update, not a hardcoded literal. |
| Budget period | Per-epoch (resettable) vs lifetime | Per-epoch is more practical. Add a `resetBudget(address)` admin function. |
| Budget scope | Per-user vs per-contract | Per-user for multi-tenant dApps. Per-contract if the dApp has a single operator. |

**Contract skeleton** (the agent should flesh this out based on the dApp's needs):

```solidity
contract X402Consumer {
    address constant HTTP_PRECOMPILE = 0x0000000000000000000000000000000000000801;

    struct HTTPResponse {
        uint16 status;
        string[] headerKeys;
        string[] headerValues;
        bytes body;
        string errorMessage;
    }

    uint256 public costPerCall;
    mapping(address => uint256) public budgetUsed;
    mapping(address => uint256) public budgetLimit;

    function fetchPaidData(
        address executor, uint256 ttl, string calldata url,
        bytes[] calldata encryptedSecrets, bytes[] calldata secretSignatures,
        string[] calldata headerKeys, string[] calldata headerValues
    ) external returns (uint16, bytes memory) {
        require(budgetUsed[msg.sender] + costPerCall <= budgetLimit[msg.sender], "Budget exceeded");

        bytes memory input = abi.encode(
            executor, encryptedSecrets, ttl, secretSignatures, bytes(""),
            url, uint8(1), headerKeys, headerValues, bytes(""),
            uint256(0), uint8(0),  // dkmsKeyIndex, dkmsKeyFormat (0 = disabled)
            true                   // piiEnabled
        );

        (bool success, bytes memory rawOutput) = HTTP_PRECOMPILE.call(input);
        require(success, "Precompile call failed");

        (, bytes memory actualOutput) = abi.decode(rawOutput, (bytes, bytes));
        HTTPResponse memory resp = abi.decode(actualOutput, (HTTPResponse));

        budgetUsed[msg.sender] += costPerCall;
        return (resp.status, resp.body);
    }
}
```

**Note:** There is no `handlePaidResponse` callback for 0x0801 — the result is returned inline via short-running settlement. Only 0x0805 (long-running) uses delivery callbacks.

---

## Shared Credentials (dKMS Pattern)

For DAOs or multi-user dApps where many users access the same paid API, the admin encrypts the credentials once and grants access to members via `SecretsAccessControl`.

This follows the delegation pattern from `ritual-dapp-secrets`:

1. Admin encrypts the premium API key to the executor's public key
2. Admin calls `SecretsAccessControl.grantAccess(memberAddress, secretsHash)` at `0xf9BF1BC8A3e79B9EBeD0fa2Db70D0513fecE32FD`
3. Member includes the shared encrypted secret in their X402 HTTP calls
4. Executor verifies access before decrypting

See `ritual-dapp-secrets` for the full `grantAccess` / `revokeAccess` / `checkAccess` API.

---

## Combining with Long-Running HTTP

When the premium API has a submit-then-poll pattern (e.g., AI inference APIs that return a job ID), use the long-running HTTP precompile (`0x0805`) instead of `0x0801`.

The X402 concern is the same — encrypted payment credentials are passed as secrets. The only difference is the precompile address and the additional polling/delivery parameters.

See `ritual-dapp-longrunning` for the full 0x0805 encoding format. Add the encrypted secrets and signatures to the `encryptedSecrets` and `secretSignatures` parameter slots.

---

## Error Handling

| Error | Cause | Fix |
|-------|-------|-----|
| `Budget exceeded` | User hit per-address spending limit | Admin resets budget or increases limit |
| `Secret template not found` | `SECRET_NAME` in URL/headers doesn't match any key in encrypted JSON | Verify key names match exactly (case-sensitive) |
| `Paid API call failed` | Invalid encrypted credentials or malformed URL | Re-encrypt credentials, verify API URL format |
| HTTP 402 Payment Required | Premium API rejected the payment token | Check that the decrypted credential is valid and funded |
| HTTP 401 Unauthorized | Decrypted credentials expired or revoked | Re-encrypt with fresh credentials |
| `insufficient deposit` | RitualWallet underfunded for HTTP call fees | Deposit more RITUAL via `ritual-dapp-wallet` pattern |
| `Only precompile` (if access control is correct) | Someone attempted to spoof the callback | Expected behavior — the access control is working |

**Credential rotation:** When a premium API token expires (401/403 from the API), the dApp must re-encrypt fresh credentials. This is an off-chain concern — the user generates a new encrypted payload and submits a new transaction. There is no on-chain retry mechanism that can refresh credentials, since the decrypted values never leave the TEE.

---

## Quick Reference

| Item | Value |
|------|-------|
| HTTP precompile | `0x0000000000000000000000000000000000000801` |
| Long-Running HTTP precompile | `0x0000000000000000000000000000000000000805` |
| SecretsAccessControl | `0xf9BF1BC8A3e79B9EBeD0fa2Db70D0513fecE32FD` |
| RitualWallet | `0x532F0dF0896F353d8C3DD8cc134e8129DA2a3948` |
| TEE Service Registry | `0x9644e8562cE0Fe12b4deeC4163c064A8862Bf47F` |
| Chain ID | 1979 |
| Payment encryption | ECIES to executor pubkey — see `ritual-dapp-secrets` |
| Secret replacement syntax | `SECRET_NAME` — keys must match encrypted JSON, `UPPER_SNAKE_CASE` |
| Budget pattern | Per-address limits with configurable `costPerCall` in consumer contract |
| Callback access control | `require(msg.sender == HTTP_PRECOMPILE)` — always enforce |

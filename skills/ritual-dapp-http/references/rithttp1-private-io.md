# RITHTTP1 private I/O

Read [the current wire reference](rithttp1.md) first. This document targets executor PR #247 at `75c04e3`, not the removed five/six-field RITHTTP1 interface. Outer HTTP/Long HTTP ABIs and input-artifact encryption are unchanged.

## Keys and trust boundaries

| Material | Purpose |
|---|---|
| Normal owner-bound `encryptedSecrets` | Reusable `storage:*`/`http:*` credentials; existing ownership, signatures and delegated ACL still apply |
| Fresh 32-byte artifact DEK | Encrypts one input artifact with AES-256-GCM |
| Verified executor public key | Unwraps the input DEK inside the selected TEE |
| User output/recovery key | Optional additional input recipient; explicit per-pipe output recipient |

A recipient key ID is `keccak256(0x04 || x || y)` over all 65 SEC1 bytes, not an Ethereum address. Verify the registered key on chain and apply the application's route/attestation policy before encrypting. Registry membership alone does not prove which binary a TEE runs. A secret/input bound to one executor must be submitted to that executor.

DA and relay see ciphertext and metadata and can withhold, delay or censor it. The selected executor decrypts inside its TEE; the upstream provider sees request plaintext. Encrypted output still relies on trusted executor execution and independent settlement verification for provenance. A raw ECIES envelope alone is not a sender signature.

## Encrypted inputs (unchanged)

Serialize exactly one JSON value; encrypt to the verified executor key, optionally also a user recovery key, then upload. The `InputRef` digest covers uploaded ciphertext, not plaintext. The executor verifies it before decryption/hydration.

```text
"RITHTTP1" || 0x01 || uint8 recipientCount
|| sorted RecipientRecord[recipientCount]
|| nonce[12] || tag[16] || ciphertext
RecipientRecord = recipientKeyId[32] || eciesWrappedDEK[125]
```

There are 1–8 unique records in strict key-ID order. The header through the nonce is AES-GCM AAD; tag precedes ciphertext. The included `encryptRitHttpArtifact`/`decryptRitHttpArtifact` implement this encoding. Supply the expected stored digest when decrypting untrusted DA. Input format fixtures retain their original [source/digest provenance](../../../examples/rithttp/provenance.json).

## Output privacy is per pipe

Each `OutputPipe` explicitly specifies its `recipientPublicKey`: empty bytes mean **plaintext**, nonempty must be a valid 65-byte uncompressed secp256k1 point. All kinds (CONTRACT, STREAM and DA) support either. Public CONTRACT usage can coexist with private STREAM and private DA. The outer `userPublicKey` does not implicitly encrypt any pipe; it still controls Long HTTP Phase 1 encryption. There are no implemented `PUBLIC_OUTPUTS` or per-pipe privacy option bits.

Selectors run before encryption and choose JSON or raw UTF8 bytes independently per pipe. CONTRACT/DA collect selected bytes in order, without added delimiters, then optionally encrypt **one** record. Plain CONTRACT/DA contain selected bytes directly. STREAM always uses a record per emission, including plaintext streams.

```text
RITPIPE1 record (50-byte header):
"RITPIPE1" || jobId[32] || uint8 pipeIndex || uint8 encoding
|| uint32_be sequence || uint32_be payloadLength || payload
```

For encrypted output the entire record is inside ECIES. CONTRACT/DA use sequence `0`, STREAM uses contiguous selected-emission sequence `0..n-1` (not the upstream SSE event count). Require the expected job, pipe index, encoding, sequence, exact length and no trailing bytes after decryption.

ECIES uses secp256k1, uncompressed ephemeral/HKDF public keys, HKDF-SHA256 and AES-256-GCM with 12-byte nonce; wire order is ephemeral key[65], nonce[12], tag[16], ciphertext. The included codec passes explicit configuration per call rather than depending on mutable global ECIES settings.

## Live streams and durable collected output

Set `STREAM_RESPONSE` to parse upstream SSE, plus `AWAIT_RESPONSE` on Long HTTP. Include a STREAM output with the desired selector, encoding and optional key. Non-JSON events such as `[DONE]` are not hardcoded away; selectors such as `fromjson? | ...` omit them. The streaming service carries base64 of the binary record/ciphertext in its opaque `token` field. Decode base64 before decryption or hashing. Then parse the **selected** payload (e.g. UTF8 deltas or provider JSON chosen by `fromjson?`), not the service wrapper or a native LLM schema.

Successful STREAM pipe settlement commits:

```text
sha256 = SHA256(concat(uint32_be(frame.length) || frame for each transmitted frame))
sizeBytes = sum(selected plaintext payload lengths)
itemCount = number of accepted frame publications
```

For encrypted streams, `frame` is ciphertext; for public streams it is the RITPIPE1 record. No archive magic/count prefix enters this hash. Do not hash base64 strings, decrypted text or a DA artifact instead. Publisher success means queue acceptance, not remote delivery acknowledgment. A client missing frames must report incomplete delivery, not accept a subset.

A DA pipe independently selects/collects bytes and optionally encrypts one sequence-0 RITPIPE1 record. Its hash/size cover that stored object. **It is not an archive of live ciphertext frames** and its digest differs from the STREAM commitment. For resumable application history, verify the DA result independently; do not compare its digest to the stream hash. Encrypted output is not automatically a multi-recipient input artifact: to reuse it as a new input, decrypt/verify it and create a fresh input artifact for the next executor.

Verify settlement before accepting output:

1. Authenticate the submitted request and derive its job ID; authenticate canonical settlement independently.
2. Require encoding `4`, the expected output count/index/kind/encoding/encryption and the relevant pipe's success. Early errors may have no pipe array.
3. For CONTRACT/DA, verify exact returned/fetched byte size and SHA-256, then decrypt/bind the collected record if encrypted.
4. For STREAM, preserve exact decoded binary frames, verify length-prefixed hash and item count, decrypt/bind each frame, then check selected plaintext byte total.
5. Keep live displayed text provisional until checks pass. A `done` transport event alone is not a chain proof.

A failed STREAM/DA pipe can coexist with successful CONTRACT usage. Preserve and account independently authenticated usage according to contract policy instead of blanket-discarding it because the aggregate `hasError` is set. Fatal read/cancel failures invalidate incomplete outputs. Do not interpret residual metadata on a failed pipe as a successful result.

## Relay authorization and privacy limits

The user must sign authorization-relevant route/executor, input digest/length, all output fields/keys/destinations, limits, nonce and deadline. Contract checks must bind the immediate caller and correct secret owner/delegate; encryption does not stop a relay authoring a different request. Verify admitted transaction destination/calldata/receipt and output settlement independently. Authenticated encrypted history should also bind a monotonic revision to resist replay.

An OpenAI-compatible API harness that sends plaintext prompts to an application relay exposes those prompts there. Private browser encryption does not transfer automatically to arbitrary API clients. The upstream HTTP provider remains trusted for its reported usage/pricing and sees the plaintext it serves.

## Included codecs and tests

[TypeScript request/results](../../../examples/rithttp/rithttp.ts), [Solidity codecs](../../../examples/rithttp/RITHTTP1.sol), and [private I/O helpers](../../../examples/rithttp/rithttp-private-io.ts) are self-contained consumer examples using public dependencies. Copy the files and install via Bun. `verifyStreamFrames` checks canonical STREAM commitments/bindings; `verifyCollectedOutput` checks CONTRACT/DA commitments and sequence-0 bindings. Obtain their expected values from independently authenticated settlement and compare result metadata with the original request first.

Run `bun install`, `bun run typecheck`, `bun test` in `examples/rithttp` with public Foundry `forge` in PATH. Tests include unchanged canonical input fixtures, new executor-generated output-pipe fixtures, tamper/replay/size/count rejection, and Solidity/viem agreement. Old `RITHTTP1 || 0x02` frames and `0x03` stream archives in the historical shared fixture are **not** current output-pipe formats; current helpers do not implement them. Public fixture keys must never protect real secrets or hold funds. Local fixtures prove codec conformance, not deployment support or live DA availability.

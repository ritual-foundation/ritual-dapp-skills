# RITHTTP1 — input references and output pipes

This reference targets [executor PR #247](https://github.com/ritual-net/executor-go-internal/pull/247), head `75c04e3423933887aec74ceea378ce214f01f95c` (merged in `de832db67515c211cc297e0b33c6dead521dad01`). Read [private I/O](rithttp1-private-io.md) for encryption, record bindings and trust boundaries. Runnable [TypeScript/Solidity codecs and cross-language fixtures](../../../examples/rithttp/) are included; no private implementation import is required by consumers.

RITHTTP1 lives inside the existing HTTP `0x0801` or Long HTTP `0x0805` **body**. Their 16/38-field outer ABIs, pricing and non-prefixed legacy HTTP behavior are unchanged. This revision deliberately breaks the previous RITHTTP1 five/six-field bodies: `contractJq`, `OutputSink[]`, parallel keys and global encryption/UTF8 flags are removed. Do not send old RITHTTP1 bytes to this decoder or new bytes to an older executor. Pin compatible executors out of band; there is no on-chain capability-negotiation bit.

## Request wire

```text
body = "RITHTTP1" || abi.encode(
  uint32 options,
  bytes jsonTemplate,
  InputRef[] inputRefs,
  OutputPipe[] outputs
)
StorageRef = (string platform, string path, string keyRef)
InputRef = (StorageRef ref, bytes32 sha256Digest)
OutputPipe = (
  uint8 kind,                // CONTRACT=0, STREAM=1, DA=2
  string jq,
  uint8 encoding,            // JSON=0, UTF8=1
  bytes recipientPublicKey,  // empty = plaintext; otherwise 65-byte secp256k1 SEC1
  StorageRef destination    // DA only; all three strings empty otherwise
)
```

`RITHTTP1` is eight ASCII bytes; `||` is concatenation, not another ABI field. Only option `AWAIT_RESPONSE=1` (bit 0) and `STREAM_RESPONSE=8` (bit 3) exist. Unknown bits and noncanonical ABI/trailing bytes are rejected. Output encryption and encoding are selected independently on each pipe, including CONTRACT. The outer `userPublicKey` does not choose pipe privacy (it still controls legacy long Phase 1 encryption).

`STREAM_RESPONSE` chooses **upstream SSE parsing**, not the presence of a STREAM destination. An SSE response may feed CONTRACT/DA without publishing live tokens; a buffered body may feed a STREAM pipe as one selected frame. A STREAM pipe needs a configured publisher before HTTP side effects.

For all RITHTTP1 requests set `piiEnabled=false` and the legacy outer `outputStorageRef=("","","")`. Secret owners/signatures, sponsor, TTL, URL/method/headers, callback and x402 configuration remain outer fields.

## Input hydration and secrets (unchanged)

A compact template can replace any JSON value with a DA slot:

```json
{
  "model": "your-provider-model",
  "messages": {"$ritual_da": 0},
  "stream": true,
  "stream_options": {"include_usage": true},
  "max_tokens": 256,
  "metadata": {"tenant": {"$ritual_secret": "http:tenant"}}
}
```

Slot `0` refers to `inputRefs[0]`. The exact `{"$ritual_da":N}` node is replaced, not interpolated as text. An artifact can hold an object, array, scalar or null. The executor:

1. Decrypts the normal owner-bound encrypted secrets map once.
2. Resolves `storage:*` credentials and downloads the input refs.
3. Verifies mandatory nonzero SHA-256 over exact stored bytes (ciphertext for encrypted artifacts).
4. Decrypts supported encrypted input artifacts with the selected executor key and parses exactly one JSON value.
5. Replaces slots present in the template. DA expansion is one level only; downloaded content cannot introduce another active DA lookup.
6. Expands whole-value `{"$ritual_secret":"http:alias"}` nodes and `{{ritual.secret:http:alias}}` markers, including those introduced by hydrated JSON. Secret values are terminal, not new syntax.
7. Validates delegated policies against the final URL, headers, body and injection locations; validates outputs and prepares storage credentials before HTTP side effects.

Whole-value secret nodes replace the node with the stored **string**; they do not parse that string as JSON. Text markers substitute strings within their containing value. An authorization header can be `Bearer {{ritual.secret:http:openrouter}}`. URL markers are supported in path/query; authority, scheme, userinfo and fragment injection fail closed.

Refs use `gcs`, `hf` or `pinata`, a nonempty path and a `storage:*` alias of at most 128 bytes. GCS paths are object names (bucket from the credential); HF paths are `owner/repo/file`; Pinata input is a CID, output is a filename hint. The returned DA URI is authoritative. Distinct output refs must not normalize to the same write destination.

## Selectors and collection

Every output selector receives a **string**: the complete buffered body, or each complete SSE `data:` payload. Use `fromjson` or `fromjson?` before object lookup. SSE multiline data fields join with a newline; comments/non-data fields do not become payloads. **`[DONE]` is delivered to selectors too**; `fromjson?` omits it without provider-specific executor logic.

The bounded AST interpreter supports fixed field/index lookup, static object/array projections, pipes, `if/elif/else`, equality/inequality, string concatenation (`+`), `empty`, `fromjson`/`fromjson?`, `tostring`, and supported `try` without a catch. It does not execute general jq: no iteration, slices, recursion, arithmetic, regex, variables, imports or custom functions. Optional field access and `//` fallback are not supported. A selector emits at most one value per input. Decimal JSON number lexemes are preserved; equality normalizes decimal exponents with bounds without enabling arithmetic.

- JSON encoding serializes the selected value; UTF8 requires a string and emits its raw UTF-8 bytes.
- `empty` (including a failed `fromjson?`) emits nothing. An empty string **does** emit an item.
- CONTRACT and DA concatenate selections in event order. There are **no implicit separators**, JSON arrays, or NDJSON newlines. If many JSON values are expected, explicitly select text with `tostring + "\n"` and UTF8, or use a single terminal projection. Multiple JSON selections otherwise produce adjacent JSON values, not one valid JSON document.
- STREAM emits each selected item immediately, framed as RITPIPE1, optionally encrypted, then base64 in the service's opaque token field.
- An encrypted CONTRACT/DA output encrypts its entire collection once. It is independent of encrypted live frames and cannot be treated as their archive.

## Three-pipe example

Copy `rithttp.ts` from [examples/rithttp](../../../examples/rithttp/) and install its public dependencies with Bun. The input digest and output recipient key below are supplied by your application after key verification, not placeholders to submit literally.

```ts
import { encodeRitHttp1, RITHTTP, PIPE, ENCODING, EMPTY_REF } from "./rithttp";
import type { Hex } from "viem";

export function chatBody(inputDigest: Hex, userPublicKey: Hex) {
  return encodeRitHttp1({
    options: RITHTTP.AWAIT_RESPONSE | RITHTTP.STREAM_RESPONSE,
    jsonTemplate: {
      model: "your-provider-model", messages: { $ritual_da: 0 },
      stream: true, stream_options: { include_usage: true }, max_tokens: 256,
    },
    inputRefs: [{
      ref: { platform: "gcs", path: "chat/request.json", keyRef: "storage:gcs" },
      sha256Digest: inputDigest,
    }],
    outputs: [
      { kind: PIPE.CONTRACT, encoding: ENCODING.JSON,
        jq: "fromjson? | if .usage != null then {id: .id, usage: .usage} else empty end",
        recipientPublicKey: "0x", destination: EMPTY_REF },
      { kind: PIPE.STREAM, encoding: ENCODING.UTF8,
        jq: "fromjson? | if .choices[0].delta.content != null then .choices[0].delta.content else empty end",
        recipientPublicKey: userPublicKey, destination: EMPTY_REF },
      { kind: PIPE.DA, encoding: ENCODING.UTF8,
        jq: "fromjson? | if .choices[0].delta.content != null then .choices[0].delta.content else empty end",
        recipientPublicKey: userPublicKey,
        destination: { platform: "gcs", path: "chat/answer.bin", keyRef: "storage:gcs" } },
    ],
  });
}
```

This returns public usage, encrypted selected text frames, and an independently encrypted collected answer from the same response. Choose selectors for the provider's actual schema. Billing contracts must authenticate the callback/job, check the expected usage pipe, validate required provider usage, reject duplicate/missing or malformed accounting data, and enforce their own economic policy. A TEE result authenticates selected provider data; the protocol does not impose provider pricing, credit caps or user admission policy.

## Result wire and failure handling

```text
result = "RITOUT1" || abi.encode(
  bool hasError, uint16 upstreamStatus, uint8 contractEncoding,
  bytes contractOutput, ArtifactReceipt[] receipts, bytes4 errorCode
)
ArtifactReceipt = (bool success, string outputUri, bytes32 sha256Digest,
                   uint64 sizeBytes, bytes4 errorCode)

// Normal output-pipe completion:
contractEncoding = 4
contractOutput = abi.encode(PipeResult[])
receipts = []
PipeResult = (
  uint8 kind, uint8 encoding, bool encrypted, bool success,
  bytes data, string outputURI, bytes32 sha256,
  uint64 sizeBytes, uint32 itemCount, bytes4 errorCode
)
```

Results match `outputs` by **position**, not by kind lookup alone. CONTRACT has `data`, DA has `outputURI`, STREAM has neither. For CONTRACT/DA, SHA-256 and size cover the exact returned/stored bytes, including encryption overhead. `itemCount` counts selected emissions. STREAM hash commits the length-prefixed **transmitted binary frames**, `sizeBytes` counts selected plaintext bytes, and `itemCount` counts accepted publications; see the private-I/O reference.

Check the seven-byte `RITOUT1` prefix and canonical outer result first. Simulated short calls may return placeholders. Early validation/preparation failures and fallback errors can have encoding `0` and no pipe array: handle them before decoding `contractOutput`. For encoding `4`, decode with `decodePipeResults` (or Solidity `RITHTTP1.decodePipeResults`) and require the expected count, kind, encoding and encryption for each application-relevant index.

`hasError` summarizes failures; it does **not** invalidate every successful pipe. A stream publish or DA upload failure preserves a successful CONTRACT usage result. Inspect each pipe's `success/errorCode` and apply the application's policy: account authenticated usage even if live delivery failed, while reporting delivery separately. Fatal upstream read failure, non-2xx response and observed cancellation invalidate incomplete outputs. Hash/size on failed pipes are not proof of a completed output. Error tags include `DGST`, `EART`, `HTTP`, `JSON`, `SECR`, `JQER`, `UPLD`, `SIZE` (four ASCII bytes; zero means none).

## Completion modes

| Mode | Options | Completion |
|---|---|---|
| Short HTTP | No `AWAIT_RESPONSE`; optional `STREAM_RESPONSE` | RITOUT1 in settled short output; fit short TTL |
| Long task API | No `AWAIT_RESPONSE` or `STREAM_RESPONSE` | Initial hydration, existing submit/poll/result flow, then pipe processing |
| Held Long HTTP | `AWAIT_RESPONSE` | Phase 1 before one cancellable request; Phase 2 returns cached result |
| Held Long SSE | `AWAIT_RESPONSE \| STREAM_RESPONSE` | Live selected frames, optional collected contract/DA, then Phase 2 |

Every RITHTTP1 Long HTTP request sets legacy `resultJsonPath="."`. Held mode still encodes all 38 outer fields, with ignored task/poll/result placeholders. `maxPollBlock` is its deadline. Completed results are cached across delivery/proof retries to avoid repeating provider calls/uploads. An open TCP request is not durable across a crash; result caching is not a general exactly-once provider-charge guarantee.

The upstream body must itself request streaming (for example `stream:true`). SSE parsing requires successful `text/event-stream`; short and long handlers can both parse SSE. The transport/authentication endpoint is shared with native LLM, but opaque tokens carry selected RITPIPE1 records/ciphertexts, **not raw provider JSON or native LLM token content**. A publisher acknowledgment means queue acceptance, not delivery to a remote subscriber. Live text remains provisional until canonical settlement verifies its hash, count, byte size and job/pipe/sequence bindings.

## Limits and deployment checklist

Current bounds: at most 8 input refs, 6 output pipes, 1 STREAM and 4 DA; 10 KiB envelope and **10 KiB full outer precompile request**; 10 MiB hydrated body/aggregate collected output; 512-byte selectors; 2 KiB aggregate CONTRACT plaintext (effective capacity may be lower after reserving callback metadata/encryption); 1 MiB per SSE event, 4,096 SSE events, 10 MiB SSE data, 14 MiB SSE wire; 5 KiB encoded callback; 1,024 bytes per returned URI. Additional AST, projection, intermediate-value and JSON-nesting budgets apply. Input downloads/decrypted content are bounded as well as the hydrated result.

Measure the **complete** 16/38-field ABI including secret blobs, signatures, callback configuration, refs and pipes. DA hydration reduces body size but does not waive the outer request cap. Large DA URI receipts can fail individually if callback capacity is exhausted while valid contract output is retained.

- Pin an executor binary compatible with this four-field revision; never infer compatibility from registry membership alone.
- Bind encryption to the executor that can decrypt the chosen secret/input, rather than picking another available executor.
- Use four fields, only current options, valid keys and empty non-DA destinations; preflight aliases and selectors.
- Authenticate callback/job and verify expected per-pipe metadata and commitments before accepting output.
- Run included Bun/Foundry codec fixtures and application-specific failure/usage tests before live deployment.

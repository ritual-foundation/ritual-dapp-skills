import { encrypt, decrypt, PrivateKey, PublicKey } from "eciesjs";
import { gcm } from "@noble/ciphers/aes";
import { hexToBytes, bytesToHex, keccak256, sha256, type Hex } from "viem";
// Explicit per-call configuration: never depend on another module's global ECIES settings.
const ECIES = {
  ellipticCurve: "secp256k1" as const,
  isEphemeralKeyCompressed: false,
  isHkdfKeyCompressed: false,
  symmetricAlgorithm: "aes-256-gcm" as const,
  symmetricNonceLength: 12 as const,
  ephemeralKeySize: 65,
};
const MAGIC = new TextEncoder().encode("RITHTTP1");
const join = (...parts: Uint8Array[]) => {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let offset = 0;
  for (const part of parts) {
    out.set(part, offset);
    offset += part.length;
  }
  return out;
};
function u32(value: number) {
  if (!Number.isInteger(value) || value < 0 || value > 0xffffffff)
    throw new Error("invalid uint32");
  const out = new Uint8Array(4);
  new DataView(out.buffer).setUint32(0, value);
  return out;
}
function hasKind(data: Uint8Array, kind: number, minimum: number) {
  if (
    data.length < minimum ||
    !MAGIC.every((b, i) => data[i] === b) ||
    data[8] !== kind
  )
    throw new Error("invalid RITHTTP1 encoding");
}
function publicKey(key: Hex) {
  const bytes = hexToBytes(key);
  if (bytes.length !== 65 || bytes[0] !== 4)
    throw new Error("recipient must be uncompressed secp256k1");
  PublicKey.fromHex(key.slice(2), "secp256k1");
  return bytes;
}
export function recipientKeyId(key: Hex): Hex {
  return keccak256(publicKey(key));
}
export function encryptRitHttpArtifact(
  plaintext: Uint8Array,
  recipients: Hex[],
): Uint8Array {
  if (recipients.length < 1 || recipients.length > 8)
    throw new Error("recipient count must be 1–8");
  const dek = crypto.getRandomValues(new Uint8Array(32));
  const records = recipients.map((key) => ({
    id: recipientKeyId(key),
    wrapped: encrypt(publicKey(key), dek, ECIES),
  }));
  records.sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  if (
    records.some(
      (r, i) =>
        r.wrapped.length !== 125 || (i > 0 && r.id === records[i - 1].id),
    )
  )
    throw new Error("invalid or duplicate recipient");
  const nonce = crypto.getRandomValues(new Uint8Array(12));
  const header = join(
    MAGIC,
    new Uint8Array([1, records.length]),
    ...records.map((r) => join(hexToBytes(r.id), r.wrapped)),
    nonce,
  );
  const sealed = gcm(dek, nonce, header).encrypt(plaintext);
  return join(header, sealed.slice(-16), sealed.slice(0, -16));
}
export function decryptRitHttpArtifact(
  privateKey: Hex,
  data: Uint8Array,
  expectedDigest?: Hex,
): Uint8Array {
  if (expectedDigest && sha256(data) !== expectedDigest.toLowerCase())
    throw new Error("artifact digest mismatch");
  hasKind(data, 1, 10);
  const count = data[9];
  if (count < 1 || count > 8) throw new Error("recipient count must be 1–8");
  const nonceOffset = 10 + count * 157,
    headerLength = nonceOffset + 12;
  if (data.length < headerLength + 16) throw new Error("truncated artifact");
  const id = recipientKeyId(
    ("0x" +
      PrivateKey.fromHex(privateKey.slice(2), "secp256k1").publicKey.toHex(
        false,
      )) as Hex,
  );
  let wrapped: Uint8Array | undefined,
    previous = "";
  for (let i = 0; i < count; i++) {
    const offset = 10 + i * 157,
      keyId = bytesToHex(data.slice(offset, offset + 32));
    if (i && keyId <= previous)
      throw new Error("recipient records must be sorted and unique");
    previous = keyId;
    if (keyId === id) wrapped = data.slice(offset + 32, offset + 157);
  }
  if (!wrapped) throw new Error("recipient not authorized");
  const dek = decrypt(privateKey.slice(2), wrapped, ECIES);
  if (dek.length !== 32) throw new Error("invalid DEK");
  return gcm(
    dek,
    data.slice(nonceOffset, headerLength),
    data.slice(0, headerLength),
  ).decrypt(
    join(
      data.slice(headerLength + 16),
      data.slice(headerLength, headerLength + 16),
    ),
  );
}

export type PipeBinding = {
  jobId: Hex;
  pipeIndex: number;
  encoding: number;
  sequence: number;
};
const PIPE_MAGIC = new TextEncoder().encode("RITPIPE1");
export function encodePipeRecord(
  binding: PipeBinding,
  payload: Uint8Array,
): Uint8Array {
  const job = hexToBytes(binding.jobId);
  if (
    job.length !== 32 ||
    !Number.isInteger(binding.pipeIndex) ||
    binding.pipeIndex < 0 ||
    binding.pipeIndex > 5 ||
    ![0, 1].includes(binding.encoding) ||
    payload.length > 10 * 1024 * 1024
  )
    throw new Error("invalid pipe binding/size");
  return join(
    PIPE_MAGIC,
    job,
    new Uint8Array([binding.pipeIndex, binding.encoding]),
    u32(binding.sequence),
    u32(payload.length),
    payload,
  );
}
export function decodePipeRecord(
  record: Uint8Array,
  expected: PipeBinding,
): Uint8Array {
  if (record.length < 50) throw new Error("truncated pipe record");
  const payload = record.slice(50),
    canonical = encodePipeRecord(expected, payload);
  if (!canonical.every((b, i) => record[i] === b))
    throw new Error("pipe binding mismatch");
  return payload;
}
export function encryptPipeRecord(
  key: Hex,
  binding: PipeBinding,
  payload: Uint8Array,
): Uint8Array {
  return encrypt(publicKey(key), encodePipeRecord(binding, payload), ECIES);
}
export function decryptPipeRecord(
  key: Hex,
  ciphertext: Uint8Array,
  expected: PipeBinding,
): Uint8Array {
  return decodePipeRecord(decrypt(key.slice(2), ciphertext, ECIES), expected);
}
// Hash exact transmitted binary records/ciphertexts, NOT base64 strings or a DA object.
export function streamDigest(frames: readonly Uint8Array[]): Hex {
  return sha256(join(...frames.flatMap((frame) => [u32(frame.length), frame])));
}
export function verifyStreamFrames(
  frames: readonly Uint8Array[],
  expected: Omit<PipeBinding, "sequence"> & {
    sha256: Hex;
    sizeBytes: bigint;
    itemCount: number;
    encrypted: boolean;
  },
  privateKey?: Hex,
): Uint8Array[] {
  if (
    frames.length !== expected.itemCount ||
    streamDigest(frames) !== expected.sha256.toLowerCase()
  )
    throw new Error("stream commitment mismatch");
  if (expected.encrypted && !privateKey)
    throw new Error("private key required");
  let count = 0n;
  const payloads = frames.map((frame, sequence) => {
    const binding = { ...expected, sequence };
    const payload = expected.encrypted
      ? decryptPipeRecord(privateKey!, frame, binding)
      : decodePipeRecord(frame, binding);
    count += BigInt(payload.length);
    return payload;
  });
  if (count !== expected.sizeBytes)
    throw new Error("stream selected-byte count mismatch");
  return payloads;
}
// CONTRACT.data and fetched DA bytes share this verification; plain outputs have no record.
export function verifyCollectedOutput(
  bytes: Uint8Array,
  expected: Omit<PipeBinding, "sequence"> & {
    sha256: Hex;
    sizeBytes: bigint;
    encrypted: boolean;
  },
  privateKey?: Hex,
): Uint8Array {
  if (
    BigInt(bytes.length) !== expected.sizeBytes ||
    sha256(bytes) !== expected.sha256.toLowerCase()
  )
    throw new Error("output commitment mismatch");
  if (!expected.encrypted) return bytes;
  if (!privateKey) throw new Error("private key required");
  return decryptPipeRecord(privateKey, bytes, { ...expected, sequence: 0 });
}

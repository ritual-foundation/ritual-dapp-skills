import { test, expect } from "bun:test";
import { ECIES_CONFIG } from "eciesjs";
import { readFileSync } from "node:fs";
import { sha256, bytesToHex, type Hex } from "viem";
import {
  recipientKeyId,
  encryptRitHttpArtifact,
  decryptRitHttpArtifact,
  encodePipeRecord,
  decodePipeRecord,
  encryptPipeRecord,
  decryptPipeRecord,
  streamDigest,
  verifyStreamFrames,
  verifyCollectedOutput,
} from "./rithttp-private-io";
const raw = readFileSync(
  new URL("./testdata/private_io_vectors.json", import.meta.url),
);
const vectors = JSON.parse(raw.toString());
const bytes = (v: string) => new Uint8Array(Buffer.from(v, "base64"));
const key = (name: string) => `0x${vectors.keys[name].private_key_hex}` as Hex;
const hex = (v: string) => `0x${v}` as Hex;
test("canonical fixture bytes retain their independently pinned digest", () => {
  expect(sha256(raw)).toBe(
    "0xb5ff13a0a263a42b009d66a71d91fcf85d0908922f5e4c97004207b61e2b3dac",
  );
});
for (const [name, a] of Object.entries(vectors.artifacts) as any)
  test(`canonical artifact ${name} decrypts for every recipient`, () => {
    for (const recipient of a.recipient_keys) {
      expect(recipientKeyId(hex(vectors.keys[recipient].public_key_hex))).toBe(
        hex(vectors.keys[recipient].recipient_id_hex),
      );
      expect(
        decryptRitHttpArtifact(
          key(recipient),
          bytes(a.bytes_base64),
          hex(a.sha256_hex),
        ),
      ).toEqual(bytes(a.plaintext_base64));
    }
  });
for (const [name, a] of Object.entries(vectors.failures) as any)
  test(`canonical malformed artifact ${name} is rejected`, () => {
    const data = a.bytes_base64
      ? bytes(a.bytes_base64)
      : bytes(vectors.artifacts[a.artifact].bytes_base64);
    expect(() =>
      decryptRitHttpArtifact(
        key(a.private_key ?? "k1"),
        data,
        a.provided_sha256_hex ? hex(a.provided_sha256_hex) : undefined,
      ),
    ).toThrow();
  });
test("new multi-recipient artifact round-trips and rejects duplicate/noncanonical public keys", () => {
  const recipients = ["k1", "k2"].map((n) =>
    hex(vectors.keys[n].public_key_hex),
  );
  const plain = new TextEncoder().encode('{"new":true}'),
    data = encryptRitHttpArtifact(plain, recipients.reverse());
  expect(decryptRitHttpArtifact(key("k1"), data, sha256(data))).toEqual(plain);
  expect(decryptRitHttpArtifact(key("k2"), data)).toEqual(plain);
  expect(() =>
    encryptRitHttpArtifact(plain, [recipients[0], recipients[0]]),
  ).toThrow();
  expect(() => encryptRitHttpArtifact(plain, ["0x04" as Hex])).toThrow();
});
test("private codec is independent of application-global ECIES settings", () => {
  const previous = { ...ECIES_CONFIG };
  try {
    ECIES_CONFIG.ellipticCurve = "x25519";
    ECIES_CONFIG.symmetricNonceLength = 16;
    const artifact = vectors.artifacts.one_recipient_empty_object;
    expect(
      decryptRitHttpArtifact(key("k1"), bytes(artifact.bytes_base64)),
    ).toEqual(bytes(artifact.plaintext_base64));
    const data = encryptRitHttpArtifact(new Uint8Array([1, 2]), [
      hex(vectors.keys.k1.public_key_hex),
    ]);
    expect(decryptRitHttpArtifact(key("k1"), data)).toEqual(
      new Uint8Array([1, 2]),
    );
  } finally {
    Object.assign(ECIES_CONFIG, previous);
  }
});

const binding = {
  jobId: ("0x" + "11".repeat(32)) as Hex,
  pipeIndex: 1,
  encoding: 1,
  sequence: 0,
};
const plain = new TextEncoder().encode("Hi!");
const publicKey = hex(vectors.keys.k1.public_key_hex);
test("RITPIPE1 exact record layout and binding checks", () => {
  const record = encodePipeRecord(binding, plain);
  expect(record.length).toBe(53);
  expect(new TextDecoder().decode(record.slice(0, 8))).toBe("RITPIPE1");
  expect(bytesToHex(record.slice(8, 40))).toBe(binding.jobId);
  expect([...record.slice(40, 50)]).toEqual([1, 1, 0, 0, 0, 0, 0, 0, 0, 3]);
  expect(decodePipeRecord(record, binding)).toEqual(plain);
  for (const bad of [
    { ...binding, jobId: ("0x" + "22".repeat(32)) as Hex },
    { ...binding, pipeIndex: 2 },
    { ...binding, encoding: 0 },
    { ...binding, sequence: 1 },
  ])
    expect(() => decodePipeRecord(record, bad)).toThrow();
  expect(() => decodePipeRecord(record.slice(0, -1), binding)).toThrow();
  expect(() =>
    decodePipeRecord(new Uint8Array([...record, 0]), binding),
  ).toThrow();
});
for (const encrypted of [false, true])
  test(`current stream and collected output verification, encrypted=${encrypted}`, () => {
    const frames = [plain, new Uint8Array()].map((payload, sequence) =>
      encrypted
        ? encryptPipeRecord(publicKey, { ...binding, sequence }, payload)
        : encodePipeRecord({ ...binding, sequence }, payload),
    );
    const expected = {
      ...binding,
      encrypted,
      sha256: streamDigest(frames),
      sizeBytes: 3n,
      itemCount: 2,
    };
    expect(verifyStreamFrames(frames, expected, key("k1"))).toEqual([
      plain,
      new Uint8Array(),
    ]);
    expect(() =>
      verifyStreamFrames([...frames].reverse(), expected, key("k1")),
    ).toThrow();
    expect(() =>
      verifyStreamFrames(frames.slice(0, 1), expected, key("k1")),
    ).toThrow();
    expect(() =>
      verifyStreamFrames(frames, { ...expected, sizeBytes: 4n }, key("k1")),
    ).toThrow();
    expect(() =>
      verifyStreamFrames(frames, { ...expected, pipeIndex: 2 }, key("k1")),
    ).toThrow();
    if (encrypted) {
      expect(() => verifyStreamFrames(frames, expected)).toThrow();
      const bad = frames[0].slice();
      bad[bad.length - 1] ^= 1;
      expect(() => decryptPipeRecord(key("k1"), bad, binding)).toThrow();
    }
    const stored = encrypted
      ? encryptPipeRecord(publicKey, binding, plain)
      : plain;
    const collected = {
      ...binding,
      encrypted,
      sha256: sha256(stored),
      sizeBytes: BigInt(stored.length),
    };
    expect(verifyCollectedOutput(stored, collected, key("k1"))).toEqual(plain);
    expect(() =>
      verifyCollectedOutput(stored, { ...collected, sizeBytes: 0n }, key("k1")),
    ).toThrow();
    expect(collected.sha256).not.toBe(expected.sha256);
  });

import {
  concatHex,
  decodeAbiParameters,
  encodeAbiParameters,
  sliceHex,
  stringToHex,
  toHex,
  size,
  type Hex,
} from "viem";
import { PublicKey } from "eciesjs";

export const RITHTTP = { AWAIT_RESPONSE: 1, STREAM_RESPONSE: 8 } as const;
export const PIPE = { CONTRACT: 0, STREAM: 1, DA: 2 } as const;
export const ENCODING = { JSON: 0, UTF8: 1 } as const;
export const EMPTY_REF = { platform: "", path: "", keyRef: "" } as const;
export type StorageRef = { platform: string; path: string; keyRef: string };
export type OutputPipe = {
  kind: number;
  jq: string;
  encoding: number;
  recipientPublicKey: Hex;
  destination: StorageRef;
};
const refComponents = [
  { name: "platform", type: "string" },
  { name: "path", type: "string" },
  { name: "keyRef", type: "string" },
] as const;
export const requestAbi = [
  { name: "options", type: "uint32" },
  { name: "jsonTemplate", type: "bytes" },
  {
    name: "inputRefs",
    type: "tuple[]",
    components: [
      { name: "ref", type: "tuple", components: refComponents },
      { name: "sha256Digest", type: "bytes32" },
    ],
  },
  {
    name: "outputs",
    type: "tuple[]",
    components: [
      { name: "kind", type: "uint8" },
      { name: "jq", type: "string" },
      { name: "encoding", type: "uint8" },
      { name: "recipientPublicKey", type: "bytes" },
      { name: "destination", type: "tuple", components: refComponents },
    ],
  },
] as const;
export const pipeResultsAbi = [
  {
    type: "tuple[]",
    components: [
      { name: "kind", type: "uint8" },
      { name: "encoding", type: "uint8" },
      { name: "encrypted", type: "bool" },
      { name: "success", type: "bool" },
      { name: "data", type: "bytes" },
      { name: "outputURI", type: "string" },
      { name: "sha256", type: "bytes32" },
      { name: "sizeBytes", type: "uint64" },
      { name: "itemCount", type: "uint32" },
      { name: "errorCode", type: "bytes4" },
    ],
  },
] as const;
export const resultAbi = [
  { name: "hasError", type: "bool" },
  { name: "upstreamStatus", type: "uint16" },
  { name: "contractEncoding", type: "uint8" },
  { name: "contractOutput", type: "bytes" },
  {
    name: "receipts",
    type: "tuple[]",
    components: [
      { name: "success", type: "bool" },
      { name: "outputUri", type: "string" },
      { name: "sha256Digest", type: "bytes32" },
      { name: "sizeBytes", type: "uint64" },
      { name: "errorCode", type: "bytes4" },
    ],
  },
  { name: "errorCode", type: "bytes4" },
] as const;

function validateRef(ref: StorageRef) {
  if (
    !["gcs", "hf", "pinata"].includes(ref.platform) ||
    !ref.path ||
    !ref.keyRef.startsWith("storage:") ||
    new TextEncoder().encode(ref.keyRef).length > 128
  )
    throw new Error("invalid storage reference");
}
// Structural checks only. Executor validation remains authoritative for selectors,
// normalized DA destinations, secrets/policies and the complete outer request size.
export function encodeRitHttp1(args: {
  options: number;
  jsonTemplate: unknown;
  inputRefs: readonly { ref: StorageRef; sha256Digest: Hex }[];
  outputs: readonly OutputPipe[];
}): Hex {
  if (
    !Number.isInteger(args.options) ||
    args.options < 0 ||
    args.options > 9 ||
    args.options & ~9
  )
    throw new Error("unknown options");
  if (
    args.inputRefs.length > 8 ||
    args.outputs.length > 6 ||
    args.outputs.filter((p) => p.kind === PIPE.STREAM).length > 1 ||
    args.outputs.filter((p) => p.kind === PIPE.DA).length > 4
  )
    throw new Error("too many refs/pipes");
  for (const input of args.inputRefs) {
    validateRef(input.ref);
    if (
      !/^0x[0-9a-fA-F]{64}$/.test(input.sha256Digest) ||
      BigInt(input.sha256Digest) === 0n
    )
      throw new Error("nonzero SHA-256 required");
  }
  for (const p of args.outputs) {
    if (
      ![0, 1, 2].includes(p.kind) ||
      ![0, 1].includes(p.encoding) ||
      !p.jq ||
      new TextEncoder().encode(p.jq).length > 512
    )
      throw new Error("invalid output pipe");
    if (p.recipientPublicKey !== "0x") {
      if (!/^0x04[0-9a-fA-F]{128}$/.test(p.recipientPublicKey))
        throw new Error("invalid recipient key");
      PublicKey.fromHex(p.recipientPublicKey.slice(2), "secp256k1");
    }
    if (p.kind === PIPE.DA) validateRef(p.destination);
    else if (Object.values(p.destination).some(Boolean))
      throw new Error("only DA takes a destination");
  }
  const template = JSON.stringify(args.jsonTemplate);
  if (template === undefined) throw new Error("JSON template required");
  const encoded = concatHex([
    stringToHex("RITHTTP1"),
    encodeAbiParameters(requestAbi, [
      args.options,
      toHex(template),
      args.inputRefs,
      args.outputs,
    ]),
  ]);
  if (size(encoded) > 10 * 1024) throw new Error("request exceeds 10 KiB");
  return encoded;
}
export function decodeRitOut1(data: Hex) {
  if (!data.startsWith(stringToHex("RITOUT1")) || size(data) > 5 * 1024)
    throw new Error("invalid RITOUT1 result");
  const tail = sliceHex(data, 7),
    decoded = decodeAbiParameters(resultAbi, tail);
  if (
    encodeAbiParameters(resultAbi, decoded).toLowerCase() !==
      tail.toLowerCase() ||
    decoded[4].length > 4
  )
    throw new Error("noncanonical RITOUT1");
  return decoded;
}
export function decodePipeResults(data: Hex) {
  if (size(data) > 5 * 1024) throw new Error("pipe results too large");
  const decoded = decodeAbiParameters(pipeResultsAbi, data);
  if (
    decoded[0].length > 6 ||
    encodeAbiParameters(pipeResultsAbi, decoded).toLowerCase() !==
      data.toLowerCase()
  )
    throw new Error("noncanonical pipe results");
  return decoded[0];
}

import { test, expect } from "bun:test";
import { PrivateKey } from "eciesjs";
import { decodeAbiParameters, encodeAbiParameters, type Hex } from "viem";
import {
  DKMS,
  REQUEST_ABI,
  RESPONSE_ABI,
  encodeDerivation,
  decodeDerivation,
  waitDerivation,
} from "./derive";
const owner = ("0x" + "11".repeat(20)) as Hex,
  executor = ("0x" + "22".repeat(20)) as Hex;
const publicKey = ("0x" + new PrivateKey().publicKey.toHex(false)) as Hex;
const output = encodeAbiParameters(RESPONSE_ABI, [owner, publicKey]);
test("canonical ten-field request and two-field result round-trip", () => {
  const fields = decodeAbiParameters(
    REQUEST_ABI,
    encodeDerivation(executor, owner, 17n),
  );
  expect(fields.length).toBe(10);
  expect(fields.slice(-3)).toEqual([owner, 17n, 1]);
  expect(decodeDerivation(output)).toEqual({
    paymentAddress: owner,
    daPublicKey: publicKey,
  });
});
test("reject bad indexes and malformed results", () => {
  expect(() => encodeDerivation(executor, owner, 2n ** 64n)).toThrow();
  expect(() => decodeDerivation("0x")).toThrow();
  expect(() =>
    decodeDerivation(encodeAbiParameters(RESPONSE_ABI, [owner, "0x04"])),
  ).toThrow();
});
test("find bare SPC result on exact origin commitment, ignoring foreign precompiles", async () => {
  const origin = ("0x" + "aa".repeat(32)) as Hex,
    commit = ("0x" + "bb".repeat(32)) as Hex;
  const client = {
    getLogs: async () => [{ args: { jobId: origin }, transactionHash: commit }],
    request: async ({ params: [hash] }: any) =>
      hash === origin
        ? null
        : {
            status: "0x1",
            spcCalls: [
              { address: executor, output: "0x1234" },
              { address: DKMS, output },
            ],
          },
  };
  expect(await waitDerivation(client, executor, origin, 0n)).toEqual({
    paymentAddress: owner,
    daPublicKey: publicKey,
  });
});
test("reverted receipt fails rather than retrying submission", async () => {
  const client = {
    getLogs: async () => [],
    request: async () => ({ status: "0x0" }),
  };
  await expect(
    waitDerivation(client, executor, ("0x" + "aa".repeat(32)) as Hex, 0n),
  ).rejects.toThrow("reverted");
});

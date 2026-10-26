import { test, expect } from "bun:test";
import { encodeEventTopics, type Hex } from "viem";
import { readShortSettlement, JOB_REMOVED } from "./settlement";
const h = (n: string) => ("0x" + n.repeat(64)) as Hex,
  a = (n: string) => ("0x" + n.repeat(40)) as Hex;
const expected = {
  originHash: h("1"),
  jobId: h("1"),
  settlementHash: h("2"),
  tracker: a("3"),
  precompile: a("4"),
};
const receipt = () => ({
  transactionHash: h("2"),
  status: "success",
  blockNumber: 7n,
  gasUsed: 9n,
  logs: [
    {
      address: a("3"),
      data: "0x",
      topics: encodeEventTopics({
        abi: [JOB_REMOVED],
        eventName: "JobRemoved",
        args: { executor: a("5"), jobId: h("1"), completed: true },
      }),
    },
  ],
  spcCalls: [{ address: a("4"), output: "0xabcd" }],
});
test("settles exact short job using commitment receipt while preserving origin hash", async () => {
  const result = await readShortSettlement(
    { getTransactionReceipt: async () => receipt() },
    expected,
  );
  expect(result).toMatchObject({
    status: "SETTLED",
    txHash: h("1"),
    settlementTxHash: h("2"),
    gasUsed: 9n,
    result: { output: "0xabcd" },
  });
});
for (const kind of [
  "wrong hash",
  "revert",
  "foreign job",
  "foreign emitter",
  "missing output",
  "ambiguous output",
])
  test(`reject ${kind}`, async () => {
    const r = receipt();
    if (kind === "wrong hash") r.transactionHash = h("9");
    if (kind === "revert") r.status = "reverted";
    if (kind === "foreign job")
      r.logs[0].topics = encodeEventTopics({
        abi: [JOB_REMOVED],
        eventName: "JobRemoved",
        args: { executor: a("5"), jobId: h("9"), completed: true },
      });
    if (kind === "foreign emitter") r.logs[0].address = a("9");
    if (kind === "missing output") r.spcCalls = [];
    if (kind === "ambiguous output") r.spcCalls.push(r.spcCalls[0]);
    await expect(
      readShortSettlement({ getTransactionReceipt: async () => r }, expected),
    ).rejects.toThrow();
  });
test("receipt-not-ready propagates for retry rather than marking success", async () => {
  await expect(
    readShortSettlement(
      {
        getTransactionReceipt: async () => {
          throw Error("not ready");
        },
      },
      expected,
    ),
  ).rejects.toThrow("not ready");
});

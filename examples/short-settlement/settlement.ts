import { decodeEventLog, parseAbiItem, type Hex, type Address } from "viem";
export const JOB_REMOVED = parseAbiItem(
  "event JobRemoved(address indexed executor,bytes32 indexed jobId,bool indexed completed)",
);
export class InvalidSettlement extends Error {}
export async function readShortSettlement(
  client: any,
  expected: {
    originHash: Hex;
    jobId: Hex;
    settlementHash: Hex;
    tracker: Address;
    precompile: Address;
  },
) {
  // Receipt-unavailable/network errors deliberately propagate for the hook to retry.
  const receipt = await client.getTransactionReceipt({
    hash: expected.settlementHash,
  });
  if (
    receipt.transactionHash?.toLowerCase() !==
      expected.settlementHash.toLowerCase() ||
    receipt.status !== "success"
  )
    throw new InvalidSettlement("Settlement receipt failed or mismatched");
  if (
    typeof receipt.blockNumber !== "bigint" ||
    typeof receipt.gasUsed !== "bigint"
  )
    throw new InvalidSettlement("Missing settlement metadata");
  if (!Array.isArray(receipt.logs))
    throw new InvalidSettlement("Missing settlement logs");
  const confirmed = receipt.logs.some((log: any) => {
    if (log.address.toLowerCase() !== expected.tracker.toLowerCase())
      return false;
    try {
      const event = decodeEventLog({
        abi: [JOB_REMOVED],
        data: log.data,
        topics: log.topics,
      });
      return (
        event.args.jobId.toLowerCase() === expected.jobId.toLowerCase() &&
        event.args.completed === true
      );
    } catch {
      return false;
    }
  });
  if (!confirmed)
    throw new InvalidSettlement("Receipt does not confirm this completed job");
  const calls = (receipt.spcCalls ?? []).filter(
    (call: any) =>
      call.address?.toLowerCase() === expected.precompile.toLowerCase(),
  );
  if (
    calls.length !== 1 ||
    !calls[0].output ||
    !/^0x(?:[0-9a-fA-F]{2})+$/.test(calls[0].output)
  )
    throw new InvalidSettlement("Missing or ambiguous SPC result");
  return {
    status: "SETTLED" as const,
    txHash: expected.originHash,
    jobId: expected.jobId,
    result: { precompile: expected.precompile, output: calls[0].output as Hex },
    settlementTxHash: expected.settlementHash,
    settledBlock: Number(receipt.blockNumber),
    gasUsed: BigInt(receipt.gasUsed),
  };
}

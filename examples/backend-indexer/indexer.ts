import { parseAbi, decodeEventLog, type Address } from "viem";
import { Database } from "./database";
import {
  readShortSettlement,
  InvalidSettlement,
} from "ritual-short-settlement";
export const TRACKER_ABI = parseAbi([
  "event JobAdded(address indexed executor,bytes32 indexed jobId,address indexed precompileAddress,uint256 commitBlock,bytes precompileInput,address callerAddress,address txOrigin,bytes32 previousBlockHash,uint256 previousBlockNumber,uint256 previousBlockTimestamp,uint256 ttl,uint256 createdAt)",
  "event Phase1Settled(bytes32 indexed jobId,address indexed executor,uint256 settledBlock)",
  "event ResultDelivered(bytes32 indexed jobId,address indexed target,bool success)",
  "event JobRemoved(address indexed executor,bytes32 indexed jobId,bool indexed completed)",
]);
const SHORT = new Set([0x801, 0x802, 0x81b]);
export class Indexer {
  constructor(
    readonly db: Database,
    readonly client: any,
    readonly tracker: Address,
    readonly startBlock: bigint,
    readonly confirmations = 2n,
    readonly chunkSize = 1000n,
  ) {
    if (startBlock < 0n || confirmations < 0n || chunkSize < 1n)
      throw new Error("invalid index bounds");
  }
  async sync() {
    const saved = this.db.getCheckpoint("lastIndexedBlock");
    if (saved !== null) {
      const anchor = await this.client.getBlock({ blockNumber: BigInt(saved) });
      if (anchor.hash !== this.db.getCheckpoint("lastIndexedHash"))
        throw Error(
          "Indexed chain reorganized: rebuild this derived index from START_BLOCK",
        );
    }
    const height = await this.client.getBlockNumber();
    if (height < this.confirmations) return;
    const head = height - this.confirmations;
    let from = saved === null ? this.startBlock : BigInt(saved) + 1n;
    while (from <= head) {
      const to =
        from + this.chunkSize - 1n > head ? head : from + this.chunkSize - 1n;
      const anchor = await this.client.getBlock({ blockNumber: to });
      const logs = await this.client.getLogs({
        address: this.tracker,
        fromBlock: from,
        toBlock: to,
      });
      logs.sort((a: any, b: any) =>
        a.blockNumber < b.blockNumber
          ? -1
          : a.blockNumber > b.blockNumber
            ? 1
            : a.logIndex - b.logIndex,
      );
      const jobs = new Map<string, any>(),
        events: any[] = [];
      for (const log of logs) {
        if (log.removed)
          throw Error(
            "Removed log encountered; retry after chain reconciliation",
          );
        if (log.address.toLowerCase() !== this.tracker.toLowerCase()) continue;
        let event: any;
        try {
          event = decodeEventLog({
            abi: TRACKER_ABI,
            data: log.data,
            topics: log.topics,
            strict: true,
          });
        } catch {
          continue;
        }
        const a = event.args,
          id = a.jobId.toLowerCase();
        events.push({ ...log, ...event });
        let job = jobs.get(id) ?? this.db.getJob(id);
        if (event.eventName === "JobAdded") {
          if (job) continue;
          job = {
            jobId: id,
            txHash: id,
            sender: a.txOrigin,
            caller: a.callerAddress,
            executor: a.executor,
            precompile: Number(BigInt(a.precompileAddress)),
            submittedBlock: a.commitBlock.toString(),
            ttl: a.ttl.toString(),
            status: "COMMITTED",
          };
        } else {
          if (!job)
            throw Error(
              "Job lifecycle event precedes its admission: configure START_BLOCK before JobAdded",
            );
          if (["SETTLED", "FAILED", "EXPIRED"].includes(job.status)) continue;
          if (event.eventName === "Phase1Settled")
            job = {
              ...job,
              status: "RESULT_READY",
              phase1Block: a.settledBlock.toString(),
            };
          if (event.eventName === "ResultDelivered")
            job = {
              ...job,
              status: a.success ? "SETTLED" : "FAILED",
              deliveryTxHash: log.transactionHash,
              error: a.success ? null : "Callback delivery failed",
            };
          if (event.eventName === "JobRemoved") {
            if (!a.completed)
              job = {
                ...job,
                status: "EXPIRED",
                error: "Job removed without completion",
              };
            else if (SHORT.has(job.precompile)) {
              try {
                const result = await readShortSettlement(this.client, {
                  originHash: job.txHash,
                  jobId: id,
                  settlementHash: log.transactionHash,
                  tracker: this.tracker,
                  precompile:
                    a.precompileAddress ??
                    "0x" + job.precompile.toString(16).padStart(40, "0"),
                });
                job = { ...job, ...result };
              } catch (error) {
                if (error instanceof InvalidSettlement)
                  job = { ...job, status: "FAILED", error: error.message };
                else throw error;
              }
            }
          }
        }
        jobs.set(id, job);
      }
      if (
        (await this.client.getBlock({ blockNumber: to })).hash !== anchor.hash
      )
        throw Error("Chain changed during backfill; retry batch");
      this.db.commitBatch(events, [...jobs.values()], {
        block: to.toString(),
        hash: anchor.hash,
      });
      from = to + 1n;
    }
  }
}

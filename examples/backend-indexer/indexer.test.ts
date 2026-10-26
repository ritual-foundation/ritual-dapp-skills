import { test, expect } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  encodeAbiParameters,
  encodeEventTopics,
  type Hex,
  type Address,
} from "viem";
import { Database } from "./database";
import { Indexer, TRACKER_ABI } from "./indexer";
const h = (n: string) => ("0x" + n.repeat(64)) as Hex,
  a = (n: string) => ("0x" + n.repeat(40)) as Address;
const tracker = a("3"),
  origin = h("1"),
  commit = h("2"),
  executor = a("4"),
  http = "0x0000000000000000000000000000000000000801";
function event(
  name: string,
  args: any,
  index: number,
  transactionHash = commit,
) {
  const schema = TRACKER_ABI.find((v) => v.name === name)!;
  return {
    address: tracker,
    blockNumber: 1n,
    blockHash: h("a"),
    transactionHash,
    logIndex: index,
    removed: false,
    topics: encodeEventTopics({ abi: [schema], eventName: name, args } as any),
    data: encodeAbiParameters(
      schema.inputs.filter((v) => !v.indexed) as any,
      schema.inputs.filter((v) => !v.indexed).map((v) => args[v.name]),
    ),
  };
}
const admission = (precompileAddress = http) =>
  event(
    "JobAdded",
    {
      executor,
      jobId: origin,
      precompileAddress,
      commitBlock: 1n,
      precompileInput: "0x",
      callerAddress: a("5"),
      txOrigin: a("6"),
      previousBlockHash: h("9"),
      previousBlockNumber: 0n,
      previousBlockTimestamp: 0n,
      ttl: 100n,
      createdAt: 1n,
    },
    0,
  );
const removal = (completed = true) =>
  event("JobRemoved", { executor, jobId: origin, completed }, 1);
function fixture(logs: any[]) {
  return {
    getBlockNumber: async () => 1n,
    getBlock: async () => ({ hash: h("a") }),
    getLogs: async () => logs,
    getTransactionReceipt: async () => ({
      transactionHash: commit,
      status: "success",
      blockNumber: 1n,
      gasUsed: 19n,
      logs,
      spcCalls: [{ address: http, output: "0xabcd" }],
    }),
  };
}
test("decode/upsert backfill persists exact short result and resumes without replaying old events", async () => {
  const dir = mkdtempSync(join(tmpdir(), "ritual-index-")),
    path = join(dir, "test.sqlite");
  let db = new Database(path);
  try {
    const client = fixture([admission(), removal()]);
    await new Indexer(db, client, tracker, 1n, 0n).sync();
    expect(db.getJob(origin)).toMatchObject({
      status: "SETTLED",
      txHash: origin,
      settlementTxHash: commit,
      result: { output: "0xabcd" },
      gasUsed: "19",
    });
    expect((db.sql.query("SELECT count(*) n FROM events").get() as any).n).toBe(
      2,
    );
    db.close();
    db = new Database(path);
    client.getLogs = async () => {
      throw Error("old range must not be queried");
    };
    await new Indexer(db, client, tracker, 1n, 0n).sync();
    expect(db.getCheckpoint("lastIndexedBlock")).toBe("1");
  } finally {
    db.close();
    rmSync(dir, { recursive: true, force: true });
  }
});
test("unavailable receipt leaves the whole chunk uncommitted and retry succeeds", async () => {
  const db = new Database(":memory:");
  try {
    const client = fixture([admission(), removal()]),
      original = client.getTransactionReceipt;
    client.getTransactionReceipt = async () => {
      throw Error("not ready");
    };
    const indexer = new Indexer(db, client, tracker, 1n, 0n);
    await expect(indexer.sync()).rejects.toThrow("not ready");
    expect(db.getJob(origin)).toBeNull();
    expect(db.getCheckpoint("lastIndexedBlock")).toBeNull();
    client.getTransactionReceipt = original;
    await indexer.sync();
    expect(db.getJob(origin).status).toBe("SETTLED");
  } finally {
    db.close();
  }
});
test("long-running completion waits through Phase 1 for delivery; cleanup false expires", async () => {
  for (const completed of [true, false]) {
    const db = new Database(":memory:");
    try {
      const logs = completed
        ? [
            admission("0x0000000000000000000000000000000000000805"),
            event(
              "Phase1Settled",
              { jobId: origin, executor, settledBlock: 1n },
              1,
            ),
            event(
              "ResultDelivered",
              { jobId: origin, target: a("7"), success: true },
              2,
            ),
          ]
        : [admission(), removal(false)];
      await new Indexer(db, fixture(logs), tracker, 1n, 0n).sync();
      expect(db.getJob(origin).status).toBe(completed ? "SETTLED" : "EXPIRED");
    } finally {
      db.close();
    }
  }
});
test("database transaction rolls back events jobs and checkpoint together on storage failure", () => {
  const db = new Database(":memory:");
  try {
    expect(() =>
      db.commitBatch(
        [{ transactionHash: commit, logIndex: 0, eventName: "test" }],
        [{ jobId: origin, status: "COMMITTED" }, { jobId: h("9") }],
        { block: "1", hash: h("a") },
      ),
    ).toThrow();
    expect(db.getJob(origin)).toBeNull();
    expect(db.getCheckpoint("lastIndexedBlock")).toBeNull();
    expect((db.sql.query("SELECT count(*) n FROM events").get() as any).n).toBe(
      0,
    );
  } finally {
    db.close();
  }
});
test("a changed persisted block hash stops indexing rather than accepting mixed history", async () => {
  const db = new Database(":memory:");
  try {
    const client = fixture([admission()]);
    const indexer = new Indexer(db, client, tracker, 1n, 0n);
    await indexer.sync();
    client.getBlock = async () => ({ hash: h("b") });
    await expect(indexer.sync()).rejects.toThrow("reorganized");
    expect(db.getJob(origin).status).toBe("COMMITTED");
  } finally {
    db.close();
  }
});

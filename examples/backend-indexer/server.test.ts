import { test, expect } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
const hash = "0x" + "aa".repeat(32);
test("actual CLI bootstraps durable backfill and serves HTTP against a local RPC fixture", async () => {
  const dir = mkdtempSync(join(tmpdir(), "ritual-api-"));
  const rpc = Bun.serve({
    hostname: "127.0.0.1",
    port: 0,
    async fetch(req) {
      const r = await req.json();
      let result: any;
      if (r.method === "eth_chainId") result = "0x30d";
      else if (r.method === "eth_getCode") result = "0x6000";
      else if (r.method === "eth_blockNumber") result = "0x2";
      else if (r.method === "eth_getLogs") result = [];
      else if (r.method === "eth_getBlockByNumber")
        result = {
          number: r.params[0],
          hash,
          parentHash: hash,
          gasLimit: "0x100000",
          gasUsed: "0x0",
          timestamp: "0x1",
          transactions: [],
          size: "0x0",
          difficulty: "0x0",
          totalDifficulty: "0x0",
          nonce: "0x0000000000000000",
          baseFeePerGas: "0x1",
        };
      else
        return Response.json({
          jsonrpc: "2.0",
          id: r.id,
          error: { code: -32601, message: r.method },
        });
      return Response.json({ jsonrpc: "2.0", id: r.id, result });
    },
  });
  const child = Bun.spawn([process.execPath, "run", "server.ts"], {
    cwd: import.meta.dir,
    env: {
      ...process.env,
      RPC_URL: rpc.url.toString(),
      EXPECTED_CHAIN_ID: "781",
      ASYNC_JOB_TRACKER: "0x" + "11".repeat(20),
      START_BLOCK: "1",
      CONFIRMATIONS: "0",
      DB_PATH: join(dir, "jobs.sqlite"),
      PORT: "0",
      HOST: "127.0.0.1",
    },
    stdout: "pipe",
    stderr: "pipe",
  });
  try {
    const reader = child.stdout.getReader();
    let output = "";
    const timeout = setTimeout(() => child.kill(), 5000);
    try {
      while (!output.includes("LISTENING=")) {
        const part = await reader.read();
        if (part.done)
          throw Error(
            "Server exited: " + (await new Response(child.stderr).text()),
          );
        output += new TextDecoder().decode(part.value);
      }
    } finally {
      clearTimeout(timeout);
      reader.releaseLock();
    }
    const url = output.match(/LISTENING=(\S+)/)![1];
    const health = await (await fetch(url + "health")).json();
    expect(health).toMatchObject({ ok: true, lastIndexedBlock: "2" });
    expect(await (await fetch(url + "jobs")).json()).toEqual([]);
    expect((await fetch(url + "jobs/0x" + "22".repeat(32))).status).toBe(404);
    expect((await fetch(url + "jobs", { method: "POST" })).status).toBe(405);
    child.kill("SIGTERM");
    expect(await child.exited).toBe(0);
  } finally {
    if (child.exitCode === null) child.kill();
    await child.exited;
    await rpc.stop(true);
    rmSync(dir, { recursive: true, force: true });
  }
}, 10000);

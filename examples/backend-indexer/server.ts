import { createPublicClient, http, getAddress } from "viem";
import { Database, json } from "./database";
import { Indexer } from "./indexer";
const required = (name: string) => {
  const value = process.env[name];
  if (!value || value.includes("<")) throw Error(`Set ${name}`);
  return value;
};
if (import.meta.main) {
  const rpc = required("RPC_URL"),
    chain = Number(required("EXPECTED_CHAIN_ID")),
    tracker = getAddress(required("ASYNC_JOB_TRACKER"));
  const start = BigInt(required("START_BLOCK")),
    client = createPublicClient({ transport: http(rpc) });
  if ((await client.getChainId()) !== chain) throw Error("Unexpected chain");
  if (
    !(await client.getCode({ address: tracker })) ||
    (await client.getCode({ address: tracker })) === "0x"
  )
    throw Error("No tracker bytecode");
  const genesis = await client.getBlock({ blockNumber: 0n });
  const db = new Database(process.env.DB_PATH ?? "jobs.sqlite");
  const profile = json({
    chain,
    tracker,
    start: start.toString(),
    genesis: genesis.hash,
  });
  if (db.getCheckpoint("profile") && db.getCheckpoint("profile") !== profile) {
    db.close();
    throw Error("Database belongs to another deployment/start block");
  }
  db.setCheckpoint("profile", profile);
  const indexer = new Indexer(
    db,
    client,
    tracker,
    start,
    BigInt(process.env.CONFIRMATIONS ?? "2"),
  );
  await indexer.sync(); // Serve only after the durable backfill has completed.
  let stopping = false,
    lastError: string | null = null;
  const server = Bun.serve({
    hostname: process.env.HOST ?? "127.0.0.1",
    port: Number(process.env.PORT ?? "3000"),
    fetch(req) {
      const url = new URL(req.url);
      if (req.method !== "GET")
        return new Response("Method not allowed", { status: 405 });
      if (url.pathname === "/health")
        return Response.json(
          {
            ok: lastError === null,
            lastIndexedBlock: db.getCheckpoint("lastIndexedBlock"),
            error: lastError,
          },
          { status: lastError ? 503 : 200 },
        );
      const match = url.pathname.match(/^\/jobs\/(0x[0-9a-fA-F]{64})$/);
      if (match) {
        const job = db.getJob(match[1]);
        return new Response(json(job ?? { error: "not found" }), {
          status: job ? 200 : 404,
          headers: { "content-type": "application/json" },
        });
      }
      if (url.pathname === "/jobs")
        return new Response(json(db.listJobs()), {
          headers: { "content-type": "application/json" },
        });
      return new Response("Not found", { status: 404 });
    },
  });
  console.log("LISTENING=" + server.url);
  const stop = () => {
    stopping = true;
  };
  process.on("SIGINT", stop);
  process.on("SIGTERM", stop);
  try {
    while (!stopping) {
      try {
        await indexer.sync();
        lastError = null;
      } catch {
        lastError =
          "Indexing failed; checkpoint retained. Inspect deployment/reorg and RPC availability.";
      }
      await Bun.sleep(1000);
    }
  } finally {
    await server.stop(true);
    db.close();
  }
}

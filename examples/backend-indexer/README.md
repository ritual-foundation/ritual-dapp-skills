# Runnable tracker indexer and API

Requires public Bun and viem. The local `ritual-short-settlement` dependency is included in the sibling directory; Bun installs it from this checkout. No private SDK, factory source, traffic generator, external database server or workstation configuration is needed.

```bash
cd examples/backend-indexer
bun install
bun run typecheck
bun test
export RPC_URL='<target RPC>' EXPECTED_CHAIN_ID='<target chain ID>'
export ASYNC_JOB_TRACKER='<verified deployment tracker>'
export START_BLOCK='<block at or before the first JobAdded you want indexed>'
export DB_PATH=jobs.sqlite
export CONFIRMATIONS=2
bun run start
```

The server validates chain ID and tracker bytecode, binds the database to chain/genesis/tracker/start block, backfills, then listens on `127.0.0.1:3000`. `GET /jobs`, `GET /jobs/0x<job-id>` and `GET /health` are read-only. HOST/PORT are configurable; exposing the service requires application-specific authentication/rate limits.

SQLite stores job data, decoded events, checkpoint height/hash and deployment profile. Events, job updates and checkpoint commit in one transaction per bounded block range. An unavailable receipt aborts that range for retry. Polling resumes from checkpoint+1 without the gap between historical backfill and starting a live watcher. Long-running jobs wait for ResultDelivered; short jobs require an exact JobRemoved receipt and matching SPC address. Results preserve raw bare SPC bytes so applications can decode the originating request's inline/private/DA/RITHTTP codec explicitly. Long-running delivery records preserve the delivery hash; application-specific callback-result decoding belongs to the consuming application.

SIGINT/SIGTERM stops polling and closes the HTTP server/database. Restart using the same DB_PATH resumes the persisted index. A changed indexed block hash stops advancement and reports unhealthy; rebuild this derived index from START_BLOCK after investigating a reorg. The example does not automatically rewrite history or certify finality. Choose CONFIRMATIONS for the selected deployment and use an archival-capable endpoint for historical logs.

Tests use real on-disk SQLite reopen/transactions, encoded tracker events and controlled RPC receipts. A separate test starts the actual CLI against a local JSON-RPC server and checks its HTTP API/shutdown. These are local integration tests, not live-network indexing claims. The PostgreSQL schema in the backend skill is an optional adaptation target; this service uses its own included SQLite schema.

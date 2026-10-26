import { Database as SQLite } from "bun:sqlite";
export const json = (value: unknown) =>
  JSON.stringify(value, (_k, v) => (typeof v === "bigint" ? v.toString() : v));
export class Database {
  readonly sql: SQLite;
  constructor(path: string) {
    this.sql = new SQLite(path, { create: true });
    this.sql.exec(`PRAGMA journal_mode=WAL;
 CREATE TABLE IF NOT EXISTS jobs(job_id TEXT PRIMARY KEY,status TEXT NOT NULL,data TEXT NOT NULL);
 CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status);
 CREATE TABLE IF NOT EXISTS events(tx_hash TEXT,log_index INTEGER,name TEXT,data TEXT,PRIMARY KEY(tx_hash,log_index));
 CREATE TABLE IF NOT EXISTS checkpoints(key TEXT PRIMARY KEY,value TEXT NOT NULL);`);
  }
  getJob(id: string): any {
    const row = this.sql
      .query("SELECT data FROM jobs WHERE job_id=?")
      .get(id.toLowerCase()) as any;
    return row ? JSON.parse(row.data) : null;
  }
  updateJob(id: string, patch: any) {
    const job = {
      ...(this.getJob(id) ?? {}),
      ...patch,
      jobId: id.toLowerCase(),
    };
    this.sql
      .query(
        "INSERT INTO jobs VALUES(?,?,?) ON CONFLICT(job_id) DO UPDATE SET status=excluded.status,data=excluded.data",
      )
      .run(job.jobId, job.status, json(job));
  }
  getJobsByStatus(statuses: string[]) {
    if (!statuses.length) return [];
    return (
      this.sql
        .query(
          `SELECT data FROM jobs WHERE status IN (${statuses.map(() => "?").join(",")}) ORDER BY job_id`,
        )
        .all(...statuses) as any[]
    ).map((r) => JSON.parse(r.data));
  }
  listJobs(limit = 100) {
    return (
      this.sql
        .query("SELECT data FROM jobs ORDER BY job_id LIMIT ?")
        .all(limit) as any[]
    ).map((r) => JSON.parse(r.data));
  }
  getCheckpoint(key: string) {
    return (
      (
        this.sql
          .query("SELECT value FROM checkpoints WHERE key=?")
          .get(key) as any
      )?.value ?? null
    );
  }
  setCheckpoint(key: string, value: string) {
    this.sql
      .query(
        "INSERT INTO checkpoints VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
      )
      .run(key, value);
  }
  commitBatch(
    events: any[],
    jobs: any[],
    checkpoint: { block: string; hash: string },
  ) {
    this.sql.transaction(() => {
      for (const event of events)
        this.sql
          .query("INSERT OR IGNORE INTO events VALUES(?,?,?,?)")
          .run(
            event.transactionHash,
            event.logIndex,
            event.eventName,
            json(event),
          );
      for (const job of jobs) this.updateJob(job.jobId, job);
      this.setCheckpoint("lastIndexedBlock", checkpoint.block);
      this.setCheckpoint("lastIndexedHash", checkpoint.hash);
    })();
  }
  close() {
    this.sql.close();
  }
}

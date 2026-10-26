# Scheduled + Async RPC Runbook

Deterministic, RPC-only debugging flow for scheduled and scheduled-async transactions.

Use this when a user has a hash but cannot tell whether a scheduled execution happened, which commitment belongs to it, or which executor was selected.

---

## Input Types

You usually start with one of these:

1. **Schedule-submission tx hash** (user called `Scheduler.schedule`)
2. **Async origin hash** (short-running or long-running async job origin)
3. **Scheduled hash** (`TxScheduled` hash for one execution index)

---

## Embedded Utility A: deterministic scheduled hashes

Copy this into a local file (for example `/tmp/scheduled_txs.py`):

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys

import requests

CALL_SCHEDULED_TOPIC = "0xcaca4474e4e795729bb2ff72d20cbac301679d1329458aba9cc4a52235266949"
EXECUTE_SELECTOR = bytes.fromhex("5601eaea")
SCHEDULED_TX_TYPE = b"\x10"
DEFAULT_SCHEDULER = "0x4E0abeE2233D73E66382b45244F7459B34E1490E"


def normalize_hash(value: str) -> str:
    h = value.lower()
    if not h.startswith("0x"):
        h = f"0x{h}"
    if len(h) != 66:
        raise ValueError(f"invalid hash: {value}")
    return h


def normalize_address(value: str) -> str:
    a = value.lower()
    if not a.startswith("0x"):
        a = f"0x{a}"
    if len(a) != 42:
        raise ValueError(f"invalid address: {value}")
    return a


def rpc_call(rpc_url: str, method: str, params: list[object]) -> object:
    res = requests.post(
        rpc_url,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        timeout=20,
    )
    res.raise_for_status()
    payload = res.json()
    if "error" in payload:
        raise RuntimeError(payload["error"])
    return payload["result"]


def read_word(data_hex: str, idx: int) -> int:
    data = data_hex[2:] if data_hex.startswith("0x") else data_hex
    start = idx * 64
    end = start + 64
    return int(data[start:end], 16)


def decode_indexed_address(topic_hex: str) -> str:
    topic = topic_hex[2:] if topic_hex.startswith("0x") else topic_hex
    return f"0x{topic[-40:]}"


def int_to_be(value: int) -> bytes:
    if value == 0:
        return b""
    return value.to_bytes((value.bit_length() + 7) // 8, "big")


def rlp_bytes(data: bytes) -> bytes:
    if len(data) == 1 and data[0] < 0x80:
        return data
    if len(data) <= 55:
        return bytes([0x80 + len(data)]) + data
    lb = int_to_be(len(data))
    return bytes([0xB7 + len(lb)]) + lb + data


def rlp_int(value: int) -> bytes:
    return rlp_bytes(int_to_be(value))


def keccak_hex(payload: bytes) -> str:
    if shutil.which("cast") is None:
        raise RuntimeError("cast is required")
    out = subprocess.run(
        ["cast", "keccak", f"0x{payload.hex()}"], capture_output=True, text=True, check=False
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "cast keccak failed")
    return out.stdout.strip().splitlines()[-1].lower()


def compute_hash(
    scheduler: str,
    origin_hash: str,
    call_id: int,
    execution_index: int,
    start_block: int,
    frequency: int,
    ttl: int,
    caller: str,
    max_fee_per_gas: int,
    max_priority_fee_per_gas: int,
    value: int,
) -> str:
    execute_calldata = (
        EXECUTE_SELECTOR + call_id.to_bytes(32, "big") + execution_index.to_bytes(32, "big")
    )
    fields = [
        rlp_int((1 << 64) - 1),
        rlp_int(max_fee_per_gas),
        rlp_int(max_priority_fee_per_gas),
        rlp_bytes(bytes.fromhex(scheduler[2:])),
        rlp_int(value),
        rlp_bytes(execute_calldata),
        rlp_bytes(bytes.fromhex(origin_hash[2:])),
        rlp_int(call_id),
        rlp_int(execution_index),
        rlp_int(start_block),
        rlp_int(frequency),
        rlp_int(ttl),
        rlp_bytes(bytes.fromhex(caller[2:])),
    ]
    return keccak_hex(SCHEDULED_TX_TYPE + b"".join(fields))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hash", required=True)
    parser.add_argument("--rpc-url", default="https://rpc.ritualfoundation.org")
    parser.add_argument("--scheduler-address", default=DEFAULT_SCHEDULER)
    args = parser.parse_args()

    origin_hash = normalize_hash(args.hash)
    scheduler = normalize_address(args.scheduler_address)

    receipt = rpc_call(args.rpc_url, "eth_getTransactionReceipt", [origin_hash])
    if not receipt:
        raise SystemExit(f"receipt not found: {origin_hash}")

    logs = receipt.get("logs", [])
    print(f"source_tx={origin_hash}")
    found = 0
    for log in logs:
        if str(log.get("address", "")).lower() != scheduler:
            continue
        topics = log.get("topics", [])
        if len(topics) < 4 or str(topics[0]).lower() != CALL_SCHEDULED_TOPIC:
            continue

        found += 1
        data = str(log["data"])
        call_id = int(str(topics[1]), 16)
        caller = decode_indexed_address(str(topics[3]))
        start_block = read_word(data, 0)
        num_calls = read_word(data, 1)
        frequency = read_word(data, 2)
        ttl = read_word(data, 4)
        max_fee_per_gas = read_word(data, 5)
        max_priority_fee_per_gas = read_word(data, 6)
        value = read_word(data, 7)

        print(
            f"\ncall id={call_id} caller={caller} start={start_block} num_calls={num_calls} "
            f"frequency={frequency} ttl={ttl}"
        )
        for execution_index in range(num_calls):
            expected_block = start_block + (execution_index * frequency)
            scheduled_hash = compute_hash(
                scheduler=scheduler,
                origin_hash=origin_hash,
                call_id=call_id,
                execution_index=execution_index,
                start_block=start_block,
                frequency=frequency,
                ttl=ttl,
                caller=caller,
                max_fee_per_gas=max_fee_per_gas,
                max_priority_fee_per_gas=max_priority_fee_per_gas,
                value=value,
            )
            print(
                f"  index={execution_index:>3} block={expected_block:>10} scheduled_hash={scheduled_hash}"
            )

    if found == 0:
        raise SystemExit("no CallScheduled events found in receipt")


if __name__ == "__main__":
    main()
```

Run it:

```bash
python3 /tmp/scheduled_txs.py \
  --hash <SCHEDULE_SUBMISSION_TX_HASH> \
  --rpc-url https://rpc.ritualfoundation.org
```

---

## Embedded Utility B: commitment lookup from async origin hash

Copy this into a local file (for example `/tmp/commitment_tx.py`):

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass

import requests

ASYNC_TRACKER = "0xf00385449fD961925A0B125F5f30b29B682D4bFb"
JOB_ADDED_TOPIC = "0xd83dc24dbfbb1495338e48098805afe63017833c8ddaf1ab7ccbed92f18b8540"
PHASE1_SETTLED_TOPIC = "0x37f71b8eed16673ade1472b9c4d690c8d8cdfb7fd0f55f9cf2c9c9e679f04db4"
JOB_REMOVED_TOPIC = "0x59725cef98fe1b85530b2a0a150f88c48a08cca2cafed999590140955f67b540"


@dataclass(frozen=True)
class Hit:
    tx_hash: str
    block: int
    job_id: str
    executor: str
    commit_block: int
    ttl: int
    phase1_settled: bool
    removed: bool
    removed_completed: bool | None


def normalize_hash(value: str) -> str:
    h = value.lower()
    if not h.startswith("0x"):
        h = f"0x{h}"
    if len(h) != 66:
        raise ValueError(f"invalid hash: {value}")
    return h


def normalize_address(value: str) -> str:
    a = value.lower()
    if not a.startswith("0x"):
        a = f"0x{a}"
    if len(a) != 42:
        raise ValueError(f"invalid address: {value}")
    return a


def rpc_call(rpc_url: str, method: str, params: list[object]) -> object:
    res = requests.post(
        rpc_url,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        timeout=20,
    )
    res.raise_for_status()
    payload = res.json()
    if "error" in payload:
        raise RuntimeError(payload["error"])
    return payload["result"]


def to_hex_block(block: int) -> str:
    return hex(max(0, block))


def decode_indexed_address(topic_hex: str) -> str:
    t = topic_hex[2:] if topic_hex.startswith("0x") else topic_hex
    return f"0x{t[-40:]}"


def read_word(data_hex: str, idx: int) -> int:
    data = data_hex[2:] if data_hex.startswith("0x") else data_hex
    return int(data[idx * 64 : (idx + 1) * 64], 16)


def has_log(
    rpc_url: str, tracker: str, from_block: int, to_block: int, topics: list[object]
) -> bool:
    logs = rpc_call(
        rpc_url,
        "eth_getLogs",
        [
            {
                "address": tracker,
                "fromBlock": to_hex_block(from_block),
                "toBlock": to_hex_block(to_block),
                "topics": topics,
            }
        ],
    )
    return isinstance(logs, list) and len(logs) > 0


def removed_status(
    rpc_url: str, tracker: str, from_block: int, to_block: int, job_id: str
) -> tuple[bool, bool | None]:
    logs = rpc_call(
        rpc_url,
        "eth_getLogs",
        [
            {
                "address": tracker,
                "fromBlock": to_hex_block(from_block),
                "toBlock": to_hex_block(to_block),
                "topics": [JOB_REMOVED_TOPIC, None, job_id],
            }
        ],
    )
    if not isinstance(logs, list) or not logs:
        return False, None
    topics = logs[0].get("topics", [])
    if isinstance(topics, list) and len(topics) >= 4:
        return True, str(topics[3]).lower().endswith("1")
    return True, None


def infer_status(phase1: bool, removed: bool, completed: bool | None) -> str:
    if removed and completed is True:
        return "completed_or_delivered"
    if removed and completed is False:
        return "removed_incomplete_or_expired"
    if phase1:
        return "phase1_settled_waiting_for_removal"
    return "commitment_seen_pending_or_processing"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hash", required=True)
    parser.add_argument("--lookback", type=int, default=2000)
    parser.add_argument("--rpc-url", default="https://rpc.ritualfoundation.org")
    parser.add_argument("--async-job-tracker-address", default=ASYNC_TRACKER)
    args = parser.parse_args()

    origin_hash = normalize_hash(args.hash)
    tracker = normalize_address(args.async_job_tracker_address)
    head = int(str(rpc_call(args.rpc_url, "eth_blockNumber", [])), 16)
    from_block = max(0, head - max(0, args.lookback))

    logs = rpc_call(
        args.rpc_url,
        "eth_getLogs",
        [
            {
                "address": tracker,
                "fromBlock": to_hex_block(from_block),
                "toBlock": to_hex_block(head),
                "topics": [JOB_ADDED_TOPIC, None, origin_hash],
            }
        ],
    )
    if not isinstance(logs, list):
        raise SystemExit("invalid eth_getLogs response")

    hits: list[Hit] = []
    for log in logs:
        topics = log.get("topics", [])
        if not isinstance(topics, list) or len(topics) < 3:
            continue
        data = str(log.get("data", "0x"))
        job_id = str(topics[2]).lower()
        phase1 = has_log(
            args.rpc_url, tracker, from_block, head, [PHASE1_SETTLED_TOPIC, job_id]
        )
        removed, completed = removed_status(
            args.rpc_url, tracker, from_block, head, job_id
        )
        hits.append(
            Hit(
                tx_hash=str(log.get("transactionHash", "")).lower(),
                block=int(str(log.get("blockNumber", "0x0")), 16),
                job_id=job_id,
                executor=decode_indexed_address(str(topics[1])),
                commit_block=read_word(data, 0),
                ttl=read_word(data, 7),
                phase1_settled=phase1,
                removed=removed,
                removed_completed=completed,
            )
        )

    hits.sort(key=lambda h: h.block)
    print(f"origin_tx={origin_hash}")
    print(f"lookback={args.lookback}")
    print(f"matches={len(hits)}")
    if not hits:
        raise SystemExit("No commitment tx found in scanned range.")

    for idx, hit in enumerate(hits):
        status = infer_status(hit.phase1_settled, hit.removed, hit.removed_completed)
        expiry = hit.commit_block + hit.ttl
        print(
            f"[{idx}] block={hit.block} tx={hit.tx_hash} job_id={hit.job_id} "
            f"executor={hit.executor} commit_block={hit.commit_block} ttl={hit.ttl} "
            f"expiry={expiry} status={status}"
        )
    print(f"\nlatest_commitment_tx={hits[-1].tx_hash}")


if __name__ == "__main__":
    main()
```

Run it:

```bash
python3 /tmp/commitment_tx.py \
  --hash <ASYNC_ORIGIN_HASH> \
  --lookback 2000 \
  --rpc-url https://rpc.ritualfoundation.org
```

---

## Step 3 — Confirm status from chain events only

For each resolved `job_id`:

- `Phase1Settled(jobId, ...)` present -> Phase 1 settled
- `JobRemoved(..., jobId, completed=true)` -> completed path
- `JobRemoved(..., jobId, completed=false)` -> incomplete/expired/removed path

If no removal event exists yet, treat as still pending/processing.

---

## Step 4 — Interpret common outcomes

- **Scheduled hashes found, no commitment found**: callback likely did not trigger async path (predicate false / skipped / reverted) or lookback window is too small.
- **Commitment found, no `Phase1Settled`**: executor processing still pending or ttl window issue.
- **`Phase1Settled` found, then `JobRemoved(completed=false)`**: async lifecycle ended unsuccessfully.
- **`JobRemoved(completed=true)`**: async lifecycle completed.

---

## Step 5 — Minimal evidence payload for users

When reporting back, include:

1. Original input hash
2. Deterministic scheduled hash(es) (if applicable)
3. Commitment tx hash(es)
4. Executor address per commitment
5. Lifecycle status per job (`phase1 settled`, `removed completed`, `removed incomplete`, `pending`)

This gives users a full chain-visible trace without requiring any non-RPC data.

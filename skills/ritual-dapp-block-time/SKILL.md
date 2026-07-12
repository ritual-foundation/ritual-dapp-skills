---
name: ritual-dapp-block-time
description: Block-time estimation and block-to-time conversion guidance for Ritual dApps. Use when setting TTL, lock durations, scheduler frequency, or polling windows.
---

# Ritual Block-Time Guidance

## Timestamps Are Milliseconds

`block.timestamp` on Ritual Chain is **milliseconds since epoch**, not unix seconds — sub-second blocks (~350ms) require sub-second resolution. Verify from any machine:

```bash
CHAIN_TS=$(curl -s https://rpc.ritualfoundation.org -X POST -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"eth_getBlockByNumber","params":["latest",false],"id":1}' \
  | python3 -c "import sys,json; print(int(json.load(sys.stdin)['result']['timestamp'],16))")
echo "chain: $CHAIN_TS  local-seconds: $(date +%s)"
# chain / local ≈ 1000 ⇒ milliseconds
```

Consequences for contract and client code:

- Any deadline, expiry, or schedule field compared against `block.timestamp` must be in **milliseconds**. Passing unix seconds silently produces a timestamp ~56,000 years in the past — checks like `deadline > block.timestamp` revert with the contract's own error, nothing indicating a unit problem.
- Client-side: `Date.now()` is already ms; do **not** divide by 1000 for values the chain will compare to `block.timestamp`, and pass chain timestamps to `new Date()` as-is when rendering.
- Wall-clock durations must be scaled: one hour = `3_600_000`, one day = `86_400_000`.


## Baseline (Conservative)

Use a conservative planning baseline of **~350ms per block** when you do not have fresh measurements from your target deployment.

- `1 block ~= 0.35s`
- `100 blocks ~= 35s`
- `300 blocks ~= 105s (~1m45s)`
- `500 blocks ~= 175s (~2m55s)`
- `5,000 blocks ~= 1,750s (~29m10s)`
- `10,000 blocks ~= 3,500s (~58m20s)`
- `100,000 blocks ~= 35,000s (~9h43m)`
- `70,000 blocks ~= 24,500s (~6h48m)`

For one day:

- `blocksPerDay ~= ceil(86,400 / 0.35) = 246,858`

## Required Preflight: Measure Recent Blocks

Before choosing production TTL/lock/scheduler values, estimate block time from recent chain data on your target RPC.

```bash
RPC_URL="${RPC_URL:-https://rpc.ritualfoundation.org}"
SAMPLE=60
LATEST=$(cast block-number --rpc-url "$RPC_URL")
OLDER=$((LATEST - SAMPLE))
LATEST_TS=$(cast block "$LATEST" --rpc-url "$RPC_URL" --json | jq -r '.timestamp')
OLDER_TS=$(cast block "$OLDER" --rpc-url "$RPC_URL" --json | jq -r '.timestamp')

uv run --quiet python3 - <<'PY' "$LATEST_TS" "$OLDER_TS" "$SAMPLE"
import sys

latest_ts = int(sys.argv[1], 0)
older_ts = int(sys.argv[2], 0)
sample = int(sys.argv[3])

avg_sec = (latest_ts - older_ts) / sample
print(f"Estimated block time: {avg_sec:.4f}s ({avg_sec*1000:.1f}ms)")
PY
```

If your measured value is materially different from 350ms, use the measured value in formulas below.

## Conversion Formulas

```text
seconds = blocks * blockTimeSeconds
blocks  = ceil(seconds / blockTimeSeconds)
```

Examples at `blockTimeSeconds = 0.35`:

- 1 hour: `ceil(3600 / 0.35) = 10,286 blocks`
- 24 hours: `ceil(86400 / 0.35) = 246,858 blocks`
- 15 minutes: `ceil(900 / 0.35) = 2,572 blocks`

## Where to Apply This

Apply these conversions consistently in:

- `ttl` / `maxPollBlock` windows
- RitualWallet lock durations
- Scheduler `frequency` and interval tables
- polling and timeout guidance in long-running workflows

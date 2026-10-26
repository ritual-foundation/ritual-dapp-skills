#!/usr/bin/env bash
# Deploy this directory's own consumer, authorize it, then call the agent precompile.
# Prerequisites: public Foundry tools (forge/cast) and uv. Never enable shell tracing.
set -euo pipefail
require_value() {
    local name="$1" value="${2-}"
    if [ -z "$value" ] || [[ "$value" == *'<'* || "$value" == *'>'* || "$value" == *YOUR_* ]]; then
        echo "ERROR: $name is required and must not be a placeholder" >&2; exit 2
    fi
}
for name in RPC_URL PRIVATE_KEY EXPECTED_CHAIN_ID ASYNC_DELIVERY_ADDRESS DA_PROVIDER; do require_value "$name" "${!name:-}"; done
for tool in cast forge uv; do command -v "$tool" >/dev/null || { echo "ERROR: $tool is required" >&2; exit 2; }; done
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY_HELPER=(uv run --quiet --with eciespy --with eth-abi --with web3 python3 "$SCRIPT_DIR/helpers.py")
TEE_SERVICE_REGISTRY="${TEE_SERVICE_REGISTRY:-0xf4495DC72143D44A93AB0ecE4d6D63a216b27839}"
SECRETS_ACCESS_CONTROL="${SECRETS_ACCESS_CONTROL:-0x0cEae62e2082829226eF5821Bb662483Db17A71F}"
ASYNC_JOB_TRACKER="${ASYNC_JOB_TRACKER:-0xf00385449fD961925A0B125F5f30b29B682D4bFb}"
RITUAL_WALLET="${RITUAL_WALLET:-0xF04076756d8129Baec46Dc0F1c526Baec490C393}"
SENDER=$(cast wallet address "$PRIVATE_KEY")
CHAIN_ID=$(cast chain-id --rpc-url "$RPC_URL")
if [ "$CHAIN_ID" != "$EXPECTED_CHAIN_ID" ]; then echo "ERROR: chain differs from expected deployment" >&2; exit 2; fi
for name in TEE_SERVICE_REGISTRY SECRETS_ACCESS_CONTROL ASYNC_JOB_TRACKER RITUAL_WALLET ASYNC_DELIVERY_ADDRESS EXTRA_CONTRACT AGENT_HEARTBEAT_ADDRESS; do
    address="${!name:-}"
    [ -z "$address" ] && continue
    if [ "$(cast code "$address" --rpc-url "$RPC_URL")" = "0x" ]; then echo "ERROR: $name has no deployed bytecode" >&2; exit 2; fi
done
if [ "$(cast call "$ASYNC_JOB_TRACKER" 'hasPendingJobForTxOrigin(address)(bool)' "$SENDER" --rpc-url "$RPC_URL")" = true ]; then
    echo "ERROR: reconcile the sender's existing job before starting this example" >&2; exit 2
fi

require_value MODEL "${MODEL:-}"
CONTRACT=SovereignAgentConsumer
WALLET_MIN_WEI="${WALLET_MIN_WEI:-5000000000000000000}"
WALLET_DEPOSIT_WEI="${WALLET_DEPOSIT_WEI:-5000000000000000000}"
send_tx() {
    local pre_nonce out hash i
    pre_nonce=$(cast nonce "$SENDER" --rpc-url "$RPC_URL")
    if out=$(cast send --private-key "$PRIVATE_KEY" --rpc-url "$RPC_URL" --async "$@" 2>&1); then
        hash=$(printf '%s' "$out" | tr -d '[:space:]')
    elif printf '%s' "$out" | grep -qiE "already known|nonce too low"; then
        # "already known": the LB double-forwarded and the tx is pooled.
        # "nonce too low": a duplicate already MINED before cast's (stale-backend)
        # nonce fetch — same recovery: wait for the nonce to pass and find the tx.
        echo "  (duplicate submission via RPC — recovering pooled/mined tx)" >&2
        hash=""
    else
        printf '%s\n' "$out" >&2; return 1
    fi
    for i in $(seq 1 90); do
        if [ "$(cast nonce "$SENDER" --rpc-url "$RPC_URL")" -gt "$pre_nonce" ]; then
            if [ -z "$hash" ]; then
                hash=$("${PY_HELPER[@]}" find-tx --rpc "$RPC_URL" \
                    --sender "$SENDER" --nonce "$pre_nonce" | awk -F= '$1=="TX_HASH"{print $2}')
            fi
            # Nonce advancement alone also occurs for reverted transactions.
            local receipt
            if ! receipt=$(cast receipt "$hash" --rpc-url "$RPC_URL" --json); then
                echo "ERROR: transaction receipt unavailable; reconcile $hash before any retry" >&2
                return 1
            fi
            if ! printf '%s' "$receipt" | "${PY_HELPER[@]}" check-receipt >/dev/null; then
                echo "ERROR: transaction $hash did not succeed; do not repeat funding blindly" >&2
                return 1
            fi
            printf '%s' "$hash"
            return 0
        fi
        sleep 2
    done
    echo "ERROR: tx from nonce $pre_nonce not mined after 180s" >&2
    return 1
}

"${PY_HELPER[@]}" check-inputs --da-provider "$DA_PROVIDER"
AVAILABLE=$(cast call "$RITUAL_WALLET" 'availableBalance(address)(uint256)' "$SENDER" --rpc-url "$RPC_URL" | awk '{print $1}')
NATIVE_BALANCE=$(cast balance "$SENDER" --rpc-url "$RPC_URL")
uv run --quiet python3 - "$NATIVE_BALANCE" "$AVAILABLE" "$WALLET_MIN_WEI" "$WALLET_DEPOSIT_WEI" "${PRELAUNCH_FUND_WEI:-0}" <<'PYCHECK'
import sys
balance, available, minimum, deposit, prelaunch = map(int, sys.argv[1:])
needed = (deposit if available < minimum else 0) + prelaunch + 5 * 10**17
if balance < needed:
    raise SystemExit("Insufficient native balance for wallet deposit, prelaunch funding and gas headroom")
PYCHECK
SELECT=(select-executor --rpc "$RPC_URL" --registry "$TEE_SERVICE_REGISTRY"
    --executor-tee-address "${EXECUTOR_TEE_ADDRESS:-}"
    --allowed-executors "${ALLOWED_EXECUTOR_ADDRESSES:-}"
    --excluded-executors "${EXCLUDED_EXECUTOR_ADDRESSES:-}")
EXECUTOR_OUT=$("${PY_HELPER[@]}" "${SELECT[@]}")
EXECUTOR=$(printf '%s\n' "$EXECUTOR_OUT" | awk -F= '$1=="EXECUTOR"{print $2}')
EXECUTOR_PUBKEY=$(printf '%s\n' "$EXECUTOR_OUT" | awk -F= '$1=="EXECUTOR_PUBKEY"{print $2}')
BYTECODE=$(forge inspect --root "$SCRIPT_DIR" "$CONTRACT.sol:$CONTRACT" bytecode)
CONSTRUCTOR=$(cast abi-encode 'f(address)' "$ASYNC_DELIVERY_ADDRESS")
DEPLOY_TX=$(send_tx --gas-limit "${DEPLOY_GAS_LIMIT:-4000000}" --create "${BYTECODE}${CONSTRUCTOR#0x}")
CONSUMER=$(cast receipt "$DEPLOY_TX" --rpc-url "$RPC_URL" --json | "${PY_HELPER[@]}" parse-deployment | awk -F= '$1=="CONSUMER"{print $2}')
echo "CONSUMER=$CONSUMER"
echo "DEPLOY_TX=$DEPLOY_TX"
AVAILABLE=$(cast call "$RITUAL_WALLET" 'availableBalance(address)(uint256)' "$SENDER" --rpc-url "$RPC_URL" | awk '{print $1}')
if uv run --quiet python3 -c 'import sys;sys.exit(not(int(sys.argv[1])<int(sys.argv[2])))' "$AVAILABLE" "$WALLET_MIN_WEI"; then
    send_tx "$RITUAL_WALLET" 'deposit()' --value "$WALLET_DEPOSIT_WEI" >/dev/null
fi
send_tx "$RITUAL_WALLET" 'approve(address,uint256)' "$CONSUMER" "$(cast max-uint)" >/dev/null

BUILD=(build-request --rpc "$RPC_URL" --consumer "$CONSUMER" --owner "$SENDER"
    --executor-tee-address "$EXECUTOR" --executor-pubkey "$EXECUTOR_PUBKEY"
    --model "$MODEL" --prompt "${PROMPT:-Say hello world}" --cli-type "${CLI_TYPE:-5}"
    --max-turns "${MAX_TURNS:-50}" --max-tokens "${MAX_TOKENS:-8192}"
    --da-provider "$DA_PROVIDER" --hf-repo-id "${HF_REPO_ID:-}" --gcs-prefix "${GCS_DA_PREFIX:-sovereign-agent}")

REQUEST=$("${PY_HELPER[@]}" "${BUILD[@]}")
CALLDATA=$(printf '%s\n' "$REQUEST" | awk -F= '$1=="CALLDATA"{print $2}')
SECRETS_HASH=$(printf '%s\n' "$REQUEST" | awk -F= '$1=="SECRETS_HASH"{print $2}')
GRANT=$("${PY_HELPER[@]}" encode-grant-calldata --delegate "$CONSUMER" --secrets-hash "$SECRETS_HASH" | awk -F= '$1=="CALLDATA"{print $2}')
send_tx "$SECRETS_ACCESS_CONTROL" --data "$GRANT" >/dev/null
FROM_BLOCK=$(cast block-number --rpc-url "$RPC_URL")
# An async origin may not have an ordinary receipt yet. Observe its exact job
# through spcCalls/JobAdded rather than inferring success from nonce advancement.
JOB_ID=$(cast send "$CONSUMER" --data "$CALLDATA" --gas-limit "${AGENT_GAS_LIMIT:-3000000}" \
    --private-key "$PRIVATE_KEY" --rpc-url "$RPC_URL" --async)
echo "JOB_ID=$JOB_ID"
OBSERVE=(--rpc "$RPC_URL" --consumer "$CONSUMER" --tracker "$ASYNC_JOB_TRACKER"
    --tx-hash "$JOB_ID" --from-block "$FROM_BLOCK")
PHASE1=$("${PY_HELPER[@]}" wait-phase1 "${OBSERVE[@]}" --timeout "${PHASE1_TIMEOUT:-180}")
printf '%s\n' "$PHASE1"

"${PY_HELPER[@]}" wait-result "${OBSERVE[@]}" --timeout "${RESULT_TIMEOUT:-600}"
echo "SOVEREIGN_INVOCATION_SUCCESS=1"
echo "CONSUMER=$CONSUMER JOB_ID=$JOB_ID"

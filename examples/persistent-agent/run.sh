#!/usr/bin/env bash
# ============================================================================
# Persistent Agent E2E (direct precompile caller mode) — derive child DKMS key, fund heartbeat address, spawn,
# and optionally verify relay communication.
#
# Usage (every value below must be filled in — this script aborts with exit
# code 2 if any required variable is unset or still contains an unfilled
# placeholder like "<YOUR_GCS_BUCKET>" or "YOUR_TOKEN"):
#   export RPC_URL=https://rpc.ritualfoundation.org
#   export FOUNDRY_ACCOUNT=my-agent                      # preferred: imported Foundry keystore account
#   export PRIVATE_KEY=0x...                             # compatibility fallback; avoid in shared shells

#   export ANTHROPIC_API_KEY=sk-ant-...                  # or OPENAI_API_KEY / GEMINI_API_KEY / OPENROUTER_API_KEY
#   export DA_PROVIDER=gcs                               # one of: hf, gcs, pinata
#   export GCS_DA_SERVICE_ACCOUNT_JSON="$(cat sa.json)"
#   export GCS_DA_BUCKET=my-agent-workspace-bucket       # a GCS bucket YOU own
#   export GCS_DA_PREFIX=agents/demo
#   export RELAY_URL=https://my-relay.example.com        # optional; omit to skip relay verify
#   export VERIFY_RELAY=1
#   bash run.sh
#
# Prerequisites: forge, cast, uv
# Factory-backed launcher mode is documented in skills/ritual-dapp-agents/SKILL.md
# ============================================================================
set -euo pipefail

# Guard: fail if a required var is unset OR if the caller left an unfilled
# placeholder (angle-brackets or "YOUR_"/"YOUR-" sentinels). We cannot rely on
# ":?" alone because e.g. `export GCS_DA_BUCKET=<YOUR_GCS_BUCKET>` sets the var
# to the literal string "<YOUR_GCS_BUCKET>" in many shells.
#
# IMPORTANT (for agents running this example on behalf of a user):
# Elicit all required values (RPC_URL, signer credentials, DA provider credentials, and
# LLM credentials) from the user BEFORE invoking this script. There are no sensible
# defaults for credentials and placeholder values will abort with exit code 2.

require_real_value() {
    local name="$1"
    local value="${2-}"
    local hint="${3:-set it to a real value}"
    if [ -z "$value" ]; then
        echo "ERROR: $name is required — $hint" >&2
        exit 2
    fi
    case "$value" in
        *"<"*|*">"*|*YOUR_*|*YOUR-*)
            echo "ERROR: $name looks like an unfilled placeholder ('$value') — $hint" >&2
            exit 2
            ;;
    esac
}

require_real_value RPC_URL "${RPC_URL:-}" "e.g. https://rpc.ritualfoundation.org"

if [ -n "${FOUNDRY_ACCOUNT:-}" ]; then
    SIGNER_ARGS=(--account "$FOUNDRY_ACCOUNT")
    SENDER=$(cast wallet address --account "$FOUNDRY_ACCOUNT")
    
    # SECURITY FIX: Request construction (helpers.py) still requires the raw PRIVATE_KEY from the environment
    # to sign the encrypted secrets blob. We enforce its presence here to prevent Python panics during spawn,
    # and strictly assert that both keys derive to the exact same address to prevent signature divergence.
    require_real_value PRIVATE_KEY "${PRIVATE_KEY:-}" "0x-prefixed private key corresponding to FOUNDRY_ACCOUNT (required for secrets payload signature)"
    
    PK_SENDER=$(cast wallet address "$PRIVATE_KEY")
    if [ "$SENDER" != "$PK_SENDER" ]; then
        echo "ERROR: Diverging credentials! FOUNDRY_ACCOUNT address ($SENDER) does not match PRIVATE_KEY address ($PK_SENDER)." >&2
        exit 2
    fi
elif [ -n "${PRIVATE_KEY:-}" ]; then
    require_real_value PRIVATE_KEY "$PRIVATE_KEY" "0x-prefixed funded key"
    SIGNER_ARGS=(--private-key "$PRIVATE_KEY")
    SENDER=$(cast wallet address "$PRIVATE_KEY")
else
    echo "ERROR: Set FOUNDRY_ACCOUNT (and its matching PRIVATE_KEY) or just PRIVATE_KEY as a compatibility fallback." >&2
    exit 2
fi

: "${DA_PROVIDER:?Set DA_PROVIDER to one of: hf, gcs, pinata}"

if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: uv is required but not installed."
    echo "Install: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY=(uv run --quiet python3)
PY_HELPER=(uv run --quiet --with eciespy --with eth-abi --with web3 python3)

WALLET="0x532F0dF0896F353d8C3DD8cc134e8129DA2a3948"
TRACKER="0xC069FFCa0389f44eCA2C626e55491b0ab045AEF5"
REGISTRY="0x9644e8562cE0Fe12b4deeC4163c064A8862Bf47F"

HEARTBEAT_CHAIN_CONTRACT="${HEARTBEAT_CHAIN_CONTRACT:-0xEF505E801f1Db392B5289690E2ffc20e840A3aCa}"
HEARTBEAT_CHAIN_INTERVAL_BLOCKS="${HEARTBEAT_CHAIN_INTERVAL_BLOCKS:-100}"
HEARTBEAT_CHAIN_TIMEOUT_BLOCKS="${HEARTBEAT_CHAIN_TIMEOUT_BLOCKS:-200}"
# WARNING: The default http://172.17.0.1:8545 is a Docker bridge address that only works
# when the chain runs on the same Docker host as the executor. For remote executors or
# production deployments, use the public RPC: https://rpc.ritualfoundation.org
AGENT_RPC_URL="${AGENT_RPC_URL:-http://172.17.0.1:8545}"
AGENT_RUNTIME="${AGENT_RUNTIME:-zeroclaw}"

PHASE1_TIMEOUT="${PHASE1_TIMEOUT:-300}"
PHASE2_TIMEOUT="${PHASE2_TIMEOUT:-300}"
PHASE1_GAS_LIMIT="${PHASE1_GAS_LIMIT:-1000000}"
DKMS_GAS_LIMIT="${DKMS_GAS_LIMIT:-500000}"
MAX_FEE_GWEI="${MAX_FEE_GWEI:-20}"
PRIORITY_FEE_GWEI="${PRIORITY_FEE_GWEI:-1}"

MIN_RITUAL_WALLET_WEI="${MIN_RITUAL_WALLET_WEI:-1000000000000000000}"   # 1 RIT
DEPOSIT_WEI="${DEPOSIT_WEI:-5000000000000000000}"                        # 5 RIT
LOCK_BLOCKS="${LOCK_BLOCKS:-100000000}"
MIN_LOCK_AHEAD_BLOCKS="${MIN_LOCK_AHEAD_BLOCKS:-10000}"

CHILD_MIN_NATIVE_WEI="${CHILD_MIN_NATIVE_WEI:-100000000000000000000}"    # 100 RIT
CHILD_FUND_WEI="${CHILD_FUND_WEI:-100000000000000000000000}"             # 100,000 RIT

EXECUTOR_TEE_ADDRESS="${EXECUTOR_TEE_ADDRESS:-}"
CONSUMER_ADDRESS="${CONSUMER_ADDRESS:-}"
TELEGRAM_DM_POLICY="${TELEGRAM_DM_POLICY:-pairing}"
VERIFY_RELAY="${VERIFY_RELAY:-0}"
RELAY_URL="${RELAY_URL:-}"

echo "Sender: $SENDER"

echo "Chain:  $(cast chain-id --rpc-url "$RPC_URL")"
echo "DA:     $DA_PROVIDER"
echo "Runtime: $AGENT_RUNTIME"

case "$AGENT_RUNTIME" in
  zeroclaw|hermes)
    ;;
  *)
    echo "ERROR: AGENT_RUNTIME must be one of: zeroclaw, hermes"
    exit 1
    ;;
esac

case "$DA_PROVIDER" in
  hf)
    require_real_value HF_TOKEN "${HF_TOKEN:-}" "HuggingFace token (hf_...) with write access to HF_REPO_ID"
    require_real_value HF_REPO_ID "${HF_REPO_ID:-}" "HuggingFace dataset ID in 'user/repo' form, e.g. alice/my-agent-workspace"
    ;;
  gcs)
    require_real_value GCS_DA_SERVICE_ACCOUNT_JSON "${GCS_DA_SERVICE_ACCOUNT_JSON:-}" "paste the full service account JSON"
    require_real_value GCS_DA_BUCKET "${GCS_DA_BUCKET:-}" "e.g. my-agent-workspace-bucket"
    ;;
  pinata)
    require_real_value DA_PINATA_JWT "${DA_PINATA_JWT:-}" "Pinata JWT bearer token"
    ;;
  *)
    echo "ERROR: DA_PROVIDER must be one of: hf, gcs, pinata"
    exit 1
    ;;
esac

if [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -z "${OPENAI_API_KEY:-}" ] && [ -z "${GEMINI_API_KEY:-}" ] && [ -z "${OPENROUTER_API_KEY:-}" ]; then
    echo "ERROR: Set one of ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY, or OPENROUTER_API_KEY"
    exit 1
fi

# ── 1. Check for pending async job ──
PENDING=$(cast call "$TRACKER" "hasPendingJobForSender(address)(bool)" "$SENDER" --rpc-url "$RPC_URL" | awk '{print $1}')
if [ "$PENDING" = "true" ]; then
    echo "ERROR: Sender has a pending async job. Use a different key or wait for it to clear."
    exit 1
fi

# ── 2. Fund / refresh RitualWallet if needed ──
CURRENT_BLOCK=$(cast block-number --rpc-url "$RPC_URL")
WALLET_BAL=$(cast call "$WALLET" "balanceOf(address)(uint256)" "$SENDER" --rpc-url "$RPC_URL" | awk '{print $1}')
LOCK_UNTIL=$(cast call "$WALLET" "lockUntil(address)(uint256)" "$SENDER" --rpc-url "$RPC_URL" | awk '{print $1}')
NEEDS_DEPOSIT=$("${PY[@]}" - "$WALLET_BAL" "$MIN_RITUAL_WALLET_WEI" "$LOCK_UNTIL" "$CURRENT_BLOCK" "$MIN_LOCK_AHEAD_BLOCKS" <<'PY'
import sys
bal = int(sys.argv[1])
min_bal = int(sys.argv[2])
lock_until = int(sys.argv[3])
current_block = int(sys.argv[4])
min_lock_ahead = int(sys.argv[5])
print("1" if (bal < min_bal or lock_until < current_block + min_lock_ahead) else "0")
PY
)
if [ "$NEEDS_DEPOSIT" = "1" ]; then
    echo "Depositing / refreshing RitualWallet (value=$DEPOSIT_WEI wei, lock=$LOCK_BLOCKS blocks)..."
    cast send "$WALLET" "deposit(uint256)" "$LOCK_BLOCKS" \
        --value "$DEPOSIT_WEI" \
        "${SIGNER_ARGS[@]}" \
        --rpc-url "$RPC_URL" >/dev/null
    echo "Updated RitualWallet."
fi
echo "RitualWallet wei: $(cast call "$WALLET" "balanceOf(address)(uint256)" "$SENDER" --rpc-url "$RPC_URL" | awk '{print $1}')"
echo "RitualWallet lockUntil: $(cast call "$WALLET" "lockUntil(address)(uint256)" "$SENDER" --rpc-url "$RPC_URL" | awk '{print $1}')"

# ── 3. Deploy / reuse consumer ──
if [ -n "$CONSUMER_ADDRESS" ]; then
    CONSUMER="$CONSUMER_ADDRESS"
    echo "Using existing consumer: $CONSUMER"
else
    echo "Deploying PersistentAgentConsumer..."
    DEPLOY_OUT=$(forge create --rpc-url "$RPC_URL" "${SIGNER_ARGS[@]}" \
        --broadcast "$SCRIPT_DIR/PersistentAgentConsumer.sol:PersistentAgentConsumer" 2>&1)
    CONSUMER=$(printf '%s\n' "$DEPLOY_OUT" | awk '/Deployed to:/ {print $3}' | tail -n1)
fi
if [ -z "$CONSUMER" ]; then
    echo "ERROR: Could not determine consumer contract address."
    exit 1
fi
echo "Consumer: $CONSUMER"

# ── 4. Select executor + build DKMS request ──
echo "Selecting executor and building DKMS request..."
BUILD_DKMS_ARGS=(
    --rpc "$RPC_URL"
    --registry "$REGISTRY"
    --owner "$SENDER"
    --key-index 0
)
if [ -n "$EXECUTOR_TEE_ADDRESS" ]; then
    BUILD_DKMS_ARGS+=(--executor-tee-address "$EXECUTOR_TEE_ADDRESS")
fi
DKMS_BUILD=$("${PY_HELPER[@]}" "$SCRIPT_DIR/helpers.py" build-dkms-request "${BUILD_DKMS_ARGS[@]}")
EXECUTOR=$(printf '%s\n' "$DKMS_BUILD" | awk -F= '$1=="EXECUTOR"{print $2}')
DKMS_INPUT=$(printf '%s\n' "$DKMS_BUILD" | awk -F= '$1=="REQUEST_INPUT"{print $2}')
if [ -z "$EXECUTOR" ] || [ -z "$DKMS_INPUT" ]; then
    echo "ERROR: Failed to build DKMS request."
    printf '%s\n' "$DKMS_BUILD"
    exit 1
fi
echo "Executor: $EXECUTOR"

# ── 5. Derive child DKMS address via 0x081B ──
echo "Deriving child DKMS heartbeat/payment address..."
DKMS_TX_HASH=$(cast send "$CONSUMER" 'callDKMSKey(bytes)' "$DKMS_INPUT" \
    --rpc-url "$RPC_URL" \
    "${SIGNER_ARGS[@]}" \
    --gas-limit "$DKMS_GAS_LIMIT" \
    --async)
echo "DKMS tx: $DKMS_TX_HASH"

DKMS_OUT=$("${PY_HELPER[@]}" "$SCRIPT_DIR/helpers.py" poll-dkms \
    --rpc "$RPC_URL" \
    --consumer "$CONSUMER" \
    --tx-hash "$DKMS_TX_HASH" \
    --timeout "$PHASE1_TIMEOUT")
CHILD_DKMS_ADDRESS=$(printf '%s\n' "$DKMS_OUT" | awk -F= '$1=="PAYMENT_ADDRESS"{print $2}')
if [ -z "$CHILD_DKMS_ADDRESS" ]; then
    echo "ERROR: Failed to derive child DKMS address."
    printf '%s\n' "$DKMS_OUT"
    exit 1
fi
echo "Child DKMS address: $CHILD_DKMS_ADDRESS"

# ── 6. Fund child DKMS address for heartbeat registration ──
CHILD_BAL=$(cast balance "$CHILD_DKMS_ADDRESS" --rpc-url "$RPC_URL")
NEEDS_CHILD_FUND=$("${PY[@]}" - "$CHILD_BAL" "$CHILD_MIN_NATIVE_WEI" <<'PY'
import sys
print("1" if int(sys.argv[1]) < int(sys.argv[2]) else "0")
PY
)
if [ "$NEEDS_CHILD_FUND" = "1" ]; then
    echo "Funding child DKMS address with native balance for heartbeat registration..."
    cast send "$CHILD_DKMS_ADDRESS" \
        --value "$CHILD_FUND_WEI" \
        "${SIGNER_ARGS[@]}" \
        --rpc-url "$RPC_URL" >/dev/null
    echo "Funded child DKMS address."
fi
echo "Child native wei: $(cast balance "$CHILD_DKMS_ADDRESS" --rpc-url "$RPC_URL")"

# ── 7. Build persistent agent request ──
echo "Building persistent-agent request..."
BUILD_ARGS=(
    --rpc "$RPC_URL"
    --registry "$REGISTRY"
    --consumer "$CONSUMER"
    --executor-tee-address "$EXECUTOR"
    --da-provider "$DA_PROVIDER"
    --agent-rpc-url "$AGENT_RPC_URL"
    --heartbeat-chain-contract "$HEARTBEAT_CHAIN_CONTRACT"
    --heartbeat-chain-interval-blocks "$HEARTBEAT_CHAIN_INTERVAL_BLOCKS"
    --heartbeat-chain-timeout-blocks "$HEARTBEAT_CHAIN_TIMEOUT_BLOCKS"
    --agent-runtime "$AGENT_RUNTIME"
)
if [ -n "${HEARTBEAT_INTERVAL:-}" ]; then
    BUILD_ARGS+=(--heartbeat-interval "$HEARTBEAT_INTERVAL")
fi
if [ -n "${HEARTBEAT_PROMPT:-}" ]; then
    BUILD_ARGS+=(--heartbeat-prompt "$HEARTBEAT_PROMPT")
fi
REQUEST_OUT=$("${PY_HELPER[@]}" "$SCRIPT_DIR/helpers.py" build-persistent-request "${BUILD_ARGS[@]}")
REQUEST_INPUT=$(printf '%s\n' "$REQUEST_OUT" | awk -F= '$1=="REQUEST_INPUT"{print $2}')
LLM_PROVIDER=$(printf '%s\n' "$REQUEST_OUT" | awk -F= '$1=="LLM_PROVIDER"{print $2}')
MODEL=$(printf '%s\n' "$REQUEST_OUT" | awk -F= '$1=="MODEL"{print $2}')
SELECTED_AGENT_RUNTIME=$(printf '%s\n' "$REQUEST_OUT" | awk -F= '$1=="AGENT_RUNTIME"{print $2}')
if [ -z "$REQUEST_INPUT" ]; then
    echo "ERROR: Failed to build persistent-agent request."
    printf '%s\n' "$REQUEST_OUT"
    exit 1
fi
echo "LLM provider: $LLM_PROVIDER"
echo "Model:        $MODEL"
echo "Runtime:      ${SELECTED_AGENT_RUNTIME:-$AGENT_RUNTIME}"

# ── 8. Submit persistent agent spawn ──
FROM_BLOCK_PHASE2=$(cast block-number --rpc-url "$RPC_URL")
echo "Submitting persistent agent call (from_block=$FROM_BLOCK_PHASE2)..."
SPAWN_TX_HASH=$(cast send "$CONSUMER" 'callPersistentAgent(bytes)' "$REQUEST_INPUT" \
    --rpc-url "$RPC_URL" \
    "${SIGNER_ARGS[@]}" \
    --gas-limit "$PHASE1_GAS_LIMIT" \
    --async)
echo "Phase 1 tx: $SPAWN_TX_HASH"

# ── 9. Poll for Phase 2 delivery ──
echo "Waiting for PersistentAgentResultDelivered (up to ${PHASE2_TIMEOUT}s)..."
PHASE2_OUT=$("${PY_HELPER[@]}" "$SCRIPT_DIR/helpers.py" poll-phase2 \
    --rpc "$RPC_URL" \
    --consumer "$CONSUMER" \
    --tx-hash "$SPAWN_TX_HASH" \
    --from-block "$FROM_BLOCK_PHASE2" \
    --timeout "$PHASE2_TIMEOUT")
printf '%s\n' "$PHASE2_OUT"

INSTANCE_ID=$(printf '%s\n' "$PHASE2_OUT" | awk -F= '$1=="INSTANCE_ID"{print $2}')
GATEWAY_URL=$(printf '%s\n' "$PHASE2_OUT" | awk -F= '$1=="GATEWAY_URL"{print $2}')
CHECKPOINT_CID=$(printf '%s\n' "$PHASE2_OUT" | awk -F= '$1=="CHECKPOINT_CID"{print $2}')

if [ -n "$RELAY_URL" ] && [ "$VERIFY_RELAY" = "1" ]; then
    echo "Verifying relay communication via $RELAY_URL ..."
    RELAY_OUT=$("${PY_HELPER[@]}" "$SCRIPT_DIR/helpers.py" verify-relay \
        --relay-url "$RELAY_URL" \
        --agent-address "$CHILD_DKMS_ADDRESS" \
        --timeout 60)
    printf '%s\n' "$RELAY_OUT"
fi

echo "Done."
echo "Instance ID:     ${INSTANCE_ID:-unknown}"
echo "Gateway URL:     ${GATEWAY_URL:-unknown}"
echo "Checkpoint CID:  ${CHECKPOINT_CID:-unknown}"
echo "Agent relay ID:  $CHILD_DKMS_ADDRESS"

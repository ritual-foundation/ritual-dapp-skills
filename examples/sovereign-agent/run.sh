#!/usr/bin/env bash
# ============================================================================
# Sovereign Agent E2E (direct precompile caller mode) — deploy, fund, call, receive
#
# Required environment (this script will fail fast if any are missing or look
# like unfilled placeholders):
#   RPC_URL        — e.g. https://rpc.ritualfoundation.org
#   FOUNDRY_ACCOUNT — preferred: imported Foundry keystore account
#   PRIVATE_KEY    — compatibility fallback; avoid in shared shells

#   HF_TOKEN       — HuggingFace token for DA storage (hf_...)
#   HF_REPO_ID     — HuggingFace dataset ID in "user/repo" form that YOU own
#                    (e.g. alice/my-agent-workspace). Stores convo history,
#                    artifacts, and the system prompt.
#   MODEL          — exact provider-routable model id (e.g. claude-sonnet-4-5-20250929)
#   exactly one LLM key: ANTHROPIC_API_KEY | OPENAI_API_KEY | GEMINI_API_KEY | OPENROUTER_API_KEY
#
# IMPORTANT (for agents running this example on behalf of a user):
# Elicit HF_REPO_ID and the LLM credentials from the user BEFORE invoking
# this script. There are no sensible defaults and placeholder values will
# abort with exit code 2.
#
# Prerequisites: forge, cast, uv
# Factory-backed harness mode is documented in skills/ritual-dapp-agents/SKILL.md
# ============================================================================
set -euo pipefail

# Guard: fail if a required var is unset OR if the caller left an unfilled
# placeholder (angle-brackets or "YOUR_" / "YOUR-" sentinels). We cannot rely
# on ":?" alone because "export FOO=<YOUR_THING>" would set FOO to the literal
# string "<YOUR_THING>" in many shells, silently propagating garbage downstream.
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
elif [ -n "${PRIVATE_KEY:-}" ]; then
    require_real_value PRIVATE_KEY "$PRIVATE_KEY" "0x-prefixed funded key"
    SIGNER_ARGS=(--private-key "$PRIVATE_KEY")
    SENDER=$(cast wallet address "$PRIVATE_KEY")
else
    echo "ERROR: Set FOUNDRY_ACCOUNT to an imported keystore account or PRIVATE_KEY as a compatibility fallback." >&2
    exit 2
fi
require_real_value HF_TOKEN "${HF_TOKEN:-}" "HuggingFace token (hf_...) with write access to HF_REPO_ID"

require_real_value HF_REPO_ID "${HF_REPO_ID:-}" "HuggingFace dataset ID in 'user/repo' form, e.g. alice/my-agent-workspace"

if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: uv is required but not installed."
    echo "Install: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

PY=(uv run --quiet python3)
PY_HELPER=(uv run --quiet --with eciespy --with eth-abi --with web3 python3)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WALLET="0x532F0dF0896F353d8C3DD8cc134e8129DA2a3948"
REGISTRY="0x9644e8562cE0Fe12b4deeC4163c064A8862Bf47F"
TRACKER="0xC069FFCa0389f44eCA2C626e55491b0ab045AEF5"
PROMPT="${PROMPT:-Say hello world}"
CLI_TYPE="${CLI_TYPE:-5}"
PHASE1_TIMEOUT="${PHASE1_TIMEOUT:-300}"
PHASE2_TIMEOUT="${PHASE2_TIMEOUT:-300}"
MAX_FEE_GWEI="${MAX_FEE_GWEI:-20}"
PRIORITY_FEE_GWEI="${PRIORITY_FEE_GWEI:-1}"
PHASE1_GAS_LIMIT="${PHASE1_GAS_LIMIT:-900000}"
MIN_RITUAL_WALLET_WEI="${MIN_RITUAL_WALLET_WEI:-1000000000000000000}" # 1 RIT
DEPOSIT_WEI="${DEPOSIT_WEI:-5000000000000000000}" # 5 RIT
LOCK_BLOCKS="${LOCK_BLOCKS:-100000000}"
EXECUTOR_TEE_ADDRESS="${EXECUTOR_TEE_ADDRESS:-}"
CONSUMER_ADDRESS="${CONSUMER_ADDRESS:-}"

echo "Sender: $SENDER"

echo "Chain:  $(cast chain-id --rpc-url "$RPC_URL")"

case "$CLI_TYPE" in
  0|5|6)
    ;;
  *)
    echo "ERROR: CLI_TYPE must be one of: 0 (claude_code), 5 (crush), 6 (zeroclaw)"
    exit 1
    ;;
esac

# ── 1. Check for pending async job ──
PENDING=$(cast call "$TRACKER" "hasPendingJobForSender(address)(bool)" "$SENDER" --rpc-url "$RPC_URL" | awk '{print $1}')
if [ "$PENDING" = "true" ]; then
    echo "ERROR: Sender has a pending async job. Use a different key or wait for it to expire."
    exit 1
fi

# ── 2. Fund RitualWallet if needed ──
WALLET_BAL=$(cast call "$WALLET" "balanceOf(address)(uint256)" "$SENDER" --rpc-url "$RPC_URL" | awk '{print $1}')
NEEDS_DEPOSIT=$("${PY[@]}" - "$WALLET_BAL" "$MIN_RITUAL_WALLET_WEI" <<'PY'
import sys
print("1" if int(sys.argv[1]) < int(sys.argv[2]) else "0")
PY
)
if [ "$NEEDS_DEPOSIT" = "1" ]; then
    echo "Depositing RitualWallet balance (value=$DEPOSIT_WEI wei, lock=$LOCK_BLOCKS blocks)..."
    cast send "$WALLET" "deposit(uint256)" "$LOCK_BLOCKS" \
        --value "$DEPOSIT_WEI" \
        "${SIGNER_ARGS[@]}" \
        --rpc-url "$RPC_URL" >/dev/null
    echo "Funded."
fi
echo "RitualWallet wei: $(cast call "$WALLET" "balanceOf(address)(uint256)" "$SENDER" --rpc-url "$RPC_URL" | awk '{print $1}')"

# ── 3. Deploy consumer contract ──
if [ -n "$CONSUMER_ADDRESS" ]; then
    CONSUMER="$CONSUMER_ADDRESS"
    echo "Using existing consumer: $CONSUMER"
else
    echo "Deploying SovereignAgentConsumer..."
    DEPLOY_OUT=$(forge create --rpc-url "$RPC_URL" "${SIGNER_ARGS[@]}" \
        --broadcast "$SCRIPT_DIR/SovereignAgentConsumer.sol:SovereignAgentConsumer" 2>&1)
    CONSUMER=$(printf '%s\n' "$DEPLOY_OUT" | awk '/Deployed to:/ {print $3}' | tail -n1)
fi
if [ -z "$CONSUMER" ]; then
    echo "ERROR: Could not determine consumer contract address."
    exit 1
fi
echo "Consumer: $CONSUMER"

# ── 4. Detect LLM provider and key ──
LLM_KEY_COUNT=0
for key_name in ANTHROPIC_API_KEY OPENAI_API_KEY GEMINI_API_KEY OPENROUTER_API_KEY; do
    if [ -n "${!key_name:-}" ]; then
        LLM_KEY_COUNT=$((LLM_KEY_COUNT + 1))
    fi
done
if [ "$LLM_KEY_COUNT" -ne 1 ]; then
    echo "ERROR: Set exactly one of ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY, or OPENROUTER_API_KEY" >&2
    exit 2
fi

if [ -n "${ANTHROPIC_API_KEY:-}" ]; then

    LLM_KEY_NAME="ANTHROPIC_API_KEY"
    SECRETS_JSON=$("${PY[@]}" - <<'PY'
import json
import os
print(json.dumps({"ANTHROPIC_API_KEY": os.environ["ANTHROPIC_API_KEY"], "HF_TOKEN": os.environ["HF_TOKEN"]}))
PY
)
elif [ -n "${OPENAI_API_KEY:-}" ]; then
    LLM_KEY_NAME="OPENAI_API_KEY"
    SECRETS_JSON=$("${PY[@]}" - <<'PY'
import json
import os
print(json.dumps({"LLM_PROVIDER": "openai", "OPENAI_API_KEY": os.environ["OPENAI_API_KEY"], "HF_TOKEN": os.environ["HF_TOKEN"]}))
PY
)
elif [ -n "${GEMINI_API_KEY:-}" ]; then
    LLM_KEY_NAME="GEMINI_API_KEY"
    SECRETS_JSON=$("${PY[@]}" - <<'PY'
import json
import os
print(json.dumps({"LLM_PROVIDER": "gemini", "GEMINI_API_KEY": os.environ["GEMINI_API_KEY"], "HF_TOKEN": os.environ["HF_TOKEN"]}))
PY
)
elif [ -n "${OPENROUTER_API_KEY:-}" ]; then
    LLM_KEY_NAME="OPENROUTER_API_KEY"
    SECRETS_JSON=$("${PY[@]}" - <<'PY'
import json
import os
print(json.dumps({"LLM_PROVIDER": "openrouter", "OPENROUTER_API_KEY": os.environ["OPENROUTER_API_KEY"], "HF_TOKEN": os.environ["HF_TOKEN"]}))
PY
)
else
    echo "ERROR: Set one of ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY, or OPENROUTER_API_KEY"
    exit 1
fi
: "${MODEL:?Set MODEL to an exact provider model id (e.g. claude-sonnet-4-5-20250929, gpt-4o-mini, gemini-2.5-flash)}"
echo "Provider key: $LLM_KEY_NAME → model=$MODEL cli_type=$CLI_TYPE"

# ── 5. Get executor + encrypt secrets ──
echo "Finding executor and encrypting secrets..."
BUILD_ARGS=(
    --rpc "$RPC_URL"
    --registry "$REGISTRY"
    --consumer "$CONSUMER"
        --secrets-stdin

    --cli-type "$CLI_TYPE"
    --model "$MODEL"
    --prompt "$PROMPT"
    --hf-repo-id "$HF_REPO_ID"
)
if [ -n "$EXECUTOR_TEE_ADDRESS" ]; then
    BUILD_ARGS+=(--executor-tee-address "$EXECUTOR_TEE_ADDRESS")
fi
RESULT=$(printf '%s' "$SECRETS_JSON" | "${PY_HELPER[@]}" "$SCRIPT_DIR/helpers.py" "${BUILD_ARGS[@]}")

EXECUTOR=$(printf '%s\n' "$RESULT" | awk -F= '$1=="EXECUTOR"{print $2}')
REQUEST_INPUT=$(printf '%s\n' "$RESULT" | awk -F= '$1=="REQUEST_INPUT"{print $2}')
if [ -z "$EXECUTOR" ] || [ -z "$REQUEST_INPUT" ]; then
    echo "ERROR: Failed to build sovereign agent request."
    printf '%s\n' "$RESULT"
    exit 1
fi
echo "Executor: $EXECUTOR"

# ── 6. Submit Phase 1 via cast (typed call, hash printed immediately) ──
FROM_BLOCK=$(cast block-number --rpc-url "$RPC_URL")
echo "Submitting sovereign agent call (from_block=$FROM_BLOCK)..."
TX_HASH=$(cast send "$CONSUMER" 'callSovereignAgent(bytes)' "$REQUEST_INPUT" \
    --rpc-url "$RPC_URL" \
    "${SIGNER_ARGS[@]}" \
    --gas-limit "$PHASE1_GAS_LIMIT" \
    --async)
echo "Phase 1 tx: $TX_HASH"

# ── 7. Poll for Phase 2 event ──
echo "Waiting for Phase 2 delivery (up to ${PHASE2_TIMEOUT}s)..."
"${PY_HELPER[@]}" "$SCRIPT_DIR/helpers.py" \
    --rpc "$RPC_URL" \
    --poll-phase2 \
    --consumer "$CONSUMER" \
    --tx-hash "$TX_HASH" \
    --from-block "$FROM_BLOCK" \
    --timeout "$PHASE2_TIMEOUT"

echo "Done."

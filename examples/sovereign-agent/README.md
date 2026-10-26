# Sovereign agent: deploy your consumer and call the precompile

This directory is a standalone application example. `run.sh` compiles and deploys the included `SovereignAgentConsumer.sol` with public Foundry tools, encrypts credentials to the selected executor's registry public key, grants the consumer access, and submits the canonical agent request. Dependencies are Foundry (`forge`, `cast`), `uv`, and public Python packages (`eciespy`, `eth-abi`, `web3`). No private Python package or separate deployment project is needed.

The selected chain must provide RitualWallet, the executor registry, SecretsAccessControl, AsyncJobTracker and AsyncDelivery. The consumer constructor accepts the selected deployment's AsyncDelivery address; do not copy an address from another chain. Its immutable owner is the deploying EOA. Only that owner can submit paid jobs; the envelope sponsor must be that EOA, with RitualWallet allowance to the consumer. The callback must target this consumer with the correct selector and zero value. The consumer uses the native transaction-hash precompile (`0x0830`) to track each origin job and rejects unauthorized, foreign and duplicate callbacks. Results are stored by job ID.

## Run

Export the deployment-specific inputs without enabling shell tracing:

```bash
export RPC_URL="<selected deployment RPC>"
export EXPECTED_CHAIN_ID=784
export PRIVATE_KEY="<funded EOA private key>"
export ASYNC_DELIVERY_ADDRESS="<verified AsyncDelivery contract>"
export DA_PROVIDER=gcs
export GCS_DA_SERVICE_ACCOUNT_JSON='<service-account JSON object>'
export GCS_DA_BUCKET="<bucket you own>"
export OPENROUTER_API_KEY="<provider key>"
export MODEL="<provider-routable model>"
# Set local system-contract overrides from your deployment configuration.
bash run.sh
```

Exactly one provider-key variable should be configured: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY` or `OPENROUTER_API_KEY`. This example checks presence and DA input shape; it does not test provider credentials before submitting a job. Provider rejection is distinct from ABI/protocol acceptance. HF DA uses `DA_PROVIDER=hf`, `HF_TOKEN` and `HF_REPO_ID=owner/repo`. GCS credentials must contain JSON, not a filename or base64 string.

The script verifies the independently supplied chain ID and required contract bytecode before writes. Existing defaults for shared system contracts are chain-784 snapshots; override every differing address for a local deployment. Registry selection accepts valid registrations with empty endpoints; `EXECUTOR_TEE_ADDRESS` is a strict pin. Optional `ALLOWED_EXECUTOR_ADDRESSES`/`EXCLUDED_EXECUTOR_ADDRESSES` restrict admission. This flow does not depend on a public executor health endpoint.

## Sovereign flow

1. Deploy `SovereignAgentConsumer(asyncDelivery)` with ordinary contract creation.
2. Fund the sender's RitualWallet and approve the consumer as spender.
3. Seal the LLM/DA credentials to the executor's registry public key, sign the exact chain/executor/precompile context and grant the consumer access to the ciphertext hash. The runtime derives its consumer-scoped DA root internally; no separate payment-key derivation is necessary for this invocation.
4. Build the flat thirteen-field agent envelope with EOA sponsor, consumer callback target, zero callback value, and the sixteen-field sovereign V1 payload.
5. Call `consumer.callSovereignAgent(input)`; it calls `0x080c`. Observe the bare Phase-1 task ID through the exact origin/commitment job and wait for that job's `SovereignAgentResultDelivered` event. Success requires its decoded success flag.

The helper reads bare `spcCalls.output` from RPC receipts/transactions; it does not confuse that field with the Solidity CALL's outer `(bytes,bytes)` wrapper. Callback lookup filters both consumer address and indexed origin job ID. The consumer independently rejects foreign and duplicate callback jobs.

| Variable | Purpose/default |
| --- | --- |
| `MODEL` | Required exact provider-routable model. |
| `PROMPT` | `Say hello world`. |
| `CLI_TYPE` | 5; supported values 0, 5, 6. |
| `MAX_TURNS`, `MAX_TOKENS` | Existing invocation limits, 50 and 8192; set lower limits for a bounded ABI test. |
| `GCS_DA_PREFIX` | GCS conversation/output namespace, `sovereign-agent`. |
| `TEE_SERVICE_REGISTRY`, `SECRETS_ACCESS_CONTROL`, `ASYNC_JOB_TRACKER`, `RITUAL_WALLET` | Selected deployment's shared system contracts. |
| `WALLET_MIN_WEI`, `WALLET_DEPOSIT_WEI` | Sender RitualWallet minimum/deposit, each 5 RIT. The deposit remains in the sender's wallet, with only actual fees charged. |
| `PHASE1_TIMEOUT`, `RESULT_TIMEOUT` | 180 and 600 seconds. |

The native-balance preflight includes any wallet deposit and 0.5 RIT gas headroom. No scheduling residency payment or derived payment-key cushion is required for this single invocation. The process may still use a temporary runtime container; the deployment operator should remove its own test instance once the bounded invocation finishes.

## Offline checks

```bash
forge test --root . -vv
uv run --with eciespy --with eth-abi --with web3 python3 -m unittest discover -s .
```

Foundry tests mock only native precompile responses and transaction hash; they exercise the literal consumer's owner, sponsor/context/callback bindings and exact-job replay guards. Python tests exercise canonical request bytes and exact receipt/event correlation. These fixture checks do not claim a live provider response or deployed-chain launch.

# Persistent agent: deploy your consumer and call the precompile

This directory is a standalone application example. `run.sh` compiles and deploys the included `PersistentAgentConsumer.sol` with public Foundry tools, encrypts credentials to the selected executor's registry public key, grants the consumer access, and submits the canonical agent request. Dependencies are Foundry (`forge`, `cast`), `uv`, and public Python packages (`eciespy`, `eth-abi`, `web3`). No private Python package or separate deployment project is needed.

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

For a low-cost OpenRouter integration check, explicitly set `MODEL=openrouter/free`. Its free-model router selects an available model matching the request's features, including tools; the selected model can vary, and free-route availability/rate limits still apply. Check the current [OpenRouter free routing](https://openrouter.ai/openrouter/free) before relying on it. This model override does not remove chain, DA or hosting costs. With a paid model, a valid key can still receive HTTP 402 when the requested output-token allowance exceeds available provider credit, even if the expected answer is short. A small direct provider request alone does not establish that the runtime's larger request will be accepted.

The script verifies the independently supplied chain ID and required contract bytecode before writes. Existing defaults for shared system contracts are chain-784 snapshots; override every differing address for a local deployment. Registry selection accepts valid registrations with empty endpoints; `EXECUTOR_TEE_ADDRESS` is a strict pin. Optional `ALLOWED_EXECUTOR_ADDRESSES`/`EXCLUDED_EXECUTOR_ADDRESSES` restrict admission. `REQUIRE_EXECUTOR_HEALTH=1` enables an explicit operator diagnostic probe; the default registry flow does not depend on a public executor health endpoint.

Phase 1 and callback observation retry transient RPC connection failures/timeouts within their configured observation deadlines, keeping the same origin job and output key. These read retries never resubmit the launch. Invalid RPC responses, decryption failures and expired observation deadlines still stop the script.

## Persistent flow and identity

1. Deploy `PersistentAgentConsumer(asyncDelivery)` with ordinary contract creation.
2. Fund the sender's RitualWallet and approve the consumer as spender.
3. Allocate `AgentIdentityRegistry.allocateAgentId(sender)` in a committed transaction, then authorize the consumer with `setAgentOperator(agentId,consumer,true)`. The EOA retains identity ownership and recall authority. `AGENT_ID` can reference an already allocated identity owned by that same EOA.
4. Seal one credential blob to the executor public key, sign its chain/executor/precompile authorization, and grant the consumer access to its ciphertext hash. Build the flat thirteen-field agent envelope around the twenty-one-field persistent V1 payload, including chain-issued agentId and revision. `applicationContext=keccak256(abi.encode(agentId,revision))`.
5. Call `consumer.callPersistentAgent(agentId,revision,input)`; the consumer calls `0x0820`. The runtime bootstraps agent identity keys internally. No separate owner-scoped key derivation or payment-key prefunding is part of this launch.
6. Observe settled Phase 1 by exact origin job ID. Its six-string response contains the prelaunch wallet address. Fund that wallet immediately, within the executor's 120-second window. The raw tracker pending index may remain true during Phase 2; it is not a reason to delay funding after settled Phase 1.
7. Require the exact job's `PersistentAgentResultDelivered` success and `AgentHeartbeat.getAssignment(agentId)` ACTIVE state. The script prints public consumer/job/agent/instance identifiers and presence flags instead of gateway credentials.

`spcCalls.output` on RPC receipts/transactions is the bare executor output. The `(bytes simulatedInput,bytes actualOutput)` wrapper belongs to the Solidity precompile CALL return. The helper correlates the exact origin job through indexed JobAdded, including a different commitment transaction hash, and filters callback address and indexed jobId. It never correlates by a nearby transaction or address substring.

## Persistent inputs and funding

| Variable | Purpose/default |
| --- | --- |
| `AGENT_IDENTITY_REGISTRY`, `AGENT_HEARTBEAT_ADDRESS` | Selected deployment's identity and heartbeat contracts. |
| `TEE_SERVICE_REGISTRY`, `SECRETS_ACCESS_CONTROL`, `ASYNC_JOB_TRACKER`, `RITUAL_WALLET` | Selected deployment's shared system contracts. |
| `AGENT_RUNTIME` | `hermes` (default) or `zeroclaw`. |
| `AGENT_REVISION` | Payload revision, default 0. |
| `AGENT_RPC_URL` | Chain RPC reachable from inside the runtime; defaults to `RPC_URL`. |
| `WALLET_MIN_WEI`, `WALLET_DEPOSIT_WEI` | Sender RitualWallet minimum/deposit, each 0.5 RIT. Deposit only when available balance is below the minimum; unused reserves are released by settlement. |
| `PRELAUNCH_FUND_WEI` | Native runtime-wallet funding, default 0.5 RIT; must cover the 0.1 RIT claim balance floor. |
| `PHASE1_TIMEOUT`, `RESULT_TIMEOUT`, `HEARTBEAT_TIMEOUT` | Observation timeouts: 180, 300, 120 seconds. |
| `UAHI_MODE` and other connector/workspace inputs | Existing runtime work-loop/connector configuration; use `UAHI_MODE=off` for an isolated ABI launch check. |

The native-balance preflight covers any wallet deposit, prelaunch funding and 0.5 RIT gas headroom. Claim and ongoing heartbeat/workload charges are paid by the runtime wallet; the launch default is a demonstration budget, not long-term funding. Read the actual heartbeat cadence from the deployment and arrange monitored top-ups for continued operation. Pinata inputs remain supported as `DA_PROVIDER=pinata` with `DA_PINATA_JWT`.

## Stop your test agent

From the identity-owner EOA, call `AgentHeartbeat.recall(agentId)` while ACTIVE and confirm the vacant assignment before stopping the container; killing an ACTIVE runtime alone can trigger revival. The deployment operator then deletes only the recorded test instance using its authenticated spawner lifecycle API. On an isolated local deployment the heartbeat contract owner can remove remaining tracking with `adminRemoveAgent(agentId)`. Preserve the last verified DA manifest if needed. These operations do not require rerunning the launch script.

## Offline checks

```bash
forge test --root . -vv
uv run --with eciespy --with eth-abi --with web3 python3 -m unittest discover -s .
```

Foundry tests mock only native precompile responses and transaction hash; they exercise the literal consumer's owner, sponsor/context/callback bindings and exact-job replay guards. Python tests exercise canonical request bytes and exact receipt/event correlation. These fixture checks do not claim a live provider response or deployed-chain launch.

The example supplies a one-time uncompressed user public key for private Phase 1 and Phase 2 output. Its private half is created exclusively with mode `0600` inside a mode `0700` temporary directory and removed on shell exit. The helper decrypts settled Phase 1 and the Phase 2 callback locally and prints only gateway/token presence flags. A decryption failure stops observation; it never falls back to plaintext or resubmits the launch. Keep the response key securely if implementing resumable observation beyond this script's lifetime.

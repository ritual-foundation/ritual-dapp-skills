# Persistent Agent Example

End-to-end `0x0820` persistent agent spawn in **direct precompile caller mode**.

## Deployment Modes

This repo supports two persistent deployment modes:

1. **Direct precompile caller mode** (this example): a consumer contract calls `0x0820` directly.
2. **Factory-backed launcher mode** (recommended for production): deploy `PersistentAgentLauncher` via `PersistentAgentFactory`, then configure/fund/arm the launcher.

For the factory-backed flow, use the factory section in `skills/ritual-dapp-agents/SKILL.md`.

The script:
- deploys a minimal consumer contract
- checks sender preflight (`AsyncJobTracker`, `RitualWallet`)
- derives the child agent's DKMS heartbeat/payment address
- auto-funds that child address for heartbeat registration
- submits the persistent agent spawn request
- waits for Phase 2 callback delivery
- optionally verifies the spawned agent responds via the persistent-agent relay

## Prerequisites

```bash
# Foundry
curl -L https://foundry.paradigm.xyz | bash && foundryup

# uv (required - script uses `uv run --with ...`)
curl -LsSf https://astral.sh/uv/install.sh | sh
uv --version
```

No `pip`/venv setup needed. `run.sh` executes `helpers.py` via:

```bash
uv run --with eciespy --with eth-abi --with web3 python3 helpers.py ...
```

## Required Inputs

Always set:
- `RPC_URL`
- `PRIVATE_KEY` (funded sender with native RITUAL)
- exactly one LLM key:
  - `ANTHROPIC_API_KEY`
  - `OPENAI_API_KEY`
  - `GEMINI_API_KEY`
  - `OPENROUTER_API_KEY`
- `DA_PROVIDER` — one of: `hf`, `gcs`, `pinata`

Provider-specific credentials are listed in [DA Provider Inputs](#da-provider-inputs) below.

## Persistent-Agent Preflight (Hard Requirements)

Do **not** continue unless these are true:

1. **Explicit DA provider chosen.** Persistent agents cannot spawn without `da_provider`.
2. **Sender has no pending async job.** One unresolved async job per sender address.
3. **Sender has enough RitualWallet balance _and_ sufficient remaining lock duration.** The script auto-deposits / refreshes the lock if needed.
4. **Child DKMS heartbeat/payment address can be derived and funded.** If the child address cannot register and post heartbeats, the agent may never become operational.

This is the biggest difference from Sovereign Agent:

- Sovereign Agent can execute with empty external DA refs (`convoHistory`, `output`), but still needs sender/DKMS-backed execution context.
- Persistent Agent **cannot**. DA is foundational because state continuity and revival depend on it.

## DA Provider Inputs

For DA payload formats and provider credential shapes, see `ritual-dapp-da`.

### `DA_PROVIDER=hf`

Required:
- `HF_TOKEN`
- `HF_REPO_ID`

Example:

```bash
export DA_PROVIDER=hf
export HF_TOKEN=hf_...
export HF_REPO_ID=my-org/my-agent-store
```

### `DA_PROVIDER=gcs`

Required:
- `GCS_DA_SERVICE_ACCOUNT_JSON`
- `GCS_DA_BUCKET`

Optional:
- `GCS_DA_PREFIX`

Example:

```bash
export DA_PROVIDER=gcs
export GCS_DA_SERVICE_ACCOUNT_JSON='{"type":"service_account",...}'
export GCS_DA_BUCKET=my-bucket
export GCS_DA_PREFIX=agents/demo
```

### `DA_PROVIDER=pinata`

Required:
- `DA_PINATA_JWT`

Optional:
- `DA_PINATA_GATEWAY`

Example:

```bash
export DA_PROVIDER=pinata
export DA_PINATA_JWT=eyJ...
export DA_PINATA_GATEWAY=https://your-gateway.mypinata.cloud
```

## Optional Inputs

- `MODEL` — defaults by provider
- `SOUL`
- `AGENTS_DOC`
- `USER_DOC`
- `MEMORY_DOC`
- `IDENTITY_DOC`
- `TOOLS_DOC`
- `TELEGRAM_BOT_TOKEN` — optional Telegram channel config
- `TELEGRAM_DM_POLICY` — default `open`
- `HEARTBEAT_INTERVAL` — optional LLM heartbeat loop (separate from on-chain heartbeat)
- `HEARTBEAT_PROMPT`
- `HEARTBEAT_CHAIN_CONTRACT` — default `0xEF505E801f1Db392B5289690E2ffc20e840A3aCa`
- `HEARTBEAT_CHAIN_INTERVAL_BLOCKS` — default `100`
- `HEARTBEAT_CHAIN_TIMEOUT_BLOCKS` — default `200`
- `AGENT_RPC_URL` — RPC the spawned agent container should use (default `http://172.17.0.1:8545`)
- `AGENT_RUNTIME` — `zeroclaw` (default) or `hermes`
- `EXECUTOR_TEE_ADDRESS` — optional debug override; default flow discovers a live executor from `TEEServiceRegistry`
- `CONSUMER_ADDRESS` — reuse an already-deployed consumer contract
- `PHASE2_TIMEOUT`, `PHASE1_GAS_LIMIT`
- `RELAY_URL` — optional relay for post-spawn chat verification (no default; set your own endpoint)
- `VERIFY_RELAY` — `1` to send a test message via relay after spawn

## Quick Start

> **Fail-fast validation:** `run.sh` aborts with exit code `2` if any
> required variable is unset or still contains an unfilled placeholder
> (angle-brackets or `YOUR_…`). The placeholders in the snippets below
> (`<YOUR_GCS_BUCKET>`, `<your-relay-host>`) are illustrative — replace
> them with real values before running.
>
> **For agents running this example on behalf of a user:** elicit the
> DA provider choice and its required credentials (GCS bucket + service
> account JSON, or HF token + repo ID, or Pinata JWT) and the LLM API
> key from the user upfront. These are per-user resources with no
> defaults.

Example using GCS:

```bash
export RPC_URL="https://rpc.ritualfoundation.org"
export PRIVATE_KEY="0x..."
export ANTHROPIC_API_KEY="sk-ant-..."

export DA_PROVIDER="gcs"
export GCS_DA_SERVICE_ACCOUNT_JSON='{"type":"service_account",...}'
export GCS_DA_BUCKET="my-agent-workspace-bucket"  # replace with a bucket you own
export GCS_DA_PREFIX="agents/demo"
export AGENT_RUNTIME="hermes"

# optional: verify operator communication if the deployment exposes the relay
export RELAY_URL="https://<your-relay-host>"
export VERIFY_RELAY=1

bash run.sh
```

## What Gets Verified

1. Sender has no pending async job (`AsyncJobTracker`)
2. Sender has enough `RitualWallet` balance and lock duration (auto-deposit / refresh if needed)
3. Child DKMS address is derived successfully
4. Child DKMS address is funded for heartbeat posting
5. Phase 1 spawn tx is submitted
6. Phase 2 callback is delivered and decoded from `PersistentAgentResultDelivered`
7. If `VERIFY_RELAY=1`, the spawned agent appears on the relay and replies to a test message

## Files

| File | Purpose |
|------|---------|
| `PersistentAgentConsumer.sol` | Minimal consumer contract with DKMS + persistent-agent helpers |
| `run.sh` | One-shot orchestrator |
| `helpers.py` | DKMS request encoding, persistent request encoding, and Phase 2 / relay polling |

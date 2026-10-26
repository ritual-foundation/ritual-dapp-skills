# On-Chain Reference Contracts

Production dApps deployed on Ritual Chain (Chain ID 784). Use these as few-shot ICL patterns for precompile encoding, interface signatures, and feature composition.

## Contract Registry

The machine-readable registry lives at `examples/registry.json`. Its example dApps were deployed on an earlier chain-784 network state (`deploy_block` 2215742) and are not part of the live system-contract set — run `eth_getCode` against your target RPC before depending on any of them. Current entries:

| Contract | Address | Features |
|----------|---------|----------|
| TweetRegistry | `0x188c30510Ec32E6F00620b4f1c2E63925aA39ea2` | Scheduler, HTTP precompile, Secrets/Delegation |
| TweetRentManager | `0xDb0f588a05F56aF801ED9e17241fa48706e8AE1f` | Scheduler, HTTP precompile, Secrets/Delegation, Contract-owned secrets |
| ExecutorCity | TBD | Agent execution, TEEServiceRegistry |
| AgentHub | TBD | Verify contracts flow |

## Pulling Contract Source

Use the pull script to fetch source, bytecode, and function selectors. It requires the public `requests` package; the commands below provision it with `uv` (or install it in your Python virtual environment with `python3 -m pip install requests`):

```bash
# Pull all registry contracts
uv run --with requests python3 scripts/pull_contracts.py

# Pull a specific registry entry
uv run --with requests python3 scripts/pull_contracts.py --name TweetRegistry

# Pull any address (ad-hoc, no registry entry needed)
uv run --with requests python3 scripts/pull_contracts.py --address 0x1234...

# Pull + register for future use
uv run --with requests python3 scripts/pull_contracts.py --address 0x1234... --register MyContract --features Scheduler HTTP

# Discover contracts deployed at a block
uv run --with requests python3 scripts/pull_contracts.py --block 2215742
```

Output per contract:
- `source.sol` — Solidity source (from explorer API or GitHub)
- `abi.json` — ABI (if verified on explorer)
- `selectors.json` — 4-byte function selectors with resolved signatures
- `bytecode.hex` — deployed bytecode
- `interfaces/` — dependency interfaces (if available)

## Source Resolution Priority

1. **Explorer API** — `https://explorer.ritualfoundation.org/api/v2/smart-contracts/{address}` — best quality, includes ABI and compiler version
2. **GitHub** — configured per contract in `registry.json` — fallback for unverified contracts
3. **Bytecode analysis** — always available; extracts selectors and resolves via 4byte.directory

## What to Look For in Reference Contracts

- **Precompile encoding** — how call data is encoded for `0x0801` (HTTP), `0x0802` (LLM), etc.
- **Callback handling** — how results are decoded and stored on delivery
- **Feature composition** — how scheduler + secrets + HTTP work together in one contract
- **Fee management** — how sponsor balance/allowance backs per-job RitualWallet escrow for async requests
- **SPC patterns** — how state writes persist after SPC calls and in two-phase async submit functions

## Agent Deployment Modes In This Repo

- `examples/sovereign-agent/` and `examples/persistent-agent/` include self-contained consumers, local compilation and direct precompile launch flows.
- Their run scripts compile and deploy those consumers directly, configure public system-contract permissions, and decode Phase-1 and callback results.

## ABI and Deployment Authority

Use the minimal interfaces included with the operation you are running: the contracts skill supplies public system interfaces, and the agent examples include their consumer source plus the registry/permissions ABIs and call signatures they use. No private contract checkout is required to build or run these examples.

For a deployed contract's additional surface, retrieve its verified ABI/source through the explorer API described above, or request a versioned ABI/artifact and deployment manifest from that deployment's operator. Match the chain ID, address and deployed bytecode to that artifact before using it. If a matching artifact is unavailable, stop that unsupported operation and report the missing artifact; do not guess an ABI or require a private repository clone.

Implementation sources can be useful optional provenance during maintainer review. Deployment configuration and matching versioned artifacts determine which interface applies; an implementation repository name alone does not establish a deployed version.

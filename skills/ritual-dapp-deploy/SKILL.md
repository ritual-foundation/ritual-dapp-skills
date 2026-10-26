---
name: ritual-dapp-deploy
description: Deployment and chain configuration for Ritual dApps. Use when deploying contracts, configuring chain connection, or setting up development environment.
---

# Ritual Chain — Deployment & Configuration Guide

## Chain Configuration

### Deployment discovery is mandatory

The addresses in this document are the live chain-784 system contracts. On a local network, load the node's generated contract configuration instead. Do not infer addresses from a prior network.

Before sending writes, call `eth_chainId`, compare it with the selected configuration, and require non-empty `eth_getCode` at every system/consumer address used by the application. An address copied from this skill is never a fallback for missing deployment configuration.

### Core Parameters

| Parameter | Value |
|-----------|-------|
| Chain ID | `784` |
| Chain Name | `Ritual` |
| Native Currency | RITUAL (18 decimals) |
| RPC (HTTP) | `https://rpc.ritualfoundation.org` |
| RPC (WebSocket) | `wss://rpc.ritualfoundation.org/ws` |
| Block Explorer | `https://explorer.ritualfoundation.org` |

> **EIP-1559 only.** Ritual Chain requires EIP-1559 (type-2) transactions. Legacy (type-0) transactions are rejected with `transaction type not supported`. Do NOT use `--legacy` flag with forge/cast, and ensure your web3 library sends EIP-1559 transactions (viem does this by default; web3.py and ethers.js may need explicit configuration).

### viem Chain & Client Setup

Create viem clients configured for Ritual Chain:

```typescript
import { createPublicClient, createWalletClient, http, defineChain } from 'viem';
import { privateKeyToAccount } from 'viem/accounts';

const ritualChain = defineChain({
  id: 784,
  name: 'Ritual',
  nativeCurrency: { name: 'RITUAL', symbol: 'RITUAL', decimals: 18 },
  rpcUrls: {
    default: {
      http: [process.env.RITUAL_RPC_URL || 'https://rpc.ritualfoundation.org'],
      webSocket: [process.env.RITUAL_WS_URL || 'wss://rpc.ritualfoundation.org/ws'],
    },
  },
  blockExplorers: {
    default: { name: 'Ritual Explorer', url: 'https://explorer.ritualfoundation.org' },
  },
});

const account = privateKeyToAccount(process.env.PRIVATE_KEY as `0x${string}`);
const publicClient = createPublicClient({ chain: ritualChain, transport: http() });
const walletClient = createWalletClient({ account, chain: ritualChain, transport: http() });
```

### viem Chain Definition (Standalone)

A standalone chain definition for use in wagmi config or other contexts:

```typescript
import { defineChain } from 'viem';

export const ritualChain = defineChain({
  id: 784,
  name: 'Ritual',
  nativeCurrency: {
    decimals: 18,
    name: 'Ritual',
    symbol: 'RITUAL',
  },
  rpcUrls: {
    default: {
      http: ['https://rpc.ritualfoundation.org'],
      webSocket: ['wss://rpc.ritualfoundation.org/ws'],
    },
  },
  blockExplorers: {
    default: {
      name: 'Ritual Explorer',
      url: 'https://explorer.ritualfoundation.org',
    },
  },
});
```

## wagmi Configuration

### Basic wagmi Setup

```typescript
import { http, createConfig } from 'wagmi';
import { injected, walletConnect } from 'wagmi/connectors';
import { defineChain } from 'viem';

const ritualChain = defineChain({
  id: 784,
  name: 'Ritual',
  nativeCurrency: {
    decimals: 18,
    name: 'Ritual',
    symbol: 'RITUAL',
  },
  rpcUrls: {
    default: {
      http: ['https://rpc.ritualfoundation.org'],
      webSocket: ['wss://rpc.ritualfoundation.org/ws'],
    },
  },
  blockExplorers: {
    default: {
      name: 'Ritual Explorer',
      url: 'https://explorer.ritualfoundation.org',
    },
  },
});

export const config = createConfig({
  chains: [ritualChain],
  connectors: [
    injected(),
    walletConnect({
      projectId: process.env.NEXT_PUBLIC_WC_PROJECT_ID!,
    }),
  ],
  transports: {
    [ritualChain.id]: http('https://rpc.ritualfoundation.org'),
  },
});
```

### wagmi with RainbowKit

```typescript
import { getDefaultConfig } from '@rainbow-me/rainbowkit';
import { defineChain } from 'viem';

const ritualChain = defineChain({
  id: 784,
  name: 'Ritual',
  nativeCurrency: { decimals: 18, name: 'Ritual', symbol: 'RITUAL' },
  rpcUrls: {
    default: {
      http: ['https://rpc.ritualfoundation.org'],
    },
  },
  blockExplorers: {
    default: {
      name: 'Ritual Explorer',
      url: 'https://explorer.ritualfoundation.org',
    },
  },
});

export const config = getDefaultConfig({
  appName: 'My Ritual dApp',
  projectId: process.env.NEXT_PUBLIC_WC_PROJECT_ID!,
  chains: [ritualChain],
});
```

### Next.js App Layout with wagmi

```typescript
// app/providers.tsx
'use client';

import { WagmiProvider } from 'wagmi';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { config } from './wagmi';

const queryClient = new QueryClient();

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <WagmiProvider config={config}>
      <QueryClientProvider client={queryClient}>
        {children}
      </QueryClientProvider>
    </WagmiProvider>
  );
}
```

## Contract Deployment with Foundry

### foundry.toml Configuration

```toml
[profile.default]
src = "src"
out = "out"
libs = ["lib"]
solc = "0.8.20"
optimizer = true
optimizer_runs = 200

[rpc_endpoints]
ritual = "${RITUAL_RPC_URL}"

[etherscan]
ritual = { key = "unused", url = "${RITUAL_VERIFIER_URL}" }
```

### Deploy Script

```solidity
// script/Deploy.s.sol
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Script, console} from "forge-std/Script.sol";
import {MyRitualConsumer} from "../src/MyRitualConsumer.sol";

contract DeployScript is Script {
    function run() external {
        uint256 deployerPrivateKey = vm.envUint("PRIVATE_KEY");

        vm.startBroadcast(deployerPrivateKey);

        MyRitualConsumer consumer = new MyRitualConsumer();
        console.log("MyRitualConsumer deployed to:", address(consumer));

        vm.stopBroadcast();
    }
}
```

### Deploy Commands

```bash
# Load environment
source .env

# Deploy to Ritual Chain
forge script script/Deploy.s.sol:DeployScript \
  --rpc-url $RITUAL_RPC_URL \
  --broadcast \
  -vvvv

# Verify an already-deployed contract
forge verify-contract \
  --chain 784 \
  --watch \
  --verifier custom \
  --verifier-url "$RITUAL_VERIFIER_URL" \
  --verifier-api-key unused \
  <CONTRACT_ADDRESS> \
  src/MyRitualConsumer.sol:MyRitualConsumer
```

### Deploy with `forge create` (Single Contract)

`forge create` deploys a single contract without needing a deploy script. This is useful for quick deployments and testing.

```bash
# Basic deployment
forge create src/MyRitualConsumer.sol:MyRitualConsumer \
  --rpc-url $RITUAL_RPC_URL \
  --private-key $PRIVATE_KEY \
  --broadcast

# With constructor arguments
forge create src/MyRitualConsumer.sol:MyRitualConsumer \
  --rpc-url $RITUAL_RPC_URL \
  --private-key $PRIVATE_KEY \
  --broadcast \
  --constructor-args 0xF04076756d8129Baec46Dc0F1c526Baec490C393 100

# Deploy + verify in one command
forge create src/MyRitualConsumer.sol:MyRitualConsumer \
  --rpc-url $RITUAL_RPC_URL \
  --private-key $PRIVATE_KEY \
  --broadcast \
  --verify \
  --verifier custom \
  --verifier-url "$RITUAL_VERIFIER_URL" \
  --verifier-api-key unused
```

> **Warning**: Without `--broadcast`, `forge create` only simulates the deployment — the contract will NOT actually be deployed on-chain. Always include `--broadcast` for real deployments.
>
> **Verification note**: Use `--verifier custom` with the chain's verification service URL. Do NOT use Sourcify (chain 784 is not registered). Do NOT point at the scanner UI hostname — use the RPC domain's `/api/verify/` path.

## Contract Verification

Ritual Chain (784) uses a custom verification service accessible via the RPC domain. Sourcify does not support chain 784. The scanner UI does not expose Etherscan/Blockscout-compatible API endpoints.

### Verify an Already-Deployed Contract

```bash
forge verify-contract \
  --chain 784 \
  --watch \
  --verifier custom \
  --verifier-url "$RITUAL_VERIFIER_URL" \
  --verifier-api-key unused \
  <CONTRACT_ADDRESS> \
  src/MyContract.sol:MyContract
```

Expected output sequence:

1. `Submitting verification for [src/MyContract.sol:MyContract] 0x...`
2. `Response: OK` / `GUID: <uuid>`
3. Status polling: `Pending in queue` (may take ~15s)
4. `Details: Pass - Verified`
5. `Contract successfully verified`

### Deploy + Verify One-Liner

For contracts without constructor args:

```bash
forge create \
  --broadcast \
  --verify \
  --verifier custom \
  --verifier-url "$RITUAL_VERIFIER_URL" \
  --verifier-api-key unused \
  --rpc-url $RITUAL_RPC_URL \
  --private-key $PRIVATE_KEY \
  src/MyContract.sol:MyContract
```

For contracts with constructor args, prefer two-step: deploy first with `forge create --broadcast`, then verify separately with `forge verify-contract`. The combined one-liner can be brittle with complex constructor arg types.

### Verification Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `unsupported_chain` | Used Sourcify (default verifier) | Add `--verifier custom --verifier-url "$RITUAL_VERIFIER_URL"` |
| `Bytecode does not match` | Compiler/optimizer/EVM version mismatch | Check `foundry.toml` matches the settings used at deploy time |
| `Pending in queue` for >2 min | Verifier service overloaded or stalled | Retry; check service health |
| HTML 404 response | Pointed verifier at scanner UI URL instead of RPC domain | Use `https://rpc.ritualfoundation.org/api/verify` not the scanner hostname |

### Foundry Project Initialization

```bash
# Create new Foundry project
forge init my-ritual-contracts
cd my-ritual-contracts

# Install OpenZeppelin (if needed)
forge install OpenZeppelin/openzeppelin-contracts

# Add remappings
echo '@openzeppelin/=lib/openzeppelin-contracts/' >> remappings.txt
```

## Contract Deployment with Hardhat

### hardhat.config.ts

```typescript
import { HardhatUserConfig } from 'hardhat/config';
import '@nomicfoundation/hardhat-toolbox';
import 'dotenv/config';

const config: HardhatUserConfig = {
  solidity: {
    version: '0.8.20',
    settings: {
      optimizer: {
        enabled: true,
        runs: 200,
      },
    },
  },
  networks: {
    ritual: {
      url: process.env.RITUAL_RPC_URL || 'https://rpc.ritualfoundation.org',
      chainId: 784,
      accounts: process.env.PRIVATE_KEY ? [process.env.PRIVATE_KEY] : [],
    },
  },
};

export default config;
```

### Hardhat Deploy Script

```typescript
// scripts/deploy.ts
import { ethers } from 'hardhat';

async function main() {
  const [deployer] = await ethers.getSigners();
  console.log('Deploying with:', deployer.address);

  const balance = await ethers.provider.getBalance(deployer.address);
  console.log('Balance:', ethers.formatEther(balance), 'RITUAL');

  const Consumer = await ethers.getContractFactory('MyRitualConsumer');
  const consumer = await Consumer.deploy();
  await consumer.waitForDeployment();

  console.log('MyRitualConsumer deployed to:', await consumer.getAddress());
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
```

### Deploy Command

```bash
npx hardhat run scripts/deploy.ts --network ritual
```

## System Contract Addresses

### Core System Contracts

| Contract | Address |
|----------|---------|
| RitualWallet | `0xF04076756d8129Baec46Dc0F1c526Baec490C393` |
| AsyncJobTracker | `0xf00385449fD961925A0B125F5f30b29B682D4bFb` |
| TEEServiceRegistry | `0xf4495DC72143D44A93AB0ecE4d6D63a216b27839` |
| Scheduler | `0x4E0abeE2233D73E66382b45244F7459B34E1490E` |
| SecretsAccessControl | `0x0cEae62e2082829226eF5821Bb662483Db17A71F` |
| AgentIdentityRegistry | `0x2cbF50F833a3AEfb5c5B27068052cB5585F5c087` |
| AgentHeartbeat | `0xDeeA4Df0C958966ED75570a05430BB0D4844a8cc` |

### Agent Consumer Contracts

Deploy the application-owned consumers included in [the agent examples](../../examples/README.md). Each compiles locally with minimal public system ABIs and calls `0x080C` or `0x0820` directly. Configure the chain's `AsyncDelivery`, sponsor wallet allowance, secret delegation, and (for persistent agents) identity operator grant. See `ritual-dapp-agents` for the launch sequence.

### Precompile Addresses (Async)

| Precompile | Short | Full Address |
|-----------|-------|-------------|
| HTTP | 0x0801 | `0x0000000000000000000000000000000000000801` |
| LLM | 0x0802 | `0x0000000000000000000000000000000000000802` |
| Long HTTP | 0x0805 | `0x0000000000000000000000000000000000000805` |
| ZK | 0x0806 | `0x0000000000000000000000000000000000000806` |
| Image | 0x0818 | `0x0000000000000000000000000000000000000818` |
| Audio | 0x0819 | `0x0000000000000000000000000000000000000819` |
| Video | 0x081A | `0x000000000000000000000000000000000000081A` |

### Precompile Addresses (Native/Sync)

| Precompile | Short | Full Address |
|-----------|-------|-------------|
| JQ | 0x0803 | `0x0000000000000000000000000000000000000803` |
| Ed25519 | 0x0009 | `0x0000000000000000000000000000000000000009` |
| SECP256R1 | 0x0100 | `0x0000000000000000000000000000000000000100` |
| Nitro | 0x0104 | `0x0000000000000000000000000000000000000104` |

### External Contracts

| Contract | Address |
|----------|---------|
| Multicall3 | _not present in the current snapshot; omit `contracts.multicall3` so viem uses individual `eth_call`s_ |
| WETH | `0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2` |
| USDC | `0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48` |
| Uniswap V3 Router | `0xE592427A0AEce92De3Edee1F18E0157C05861564` |
| Uniswap V3 Factory | `0x1F98431c8aD98523631AE4a59f267346ea31F984` |

### Addresses as TypeScript Constants

Use these inline constants in your TypeScript code:

```typescript
// Precompile addresses (async)
const PRECOMPILES = {
  HTTP_CALL: '0x0000000000000000000000000000000000000801',
  LLM: '0x0000000000000000000000000000000000000802',
  LONG_RUNNING_HTTP: '0x0000000000000000000000000000000000000805',
  ZK_TWO_PHASE: '0x0000000000000000000000000000000000000806',
  IMAGE_CALL: '0x0000000000000000000000000000000000000818',
  AUDIO_CALL: '0x0000000000000000000000000000000000000819',
  VIDEO_CALL: '0x000000000000000000000000000000000000081A',
  JQ: '0x0000000000000000000000000000000000000803',
} as const;

// Core system contracts
const SYSTEM_CONTRACTS = {
  RITUAL_WALLET: '0xF04076756d8129Baec46Dc0F1c526Baec490C393',
  ASYNC_JOB_TRACKER: '0xf00385449fD961925A0B125F5f30b29B682D4bFb',
  TEE_SERVICE_REGISTRY: '0xf4495DC72143D44A93AB0ecE4d6D63a216b27839',
  SCHEDULER: '0x4E0abeE2233D73E66382b45244F7459B34E1490E',
  SECRETS_ACCESS_CONTROL: '0x0cEae62e2082829226eF5821Bb662483Db17A71F',
  AGENT_IDENTITY_REGISTRY: '0x2cbF50F833a3AEfb5c5B27068052cB5585F5c087',
  AGENT_HEARTBEAT: '0xDeeA4Df0C958966ED75570a05430BB0D4844a8cc',
} as const;


```

### Solidity Address Constants

For use in smart contracts:

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

library RitualAddresses {
    // Precompiles (async)
    address constant HTTP_PRECOMPILE       = address(0x0801);
    address constant LLM_PRECOMPILE        = address(0x0802);
    address constant LONG_HTTP_PRECOMPILE  = address(0x0805);
    address constant ZK_PRECOMPILE         = address(0x0806);
    address constant IMAGE_PRECOMPILE      = address(0x0818);
    address constant AUDIO_PRECOMPILE      = address(0x0819);
    address constant VIDEO_PRECOMPILE      = address(0x081A);

    // Precompiles (native)
    address constant JQ_PRECOMPILE         = address(0x0803);
    address constant ED25519_PRECOMPILE    = address(0x0009);
    address constant SECP256R1_PRECOMPILE  = address(0x0100);
    address constant NITRO_PRECOMPILE      = address(0x0104);

    // System contracts
    address constant RITUAL_WALLET         = 0xF04076756d8129Baec46Dc0F1c526Baec490C393;
    address constant ASYNC_JOB_TRACKER     = 0xf00385449fD961925A0B125F5f30b29B682D4bFb;
    address constant TEE_SERVICE_REGISTRY  = 0xf4495DC72143D44A93AB0ecE4d6D63a216b27839;
    address constant SCHEDULER             = 0x4E0abeE2233D73E66382b45244F7459B34E1490E;
    address constant SECRETS_ACCESS_CONTROL = 0x0cEae62e2082829226eF5821Bb662483Db17A71F;
    address constant AGENT_IDENTITY_REGISTRY = 0x2cbF50F833a3AEfb5c5B27068052cB5585F5c087;
    address constant AGENT_HEARTBEAT        = 0xDeeA4Df0C958966ED75570a05430BB0D4844a8cc;
}
```

## Environment Configuration

### .env Template

```bash
# ===== Chain Connection =====
RITUAL_RPC_URL=https://rpc.ritualfoundation.org
RITUAL_WS_URL=wss://rpc.ritualfoundation.org/ws

# ===== Deployer Account =====
PRIVATE_KEY=0x...your_deployer_private_key...

# ===== Contract Verification =====
RITUAL_VERIFIER_URL=https://rpc.ritualfoundation.org/api/verify

# ===== Frontend (public) =====
NEXT_PUBLIC_RITUAL_RPC_URL=https://rpc.ritualfoundation.org
NEXT_PUBLIC_WC_PROJECT_ID=your_walletconnect_project_id

# ===== Optional: Deployed Contract Addresses =====
NEXT_PUBLIC_CONSUMER_CONTRACT=0x...your_deployed_contract...
```

### Agent Consumer Preflight

Verify the deployed consumer and each public system contract used by the flow. Check its `asyncDelivery()` address against the selected chain, sponsor balance/allowance to the consumer, secret grants to the consumer, and persistent identity operator approval before submitting.

```bash
cast code "$CONSUMER_ADDRESS" --rpc-url "$RITUAL_RPC_URL"
cast call "$CONSUMER_ADDRESS" "asyncDelivery()(address)" --rpc-url "$RITUAL_RPC_URL"
```

### Encrypted Secrets (dKMS) Configuration

Encrypted secrets require the dKMS service to be enabled and registered:

```bash
DKMS_ENABLED=true                              # Enable dKMS support in executor
TEE_SERVICE_REGISTRY_CONTRACT_ADDRESS=0x...     # Registry for dKMS endpoint discovery
```

The executor discovers dKMS endpoints dynamically from `TEEServiceRegistry`. If `DKMS_ENABLED` is `false` (the default), encrypted secret operations will time out silently.

### .gitignore Entries

```gitignore
# Environment
.env
.env.local
.env.*.local

# Foundry
out/
cache/
broadcast/

# Hardhat
artifacts/
cache/
typechain-types/

# Dependencies
node_modules/
```

### TypeScript Environment Typing

```typescript
// env.d.ts
declare namespace NodeJS {
  interface ProcessEnv {
    RITUAL_RPC_URL: string;
    RITUAL_WS_URL: string;
    PRIVATE_KEY: `0x${string}`;
    RITUAL_VERIFIER_URL?: string;
    NEXT_PUBLIC_RITUAL_RPC_URL: string;
    NEXT_PUBLIC_WC_PROJECT_ID: string;
    NEXT_PUBLIC_CONSUMER_CONTRACT?: `0x${string}`;
  }
}
```

## Deployment-Specific Funding

Fund through the authorized operational process and confirm cost before sending. Local networks may publish a faucet in their generated configuration — never try a remembered faucet URL against the live chain.

## Development Workflow

### Recommended Project Structure

```
my-ritual-dapp/
├── contracts/               # Foundry project
│   ├── src/
│   │   └── MyConsumer.sol
│   ├── script/
│   │   └── Deploy.s.sol
│   ├── test/
│   │   └── MyConsumer.t.sol
│   ├── foundry.toml
│   └── .env
├── frontend/                # Next.js app
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx
│   │   └── providers.tsx
│   ├── lib/
│   │   ├── wagmi.ts
│   │   ├── ritual.ts        # viem client setup
│   │   └── addresses.ts     # Deployed contract addresses
│   ├── package.json
│   └── .env.local
├── backend/                 # Optional API/indexer
│   ├── src/
│   │   └── index.ts
│   └── package.json
└── README.md
```

### viem Client Setup for Frontend

```typescript
// frontend/lib/ritual.ts
import { createPublicClient, createWalletClient, http, defineChain } from 'viem';
import { privateKeyToAccount } from 'viem/accounts';

const ritualChain = defineChain({
  id: 784,
  name: 'Ritual',
  nativeCurrency: { name: 'RITUAL', symbol: 'RITUAL', decimals: 18 },
  rpcUrls: {
    default: {
      http: [process.env.NEXT_PUBLIC_RITUAL_RPC_URL || 'https://rpc.ritualfoundation.org'],
    },
  },
  blockExplorers: {
    default: { name: 'Ritual Explorer', url: 'https://explorer.ritualfoundation.org' },
  },
});

// Read-only client for frontend (no private key needed)
let publicClientInstance: ReturnType<typeof createPublicClient> | null = null;

export function getPublicClient() {
  if (!publicClientInstance) {
    publicClientInstance = createPublicClient({ chain: ritualChain, transport: http() });
  }
  return publicClientInstance;
}

// For server-side operations that need signing
export function getSignerClients(privateKey: `0x${string}`) {
  const account = privateKeyToAccount(privateKey);
  return {
    publicClient: createPublicClient({ chain: ritualChain, transport: http() }),
    walletClient: createWalletClient({ account, chain: ritualChain, transport: http() }),
  };
}
```

### Deploying and Wiring Contracts

Step-by-step deployment workflow:

```bash
# 1. Compile contracts
cd contracts
forge build

# 2. Run tests locally
forge test -vvv

# 3. Deploy to Ritual
forge script script/Deploy.s.sol:DeployScript \
  --rpc-url $RITUAL_RPC_URL \
  --broadcast \
  -vvvv

# 4. Note the deployed address from output
# MyRitualConsumer deployed to: 0x1234...

# 5. Verify on explorer
forge verify-contract \
  --chain 784 \
  --watch \
  --verifier custom \
  --verifier-url "$RITUAL_VERIFIER_URL" \
  --verifier-api-key unused \
  0x1234... \
  src/MyRitualConsumer.sol:MyRitualConsumer

# 6. Update frontend .env
echo 'NEXT_PUBLIC_CONSUMER_CONTRACT=0x1234...' >> ../frontend/.env.local
```

## RPC Proxy (for Restricted Environments)

When the RPC endpoint is not directly reachable from the browser (IP-restricted or CORS-constrained), proxy RPC calls through your Next.js API route:

```typescript
// app/api/rpc/route.ts
import { NextResponse } from 'next/server';

const RPC_URL = process.env.RITUAL_RPC_URL ?? 'https://rpc.ritualfoundation.org';
const MAX_BODY_BYTES = 100_000;
const ALLOWED_METHODS = new Set([
  'eth_blockNumber', 'eth_call', 'eth_chainId', 'eth_estimateGas',
  'eth_feeHistory', 'eth_gasPrice', 'eth_getBalance', 'eth_getBlockByHash',
  'eth_getBlockByNumber', 'eth_getCode', 'eth_getLogs',
  'eth_getTransactionByHash', 'eth_getTransactionCount',
  'eth_getTransactionReceipt', 'eth_maxPriorityFeePerGas',
]);

function rpcError(status: number, code: number, message: string, id: string | number | null = null) {
  return NextResponse.json({ jsonrpc: '2.0', error: { code, message }, id },
    { status, headers: { 'Cache-Control': 'no-store' } });
}

export async function POST(req: Request) {
  if (Number(req.headers.get('content-length') ?? '0') > MAX_BODY_BYTES) {
    return rpcError(413, -32600, 'Request too large');
  }
  // Count bytes while reading, even if Content-Length is absent or inaccurate.
  const reader = req.body?.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  if (reader) {
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        size += value.byteLength;
        if (size > MAX_BODY_BYTES) {
          await reader.cancel();
          return rpcError(413, -32600, 'Request too large');
        }
        chunks.push(value);
      }
    } catch { return rpcError(400, -32600, 'Unreadable request'); }
    finally { reader.releaseLock(); }
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  const raw = new TextDecoder().decode(bytes);
  let body: unknown;
  try { body = JSON.parse(raw); } catch { return rpcError(400, -32700, 'Parse error'); }
  if (!body || Array.isArray(body) || typeof body !== 'object') {
    return rpcError(400, -32600, 'Invalid JSON-RPC request');
  }
  const { jsonrpc, method, params, id = null } = body as Record<string, unknown>;
  if (jsonrpc !== '2.0' || typeof method !== 'string' ||
      !(id === null || typeof id === 'string' || (typeof id === 'number' && Number.isFinite(id))) ||
      !(params === undefined || Array.isArray(params) || (params !== null && typeof params === 'object'))) {
    return rpcError(400, -32600, 'Invalid JSON-RPC request');
  }
  if (!ALLOWED_METHODS.has(method)) return rpcError(403, -32601, 'Method not allowed', id);
  try {
    const response = await fetch(RPC_URL, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: raw,
      cache: 'no-store', signal: AbortSignal.timeout(10_000),
    });
    const responseBody = await response.text();
    return new NextResponse([204, 205, 304].includes(response.status) ? null : responseBody, {
      status: response.status,
      headers: { 'Content-Type': response.headers.get('content-type') ?? 'application/json', 'Cache-Control': 'no-store' },
    });
  } catch { return rpcError(504, -32000, 'RPC upstream unavailable', id); }
}
```

This read-method allowlist rejects batches and transaction submission. Wallets may submit through their own provider; if the application needs server-proxied writes, add an authenticated, rate-limited submission route explicitly. Enforce request duration, body limits and per-user/IP rate limits at the hosting edge too. Never expose `admin_*`, `debug_*`, `personal_*`, or unlocked-account methods.

Then configure your wagmi/viem transport to use `/api/rpc` instead of the direct RPC URL:

```typescript
const ritualChain = defineChain({
  id: 784,
  name: 'Ritual',
  nativeCurrency: { name: 'RITUAL', symbol: 'RITUAL', decimals: 18 },
  rpcUrls: {
    default: { http: ['/api/rpc'] },
  },
});
```

## Post-Deployment Checklist

After deploying your dApp contracts, verify these items:

### Contract Source Verification

- [ ] Run `forge verify-contract --chain 784 --watch --verifier custom --verifier-url "$RITUAL_VERIFIER_URL" --verifier-api-key unused <ADDRESS> <CONTRACT_ID>` and confirm `Pass - Verified`
- [ ] Constructor arguments are correctly encoded (if any)
- [ ] Source code matches the deployed bytecode (Foundry verifier compiles locally and compares)

### RitualWallet Setup

- [ ] Deployer/operator has deposited RITUAL into RitualWallet
- [ ] Deposit amount is sufficient for expected async call volume
- [ ] Available balance covers the expected async call volume (deposits credit `availableBalance` immediately)
- [ ] Deposit is against the **sponsor account** (`ReserveConfig.sponsor`) — the account whose `availableBalance`/allowance backs the job escrow. This defaults to the signing EOA but can be a designated sponsor (a contract or third party). Confirm the funded account matches whichever address is set as the job's sponsor, not unconditionally the signing EOA.

```typescript
import { formatEther } from 'viem';

const RITUAL_WALLET = '0xF04076756d8129Baec46Dc0F1c526Baec490C393' as const;
const RITUAL_WALLET_ABI = [
  { inputs: [{ name: 'account', type: 'address' }], name: 'availableBalance', outputs: [{ type: 'uint256' }], stateMutability: 'view', type: 'function' },
] as const;

const balance = await publicClient.readContract({
  address: RITUAL_WALLET,
  abi: RITUAL_WALLET_ABI,
  functionName: 'availableBalance',
  args: [deployerAddress],
});
console.log('RitualWallet balance:', formatEther(balance), 'RITUAL');
```

### Executor Availability

- [ ] Executors with required capabilities are registered and online
- [ ] If the dApp emits RITHTTP1 bodies, the selected deployment's entire eligible HTTP executor fleet explicitly supports the exact modes used. Private I/O requires matching artifact/frame codecs across executor, shared library, streaming service, contracts, and client, proven with canonical vectors. Capability registration or a PR number does not prove deployed binary support; do not submit to a mixed/legacy fleet.
- [ ] Tested with a sample request to confirm executor responds

```typescript
const TEE_SERVICE_REGISTRY = '0xf4495DC72143D44A93AB0ecE4d6D63a216b27839' as const;
const TEE_SERVICE_REGISTRY_ABI = [
  {
    inputs: [{ name: 'capability', type: 'uint8' }, { name: 'checkValidity', type: 'bool' }],
    name: 'getServicesByCapability',
    outputs: [{
      type: 'tuple[]',
      components: [
        { name: 'node', type: 'tuple', components: [
          { name: 'paymentAddress', type: 'address' },
          { name: 'teeAddress', type: 'address' },
          { name: 'teeType', type: 'uint8' },
          { name: 'executorSecretsAuthPublicKey', type: 'bytes' },
          { name: 'endpoint', type: 'string' },
          { name: 'mTlsSpkiHash', type: 'bytes32' },
          { name: 'capability', type: 'uint8' },
        ]},
        { name: 'isValid', type: 'bool' },
        { name: 'workloadId', type: 'bytes32' },
      ],
    }],
    stateMutability: 'view',
    type: 'function',
  },
] as const;

const HTTP_CALL_CAPABILITY = 0;

const services = await publicClient.readContract({
  address: TEE_SERVICE_REGISTRY,
  abi: TEE_SERVICE_REGISTRY_ABI,
  functionName: 'getServicesByCapability',
  args: [HTTP_CALL_CAPABILITY, true],
});

const validServices = services.filter((svc) => svc.isValid);

console.log(`Found ${services.length} HTTP services (${validServices.length} valid)`);
```

### Contract Configuration

- [ ] Precompile addresses are correct in contract constants
- [ ] Callback selectors match the receiving function signatures
- [ ] Access control is properly configured (owner, allowed callers)
- [ ] Gas limits for callbacks are sufficient

### Frontend Integration

- [ ] The wagmi/viem chain ID matches the selected deployment manifest/profile (784 only for the labeled chain-784 system-contract table)
- [ ] Contract ABI is imported (from Foundry `out/` or Hardhat `artifacts/`)
- [ ] Deployed contract address is set in environment variables
- [ ] Wallet connection works (MetaMask, WalletConnect, etc.)
- [ ] Users can switch to Ritual Chain if on wrong network

### Monitoring

- [ ] Event listeners are set up for async job lifecycle events
- [ ] Error handling covers all 9 async states (including FAILED, EXPIRED)
- [ ] Logging captures transaction hashes for debugging

## Common Issues and Solutions

### Hardcoded Contract Addresses Cause Silent Failures After Redeployment

**Symptom**: After redeploying contracts to a different chain or after a fresh deployment, the frontend shows empty state — no markets, no data, no errors. Contract calls silently revert because they target the old address which either does not exist or has different bytecode on the new chain.

**Cause**: Contract addresses were hardcoded directly in source files (e.g., `const CONSUMER = '0xabc...'`). After redeployment, the address changes but the source code still points to the old one.

**Solution**: Always read deployed contract addresses from environment variables, with an optional fallback for local development:

```typescript
// lib/addresses.ts
import { type Address } from 'viem';

// Always read from environment — never hardcode deployment-specific addresses
export const CONSUMER_ADDRESS = (
  process.env.NEXT_PUBLIC_CONSUMER_ADDRESS ?? '0x0000000000000000000000000000000000000000'
) as Address;

export const MARKET_ADDRESS = (
  process.env.NEXT_PUBLIC_MARKET_ADDRESS ?? '0x0000000000000000000000000000000000000000'
) as Address;

export const CONSUMER_ADDRESS = (
  process.env.NEXT_PUBLIC_CONSUMER_CONTRACT ?? '0x0000000000000000000000000000000000000000'
) as Address;
```

Then in `.env.local` (frontend) or `.env` (backend):

```bash
NEXT_PUBLIC_CONSUMER_ADDRESS=0x1234...actual_deployed_address
NEXT_PUBLIC_MARKET_ADDRESS=0x5678...actual_deployed_address
NEXT_PUBLIC_CONSUMER_CONTRACT=0xabcd...actual_deployed_address
```

**Rules**:
1. **System contracts** (RitualWallet, AsyncJobTracker, precompiles) have fixed addresses across all Ritual Chain deployments — these CAN be hardcoded as constants
2. **Your deployed contracts** (factories, markets, consumers) get new addresses on each deployment — these MUST come from environment variables
3. After redeployment, update `.env.local` with the new addresses from the deploy script output and restart the frontend
4. Add a startup check to verify critical addresses are set:

```typescript
// lib/addresses.ts
if (!process.env.NEXT_PUBLIC_CONSUMER_ADDRESS) {
  console.warn(
    'NEXT_PUBLIC_CONSUMER_ADDRESS not set — contract reads will fail. ' +
    'Run the deploy script and update .env.local with the new address.'
  );
}
```

### "No executors found" Error

The TEEServiceRegistry has no services registered for the requested capability.

```typescript
const HTTP_CALL_CAPABILITY = 0;

const services = await publicClient.readContract({
  address: '0xf4495DC72143D44A93AB0ecE4d6D63a216b27839',
  abi: TEE_SERVICE_REGISTRY_ABI,  // defined above
  functionName: 'getServicesByCapability',
  args: [HTTP_CALL_CAPABILITY, true],
});

if (services.length === 0) {
  console.error('No HTTP services available. Check:');
  console.error('1. Are services registered on this network?');
  console.error('2. Is the capability enum correct?');
}
```

### Insufficient RitualWallet Balance

Async calls fail if your RitualWallet available balance is too low.

```typescript
import { parseEther } from 'viem';

const RITUAL_WALLET = '0xF04076756d8129Baec46Dc0F1c526Baec490C393' as const;
const DEPOSIT_ABI = [
  { inputs: [], name: 'deposit', outputs: [], stateMutability: 'payable', type: 'function' },
] as const;

// Deposit 5 RITUAL (immediately credited to availableBalance — no time lock)
const hash = await walletClient.writeContract({
  address: RITUAL_WALLET,
  abi: DEPOSIT_ABI,
  functionName: 'deposit',
  args: [],
  value: parseEther('5'),
});
await publicClient.waitForTransactionReceipt({ hash });
```

### Wrong Chain in Wallet

Users connecting from MetaMask may be on the wrong network.

```typescript
import { useChainId, useSwitchChain } from 'wagmi';

function ChainGuard({ children }: { children: React.ReactNode }) {
  const chainId = useChainId();
  const { switchChain } = useSwitchChain();

  if (chainId !== 784) {
    return (
      <button onClick={() => switchChain({ chainId: 784 })}>
        Switch to Ritual Chain
      </button>
    );
  }

  return <>{children}</>;
}
```

### Gas Estimation Failures

Async precompile calls cannot be gas-estimated with standard `estimateGas`. Use explicit gas limits:

```typescript
const HTTP_PRECOMPILE = '0x0000000000000000000000000000000000000801' as const;

// Encode the request using encodeAbiParameters (see ritual-dapp-overview for full encoding)
const hash = await walletClient.sendTransaction({
  to: HTTP_PRECOMPILE,
  data: encoded,
  gas: 2_000_000n,
  maxFeePerGas: 20_000_000_000n,
  maxPriorityFeePerGas: 2_000_000_000n,
});
```

## Package.json Dependencies

### Frontend (Next.js + viem)

```json
{
  "dependencies": {
    "@rainbow-me/rainbowkit": "^2.0.0",
    "@tanstack/react-query": "^5.0.0",
    "eciesjs": "^0.4.0",
    "next": "^14.0.0",
    "react": "^18.0.0",
    "react-dom": "^18.0.0",
    "viem": "^2.0.0",
    "wagmi": "^2.0.0"
  },
  "devDependencies": {
    "@types/node": "^20.0.0",
    "@types/react": "^18.0.0",
    "typescript": "^5.0.0"
  }
}
```

### Backend (Node.js + viem)

```json
{
  "dependencies": {
    "viem": "^2.0.0",
    "eciesjs": "^0.4.0",
    "dotenv": "^16.0.0"
  },
  "devDependencies": {
    "@types/node": "^20.0.0",
    "typescript": "^5.0.0",
    "tsx": "^4.0.0"
  }
}
```

## Related Skills

- **`ritual-dapp-overview`** — Architecture overview, precompile categories, async lifecycle
- **`ritual-dapp-contracts`** — Consumer contract patterns and Solidity templates
- **`ritual-dapp-frontend`** — React/Next.js frontend with async state machine
- **`ritual-dapp-wallet`** — RitualWallet deposit, allowance/escrow, and fee management
- **`ritual-dapp-testing`** — Testing and debugging Ritual dApps

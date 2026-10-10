---
name: ritual-dapp-deploy
description: Deployment and chain configuration for Ritual dApps. Use when deploying contracts, configuring chain connection, or setting up development environment.
---

# Ritual Chain — Deployment & Configuration Guide

## Chain Configuration

### Core Parameters

| Parameter | Value |
|-----------|-------|
| Chain ID | `1979` |
| Chain Name | `Ritual` |
| Native Currency | RITUAL (18 decimals, testnet, no real value) |
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
  id: 1979,
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
  contracts: {
    multicall3: { address: '0x5577Ea679673Ec7508E9524100a188E7600202a3' },
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
  id: 1979,
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
  contracts: {
    multicall3: {
      address: '0x5577Ea679673Ec7508E9524100a188E7600202a3',
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
  id: 1979,
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
  contracts: {
    multicall3: {
      address: '0x5577Ea679673Ec7508E9524100a188E7600202a3',
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
  id: 1979,
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
  --chain 1979 \
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
  --constructor-args 0x532F0dF0896F353d8C3DD8cc134e8129DA2a3948 100

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
> **Verification note**: Use `--verifier custom` with the chain's verification service URL. Do NOT use Sourcify (chain 1979 is not registered). Do NOT point at the scanner UI hostname — use the RPC domain's `/api/verify/` path.

## Contract Verification

Ritual Chain (1979) uses a custom verification service accessible via the RPC domain. Sourcify does not support chain 1979. The scanner UI does not expose Etherscan/Blockscout-compatible API endpoints.

### Verify an Already-Deployed Contract

```bash
forge verify-contract \
  --chain 1979 \
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
      chainId: 1979,
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
| RitualWallet | `0x532F0dF0896F353d8C3DD8cc134e8129DA2a3948` |
| AsyncJobTracker | `0xC069FFCa0389f44eCA2C626e55491b0ab045AEF5` |
| TEEServiceRegistry | `0x9644e8562cE0Fe12b4deeC4163c064A8862Bf47F` |
| Scheduler | `0x56e776BAE2DD60664b69Bd5F865F1180ffB7D58B` |
| SecretsAccessControl | `0xf9BF1BC8A3e79B9EBeD0fa2Db70D0513fecE32FD` |

### Agent Factory Contracts

| Contract | Address |
|----------|---------|
| SovereignAgentFactory | `0x9dC4C054e53bCc4Ce0A0Ff09E890A7a8e817f304` |
| PersistentAgentFactory | `0xD4AA9D55215dc8149Af57605e70921Ea16b73591` |

Verify before launch:

```bash
cast code "0x9dC4C054e53bCc4Ce0A0Ff09E890A7a8e817f304" --rpc-url "$RITUAL_RPC_URL"
cast code "0xD4AA9D55215dc8149Af57605e70921Ea16b73591" --rpc-url "$RITUAL_RPC_URL"
```

If either returns `0x`, your deployment config is wrong for that RPC.

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
| ONNX | 0x0800 | `0x0000000000000000000000000000000000000800` |
| JQ | 0x0803 | `0x0000000000000000000000000000000000000803` |
| Ed25519 | 0x0009 | `0x0000000000000000000000000000000000000009` |
| SECP256R1 | 0x0100 | `0x0000000000000000000000000000000000000100` |
| Nitro | 0x0104 | `0x0000000000000000000000000000000000000104` |

### External Contracts

| Contract | Address |
|----------|---------|
| Multicall3 | `0x5577Ea679673Ec7508E9524100a188E7600202a3` |
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
  ONNX: '0x0000000000000000000000000000000000000800',
  JQ: '0x0000000000000000000000000000000000000803',
} as const;

// Core system contracts
const SYSTEM_CONTRACTS = {
  RITUAL_WALLET: '0x532F0dF0896F353d8C3DD8cc134e8129DA2a3948',
  ASYNC_JOB_TRACKER: '0xC069FFCa0389f44eCA2C626e55491b0ab045AEF5',
  TEE_SERVICE_REGISTRY: '0x9644e8562cE0Fe12b4deeC4163c064A8862Bf47F',
  SCHEDULER: '0x56e776BAE2DD60664b69Bd5F865F1180ffB7D58B',
  SECRETS_ACCESS_CONTROL: '0xf9BF1BC8A3e79B9EBeD0fa2Db70D0513fecE32FD',
} as const;

// Agent factory contracts
const AGENT_FACTORIES = {
  SOVEREIGN_FACTORY: '0x9dC4C054e53bCc4Ce0A0Ff09E890A7a8e817f304',
  PERSISTENT_FACTORY: '0xD4AA9D55215dc8149Af57605e70921Ea16b73591',
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
    address constant ONNX_PRECOMPILE       = address(0x0800);
    address constant JQ_PRECOMPILE         = address(0x0803);
    address constant ED25519_PRECOMPILE    = address(0x0009);
    address constant SECP256R1_PRECOMPILE  = address(0x0100);
    address constant NITRO_PRECOMPILE      = address(0x0104);

    // System contracts
    address constant RITUAL_WALLET         = 0x532F0dF0896F353d8C3DD8cc134e8129DA2a3948;
    address constant ASYNC_JOB_TRACKER     = 0xC069FFCa0389f44eCA2C626e55491b0ab045AEF5;
    address constant TEE_SERVICE_REGISTRY  = 0x9644e8562cE0Fe12b4deeC4163c064A8862Bf47F;
    address constant SCHEDULER             = 0x56e776BAE2DD60664b69Bd5F865F1180ffB7D58B;
    address constant SECRETS_ACCESS_CONTROL = 0xf9BF1BC8A3e79B9EBeD0fa2Db70D0513fecE32FD;
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
SOVEREIGN_FACTORY_ADDRESS=0x9dC4C054e53bCc4Ce0A0Ff09E890A7a8e817f304
PERSISTENT_FACTORY_ADDRESS=0xD4AA9D55215dc8149Af57605e70921Ea16b73591
```

### Agent Factory Preflight

```bash
# 1) Address has code
cast code "$SOVEREIGN_FACTORY_ADDRESS" --rpc-url "$RITUAL_RPC_URL"
cast code "$PERSISTENT_FACTORY_ADDRESS" --rpc-url "$RITUAL_RPC_URL"

# 2) Wiring sanity
cast call "$SOVEREIGN_FACTORY_ADDRESS" "scheduler()(address)" --rpc-url "$RITUAL_RPC_URL"
cast call "$SOVEREIGN_FACTORY_ADDRESS" "ritualWallet()(address)" --rpc-url "$RITUAL_RPC_URL"
cast call "$PERSISTENT_FACTORY_ADDRESS" "scheduler()(address)" --rpc-url "$RITUAL_RPC_URL"
cast call "$PERSISTENT_FACTORY_ADDRESS" "ritualWallet()(address)" --rpc-url "$RITUAL_RPC_URL"
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
    SOVEREIGN_FACTORY_ADDRESS?: `0x${string}`;
    PERSISTENT_FACTORY_ADDRESS?: `0x${string}`;
  }
}
```

## Testnet Faucet

### Web UI
Navigate to `https://faucet.ritualfoundation.org`, connect your wallet or paste your address, and request testnet RITUAL.

### Programmatic (REST API)

For headless/SSH environments, use the faucet API directly:

```bash
# Check faucet info (payout amount, rate limits)
curl https://faucet.ritualfoundation.org/api/info

# Claim testnet RITUAL
curl -X POST https://faucet.ritualfoundation.org/api/claim \
  -H "Content-Type: application/json" \
  -d '{"address": "0xYourAddressHere"}'
```

Rate-limited per address. For larger amounts needed for load testing, reach out via Ritual Discord.

For private/internal testnet deployments, the faucet runs on a deployment-specific endpoint. Consult your chain-deployment-infra configuration for the correct faucet service URL.

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
  id: 1979,
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
  --chain 1979 \
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

When the RPC endpoint is not directly reachable from the browser (internal testnet, IP-restricted, CORS
issues), proxy RPC calls through a hardened Next.js API route. A route that blindly forwards the request
body exposes the upstream as a public JSON-RPC relay.

```typescript
// app/api/rpc/route.ts
import { NextResponse } from 'next/server';

const RPC_URL = process.env.RITUAL_RPC_URL || 'https://rpc.ritualfoundation.org';
const MAX_BODY_BYTES = 100_000;
const ALLOWED_METHODS = new Set([
  'eth_blockNumber', 'eth_call', 'eth_chainId', 'eth_estimateGas',
  'eth_feeHistory', 'eth_gasPrice', 'eth_getBalance', 'eth_getBlockByHash',
  'eth_getBlockByNumber', 'eth_getCode', 'eth_getLogs',
  'eth_getTransactionByHash', 'eth_getTransactionCount',
  'eth_getTransactionReceipt', 'eth_maxPriorityFeePerGas',
]);

function rpcError(status: number, code: number, message: string, id: unknown = null) {
  return NextResponse.json(
    { jsonrpc: '2.0', error: { code, message }, id },
    { status, headers: { 'Cache-Control': 'no-store' } },
  );
}

export async function POST(req: Request) {
  const declaredLength = Number(req.headers.get('content-length') ?? '0');
  if (declaredLength > MAX_BODY_BYTES) return rpcError(413, -32600, 'Request too large');

  const raw = await req.text();
  if (new TextEncoder().encode(raw).byteLength > MAX_BODY_BYTES) {
    return rpcError(413, -32600, 'Request too large');
  }

  let body: unknown;
  try { body = JSON.parse(raw); } catch { return rpcError(400, -32700, 'Parse error'); }
  if (
    !body || Array.isArray(body) || typeof body !== 'object' ||
    (body as any).jsonrpc !== '2.0' || typeof (body as any).method !== 'string'
  ) {
    return rpcError(400, -32600, 'Invalid JSON-RPC request');
  }

  const { method, id = null } = body as { method: string; id?: unknown };
  if (!ALLOWED_METHODS.has(method)) return rpcError(403, -32601, 'Method not allowed', id);

  try {
    const resp = await fetch(RPC_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: raw,
      cache: 'no-store',
      signal: AbortSignal.timeout(10_000),
    });
    return new NextResponse(await resp.text(), {
      status: resp.status,
      headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
    });
  } catch {
    return rpcError(504, -32000, 'RPC upstream unavailable', id);
  }
}
```

Keep batch requests disabled unless every item is validated and the batch length is capped. Add rate
limiting at the CDN/edge layer, and extend `ALLOWED_METHODS` only when the application needs another
method. Never proxy `admin_*`, `debug_*`, `personal_*`, or unlocked-account methods.

Then configure your wagmi/viem transport to use `/api/rpc` instead of the direct RPC URL:

```typescript
const ritualChain = defineChain({
  id: 1979,
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

- [ ] Run `forge verify-contract --chain 1979 --watch --verifier custom --verifier-url "$RITUAL_VERIFIER_URL" --verifier-api-key unused <ADDRESS> <CONTRACT_ID>` and confirm `Pass - Verified`
- [ ] Constructor arguments are correctly encoded (if any)
- [ ] Source code matches the deployed bytecode (Foundry verifier compiles locally and compares)

### RitualWallet Setup

- [ ] Deployer/operator has deposited RITUAL into RitualWallet
- [ ] Deposit amount is sufficient for expected async call volume
- [ ] Lock duration covers the maximum expected execution time (use `100_000n` blocks for development — 5000 blocks is ~29 min on the ~350ms conservative baseline; confirm with `ritual-dapp-block-time`)
- [ ] Deposit is against the **signing EOA**, not just the contract address (async precompile fee checks use the EOA, not `address(this)`)

```typescript
import { formatEther } from 'viem';

const RITUAL_WALLET = '0x532F0dF0896F353d8C3DD8cc134e8129DA2a3948' as const;
const RITUAL_WALLET_ABI = [
  { inputs: [{ name: 'user', type: 'address' }], name: 'balanceOf', outputs: [{ type: 'uint256' }], stateMutability: 'view', type: 'function' },
] as const;

const balance = await publicClient.readContract({
  address: RITUAL_WALLET,
  abi: RITUAL_WALLET_ABI,
  functionName: 'balanceOf',
  args: [deployerAddress],
});
console.log('RitualWallet balance:', formatEther(balance), 'RITUAL');
```

### Executor Availability

- [ ] Executors with required capabilities are registered and online
- [ ] Tested with a sample request to confirm executor responds

```typescript
const TEE_SERVICE_REGISTRY = '0x9644e8562cE0Fe12b4deeC4163c064A8862Bf47F' as const;
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
          { name: 'publicKey', type: 'bytes' },
          { name: 'endpoint', type: 'string' },
          { name: 'certPubKeyHash', type: 'bytes32' },
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

- [ ] Chain ID 1979 is configured in wagmi/viem
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

**Cause**: Contract addresses were hardcoded directly in source files (e.g., `const FACTORY = '0xabc...'`). After redeployment, the address changes but the source code still points to the old one.

**Solution**: Always read deployed contract addresses from environment variables, with an optional fallback for local development:

```typescript
// lib/addresses.ts
import { type Address } from 'viem';

// Always read from environment — never hardcode deployment-specific addresses
export const FACTORY_ADDRESS = (
  process.env.NEXT_PUBLIC_FACTORY_ADDRESS ?? '0x0000000000000000000000000000000000000000'
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
NEXT_PUBLIC_FACTORY_ADDRESS=0x1234...actual_deployed_address
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
if (!process.env.NEXT_PUBLIC_FACTORY_ADDRESS) {
  console.warn(
    'NEXT_PUBLIC_FACTORY_ADDRESS not set — contract reads will fail. ' +
    'Run the deploy script and update .env.local with the new address.'
  );
}
```

### "No executors found" Error

The TEEServiceRegistry has no services registered for the requested capability.

```typescript
const HTTP_CALL_CAPABILITY = 0;

const services = await publicClient.readContract({
  address: '0x9644e8562cE0Fe12b4deeC4163c064A8862Bf47F',
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

Async calls fail if your RitualWallet deposit is too low or not locked.

```typescript
import { parseEther } from 'viem';

const RITUAL_WALLET = '0x532F0dF0896F353d8C3DD8cc134e8129DA2a3948' as const;
const DEPOSIT_ABI = [
  { inputs: [{ name: 'lockDuration', type: 'uint256' }], name: 'deposit', outputs: [], stateMutability: 'payable', type: 'function' },
] as const;

// Deposit 5 RITUAL, locked for 500 blocks
const hash = await walletClient.writeContract({
  address: RITUAL_WALLET,
  abi: DEPOSIT_ABI,
  functionName: 'deposit',
  args: [5000n],
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

  if (chainId !== 1979) {
    return (
      <button onClick={() => switchChain({ chainId: 1979 })}>
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
- **`ritual-dapp-wallet`** — RitualWallet deposit, locking, and fee management
- **`ritual-dapp-testing`** — Testing and debugging Ritual dApps

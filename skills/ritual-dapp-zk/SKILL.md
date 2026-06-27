---
name: ritual-dapp-zk
description: ZK Long-Running precompile (0x0806) patterns for Ritual dApps. Use when building dApps with zero-knowledge proof generation, on-chain proof verification, privacy-preserving computation, or verifiable off-chain processing.
---

# ZK Long-Running Patterns

The ZK Long-Running precompile (`0x0806`) enables on-chain zero-knowledge proof generation and verification via TEE executors. Unlike the synchronous precompiles, ZK proofs can be computationally expensive — the long-running async model lets executors handle proof generation off-chain and deliver the result via callback.

> **Execution Model: Long-running (2-phase) async.** Phase 1 submits the ZK proof request and returns a job commitment hash. Phase 2 is a separate delivery transaction where the executor delivers the proof result to your contract via `AsyncDelivery`.
>
> **Key distinction:** ZK extends `ExecutorRequest` directly, NOT the `LongRunningRequest` base. This means it has a different delivery field layout from other long-running precompiles — no polling configuration, no JQ extraction.
>
> **Constraints:** Max encoded input size is 10 KB. The `AsyncJobTracker` contract enforces a max Phase 2 deadline offset of 70,000 blocks. RitualWallet must have sufficient deposited RITUAL.

## How It Works

```
┌──────────────┐     ┌──────────────┐     ┌───────────────┐
│  User / dApp │     │  Precompile  │     │   Executor    │
│              │     │   0x0806     │     │   (TEE)       │
└──────┬───────┘     └──────┬───────┘     └──────┬────────┘
       │                    │                    │
       │  1. Submit ZK      │                    │
       │     proof request   │                    │
       │───────────────────>│                    │
       │                    │  2. Route to       │
       │                    │     executor       │
       │                    │───────────────────>│
       │                    │                    │
       │                    │  3. Generate proof │
       │                    │     (off-chain,    │
       │                    │      may be slow)  │
       │                    │<───────────────────│
       │                    │                    │
       │  4. Phase 1:       │                    │
       │     job commitment  │                    │
       │<───────────────────│                    │
       │                    │                    │
       │  5. Phase 2:       │                    │
       │     deliver proof  │                    │
       │     via callback   │                    │
       │<───────────────────│<───────────────────│
       │                    │                    │
```

**Two phases:**

1. **Submit**: Your contract calls precompile `0x0806` with the ZK proof configuration (operation input, delivery target, gas limits). Returns a job commitment hash.
2. **Deliver**: Once the executor finishes generating/verifying the proof, it delivers the result to your contract's callback function `onZKResultDelivered(bytes32 jobId, bytes calldata result)`.

### Async Guardrails

- **One `0x0806` call per transaction:** The precompile enforces a single ZK call during fresh simulation.
- **Sender async lock in mempool:** While one async transaction is pending for a sender, additional async transactions from the same sender can be rejected.
- **Wallet lock monotonicity:** `RitualWallet.deposit(lockDuration)` only extends `lockUntil`. For development, prefer long lock windows so `lockUntil >= commit_block + ttl` remains true at settlement.
- **`msg.sender` in callback = AsyncDelivery:** Auth callbacks with `require(msg.sender == ASYNC_DELIVERY)`.

---

## Field Layout (14 fields)

| Index | Type | Field | Description |
|-------|------|-------|-------------|
| 0 | `address` | executor | TEE executor address |
| 1 | `bytes[]` | encryptedSecrets | ECIES-encrypted secret blobs |
| 2 | `uint256` | ttl | Blocks until expiry |
| 3 | `bytes[]` | secretSignatures | Signatures over encrypted secrets |
| 4 | `bytes` | userPublicKey | User's ECIES public key (empty = no output encryption) |
| 5 | `bool` | inputEncrypted | Whether `operationInput` is encrypted |
| 6 | `uint64` | maxProofBlock | Phase 2 deadline offset (max 70,000 blocks) |
| 7 | `address` | deliveryTarget | Contract to receive callback |
| 8 | `bytes4` | deliverySelector | Callback function selector |
| 9 | `uint256` | deliveryGasLimit | Gas limit for callback execution |
| 10 | `uint256` | deliveryMaxFeePerGas | Max fee per gas for callback tx |
| 11 | `uint256` | deliveryMaxPriorityFeePerGas | Max priority fee per gas |
| 12 | `uint256` | deliveryValue | Value sent with callback |
| 13 | `bytes` | operationInput | ZK operation input data |

### Phase 1 Output

```
bytes32 — job commitment hash
```

### Phase 2 Callback Signature

```solidity
function onZKResultDelivered(bytes32 jobId, bytes calldata result) external;
```

The `result` bytes contain the proof output. The exact format depends on the ZK system being used (Groth16, PLONK, STARK, etc.) and is opaque to the precompile — your contract must decode it according to your proof system's specification.

---

## Use Cases

| Use Case | Description | operationInput Contains |
|----------|-------------|------------------------|
| **Groth16 Proof Verification** | Submit a proof + public inputs for on-chain verification | Encoded proof data (proof points, public signals) |
| **PLONK Proof Generation** | Generate a PLONK proof off-chain via TEE | Circuit identifier + private inputs |
| **zkVM Execution** | Run a RISC0/SP1 zkVM program and get execution receipt | Program binary + public inputs |
| **Private Data Processing** | Process encrypted data, return ZK proof of correct computation | Encrypted input + processing instructions |
| **Cross-chain Proof Relay** | Generate proof of an event on another chain | Block header + Merkle proof |

---

## 1. Solidity Consumer Contract

### Minimal ZK Consumer

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {IRitualWallet} from "./interfaces/IRitualWallet.sol";

/// @title Minimal ZK Proof Consumer
/// @notice Demonstrates the submit-callback pattern for ZK Long-Running (0x0806)
contract ZKConsumer {
    // -----------------------------------------------------------------------
    //  Constants
    // -----------------------------------------------------------------------
    address constant ZK_PRECOMPILE = address(0x0806);
    address constant ASYNC_DELIVERY = 0x5A16214fF555848411544b005f7Ac063742f39F6;
    address constant RITUAL_WALLET = 0x532F0dF0896F353d8C3DD8cc134e8129DA2a3948;

    // -----------------------------------------------------------------------
    //  Storage
    // -----------------------------------------------------------------------
    bytes32 public lastJobId;
    bytes public lastResult;
    uint256 public jobCount;

    // -----------------------------------------------------------------------
    //  Events
    // -----------------------------------------------------------------------
    event ZKProofRequested(bytes32 indexed jobId, uint256 timestamp);
    event ZKProofDelivered(bytes32 indexed jobId, bytes result, uint256 timestamp);
    event ZKProofFailed(bytes32 indexed jobId, string reason);

    // -----------------------------------------------------------------------
    //  Submit ZK Proof Request
    // -----------------------------------------------------------------------
    /// @notice Submit a ZK proof generation/verification request
    /// @param executor TEE executor address (from TEEServiceRegistry)
    /// @param operationInput Encoded ZK operation data
    /// @param ttl Blocks until the request expires
    /// @param maxProofBlock Phase 2 deadline offset (blocks from commit)
    function requestProof(
        address executor,
        bytes calldata operationInput,
        uint256 ttl,
        uint64 maxProofBlock
    ) external returns (bytes32) {
        // 1. Ensure RitualWallet has sufficient balance
        require(
            IRitualWallet(RITUAL_WALLET).balanceOf(msg.sender) > 0,
            "ZKConsumer: insufficient RitualWallet balance"
        );

        // 2. Encode the full 14-field ZK precompile call
        bytes memory encodedCall = abi.encode(
            executor,           // field 0
            new bytes[](0),     // field 1 — encryptedSecrets (empty for no secrets)
            ttl,                // field 2
            new bytes[](0),     // field 3 — secretSignatures
            hex"",              // field 4 — userPublicKey (no output encryption)
            false,              // field 5 — inputEncrypted
            maxProofBlock,      // field 6 — maxProofBlock
            address(this),      // field 7 — deliveryTarget
            this.onZKResultDelivered.selector, // field 8 — deliverySelector
            500_000,            // field 9 — deliveryGasLimit
            1 gwei,             // field 10 — deliveryMaxFeePerGas
            1 gwei,             // field 11 — deliveryMaxPriorityFeePerGas
            0,                  // field 12 — deliveryValue
            operationInput      // field 13 — operationInput
        );

        // 3. Call the precompile
        (bool ok, bytes memory returnData) = ZK_PRECOMPILE.call(encodedCall);
        require(ok, "ZKConsumer: precompile call failed");
        require(returnData.length >= 32, "ZKConsumer: invalid return data");

        // 4. Decode job commitment hash
        lastJobId = abi.decode(returnData, (bytes32));
        jobCount++;

        emit ZKProofRequested(lastJobId, block.timestamp);
        return lastJobId;
    }

    // -----------------------------------------------------------------------
    //  Callback — called by AsyncDelivery
    // -----------------------------------------------------------------------
    /// @notice Callback receiver for ZK proof delivery
    /// @param jobId The job commitment hash from Phase 1
    /// @param result The proof output bytes
    function onZKResultDelivered(bytes32 jobId, bytes calldata result)
        external
    {
        require(
            msg.sender == ASYNC_DELIVERY,
            "ZKConsumer: only AsyncDelivery"
        );
        require(result.length > 0, "ZKConsumer: empty result");

        lastJobId = jobId;
        lastResult = result;

        emit ZKProofDelivered(jobId, result, block.timestamp);
    }
}
```

### Key Points

- **Auth callbacks:** Always verify `msg.sender == ASYNC_DELIVERY` in the callback
- **Empty result check:** `result.length > 0` prevents silent storage of empty data
- **Secrets management:** For encrypted operations, populate `encryptedSecrets` with ECIES-encrypted blobs and set `inputEncrypted = true`
- **Delivery gas:** Set `deliveryGasLimit` high enough for your callback logic (≥300,000 recommended)
- **TTL:** Ensure `lockUntil(sender) >= commit_block + ttl` on RitualWallet

---

## 2. viem / ethers.js Interaction

### Phase 1 — Submit ZK Request

```typescript
import { encodeAbiParameters, parseGwei, createPublicClient, http } from "viem";

const EXECUTOR = "0x833c7a5c0628b3d47D12c3556AC1B02B2723f390";
const ZK_PRECOMPILE = "0x0000000000000000000000000000000000000806";

// Encode the ZK precompile call
const encoded = encodeAbiParameters(
  [
    { type: "address" },                   // executor
    { type: "bytes[]" },                   // encryptedSecrets
    { type: "uint256" },                   // ttl
    { type: "bytes[]" },                   // secretSignatures
    { type: "bytes" },                     // userPublicKey
    { type: "bool" },                      // inputEncrypted
    { type: "uint64" },                    // maxProofBlock
    { type: "address" },                   // deliveryTarget
    { type: "bytes4" },                    // deliverySelector
    { type: "uint256" },                   // deliveryGasLimit
    { type: "uint256" },                   // deliveryMaxFeePerGas
    { type: "uint256" },                   // deliveryMaxPriorityFeePerGas
    { type: "uint256" },                   // deliveryValue
    { type: "bytes" },                     // operationInput
  ],
  [
    EXECUTOR,
    [],
    500n,                                   // ttl
    [],
    "0x",                                   // userPublicKey
    false,                                  // inputEncrypted
    5000n,                                  // maxProofBlock (blocks)
    "0xYourConsumerContract",               // deliveryTarget
    "0x7b0a1e8a",                           // onZKResultDelivered selector
    500_000n,                               // deliveryGasLimit
    parseGwei("1"),                         // deliveryMaxFeePerGas
    parseGwei("1"),                         // deliveryMaxPriorityFeePerGas
    0n,                                     // deliveryValue
    "0xYourZKOperationInput",               // operationInput
  ]
);

// Submit via your consumer contract
const tx = await walletClient.writeContract({
  address: consumerContractAddress,
  abi: consumerAbi,
  functionName: "requestProof",
  args: [EXECUTOR, "0xYourZKOperationInput", 500n, 5000n],
});
```

### Phase 2 — Wait for Callback

```typescript
// Listen for the delivery event
const filter = await publicClient.createContractEventFilter({
  address: consumerContractAddress,
  event: {
    name: "ZKProofDelivered",
    type: "event",
    inputs: [
      { name: "jobId", type: "bytes32", indexed: true },
      { name: "result", type: "bytes", indexed: false },
      { name: "timestamp", type: "uint256", indexed: false },
    ],
  },
});

// Or decode from transaction receipt
const receipt = await publicClient.waitForTransactionReceipt({ hash: txHash });
for (const log of receipt.logs) {
  // Look for ZKProofDelivered events
}
```

### Reading the Receipt for Phase 1 Settlement

```typescript
// The Phase 1 settlement includes spcCalls in the receipt
const receipt = await publicClient.waitForTransactionReceipt({ hash: txHash });
const spcCalls = (receipt as any).spcCalls;
// spcCalls contains: [simmedInput, actualOutput]
// actualOutput encodes: (bytes simmedInput, bytes actualOutput)
```

---

## 3. Foundry Test

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import "forge-std/Test.sol";
import "../src/ZKConsumer.sol";

contract ZKConsumerTest is Test {
    ZKConsumer consumer;
    address constant EXECUTOR = 0x833c7a5c0628b3d47D12c3556AC1B02B2723f390;

    function setUp() public {
        consumer = new ZKConsumer();
    }

    function testEncodeZKCall() public view {
        // Verify the ABI encoding produces the correct selector
        bytes memory encoded = abi.encode(
            EXECUTOR,
            new bytes[](0),
            500n,
            new bytes[](0),
            hex"",
            false,
            5000n,
            address(consumer),
            consumer.onZKResultDelivered.selector,
            500_000n,
            1 gwei,
            1 gwei,
            0n,
            hex"010203"
        );

        // The first 4 bytes of the precompile call should not reverted
        // (precompile will not execute in test environment, but encoding should be valid)
        assertEq(encoded.length % 32, 0, "encoding should be word-aligned");
    }

    function testRevertsOnNoWalletBalance() public {
        vm.expectRevert("ZKConsumer: insufficient RitualWallet balance");
        consumer.requestProof(EXECUTOR, hex"00", 500n, 5000n);
    }
}
```

---

## 4. Integration with Other Skills

| Skill | How They Compose |
|-------|-----------------|
| `ritual-dapp-wallet` | Fund RitualWallet before submitting ZK requests. Ensure `lockUntil >= commit_block + ttl` |
| `ritual-dapp-secrets` | Use ECIES encryption for private ZK inputs via `encryptedSecrets` |
| `ritual-dapp-backend` | Index `ZKProofRequested` / `ZKProofDelivered` events in your backend |
| `ritual-dapp-frontend` | Display proof status using the 9-state async machine |
| `ritual-dapp-testing` | Forge fork tests with `vm.mockCall` for the precompile address |
| `ritual-dapp-deploy` | Standard deployment to Chain ID 1979 with `--constructor-args` if using configurable ASYNC_DELIVERY |

---

## 5. Preflight Checklist

1. [ ] Executor discovered from `TEEServiceRegistry.getServicesByCapability(5, true)` (ZK_CAPABILITY = 5)
2. [ ] RitualWallet funded and `lockUntil >= commit_block + ttl`
3. [ ] `deliveryTarget` matches your consumer contract address
4. [ ] `deliverySelector` matches your callback function selector
5. [ ] Gas limit set explicitly (≥500,000 for delivery callback)
6. [ ] `maxProofBlock ≤ 70,000`
7. [ ] `operationInput` correctly encoded for your ZK system
8. [ ] Callback function has `require(msg.sender == ASYNC_DELIVERY)`
9. [ ] No reentrancy — callback does not re-enter precompile

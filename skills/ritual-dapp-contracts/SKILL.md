---
name: ritual-dapp-contracts
description: Ritual chain precompile addresses, system contracts, ABI encoding, and callback security. Use when writing Solidity contracts that call Ritual precompiles, handle async callbacks, or interact with the Scheduler and RitualWallet.
---

# Ritual Smart Contract Development

## Execution Models

Ritual precompiles use one of three execution models. The full precompile list is in the table below — this section covers how each model works so you know what your contract needs.

| | Synchronous | Async (short-running) | Async (long-running) |
|---|---|---|---|
| How it works | Call returns result in the same transaction | Transaction is deferred until the TEE executor's result is available, then re-executed with the result injected into the precompile (fulfilled replay) — looks synchronous from your contract's perspective | Phase 1: returns a task ID, settles fees, releases nonce. Phase 2: executor delivers result via callback in a separate tx |
| RitualWallet deposit | No | Yes — lock must cover `commit_block + ttl` | Yes — lock must cover `commit_block + ttl` |
| Executor from TEEServiceRegistry | No | Yes | Yes |
| Callback function | No | No | Yes — guarded by `msg.sender == ASYNC_DELIVERY` with sufficient `deliveryGasLimit` |
| Sender nonce lock | None | Until settlement | Until Phase 1 settlement |
| Output delivery | Same call | Transaction receipt `spcCalls` field | Separate callback tx |
| Output format | Precompile-specific | `abi.decode(raw, (bytes simmedInput, bytes actualOutput))` | Precompile-specific, delivered to your callback |

## System Contracts

| Contract | Address |
|---|---|
| RitualWallet | `0x532F0dF0896F353d8C3DD8cc134e8129DA2a3948` |
| AsyncJobTracker | `0xC069FFCa0389f44eCA2C626e55491b0ab045AEF5` |
| AsyncDelivery | `0x5A16214fF555848411544b005f7Ac063742f39F6` |
| TEEServiceRegistry | `0x9644e8562cE0Fe12b4deeC4163c064A8862Bf47F` |
| Scheduler | `0x56e776BAE2DD60664b69Bd5F865F1180ffB7D58B` |
| SecretsAccessControl | `0xf9BF1BC8A3e79B9EBeD0fa2Db70D0513fecE32FD` |

## Agent Factory Contracts

| Contract | Address |
|---|---|
| SovereignAgentFactory | `0x9dC4C054e53bCc4Ce0A0Ff09E890A7a8e817f304` |
| PersistentAgentFactory | `0xD4AA9D55215dc8149Af57605e70921Ea16b73591` |

Preflight before launch:

```bash
cast code "0x9dC4C054e53bCc4Ce0A0Ff09E890A7a8e817f304" --rpc-url "$RPC_URL"
cast code "0xD4AA9D55215dc8149Af57605e70921Ea16b73591" --rpc-url "$RPC_URL"
```

## Precompile Addresses

| Address | Name | Type | ABI Fields | Skill |
|---|---|---|---|---|
| `0x0800` | ONNX ML Inference | Synchronous | 7 | `ritual-dapp-onnx` |
| `0x0801` | HTTP Call | Async (short-running) | 13 | `ritual-dapp-http` |
| `0x0802` | LLM Call | Async (short-running) | 30 | `ritual-dapp-llm` |
| `0x0803` | JQ JSON Query | Synchronous | 3 | `ritual-dapp-http` §7 |
| `0x0805` | Long-Running HTTP | Async (long-running) | 35 | `ritual-dapp-longrunning` |
| `0x0806` | ZK Long-Running | Async (long-running) | 14 | — |
| `0x0807` | FHE/CKKS Inference | Async (long-running) | 19 | — |
| `0x080C` | Sovereign Agent | Async (long-running) | 23 | `ritual-dapp-agents` |
| `0x0818` | Image Generation | Async (long-running) | 18 | `ritual-dapp-multimodal` |
| `0x0819` | Audio Generation | Async (long-running) | 18 | `ritual-dapp-multimodal` |
| `0x081A` | Video Generation | Async (long-running) | 18 | `ritual-dapp-multimodal` |
| `0x081B` | DKMS Key Derivation | Async | 8 | — |
| `0x0820` | Persistent Agent | Async (long-running) | 26 | `ritual-dapp-agents` |
| `0x0009` | Ed25519 Verify | Synchronous | 3 | `ritual-dapp-ed25519` |
| `0x0100` | SECP256R1/P-256 | Synchronous | 3 | `ritual-dapp-passkey` |
| `0x0830` | TX Hash | Synchronous | 0 (any input) | — |

---

## Interfaces

### IRitualWallet

```solidity
interface IRitualWallet {
    function deposit(uint256 lockDuration) external payable;
    function depositFor(address user, uint256 lockDuration) external payable;
    function withdraw(uint256 amount) external;
    function balanceOf(address account) external view returns (uint256);
    function lockUntil(address account) external view returns (uint256);
}
```

There is no `lockedBalanceOf`. There is no `emergencyWithdraw`. `lockUntil` returns a block number, not a balance. Lock is monotonic — new deposits only extend, never shorten. See `ritual-dapp-wallet` for deposit sizing, lock duration guidance, and EOA vs contract deposit semantics.

### IScheduler

```solidity
interface IScheduler {
    function schedule(
        bytes memory data,
        uint32 gas,
        uint32 startBlock,
        uint32 numCalls,
        uint32 frequency,
        uint32 ttl,
        uint256 maxFeePerGas,
        uint256 maxPriorityFeePerGas,
        uint256 value,
        address payer
    ) external returns (uint256 callId);

    function schedule(
        bytes memory data,
        uint32 gas,
        uint32 numCalls,
        uint32 frequency
    ) external returns (uint256 callId);

    function cancel(uint256 callId) external;
    function getCallState(uint256 callId) external view returns (uint8);
    function approveScheduler(address schedulerContract) external;
    function revokeScheduler(address schedulerContract) external;
}
```

The Scheduler always calls back `msg.sender` — there is no `target` parameter. Only contracts can schedule (not EOAs). Returns `uint256`, not `bytes32`. The first `uint256` parameter of your callback (bytes 4–35) is overwritten with the real `executionIndex` at execution time. See `ritual-dapp-scheduler` for full usage patterns, predicate scheduling, and TTL sizing.

CallState: SCHEDULED=0, EXECUTING=1, COMPLETED=2, CANCELLED=3, EXPIRED=4.

### ITEEServiceRegistry

```solidity
interface ITEEServiceRegistry {
    struct TEEServiceNode {
        address paymentAddress;
        address teeAddress;
        uint8 teeType;
        bytes publicKey;
        string endpoint;
        bytes32 certPubKeyHash;
        uint8 capability;
    }

    struct TEEServiceContext {
        TEEServiceNode node;
        bool isValid;
        bytes32 workloadId;
    }

    function getServicesByCapability(
        uint8 capability,
        bool checkValidity
    ) external view returns (TEEServiceContext[] memory);

    function getService(address addr, bool checkValidity)
        external
        view
        returns (TEEServiceContext memory);

    function getCapabilityIndexStatus()
        external
        view
        returns (uint256 cursor, uint256 total, bool initialized, bool finalized);

    function getIndexedServiceCountByCapability(uint8 capability)
        external
        view
        returns (uint256 count);

    function getIndexedServiceByCapabilityAt(uint8 capability, uint256 index)
        external
        view
        returns (address teeAddress);

    function pickServiceByCapability(
        uint8 capability,
        bool checkValidity,
        uint256 seed,
        uint256 maxProbes
    ) external view returns (address teeAddress, bool found);
}
```

Capabilities: HTTP_CALL=0, LLM=1, WORMHOLE_QUERY=2, STREAMING=3, VLLM_PROXY=4, ZK_CALL=5, DKMS=6, IMAGE_CALL=7, AUDIO_CALL=8, VIDEO_CALL=9, FHE=10. Agent precompiles route through HTTP_CALL (0) — see `ritual-dapp-agents` for details.

**Executor selection pattern:** do **not** hardcode executor `teeAddress` constants as a default production pattern.

Use indexed capability APIs when `getCapabilityIndexStatus().finalized == true`:

1. `pickServiceByCapability(capability, true, seed, maxProbes)` for bounded random selection.
2. If needed, iterate with `getIndexedServiceCountByCapability` + `getIndexedServiceByCapabilityAt`.
3. Fallback to `getServicesByCapability(...)` only when indexed state is not finalized.

If your contract stores executor preferences, make them updatable and validate against registry results.

### AsyncJobTracker (read-only)

AsyncJobTracker (`0xC069FFCa0389f44eCA2C626e55491b0ab045AEF5`) is a system contract — the block builder and executors write to it, dApps only read from it. Full ABI is verified on the [block explorer](https://explorer.ritualfoundation.org/address/0xC069FFCa0389f44eCA2C626e55491b0ab045AEF5). The two things you need from it: **watch events** (for indexing) and **check sender lock** (before submitting).

**Events:**

```solidity
event JobAdded(
    address indexed executor,
    bytes32 indexed jobId,
    address indexed precompileAddress,
    uint256 commitBlock,
    bytes precompileInput,
    address senderAddress,
    bytes32 previousBlockHash,
    uint256 previousBlockNumber,
    uint256 previousBlockTimestamp,
    uint256 ttl,
    uint256 createdAt
);

event Phase1Settled(bytes32 indexed jobId, address indexed executor, uint256 settledBlock);
event ResultDelivered(bytes32 indexed jobId, address indexed target, bool success);
event JobRemoved(address indexed executor, bytes32 indexed jobId, bool indexed completed);
```

**View functions:**

```solidity
function hasPendingJobForSender(address sender) external view returns (bool);
function isLongRunning(bytes32 jobId) external view returns (bool);
function isPhase1Settled(bytes32 jobId) external view returns (bool);
```

`hasPendingJobForSender` is the canonical sender lock check — call it before submitting any async transaction. `isLongRunning` tells you if a job uses long-running async delivery. `isPhase1Settled` tells you if Phase 1 settlement happened (long-running async only).

There is also `getJob(bytes32) returns (Job memory, bytes memory, bytes memory)` which returns a 14-field struct for advanced status reconciliation. The `Job` struct has `commitBlock` and `ttl` fields — compute expiry as `commitBlock + ttl` (there is no `expiryBlock` field or getter). For short-running async precompiles (HTTP, LLM, DKMS), settlement removes the job and `getJob` reverts with "not found". See `ritual-dapp-backend` for the full polling pattern.

---

## ABI Encoding Reference

### HTTP Methods (used by 0x0801, 0x0805)

GET=1, POST=2, PUT=3, DELETE=4, PATCH=5, HEAD=6, OPTIONS=7. Method code 0 is invalid and rejected at the RPC level.

### Short-Running Async Output Envelope

All short-running async precompiles (0x0801, 0x0802) return a two-layer envelope:

```solidity
(bytes memory simmedInput, bytes memory actualOutput) = abi.decode(raw, (bytes, bytes));
```

The inner `actualOutput` is precompile-specific. For HTTP (5 fields):

```solidity
(uint16 statusCode, string[] headerKeys, string[] headerValues, bytes body, string errorMessage)
```

### Long-Running Async Base Fields

All long-running async precompiles share these base fields at the start of their ABI:

| Field | Type | Description |
|---|---|---|
| executor | address | TEE executor from registry |
| encryptedSecrets | bytes[] | ECIES-encrypted secrets (or empty) |
| ttl | uint256 | Max blocks for Phase 1 settlement (1–500) |
| secretSignatures | bytes[] | EIP-191 signatures over encrypted secrets |
| userPublicKey | bytes | 65-byte uncompressed secp256k1 key (or empty) |

Followed by precompile-specific polling config, delivery config, and payload fields. See each precompile's skill for the complete ABI layout.

### Trailing Fields (HTTP, Long-Running HTTP)

HTTP (0x0801) and Long-Running HTTP (0x0805) append these fields after the core request:

| Field | Type | Description |
|---|---|---|
| dkmsKeyIndex | uint256 | Key index for dKMS derivation (0 = disabled) |
| dkmsKeyFormat | uint8 | Key format (0 = disabled, 1 = Eth/secp256k1) |
| piiEnabled | bool | Enable PII redaction (independent of dKMS) |

`dkmsKeyIndex` and `dkmsKeyFormat` control dKMS key derivation. `piiEnabled` controls PII redaction and is independent of dKMS. Always encode all 13 fields for HTTP and all 35 fields for Long-Running HTTP — set unused fields to zero.

---

## Callback Security

All long-running async callbacks are delivered by the AsyncDelivery contract. Always verify `msg.sender`,
but do not stop there: that check authenticates the delivery transport, not the job. A caller can choose a
`deliveryTarget` and `deliverySelector` in its own request, so a contract that accepts every callback from
AsyncDelivery can still process a result for a job it never submitted.

Record the current transaction hash before calling the long-running precompile. The callback `jobId` is that
hash, so the contract can reject unknown jobs and consume each expected callback exactly once.

```solidity
address constant ASYNC_DELIVERY = 0x5A16214fF555848411544b005f7Ac063742f39F6;
address constant TX_HASH_PRECOMPILE = address(0x0830);

mapping(bytes32 => bool) public pendingJobs;

modifier onlyAsyncDelivery() {
    require(msg.sender == ASYNC_DELIVERY, "only async delivery");
    _;
}

function _trackCurrentJob() internal returns (bytes32 jobId) {
    (bool ok, bytes memory output) = TX_HASH_PRECOMPILE.staticcall("");
    require(ok && output.length == 32, "tx hash unavailable");
    jobId = abi.decode(output, (bytes32));
    require(!pendingJobs[jobId], "job already pending");
    pendingJobs[jobId] = true;
}

function onResult(bytes32 jobId, bytes calldata result) external onlyAsyncDelivery {
    require(pendingJobs[jobId], "unknown or fulfilled job");
    delete pendingJobs[jobId]; // effects before processing or external calls
    // process result
}
```

Call `_trackCurrentJob()` immediately before the long-running precompile call, and encode
`address(this)` plus the matching callback selector into the delivery configuration. Also apply the
application's access control to the submission function; pending-job tracking proves that the job passed
through this contract, not that every caller was authorized to create it.

### Escape Hatch for Stuck State

Async callbacks are NOT guaranteed. If an executor fails or TTL expires, the callback never fires. Never gate user actions on async state without a timeout:

```solidity
uint256 public constant PENDING_TTL = 500;

function _checkAutoExpiry(address user) internal {
    if (hasPending[user] && block.number > pendingBlock[user] + PENDING_TTL) {
        hasPending[user] = false;
    }
}
```

---

## Error Handling

**Synchronous precompiles** (ONNX, JQ, Ed25519, SECP256R1): errors revert the transaction. Use try/catch.

**Short-running async** (HTTP, LLM): the transaction settles even if the executor hit an error. Check the output:
```solidity
(uint16 statusCode, , , bytes memory body, string memory err) = abi.decode(
    output, (uint16, string[], string[], bytes, string)
);
if (bytes(err).length > 0) { /* executor error */ }
if (statusCode >= 400) { /* HTTP error */ }
```

**Two-phase async** (Agent, Long HTTP, etc.): Phase 1 returns a task ID. Phase 2 delivers via callback. If the callback reverts, `AsyncDelivery` emits `DeliveryFailed(bytes32 jobId, address user, string reason)`.

---

## Testing

### Foundry Unit Tests

```solidity
import "forge-std/Test.sol";

contract ConsumerTest is Test {
    address constant ASYNC_DELIVERY = 0x5A16214fF555848411544b005f7Ac063742f39F6;

    function test_callbackOnlyFromDelivery() public {
        AgentConsumer consumer = new AgentConsumer();
        bytes32 jobId = keccak256("test");
        bytes memory result = abi.encode(uint8(1), true, "hello", "", uint16(1), uint16(0), "");

        vm.prank(address(0xdead));
        vm.expectRevert("only async delivery");
        consumer.onAgentResult(jobId, result);

        vm.prank(ASYNC_DELIVERY);
        consumer.onAgentResult(jobId, result);
        assertTrue(consumer.fulfilled(jobId));
    }

    function test_idempotentCallback() public {
        AgentConsumer consumer = new AgentConsumer();
        bytes32 jobId = keccak256("test");
        bytes memory result = abi.encode(uint8(1), true, "hello", "", uint16(1), uint16(0), "");

        vm.prank(ASYNC_DELIVERY);
        consumer.onAgentResult(jobId, result);

        vm.prank(ASYNC_DELIVERY);
        vm.expectRevert("already fulfilled");
        consumer.onAgentResult(jobId, result);
    }
}
```

### Mock Precompile Responses

```solidity
function test_mockHTTP() public {
    bytes memory mockOutput = abi.encode(
        uint16(200), new string[](0), new string[](0),
        bytes('{"price":3500}'), ""
    );
    bytes memory mockRaw = abi.encode(bytes(""), mockOutput);

    vm.mockCall(address(0x0801), "", mockRaw);

    (uint16 status, bytes memory body) = consumer.makeGET(
        address(0xE1), "https://api.example.com/price"
    );
    assertEq(status, 200);
}
```

### Fork Testing

```solidity
function setUp() public {
    vm.createSelectFork("https://rpc.ritualfoundation.org");
}

function test_walletDeposit() public {
    IRitualWallet wallet = IRitualWallet(0x532F0dF0896F353d8C3DD8cc134e8129DA2a3948);
    vm.deal(address(this), 1 ether);
    wallet.deposit{value: 0.5 ether}(5000);
    assertEq(wallet.balanceOf(address(this)), 0.5 ether);
}
```

---

## Security Checklist

- [ ] All callback functions have `onlyAsyncDelivery` modifier (`msg.sender == 0x5A16...39F6`)
- [ ] Callbacks are idempotent (check-and-set fulfillment flag before processing)
- [ ] Follows Check-Effects-Interactions pattern
- [ ] Stuck-state escape hatch (TTL-based auto-expiry or admin override)
- [ ] RitualWallet has sufficient balance with lock covering `commit_block + ttl`
- [ ] Executor address fetched from TEEServiceRegistry (not zero address)
- [ ] `deliverySelector` matches the actual callback function's selector
- [ ] `deliveryGasLimit` is sufficient for callback execution
- [ ] HTTP method codes are correct (GET=1, POST=2, PUT=3, DELETE=4, PATCH=5)
- [ ] HTTP encoding has all 13 fields (including `dkmsKeyIndex`, `dkmsKeyFormat`, `piiEnabled`)
- [ ] `receive()` present if contract needs to accept native RITUAL
- [ ] Events emitted for all state changes (for off-chain indexing)

---

## Constraints Quick Reference

| Constraint | Value |
|---|---|
| Block time | ~350ms (conservative baseline) |
| Chain ID | 1979 |
| RPC | `https://rpc.ritualfoundation.org` |
| Max TTL (async commitment) | 500 blocks (~175s, ~2.9m) |
| Min TTL (async commitment) | 1 block |
| Max Phase 2 deadline offset | 70,000 blocks (~6.8h) |
| Max precompile input size | 10 KB |
| Max HTTP response size | 5 KB |
| Max long-running calls per tx | 1 |
| Max async commits per sender per block | 1 |
| Sender lock | Until Phase 1 settlement |
| Scheduler: only contracts can schedule | EOAs cannot call `schedule()` |
| Scheduler: `frequency >= 1` | Required |
| Scheduler: `startBlock > block.number` | Required |
| Scheduler: MAX_TTL | 500 (set at deployment, immutable) |

For timing conversion formulas and measurement preflight on your target RPC, see `ritual-dapp-block-time`.

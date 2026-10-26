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
| RitualWallet deposit | No | Yes — sponsor `availableBalance` (+ `allowance(sponsor, caller)` if delegated) must cover the reserved fees | Yes — sponsor `availableBalance` (+ `allowance(sponsor, caller)` if delegated) must cover the reserved fees |
| Executor from TEEServiceRegistry | No | Yes | Yes |
| Callback function | No | No | Yes — guarded by `msg.sender == ASYNC_DELIVERY` with sufficient `deliveryGasLimit` |
| Sender nonce lock | None | Until settlement | Until Phase 1 settlement |
| Output delivery | Same call | Transaction receipt `spcCalls` field | Separate callback tx |
| Output format | Precompile-specific | `abi.decode(raw, (bytes simmedInput, bytes actualOutput))` | Precompile-specific, delivered to your callback |

## System Contracts

These are the live chain-784 system contracts. On a local network, resolve addresses from the node's generated configuration; verify bytecode either way. Use this skill’s included minimal interfaces for covered operations. Additional methods require a matching verified ABI or versioned deployment artifact; see [ABI retrieval](../../examples/README.md#abi-and-deployment-authority). A private source checkout is not required.

| Contract | Address |
|---|---|
| RitualWallet | `0xF04076756d8129Baec46Dc0F1c526Baec490C393` |
| AsyncJobTracker | `0xf00385449fD961925A0B125F5f30b29B682D4bFb` |
| AsyncDelivery | `0x508f57AE70967Da28AE0Ab6b95532878c4D0F440` |
| TEEServiceRegistry | `0xf4495DC72143D44A93AB0ecE4d6D63a216b27839` |
| Scheduler | `0x4E0abeE2233D73E66382b45244F7459B34E1490E` |
| SecretsAccessControl | `0x0cEae62e2082829226eF5821Bb662483Db17A71F` |
| AgentHeartbeat | `0xDeeA4Df0C958966ED75570a05430BB0D4844a8cc` |
| AgentIdentityRegistry | `0x2cbF50F833a3AEfb5c5B27068052cB5585F5c087` |

## Agent Consumer Contracts

Deploy the application-owned consumers included in [the agent examples](../../examples/README.md). Each compiles locally with minimal public system ABIs and calls `0x080C` or `0x0820` directly. Configure the chain's `AsyncDelivery`, sponsor wallet allowance, secret delegation, and (for persistent agents) identity operator grant. See `ritual-dapp-agents` for the launch sequence.

## Precompile Addresses

| Address | Name | Type | ABI Fields | Skill |
|---|---|---|---|---|
| `0x0801` | HTTP Call | Async (short-running) | 16 | `ritual-dapp-http` |
| `0x0802` | LLM Call | Async (short-running) | 32 | `ritual-dapp-llm` |
| `0x0803` | JQ JSON Query | Synchronous | 3 | `ritual-dapp-http` §7 |
| `0x0805` | Long-Running HTTP | Async (long-running) | 38 | `ritual-dapp-longrunning` |
| `0x0806` | ZK Long-Running | Async (long-running) | 16 | — |
| `0x0807` | FHE/CKKS Inference | Async (long-running) | 21 | — |
| `0x080C` | Sovereign Agent | Async (long-running) | 13-field envelope | `ritual-dapp-agents` |
| `0x0818` | Image Generation | Async (long-running) | 20 | `ritual-dapp-multimodal` |
| `0x0819` | Audio Generation | Async (long-running) | 20 | `ritual-dapp-multimodal` |
| `0x081A` | Video Generation | Async (long-running) | 20 | `ritual-dapp-multimodal` |
| `0x081B` | DKMS Key Derivation | Async | 10 | — |
| `0x0820` | Persistent Agent | Async (long-running) | 13-field envelope | `ritual-dapp-agents` |
| `0x0009` | Ed25519 Verify | Synchronous | 3 | `ritual-dapp-ed25519` |
| `0x0100` | SECP256R1/P-256 | Synchronous | 3 | `ritual-dapp-passkey` |
| `0x0830` | TX Hash | Synchronous | 0 (any input) | — |

---

## Interfaces

### IRitualWallet

```solidity
interface IRitualWallet {
    enum EscrowStatus { NONE, ACTIVE, SETTLED, EXPIRED }

    struct Escrow {
        address sponsor;
        uint256 reserved;
        uint256 paid;
        uint64 expiryBlock;
        EscrowStatus status;
    }

    function deposit() external payable;
    function depositFor(address account) external payable;
    function withdraw(uint256 amount) external;
    function availableBalance(address account) external view returns (uint256);
    function reservedBalance(address account) external view returns (uint256);
    function allowance(address sponsor, address caller) external view returns (uint256);
    function approve(address caller, uint256 amount) external;
    function increaseAllowance(address caller, uint256 amount) external;
    function decreaseAllowance(address caller, uint256 amount) external;
    function escrows(bytes32 escrowId) external view returns (Escrow memory);
}
```

There is no `emergencyWithdraw`. There is no lock — deposits are immediately available; the balance getter is `availableBalance`. Accounting is two-bucket: `availableBalance(account)` is spendable now, `reservedBalance(account)` is what active escrows hold. To let a consumer contract reserve funds on your behalf, grant a sponsor→caller allowance with `approve(caller, amount)` (read it back via `allowance(sponsor, caller)`; `type(uint256).max` is infinite and never decremented); per-job escrow state lives in `escrows(escrowId)`. This is not an exhaustive list of the V2 surface — `increaseAllowance`/`decreaseAllowance` and the escrow accessors also exist. See `ritual-dapp-wallet` for deposit sizing, allowance guidance, and EOA vs contract deposit semantics.

### IAgentIdentityRegistry / AgentIdentityRegistry

AgentIdentityRegistry (`0x2cbF50F833a3AEfb5c5B27068052cB5585F5c087`) is the canonical on-chain source of agent-id ownership and operator delegation. A chain-issued `agentId` is required to spawn a Persistent Agent (0x0820) — see `ritual-dapp-agents`.

```solidity
interface IAgentIdentityRegistry {
    struct AgentIdentity {
        uint256 agentId;
        address owner;
    }

    function getIdentity(uint256 agentId) external view returns (AgentIdentity memory);
    function ownerOf(uint256 agentId) external view returns (address);
}

// Full AgentIdentityRegistry surface (beyond the IAgentIdentityRegistry read subset):
//   function allocateAgentId(address identityOwner) external returns (uint256 agentId);
//   function agentIdsOf(address identityOwner) external view returns (uint256[] memory);
//   function getOwnerAgentIds(address identityOwner) external view returns (uint256[] memory);
//   function exists(uint256 agentId) external view returns (bool);
//   function setAgentOperator(uint256 agentId, address operator, bool approved) external;
//   function isAgentOperator(uint256 agentId, address operator) external view returns (bool);
//   uint256 public nextAgentId;
//   event AgentIdAllocated(uint256 indexed agentId, address indexed owner, address indexed allocator);
//   event AgentOperatorSet(uint256 indexed agentId, address indexed operator, bool approved);
//   errors: InvalidOwner, InvalidOperator, IdentityOwnerMismatch, NotAgentOwner, UnknownAgentId
```

`allocateAgentId` requires `identityOwner == msg.sender` (else reverts `IdentityOwnerMismatch`) and allocates `++nextAgentId`. Operator delegation (`setAgentOperator`) grants *action-initiation* authority only — `operator == address(0)` is rejected with `InvalidOperator`, and the DKMS derivation principal always stays the owner (keyed by `agentId`).

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
        address sponsor
    ) external returns (uint256 callId);

    function schedule(
        bytes memory data,
        uint32 gas,
        uint32 numCalls,
        uint32 frequency
    ) external returns (uint256 callId);

    function cancel(uint256 callId) external;
    function getCallState(uint256 callId) external view returns (uint8);
}
```

The Scheduler always calls back `msg.sender` — there is no `target` parameter. Only contracts can schedule (not EOAs). Returns `uint256`, not `bytes32`. The first `uint256` parameter of your callback (bytes 4–35) is overwritten with the real `executionIndex` at execution time. There is no `approveScheduler`/`revokeScheduler` — to authorize a `sponsor != msg.sender`, the sponsor calls `RitualWallet.approve(scheduledConsumer, amount)` (the same unified allowance used by async precompiles); revoke by lowering it via `approve(caller, 0)` / `decreaseAllowance(caller, amount)`. See `ritual-dapp-scheduler` for full usage patterns, predicate scheduling, and TTL sizing.

CallState: SCHEDULED=0, EXECUTING=1, COMPLETED=2, CANCELLED=3, EXPIRED=4.

### ITEEServiceRegistry

```solidity
interface ITEEServiceRegistry {
    struct TEEServiceNode {
        address paymentAddress;
        address teeAddress;
        uint8 teeType;
        bytes executorSecretsAuthPublicKey;
        string endpoint;
        bytes32 mTlsSpkiHash;
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

AsyncJobTracker (`0xf00385449fD961925A0B125F5f30b29B682D4bFb`) is a system contract — the block builder and executors write to it, dApps only read from it. Full ABI is verified on the [block explorer](https://explorer.ritualfoundation.org/address/0xf00385449fD961925A0B125F5f30b29B682D4bFb). The two things you need from it: **watch events** (for indexing) and **check the tx-origin nonce lock** (before submitting).

**Events:**

```solidity
event JobAdded(
    address indexed executor,
    bytes32 indexed jobId,
    address indexed precompileAddress,
    uint256 commitBlock,
    bytes precompileInput,
    address callerAddress,
    address txOrigin,
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
function hasPendingJobForTxOrigin(address txOrigin) external view returns (bool);
function isLongRunning(bytes32 jobId) external view returns (bool);
function isPhase1Settled(bytes32 jobId) external view returns (bool);
```

`hasPendingJobForTxOrigin` is the canonical nonce-lock check, keyed on `txOrigin` (== the EOA signer for ordinary user txs; system txs set `txOrigin = 0` and are exempt) — call it before submitting any non-system async transaction. `isLongRunning` tells you if a job uses long-running async delivery. `isPhase1Settled` tells you if Phase 1 settlement happened (long-running async only).

There is also `getJob(bytes32) returns (Job memory, bytes memory, bytes memory)` which returns a 14-field struct for advanced status reconciliation. The `Job` struct has `commitBlock` and `ttl` fields — compute expiry as `commitBlock + ttl` (there is no `expiryBlock` field or getter). For short-running async precompiles (HTTP, LLM, DKMS), settlement removes the job and `getJob` reverts with "not found". See `ritual-dapp-backend` for the full polling pattern.

---

## ABI Encoding Reference

### HTTP Methods (used by 0x0801, 0x0805)

GET=1, POST=2, PUT=3, DELETE=4, PATCH=5, HEAD=6, OPTIONS=7. Method code 0 is invalid and rejected at the RPC level.

### Short-Running Async Output Envelope

The Solidity CALL return from a short-running async precompile (0x0801, 0x0802) has a two-layer envelope:

```solidity
(bytes memory simmedInput, bytes memory actualOutput) = abi.decode(raw, (bytes, bytes));
```

RPC receipt `spcCalls[i].output` already contains the bare `actualOutput`. Decode that field directly with the response ABI below.

The inner `actualOutput` is precompile-specific. For inline HTTP output (5 fields):

```solidity
(uint16 statusCode, string[] headerKeys, string[] headerValues, bytes body, string errorMessage)
```

When the HTTP request sets `output_storage_ref` (DA output), the executor uploads the (ECIES-encrypted) ABI-encoded HTTPCallResponse off-chain and `actualOutput` is instead a DA result envelope (5 fields):

```solidity
(bool hasError, string outputUri, bytes32 outputContentHash, uint64 outputSizeBytes, string errorMessage)
```

To read it: decode the envelope, fetch the bytes from `outputUri`, verify the sha256 and size, ABI-decode the stored bytes as a single `bytes` value to extract the ciphertext, ECIES-decrypt with the user private key, then decode the recovered bytes as the inline HTTPCallResponse above. DA output encryption is fail-closed — it requires a valid 65-byte `user_public_key` with a `0x04` prefix.

When the HTTP `body` starts with `RITHTTP1`, the outer `output_storage_ref` must be empty and `actualOutput` instead starts with `RITOUT1`. Guard the seven-byte prefix, then decode `(bool hasError, uint16 upstreamStatus, uint8 contractEncoding, bytes contractOutput, ArtifactReceipt[] receipts, bytes4 errorCode)`. The same bytes arrive in a long-running Phase 2 callback. Authenticate the callback and pending job first. Normal completion uses encoding `4`: decode `contractOutput` as `PipeResult[]`, matched by index to requested outputs; outer receipts are empty. Early failures can have encoding `0` and no pipe results. Inspect each required pipe's success, kind, encoding, encryption, size and hash before bounded state writes. A failed live stream or DA upload can leave valid CONTRACT usage: preserve accounting according to application policy instead of blanket-rejecting the aggregate `hasError`. Use `RITHTTP1.encodeRequest(options,jsonTemplate,inputRefs,outputs)` and `RITHTTP1.decodePipeResults`. See the [base](../ritual-dapp-http/references/rithttp1.md) and [private-I/O](../ritual-dapp-http/references/rithttp1-private-io.md) references.

### Long-Running Async Base Fields

All long-running async precompiles share these base fields at the start of their ABI:

| Field | Type | Description |
|---|---|---|
| executor | address | TEE executor from registry |
| sponsor | address | RitualWallet account escrowing payment for this async job (non-zero) |
| secretOwners | address[] | explicit owner per encrypted secret blob; parallel to encryptedSecrets and secretSignatures (all empty together when no secrets, each owner non-zero) |
| encryptedSecrets | bytes[] | ECIES-encrypted secrets (or empty) |
| ttl | uint256 | Max blocks for Phase 1 settlement (1–500) |
| secretSignatures | bytes[] | EIP-191 owner signatures over each blob's domain-separated secret-authorization payload (not the raw ciphertext); signer = secretOwners[i] |
| userPublicKey | bytes | 65-byte uncompressed secp256k1 key (or empty) |

Followed by precompile-specific polling config, delivery config, and payload fields. See each precompile's skill for the complete ABI layout.

### Trailing Fields (HTTP, Long-Running HTTP)

HTTP (0x0801) and Long-Running HTTP (0x0805) append these fields after the core request:

| Field | Type | Description |
|---|---|---|
| dkmsKeyIndex | uint256 | Key index for dKMS derivation (0 = disabled) |
| dkmsKeyFormat | uint8 | Key format (0 = disabled, 1 = Eth/secp256k1) |
| piiEnabled | bool | Enable PII redaction (independent of dKMS) |

`dkmsKeyIndex` and `dkmsKeyFormat` control dKMS key derivation. `piiEnabled` controls PII redaction and is independent of dKMS. Always encode all 16 fields for HTTP and all 38 fields for Long-Running HTTP — set unused fields to zero.

---

## Callback Security

Authenticate both the delivery sender and the job. A caller can choose this contract as a delivery target for a job submitted elsewhere; `msg.sender == AsyncDelivery` alone does not establish provenance.

Record the origin transaction hash using `0x0830` immediately before submitting the long-running call. Consume that pending job before processing its result:

```solidity
address constant ASYNC_DELIVERY = 0x508f57AE70967Da28AE0Ab6b95532878c4D0F440;
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
    delete pendingJobs[jobId];
    // process result
}
```

Encode this contract and its matching selector as the delivery target. Submission access control is application-specific: pending-job tracking proves this contract submitted the job, not that every caller should be authorized to create paid jobs.

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

**Synchronous precompiles** (JQ, Ed25519, SECP256R1): check low-level call success and the expected return shape before decoding. Do not assume every failure reverts: JQ query/type failures can return empty output on a successful call. See the [JQ compatibility notes](../ritual-dapp-precompiles/SKILL.md#query-compatibility-and-silent-failures).

**Short-running async** (HTTP, LLM): the transaction settles even if the executor hit an error. Check the output:
```solidity
(uint16 statusCode, , , bytes memory body, string memory err) = abi.decode(
    output, (uint16, string[], string[], bytes, string)
);
if (bytes(err).length > 0) { /* executor error */ }
if (statusCode >= 400) { /* HTTP error */ }
```

**Two-phase async** (Agent, Long HTTP, etc.): Phase 1 returns a task ID. Phase 2 delivers via callback. If the callback reverts, `AsyncDelivery` emits `Delivered(bytes32 jobId, address sponsor, address target, bool success, uint256 gasConsumed, uint256 gasRefunded, uint256 valueRefunded)` with `success = false` and refunds the reverted callback value to the escrow sponsor (there is no `DeliveryFailed` event).

---

## Testing

### Foundry Unit Tests

```solidity
import "forge-std/Test.sol";

contract ConsumerTest is Test {
    address constant ASYNC_DELIVERY = 0x508f57AE70967Da28AE0Ab6b95532878c4D0F440;

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
    IRitualWallet wallet = IRitualWallet(0xF04076756d8129Baec46Dc0F1c526Baec490C393);
    vm.deal(address(this), 1 ether);
    wallet.deposit{value: 0.5 ether}();
    assertEq(wallet.availableBalance(address(this)), 0.5 ether);
}
```

---

## Security Checklist

- [ ] All callback functions have `onlyAsyncDelivery` modifier (`msg.sender == 0x508f...F440`)
- [ ] Callbacks are idempotent (check-and-set fulfillment flag before processing)
- [ ] Follows Check-Effects-Interactions pattern
- [ ] Stuck-state escape hatch (TTL-based auto-expiry or admin override)
- [ ] Payer/sponsor RitualWallet has sufficient available balance (and, for sponsored/delegated calls, `allowance(sponsor, caller)`) to cover the required reserve. For long-running HTTP this includes Phase 1 HTTP fee, worst-case Phase 2 polling escrow (`FEE_PER_POLL_BLOCK_WEI * (ttl + maxPollBlock)`), worst-case output payload fee, and callback gas/value.
- [ ] Executor address fetched from TEEServiceRegistry (not zero address)
- [ ] `deliverySelector` matches the actual callback function's selector
- [ ] `deliveryGasLimit` is sufficient for callback execution
- [ ] HTTP method codes are correct (GET=1, POST=2, PUT=3, DELETE=4, PATCH=5)
- [ ] HTTP encoding has all 16 fields (including `sponsor`, `secret_owners`, `dkmsKeyIndex`, `dkmsKeyFormat`, `piiEnabled`, `output_storage_ref`)
- [ ] `receive()` present if contract needs to accept native RITUAL
- [ ] Events emitted for all state changes (for off-chain indexing)

---

## Constraints Quick Reference

| Constraint | Value |
|---|---|
| Block time | ~350ms (conservative baseline) |
| Chain ID | 784 |
| RPC | `https://rpc.ritualfoundation.org` |
| Max TTL (async commitment) | 500 blocks (~175s at the ~350ms baseline; chain-config value) |
| Min TTL (async commitment) | 1 block |
| Max Phase 2 deadline offset | 70,000 blocks (~6.8h) |
| Max precompile input size | 10 KB |
| Max HTTP response size | 5 KB (chain-config value) |
| Max long-running calls per tx | 1 |
| Max async commits per sender per block | 1 |
| Sender lock | Until Phase 1 settlement |
| Scheduler: only contracts can schedule | EOAs cannot call `schedule()` |
| Scheduler: `frequency >= 1` | Required |
| Scheduler: `startBlock > block.number` | Required |
| Scheduler: MAX_TTL | 500 (set at deployment, immutable) |

For timing conversion formulas and measurement preflight on your target RPC, see `ritual-dapp-block-time`.

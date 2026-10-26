---
name: ritual-dapp-testing
description: Testing and debugging patterns for Ritual dApps. Use when writing tests, debugging issues, or setting up CI/CD for Ritual applications.
---

# Testing & Debugging — Ritual dApp Patterns

> **Do not test with Anvil, Hardhat network, or a Foundry fork.** Ritual's asynchronous precompiles (HTTP `0x0801`, LLM `0x0802`, DKMS `0x081B`, and the two-phase ones `0x0805`/`0x0806`/`0x0807`/`0x080C`/`0x0818`–`0x081A`/`0x0820`) only exist on a real Ritual node: the block builder commits the job, a TEE executor computes off-chain, and the builder replays your transaction with the result injected. Anvil and every other local EVM have no code at those addresses, so a call returns empty bytes — a "passing" local test proves nothing about the precompile. Unit tests may mock the envelope with `vm.mockCall`/`vm.etch` to check encoding/decoding; everything else runs against the RPC you were given (`RITUAL_RPC_URL`), and a settled on-chain receipt is the only proof that a precompile integration works.

## Overview

Ritual dApps span multiple layers — Solidity contracts, TypeScript viem interactions, backend services, and frontends — each requiring a different testing strategy. The async nature of Ritual precompiles adds complexity: a single user action may touch commit, execute, and settle phases across multiple blocks.

### Testing Pyramid for Ritual dApps

```
                    ┌─────────────────┐
                    │   E2E Tests     │  Few, slow, high confidence
                    │  (Real chain)   │  Real executors
                    ├─────────────────┤
                    │  Integration    │  Moderate count
                    │  Tests          │  viem ↔ chain, fork tests
                    ├─────────────────┤
                    │  Unit Tests     │  Many, fast, isolated
                    │  (Foundry +     │  Contracts + codecs + hooks
                    │   Vitest)       │
                    └─────────────────┘
```

| Layer | Tool | What It Tests | Speed |
|-------|------|---------------|-------|
| Solidity unit tests | Foundry (`forge test`) | Contract logic, encoding, access control | Fast (~1s) |
| Solidity fuzz tests | Foundry (`forge test`) | Edge cases via randomized inputs | Medium (~10s) |
| Solidity fork tests | Foundry (`forge test --fork-url`) | Against live chain state | Slow (~30s) |
| viem codec tests | Vitest / Jest | Encode/decode round-trips, type safety | Fast (~1s) |
| viem integration tests | Vitest / Jest | Real transactions on chain | Slow (~60s) |
| Backend unit tests | Vitest | Event parsing, DB queries, webhook signing | Fast (~1s) |
| Frontend component tests | React Testing Library | Hook state machines, UI rendering | Fast (~2s) |
| E2E acceptance tests | Playwright + chain | Full user flow through real chain | Very slow (~120s) |

---

## 1. Foundry Unit Tests

### Basic Consumer Contract Test

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";

contract HTTPConsumer {
    address constant HTTP_PRECOMPILE = address(0x0801);
    event ResponseReceived(uint16 status, string body);

    struct StorageRef {
        string platform;
        string path;
        string keyRef;
    }

    function decodeSettlement(bytes memory rawOutput)
        public
        pure
        returns (uint16 status, bytes memory body, string memory err)
    {
        (, bytes memory actualOutput) = abi.decode(rawOutput, (bytes, bytes));
        (status, , , body, err) = abi.decode(
            actualOutput,
            (uint16, string[], string[], bytes, string)
        );
    }

    function fetchData(address executor, address sponsor, uint256 ttl, string calldata url)
        external
        returns (uint16 status, bytes memory body)
    {
        bytes memory input = abi.encode(
            executor, sponsor, new address[](0), new bytes[](0), ttl, new bytes[](0), bytes(""),
            url, uint8(1), new string[](0), new string[](0), bytes(""),
            uint256(0), uint8(0), false, StorageRef("", "", "")
        );
        (bool success, bytes memory rawOutput) = HTTP_PRECOMPILE.call(input);
        require(success, "Precompile call failed");
        string memory err;
        (status, body, err) = decodeSettlement(rawOutput);
        require(bytes(err).length == 0, err);
        emit ResponseReceived(status, string(body));
        return (status, body);
    }
}

contract HTTPConsumerTest is Test {
    HTTPConsumer consumer;
    address executor = makeAddr("executor");

    function setUp() public {
        consumer = new HTTPConsumer();
        vm.deal(address(consumer), 10 ether);
    }

    function test_DecodeSettlement_UnwrapsSpcEnvelope() public {
        bytes memory rawOutput = abi.encode(
            bytes("simulated-input"),
            abi.encode(
                uint16(200),
                new string[](0),
                new string[](0),
                bytes('{"price": 3500}'),
                ""
            )
        );

        (uint16 status, bytes memory body, string memory err) =
            consumer.decodeSettlement(rawOutput);

        assertEq(status, 200);
        assertEq(string(body), '{"price": 3500}');
        assertEq(err, "");
    }

    function test_FetchData_EmitsEvent() public {
        vm.expectEmit(false, false, false, true);
        emit HTTPConsumer.ResponseReceived(200, '{"price": 3500}');

        bytes memory rawOutput = abi.encode(
            bytes("simulated-input"),
            abi.encode(
                uint16(200),
                new string[](0),
                new string[](0),
                bytes('{"price": 3500}'),
                ""
            )
        );
        (uint16 status, bytes memory body, string memory err) =
            consumer.decodeSettlement(rawOutput);
        require(bytes(err).length == 0, err);
        emit HTTPConsumer.ResponseReceived(status, string(body));
    }
}
```

### Async Consumer with Callback Tests

This callback-only unit fixture seeds pending-job state with an origin job hash; it does not implement job submission.

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";

contract AsyncConsumer {
    address public deliveryAddress;

    mapping(bytes32 => bool) public pendingJobs;
    mapping(bytes32 => bytes) public results;

    event JobCompleted(bytes32 indexed jobId, bytes result);

    constructor(address _deliveryAddress) {
        deliveryAddress = _deliveryAddress;
    }

    function onResult(bytes32 jobId, bytes calldata result) external {
        require(msg.sender == deliveryAddress, "Unauthorized delivery");
        require(pendingJobs[jobId], "Unknown job");

        pendingJobs[jobId] = false;
        results[jobId] = result;
        emit JobCompleted(jobId, result);
    }
}

contract AsyncConsumerTest is Test {
    AsyncConsumer consumer;
    address delivery = makeAddr("delivery");
    address attacker = makeAddr("attacker");
    bytes32 jobId = keccak256("test-job");

    function setUp() public {
        consumer = new AsyncConsumer(delivery);
    }

    function test_OnResult_StoresResult() public {
        // Simulate pending job
        vm.store(
            address(consumer),
            keccak256(abi.encode(jobId, uint256(1))), // pendingJobs slot
            bytes32(uint256(1))
        );

        bytes memory result = abi.encode("hello world");

        vm.prank(delivery);
        consumer.onResult(jobId, result);

        assertEq(consumer.results(jobId), result);
    }

    function test_OnResult_RevertsUnauthorized() public {
        vm.store(
            address(consumer),
            keccak256(abi.encode(jobId, uint256(1))),
            bytes32(uint256(1))
        );

        vm.prank(attacker);
        vm.expectRevert("Unauthorized delivery");
        consumer.onResult(jobId, "");
    }

    function test_OnResult_RevertsUnknownJob() public {
        vm.prank(delivery);
        vm.expectRevert("Unknown job");
        consumer.onResult(jobId, "");
    }

    function test_OnResult_EmitsEvent() public {
        vm.store(
            address(consumer),
            keccak256(abi.encode(jobId, uint256(1))),
            bytes32(uint256(1))
        );

        bytes memory result = abi.encode("data");

        vm.expectEmit(true, false, false, true);
        emit AsyncConsumer.JobCompleted(jobId, result);

        vm.prank(delivery);
        consumer.onResult(jobId, result);
    }
}
```

### Fuzz Testing Fee Calculations

```solidity
contract FeeCalculatorTest is Test {
    uint256 constant BASE_FEE = 10_000_000_000_000_000; // 0.01 RIT (HTTP_EXECUTOR_BASE_FEE_WEI)
    uint256 constant PER_BYTE_FEE = 350_000_000; // 0.35 gwei/byte input — snapshot value; confirm against deployed config
    uint256 constant MAX_INPUT_SIZE = 10 * 1024; // 10KB async input cap

    function calculateFee(uint256 inputSize) internal pure returns (uint256) {
        require(inputSize <= MAX_INPUT_SIZE, "Input too large");
        return BASE_FEE + (inputSize * PER_BYTE_FEE);
    }

    function testFuzz_FeeCalculation(uint256 inputSize) public pure {
        inputSize = bound(inputSize, 0, MAX_INPUT_SIZE);
        uint256 fee = calculateFee(inputSize);
        assertGe(fee, BASE_FEE);
        assertLe(fee, BASE_FEE + MAX_INPUT_SIZE * PER_BYTE_FEE);
    }

    function testFuzz_FeeMonotonicallyIncreases(uint256 a, uint256 b) public pure {
        a = bound(a, 0, MAX_INPUT_SIZE - 1);
        b = bound(b, a + 1, MAX_INPUT_SIZE);
        assertLt(calculateFee(a), calculateFee(b));
    }

    function testFuzz_FeeRevertsOverMax(uint256 inputSize) public {
        inputSize = bound(inputSize, MAX_INPUT_SIZE + 1, type(uint256).max);
        vm.expectRevert("Input too large");
        this.calculateFeeExternal(inputSize);
    }

    function calculateFeeExternal(uint256 inputSize) external pure returns (uint256) {
        return calculateFee(inputSize);
    }
}
```

---

## 2. Mock Precompile Responses

In unit tests, precompile addresses aren't available. Use `vm.mockCall` or etch bytecode to simulate responses.

### Using vm.mockCall

```solidity
contract MockPrecompileTest is Test {
    address constant HTTP_PRECOMPILE = address(0x0801);

    function test_MockHTTPResponse() public {
        // Async precompile results are wrapped in a short-running async envelope: (bytes simulatedInput, bytes actualOutput)
        bytes memory innerResponse = abi.encode(
            uint16(200),
            new string[](0),
            new string[](0),
            bytes('{"result": "ok"}'),
            ""
        );
        bytes memory spcEnvelope = abi.encode(bytes("simulated-input"), innerResponse);

        vm.mockCall(
            HTTP_PRECOMPILE,
            bytes(""),
            spcEnvelope
        );

        (bool success, bytes memory result) = HTTP_PRECOMPILE.call(
            abi.encode("anything")
        );
        assertTrue(success);

        // Unwrap short-running async envelope, then decode inner response
        (, bytes memory actualOutput) = abi.decode(result, (bytes, bytes));
        (uint16 status, , , bytes memory body, ) =
            abi.decode(actualOutput, (uint16, string[], string[], bytes, string));
        assertEq(status, 200);
        assertEq(string(body), '{"result": "ok"}');
    }

    // When the request sets output_storage_ref, the executor uploads the
    // (ECIES-encrypted) ABI-encoded HTTPCallResponse off-chain and actualOutput
    // becomes a DA result envelope instead of the inline HTTPCallResponse:
    //   (bool has_error, string output_uri, bytes32 output_content_hash, uint64 output_size_bytes, string error_message)
    // The stored bytes (fetched from output_uri, verified against output_content_hash,
    // then decrypted with the user private key) are the inline HTTPCallResponse above.
    function test_MockHTTPResponse_DAOutput() public {
        bytes32 contentHash = sha256(bytes('{"result": "ok"}')); // executor uses sha256 of the stored bytes
        bytes memory daEnvelope = abi.encode(
            false,                              // has_error
            "gs://ritual-da/responses/abc",    // output_uri
            contentHash,                        // output_content_hash
            uint64(64),                         // output_size_bytes
            ""                                  // error_message
        );
        bytes memory spcEnvelope = abi.encode(bytes("simulated-input"), daEnvelope);

        vm.mockCall(HTTP_PRECOMPILE, bytes(""), spcEnvelope);

        (bool success, bytes memory result) = HTTP_PRECOMPILE.call(
            abi.encode("anything")
        );
        assertTrue(success);

        // Unwrap short-running async envelope, then decode the DA result envelope.
        (, bytes memory actualOutput) = abi.decode(result, (bytes, bytes));
        (bool hasError, string memory outputUri, bytes32 outputHash, uint64 size, ) =
            abi.decode(actualOutput, (bool, string, bytes32, uint64, string));
        assertFalse(hasError);
        assertEq(outputUri, "gs://ritual-da/responses/abc");
        assertEq(outputHash, contentHash);
        assertEq(size, 64);
        // dApp then fetches outputUri, verifies sha256 == outputHash, decrypts,
        // and ABI-decodes the inline HTTPCallResponse from the stored bytes.
    }
}
```

### Using vm.etch for Complex Mocks

```solidity
contract PrecompileMock {
    fallback(bytes calldata input) external returns (bytes memory) {
        bytes memory innerResponse = abi.encode(
            uint16(200),
            new string[](0),
            new string[](0),
            bytes('{"mocked": true}'),
            ""
        );
        return abi.encode(input, innerResponse); // short-running async envelope: (simulatedInput, actualOutput)
    }
}

contract EtchMockTest is Test {
    address constant HTTP_PRECOMPILE = address(0x0801);

    function setUp() public {
        PrecompileMock mock = new PrecompileMock();
        vm.etch(HTTP_PRECOMPILE, address(mock).code);
    }

    function test_PrecompileReturnsFixedResponse() public {
        (bool ok, bytes memory result) = HTTP_PRECOMPILE.call(abi.encode("test"));
        assertTrue(ok);

        (, bytes memory actualOutput) = abi.decode(result, (bytes, bytes));
        (, , , bytes memory body, ) =
            abi.decode(actualOutput, (uint16, string[], string[], bytes, string));
        assertEq(string(body), '{"mocked": true}');
    }
}
```

### Parameterized Mock — Return Different Results per Input

```solidity
contract ParameterizedMock {
    mapping(bytes32 => bytes) public responses;

    function setResponse(bytes32 inputHash, bytes calldata response) external {
        responses[inputHash] = response;
    }

    fallback(bytes calldata input) external returns (bytes memory) {
        bytes32 key = keccak256(input);
        bytes memory resp = responses[key];
        require(resp.length > 0, "No mock response for input");
        return resp;
    }
}

contract ParameterizedMockTest is Test {
    address constant HTTP_PRECOMPILE = address(0x0801);
    ParameterizedMock mock;

    function setUp() public {
        mock = new ParameterizedMock();
        vm.etch(HTTP_PRECOMPILE, address(mock).code);
        mock = ParameterizedMock(HTTP_PRECOMPILE);
    }

    function test_DifferentResponsesPerInput() public {
        bytes memory input1 = abi.encode("https://api.example.com/a");
        bytes memory input2 = abi.encode("https://api.example.com/b");

        bytes memory inner1 = abi.encode(uint16(200), new string[](0), new string[](0), bytes("A"), "");
        bytes memory inner2 = abi.encode(uint16(200), new string[](0), new string[](0), bytes("B"), "");

        mock.setResponse(keccak256(input1), abi.encode(input1, inner1));
        mock.setResponse(keccak256(input2), abi.encode(input2, inner2));

        (, bytes memory r1) = HTTP_PRECOMPILE.call(input1);
        (, bytes memory r2) = HTTP_PRECOMPILE.call(input2);

        (, bytes memory out1) = abi.decode(r1, (bytes, bytes));
        (, bytes memory out2) = abi.decode(r2, (bytes, bytes));
        (, , , bytes memory body1, ) = abi.decode(out1, (uint16, string[], string[], bytes, string));
        (, , , bytes memory body2, ) = abi.decode(out2, (uint16, string[], string[], bytes, string));

        assertEq(string(body1), "A");
        assertEq(string(body2), "B");
    }
}
```

---

## 3. Fork Testing — Test Against Live Ritual Chain

Fork testing runs your contracts against real chain state, including real system contracts and precompile behavior.

### Basic Fork Test

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";

contract ForkTest is Test {
    address constant RITUAL_WALLET = 0xF04076756d8129Baec46Dc0F1c526Baec490C393;
    address constant ASYNC_JOB_TRACKER = 0xf00385449fD961925A0B125F5f30b29B682D4bFb;
    address constant TEE_SERVICE_REGISTRY = 0xf4495DC72143D44A93AB0ecE4d6D63a216b27839;

    uint256 ritualFork;

    function setUp() public {
        ritualFork = vm.createFork(vm.envString("RITUAL_RPC_URL"));
        vm.selectFork(ritualFork);
    }

    function test_RitualWalletDeposit() public {
        address user = makeAddr("user");
        vm.deal(user, 1 ether);

        vm.prank(user);
        (bool ok,) = RITUAL_WALLET.call{value: 0.1 ether}(
            abi.encodeWithSignature("deposit()") // deposits credit available balance immediately (no lock)
        );
        assertTrue(ok, "Deposit failed");

        (bool ok2, bytes memory result) = RITUAL_WALLET.call(
            abi.encodeWithSignature("availableBalance(address)", user)
        );
        assertTrue(ok2);
        uint256 balance = abi.decode(result, (uint256));
        assertGe(balance, 0.1 ether);
    }

    function test_TEERegistryHasExecutors() public {
        (bool ok, bytes memory result) = TEE_SERVICE_REGISTRY.call(
            abi.encodeWithSignature("getServicesByCapability(uint8,bool)", uint8(0), false) // HTTP_CALL
        );
        assertTrue(ok, "Registry query failed");
    }

    function test_AsyncJobTrackerJobCount() public {
        address executor = address(0x1234);
        (bool ok, bytes memory result) = ASYNC_JOB_TRACKER.call(
            abi.encodeWithSignature("getJobCount(address)", executor)
        );
        assertTrue(ok);
        uint256 count = abi.decode(result, (uint256));
        console.log("Active jobs for executor:", count);
    }
}
```

### Fork Test with Contract Deployment

```solidity
contract DeployAndTestOnFork is Test {
    HTTPConsumer consumer;

    function setUp() public {
        vm.createSelectFork(vm.envString("RITUAL_RPC_URL"));

        consumer = new HTTPConsumer();
        vm.deal(address(consumer), 1 ether);

        // Deposit fees in RitualWallet
        vm.prank(address(consumer));
        (bool ok,) = address(0xF04076756d8129Baec46Dc0F1c526Baec490C393).call{value: 0.1 ether}(
            abi.encodeWithSignature("deposit()") // deposits credit available balance immediately (no lock)
        );
        assertTrue(ok);
    }

    function test_SubmitHTTPRequest_OnFork() public {
        // This will create a real commitment on the forked state
        consumer.fetchData(
            address(0x1234), // executor address from registry
            address(consumer), // sponsor: RitualWallet account backing the job
            100,
            "https://api.example.com/test"
        );
    }
}
```

### Foundry Configuration for Fork Tests

```toml
# foundry.toml
[profile.default]
src = "src"
out = "out"
libs = ["lib"]
solc_version = "0.8.24"

[profile.fork]
fork_url = "${RITUAL_RPC_URL}"
fork_block_number = 0  # latest

[rpc_endpoints]
ritual = "${RITUAL_RPC_URL}"
```

Run fork tests: `RITUAL_RPC_URL=https://rpc.ritualfoundation.org forge test --match-contract ForkTest -vvv`

### eth_call Behavior with Precompiles

When testing precompiles via `eth_call` (read-only simulation), behavior differs between sync and async precompiles.

**Sync precompiles** (JQ, Ed25519): execute normally and return real computation results. Standard `eth_call` testing works.

**All async precompiles** (HTTP 0x0801, LLM 0x0802, Long HTTP 0x0805, Sovereign Agent 0x080C, etc.): the EVM injects a default `AsyncCommitmentContext` in `Building` mode with empty `pending_spc_calls`. Each precompile hits the "fresh simulation" code path and returns:

```
abi.encode(bytes callInput, bytes empty)
```

The call succeeds (no revert), but the output's second element is always empty bytes — no actual HTTP response, LLM result, or task ID is returned. This is the short-running async envelope `(bytes simulatedInput, bytes actualOutput)` with `actualOutput = ""`.

To test async precompiles, submit a real transaction and wait for settlement, or use `vm.mockCall` / `vm.etch` (Section 2) for unit tests.

Source: `ritual-revm-internal/crates/precompile/src/http_call.rs:265-287`, `async_common.rs:12-50`, `reth/crates/evm/src/lib.rs:308-313`.

---

## 4. Precompile Encoding Unit Tests (Vitest)

### ABI Encoding Round-Trip Tests

```typescript
import { describe, it, expect } from 'vitest';
import { hexToBytes, encodeAbiParameters, decodeAbiParameters, toHex, getAddress, type Address } from 'viem';

const HTTP_REQUEST_TYPES = [
  { name: 'executor', type: 'address' },
  { name: 'sponsor', type: 'address' },
  { name: 'secretOwners', type: 'address[]' },
  { name: 'encryptedSecrets', type: 'bytes[]' },
  { name: 'ttl', type: 'uint256' },
  { name: 'secretSignatures', type: 'bytes[]' },
  { name: 'userPublicKey', type: 'bytes' },
  { name: 'url', type: 'string' },
  { name: 'method', type: 'uint8' },
  { name: 'headerKeys', type: 'string[]' },
  { name: 'headerValues', type: 'string[]' },
  { name: 'body', type: 'bytes' },
  { name: 'dkmsKeyIndex', type: 'uint256' },
  { name: 'dkmsKeyFormat', type: 'uint8' },
  { name: 'piiEnabled', type: 'bool' },
  { name: 'outputStorageRef', type: 'tuple', components: [
    { name: 'platform', type: 'string' },
    { name: 'path', type: 'string' },
    { name: 'keyRef', type: 'string' },
  ] }, // DA output ref (platform, path, keyRef); ['','',''] = inline response
] as const;

const HTTP_RESPONSE_TYPES = [
  { type: 'uint16' },
  { type: 'string[]' },
  { type: 'string[]' },
  { type: 'bytes' },
  { type: 'string' },
] as const;

describe('HTTP Call request encoding', () => {
  const executor: Address = '0x1234567890abcdef1234567890abcdef12345678';
  const sponsor: Address = '0xabcdefabcdefabcdefabcdefabcdefabcdefabcd';

  it('encodes and decodes a GET request', () => {
    const encoded = encodeAbiParameters(HTTP_REQUEST_TYPES, [
      executor, sponsor, [], [], 100n, [], '0x',
      'https://api.example.com/data', 1, ['Accept'], ['application/json'],
      '0x',
      0n, 0, false, ['', '', ''],
    ]);
    expect(encoded).toMatch(/^0x/);

    const decoded = decodeAbiParameters(HTTP_REQUEST_TYPES, encoded);
    expect(decoded[0]).toBe(getAddress(executor));
    expect(decoded[7]).toBe('https://api.example.com/data');
    expect(decoded[8]).toBe(1); // GET
    expect(decoded[9]).toEqual(['Accept']);
    expect(decoded[10]).toEqual(['application/json']);
    expect(decoded[4]).toBe(100n);
  });

  it('encodes and decodes a POST request with body', () => {
    const body = JSON.stringify({ query: 'test' });

    const encoded = encodeAbiParameters(HTTP_REQUEST_TYPES, [
      executor, sponsor, [], [], 200n, [], '0x',
      'https://api.example.com/query', 2,
      ['Content-Type'], ['application/json'],
      toHex(body),
      0n, 0, false, ['', '', ''],
    ]);

    const decoded = decodeAbiParameters(HTTP_REQUEST_TYPES, encoded);
    expect(decoded[7]).toBe('https://api.example.com/query');
    expect(decoded[8]).toBe(2); // POST
    expect(new TextDecoder().decode(hexToBytes(decoded[11]))).toBe(body);
  });

  it('handles empty headers and body', () => {
    const encoded = encodeAbiParameters(HTTP_REQUEST_TYPES, [
      executor, sponsor, [], [], 50n, [], '0x',
      'https://test.com', 1, [], [],
      '0x',
      0n, 0, false, ['', '', ''],
    ]);

    const decoded = decodeAbiParameters(HTTP_REQUEST_TYPES, encoded);
    expect(decoded[9]).toEqual([]); // headerKeys
    expect(decoded[10]).toEqual([]); // headerValues
  });
});

describe('HTTP Call response decoding', () => {
  it('decodes a success response', () => {
    const encoded = encodeAbiParameters(HTTP_RESPONSE_TYPES, [
      200,
      ['content-type'],
      ['application/json'],
      toHex('{"price": 3500}'),
      '',
    ]);

    const [statusCode, , , body, errorMessage] =
      decodeAbiParameters(HTTP_RESPONSE_TYPES, encoded);

    expect(statusCode).toBe(200);
    expect(errorMessage).toBe('');
    expect(JSON.parse(new TextDecoder().decode(hexToBytes(body)))).toEqual({ price: 3500 });
  });

  it('decodes an error response', () => {
    const encoded = encodeAbiParameters(HTTP_RESPONSE_TYPES, [
      0, [], [], '0x', 'executor timeout',
    ]);

    const [statusCode, , , , errorMessage] =
      decodeAbiParameters(HTTP_RESPONSE_TYPES, encoded);

    expect(statusCode).toBe(0);
    expect(errorMessage).toBe('executor timeout');
  });

  it('round-trips through ABI encoding', () => {
    const bodyText = 'hello';
    const encoded = encodeAbiParameters(HTTP_RESPONSE_TYPES, [
      200, [], [], toHex(bodyText), '',
    ]);

    const [statusCode, , , body] = decodeAbiParameters(HTTP_RESPONSE_TYPES, encoded);
    expect(statusCode).toBe(200);
    expect(new TextDecoder().decode(hexToBytes(body))).toBe('hello');
  });
});
```

### Executor Query Tests

For executor discovery tests (`getServicesByCapability`, TEEServiceRegistry ABI, mock executor responses), see `ritual-dapp-deploy` and `ritual-dapp-contracts`.

### RITHTTP1 protocol matrix

When a dApp uses RITHTTP1, start with [the included Bun/Foundry codecs and upstream-generated fixtures](../../examples/rithttp/), [wire schema](../ritual-dapp-http/references/rithttp1.md) and [private I/O](../ritual-dapp-http/references/rithttp1-private-io.md). Minimum coverage:

- Exact canonical four-field request and encoding-4 results across TypeScript, Solidity and pinned executor fixtures; reject unknown flags, trailing bytes, old five/six-field requests and early-error/no-array misuse.
- Ordered `$ritual_da` slots, exact stored-byte SHA-256, one-level hydration, post-hydration `http:*` expansion and terminal secret values; unchanged input artifact vectors for every recipient and malformed-artifact rejection.
- 8 inputs, 6 total pipes, 1 STREAM, 4 DA; valid recipient points, empty non-DA refs, duplicate normalized DA paths and real full 16/38-field request/callback size limits.
- String selector input, `fromjson?`, `[DONE]` omission by selector, decimal preservation, static projections, empty vs empty-string emission, rejected iteration/arithmetic and explicit collection delimiters.
- Every pipe kind with both plaintext and encryption, buffered and SSE upstreams; independent selectors, keys and encodings. Confirm encrypted CONTRACT works and public STREAM still uses a RITPIPE1 record.
- Encoding-4 ordered metadata and per-pipe success: stream publication/DA upload failure preserves valid CONTRACT usage; fatal upstream read/cancel cannot authenticate incomplete collections.
- STREAM length-prefixed binary-frame commitment, selected plaintext byte total, item count and job/pipe/encoding/sequence/payload-length bindings; reject tampering, replay, omission and reordering. DA hash/size must cover its independent stored bytes, never the live stream commitment.
- Short rejection of `AWAIT_RESPONSE`; Long HTTP `resultJsonPath="."`, held deadlines/cancellation, and completed result retry without another upstream call/upload. An open TCP request is not crash durable.

Network coverage should exercise GCS/HF/Pinata hydration/upload, legacy task polling, held responses, authenticated short/long SSE, subscriber loss and independent settlement verification. Local mocks/fixtures prove component behavior, not deployed fleet support or cloud-storage availability. Pin compatible executor code before live tests; keep secret/input routing bound to the executor that can decrypt them.


---

## 5. Integration Tests — viem Against Ritual Chain

Integration tests send real transactions to Ritual Chain. They require RITUAL balance and take longer to run.

### Setup

```typescript
// test/setup.ts
import { createPublicClient, createWalletClient, http, defineChain } from 'viem';
import { privateKeyToAccount } from 'viem/accounts';

export const ritualChain = defineChain({
  id: 784,
  name: 'Ritual',
  nativeCurrency: { name: 'RITUAL', symbol: 'RITUAL', decimals: 18 },
  rpcUrls: {
    default: { http: [process.env.RITUAL_RPC_URL ?? 'https://rpc.ritualfoundation.org'] },
  },
  blockExplorers: {
    default: { name: 'Ritual Explorer', url: 'https://explorer.ritualfoundation.org' },
  },
});

export function getTestClients() {
  if (!process.env.RITUAL_RPC_URL || !process.env.TEST_PRIVATE_KEY) {
    throw new Error('RITUAL_RPC_URL and TEST_PRIVATE_KEY required for integration tests');
  }

  const account = privateKeyToAccount(process.env.TEST_PRIVATE_KEY as `0x${string}`);

  const publicClient = createPublicClient({
    chain: ritualChain,
    transport: http(process.env.RITUAL_RPC_URL),
  });

  const walletClient = createWalletClient({
    account,
    chain: ritualChain,
    transport: http(process.env.RITUAL_RPC_URL),
  });

  return { publicClient, walletClient, account };
}
```

### HTTP Call Integration Test

```typescript
import { describe, it, expect, beforeAll } from 'vitest';
import { getTestClients } from './setup';
import { parseEther, encodeAbiParameters, type Address } from 'viem';

const RITUAL_WALLET: Address = '0xF04076756d8129Baec46Dc0F1c526Baec490C393';
const HTTP_PRECOMPILE: Address = '0x0000000000000000000000000000000000000801';

const ritualWalletAbi = [
  { name: 'availableBalance', type: 'function', stateMutability: 'view',
    inputs: [{ name: 'account', type: 'address' }], outputs: [{ type: 'uint256' }] },
  { name: 'deposit', type: 'function', stateMutability: 'payable',
    inputs: [], outputs: [] },
] as const;

describe('HTTP Call (integration)', () => {
  let clients: ReturnType<typeof getTestClients>;

  beforeAll(async () => {
    clients = getTestClients();

    const balance = await clients.publicClient.readContract({
      address: RITUAL_WALLET,
      abi: ritualWalletAbi,
      functionName: 'availableBalance',
      args: [clients.account.address],
    });

    if (balance < parseEther('0.01')) {
      const hash = await clients.walletClient.writeContract({
        address: RITUAL_WALLET,
        abi: ritualWalletAbi,
        functionName: 'deposit',
        args: [],
        value: parseEther('0.05'),
      });
      await clients.publicClient.waitForTransactionReceipt({ hash });
    }
  }, 30_000);

  it('submits a GET request and receives a transaction hash', async () => {
    const executor: Address = '0x...'; // selected executor from TEEServiceRegistry

    const encoded = encodeAbiParameters(
      [
        { name: 'executor', type: 'address' },
        { name: 'sponsor', type: 'address' },
        { name: 'secretOwners', type: 'address[]' },
        { name: 'encryptedSecrets', type: 'bytes[]' },
        { name: 'ttl', type: 'uint256' },
        { name: 'secretSignatures', type: 'bytes[]' },
        { name: 'userPublicKey', type: 'bytes' },
        { name: 'url', type: 'string' },
        { name: 'method', type: 'uint8' },
        { name: 'headerKeys', type: 'string[]' },
        { name: 'headerValues', type: 'string[]' },
        { name: 'body', type: 'bytes' },
        { name: 'dkmsKeyIndex', type: 'uint256' },
        { name: 'dkmsKeyFormat', type: 'uint8' },
        { name: 'piiEnabled', type: 'bool' },
        { name: 'outputStorageRef', type: 'tuple', components: [
          { name: 'platform', type: 'string' },
          { name: 'path', type: 'string' },
          { name: 'keyRef', type: 'string' },
        ] },
      ],
      [
        executor, clients.account.address, [], [], 100n, [], '0x',
        'https://httpbin.org/get', 1, [], [],
        '0x',
        0n, 0, false, ['', '', ''],
      ]
    );

    const hash = await clients.walletClient.sendTransaction({
      to: HTTP_PRECOMPILE,
      data: encoded,
      gas: 2_000_000n,
    });

    expect(hash).toMatch(/^0x[0-9a-f]{64}$/);

    const receipt = await clients.publicClient.waitForTransactionReceipt({ hash });
    expect(receipt.status).toBe('success');
  }, 60_000);
});
```

### Wallet Integration Test

```typescript
import { describe, it, expect, beforeAll } from 'vitest';
import { getTestClients } from './setup';
import { parseEther, type Address } from 'viem';

const RITUAL_WALLET: Address = '0xF04076756d8129Baec46Dc0F1c526Baec490C393';

const ritualWalletAbi = [
  { name: 'availableBalance', type: 'function', stateMutability: 'view',
    inputs: [{ name: 'account', type: 'address' }], outputs: [{ type: 'uint256' }] },
  { name: 'deposit', type: 'function', stateMutability: 'payable',
    inputs: [], outputs: [] },
] as const;

describe('RitualWallet (integration)', () => {
  let clients: ReturnType<typeof getTestClients>;

  beforeAll(() => {
    clients = getTestClients();
  });

  it('deposits and reads balance', async () => {
    const before = await clients.publicClient.readContract({
      address: RITUAL_WALLET,
      abi: ritualWalletAbi,
      functionName: 'availableBalance',
      args: [clients.account.address],
    });

    const hash = await clients.walletClient.writeContract({
      address: RITUAL_WALLET,
      abi: ritualWalletAbi,
      functionName: 'deposit',
      args: [],
      value: parseEther('0.001'),
    });
    await clients.publicClient.waitForTransactionReceipt({ hash });

    const after = await clients.publicClient.readContract({
      address: RITUAL_WALLET,
      abi: ritualWalletAbi,
      functionName: 'availableBalance',
      args: [clients.account.address],
    });

    expect(after).toBeGreaterThan(before);
  }, 30_000);
});
```

---

## 6. Frontend Testing

For frontend component and hook testing patterns (React Testing Library, wagmi mocks, state machine transitions), see `ritual-dapp-frontend`.

---

## 7. Debugging Guide

### Common Issues and Solutions

#### Transaction stuck in pending

**Symptoms**: Transaction submitted successfully but job never settles.

**Diagnosis**:
```typescript
import { createPublicClient, http, defineChain, type Address, type Hex } from 'viem';

const ritualChain = defineChain({
  id: 784,
  name: 'Ritual',
  nativeCurrency: { name: 'RITUAL', symbol: 'RITUAL', decimals: 18 },
  rpcUrls: {
    default: { http: [process.env.RITUAL_RPC_URL ?? 'https://rpc.ritualfoundation.org'] },
  },
});

const publicClient = createPublicClient({
  chain: ritualChain,
  transport: http(process.env.RITUAL_RPC_URL),
});

const TEE_SERVICE_REGISTRY: Address = '0xf4495DC72143D44A93AB0ecE4d6D63a216b27839';
const ASYNC_JOB_TRACKER: Address = '0xf00385449fD961925A0B125F5f30b29B682D4bFb';

// 1. Check if services are available for your precompile type
const services = await publicClient.readContract({
  address: TEE_SERVICE_REGISTRY,
  abi: [{
    name: 'getServicesByCapability',
    type: 'function',
    stateMutability: 'view',
    inputs: [{ name: 'capability', type: 'uint8' }, { name: 'checkValidity', type: 'bool' }],
    outputs: [{ type: 'tuple[]', components: [
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
    ] }],
  }] as const,
  functionName: 'getServicesByCapability',
  args: [0, true], // 0 = HTTP_CALL capability
});
console.log('Available services:', services.length);

if (services.length === 0) {
  console.error('No services registered for HTTP_CALL capability');
  console.log('Check TEEServiceRegistry at', TEE_SERVICE_REGISTRY);
}

// 2. Check tx-origin lock on AsyncJobTracker
const isLocked = await publicClient.readContract({
  address: ASYNC_JOB_TRACKER,
  abi: [{
    name: 'hasPendingJobForTxOrigin', type: 'function', stateMutability: 'view',
    inputs: [{ name: 'txOrigin', type: 'address' }],
    outputs: [{ type: 'bool' }],
  }] as const,
  functionName: 'hasPendingJobForTxOrigin',
  args: [testEOA],
});
console.log('Tx origin locked:', isLocked);

// For full job status polling (getJob returns a 14-field struct),
// see the AsyncJobTracker interface in the ritual-dapp-contracts skill.
// Compute expiry as commitBlock + ttl (there is no expiryBlock field).
```

**Fixes**:
- **No services**: Wait for service registration or check TEEServiceRegistry
- **TTL expired**: Increase `ttl` parameter (try 200n or 500n)
- **Executor not responding**: Try a different executor address

#### Executor not found

**Symptoms**: `No services found for capability` error.

**Diagnosis**:
```typescript
// Common capability IDs used by these skills
const capabilityNames: Record<number, string> = {
  0: 'HTTP_CALL',
  1: 'LLM',
  2: 'WORMHOLE_QUERY',
  3: 'STREAMING',
  4: 'VLLM_PROXY',
  5: 'ZK_CALL',
  6: 'DKMS',
  7: 'IMAGE_CALL',
  8: 'AUDIO_CALL',
  9: 'VIDEO_CALL',
  10: 'FHE',
};

for (const cap of Object.keys(capabilityNames).map(Number)) {
  try {
    const services = await publicClient.readContract({
      address: TEE_SERVICE_REGISTRY,
      abi: [{
        name: 'getServicesByCapability',
        type: 'function',
        stateMutability: 'view',
        inputs: [{ name: 'capability', type: 'uint8' }, { name: 'checkValidity', type: 'bool' }],
        outputs: [{ type: 'tuple[]' }],
      }] as const,
      functionName: 'getServicesByCapability',
      args: [cap, true],
    });
    console.log(`${capabilityNames[cap]}: ${services.length} service(s)`);
  } catch (err) {
    console.log(`${capabilityNames[cap]}: unavailable`);
  }
}
```

**Fixes**:
- Verify you're using the correct capability for your precompile
- Confirm the TEEServiceRegistry has registered executors on the network you're targeting

#### Callback not firing

**Symptoms**: Job settles but `onResult` / delivery callback never executes.

**Checklist**:
1. **Delivery target correct?** — The `deliveryTarget` address must be your contract
2. **Delivery selector correct?** — Must match `bytes4(keccak256("onResult(bytes32,bytes)"))`
3. **Gas limit sufficient?** — Callback execution needs gas; try 500,000+
4. **Contract accepts the call?** — The callback function must be `external` (not `internal`/`private`)
5. **No revert in callback?** — If callback reverts, delivery marks as failed

```typescript
import { encodeFunctionData, keccak256, toHex } from 'viem';

// Verify your selector matches
const expectedSelector = keccak256(
  toHex('onResult(bytes32,bytes)')
).slice(0, 10); // first 4 bytes
console.log('Expected selector:', expectedSelector);

// Common selectors:
// handleHTTPResponse(bytes)     → 0x... (calculate for your function)
// onResult(bytes32,bytes)       → 0x... (calculate for your function)
```

#### Insufficient balance

**Symptoms**: Transaction reverts with "insufficient balance" or "deposit required".

**Diagnosis**:
```typescript
import { parseEther, formatEther, type Address } from 'viem';

const RITUAL_WALLET: Address = '0xF04076756d8129Baec46Dc0F1c526Baec490C393';
const walletAbi = [
  { name: 'availableBalance', type: 'function', stateMutability: 'view',
    inputs: [{ name: 'account', type: 'address' }], outputs: [{ type: 'uint256' }] },
  { name: 'deposit', type: 'function', stateMutability: 'payable',
    inputs: [], outputs: [] },
] as const;

const userAddress = walletClient.account.address;

// Check RitualWallet balance
const balance = await publicClient.readContract({
  address: RITUAL_WALLET,
  abi: walletAbi,
  functionName: 'availableBalance',
  args: [userAddress],
});
console.log('Wallet balance:', formatEther(balance), 'RITUAL');

// Check native balance
const nativeBalance = await publicClient.getBalance({ address: userAddress });
console.log('Native balance:', formatEther(nativeBalance), 'RITUAL');

// Deposit if needed
if (balance < parseEther('0.01')) {
  console.log('Depositing 0.05 RITUAL...');
  const hash = await walletClient.writeContract({
    address: RITUAL_WALLET,
    abi: walletAbi,
    functionName: 'deposit',
    args: [],
    value: parseEther('0.05'),
  });
  await publicClient.waitForTransactionReceipt({ hash });
}
```

#### Wrong result format

**Symptoms**: Decoded result is garbage, wrong types, or throws decoding error.

**Checklist**:
1. Ensure you're using the correct codec for the precompile type
2. Check that your Solidity `abi.decode` matches the precompile's output ABI
3. For HTTP responses: body is `bytes`, not `string` — cast if needed

```typescript
import { hexToBytes, decodeAbiParameters, type Hex } from 'viem';

// HTTP precompile (0x0801) response format
const [statusCode, headerKeys, headerValues, body, errorMessage] =
  decodeAbiParameters(
    [{ type: 'uint16' }, { type: 'string[]' }, { type: 'string[]' }, { type: 'bytes' }, { type: 'string' }],
    resultHex as Hex
  );

// Common mistake: trying to JSON.parse raw bytes
// Wrong:
const bad = JSON.parse(resultHex); // ❌

// Correct: decode via ABI, then parse the body bytes
const textBody = new TextDecoder().decode(hexToBytes(body));
const data = JSON.parse(textBody); // ✅ properly decoded
```

#### Tracing stuck transactions

Use `debug_traceTransaction` with the `callTracer` to see exactly what happened inside a transaction:

```bash
cast rpc debug_traceTransaction <TX_HASH> '{"tracer": "callTracer"}' --rpc-url https://rpc.ritualfoundation.org
```

This returns the full call tree — precompile calls, internal calls, reverts with reason strings. Useful for diagnosing why an async job was rejected or why a callback failed.

---

## 8. Common Error Codes and Fixes

| Error | Cause | Fix |
|-------|-------|-----|
| `No services found for capability` | No TEE services registered for this precompile type | Check TEEServiceRegistry; use correct capability ID |
| `Precompile call failed` | call to precompile address reverted | Check input encoding matches precompile ABI |
| `Insufficient deposit` | RitualWallet balance too low | Call `ritualWalletHelper.deposit()` before request |
| `Job expired` | TTL too short; executor didn't settle in time | Increase `ttl` parameter |
| `Unauthorized delivery` | Callback sender isn't the expected delivery address | Verify delivery address in contract constructor |
| `Unknown job` | Callback for a job ID that doesn't exist in your mapping | Ensure job was properly registered in `submitJob` |
| `Input too large` | Encoded request exceeds 10KB async input limit | Reduce request size; move data off-chain |
| `Executor timeout` | Executor didn't respond within the execution window | Retry with different executor or higher TTL |
| `Invalid secret signature` | Signed the raw ciphertext instead of the domain-separated authorization payload, or signed with a key whose address != `secret_owners[i]` | Rebuild the `RITUAL_SECRET_AUTHORIZATION_V1` preimage (domain ‖ uint16(len(useContext)) ‖ useContext ‖ uint256(chainId) ‖ executor ‖ owner ‖ keccak256(blob)) and sign it with the owner's private key |
| `Decoding error` | ABI mismatch between encoder and decoder | Verify codec type matches precompile |
| `Transaction reverted without reason` | Contract logic error or insufficient gas | Increase gas limit; check contract with `forge test -vvvv` |
| `Nonce too low` | Concurrent transactions from same account | Wait for pending tx or use nonce manager |

---

## 9. Environment & Run Commands

Ritual Chain (current configured snapshot: ID 784; classify the deployment before funding or writes).

```bash
RITUAL_RPC_URL=https://rpc.ritualfoundation.org
RITUAL_WS_URL=wss://rpc.ritualfoundation.org/ws
```

| Test type | Command |
|-----------|---------|
| Solidity unit tests | `forge test --no-match-contract Fork -vvv` |
| Solidity fork tests | `RITUAL_RPC_URL=... forge test --match-contract Fork -vvv` |
| Fuzz tests | `forge test --match-test testFuzz -vvv` |
| Gas snapshots | `forge snapshot --check` |
| TypeScript unit tests | `npx vitest run` |
| Integration tests (on-chain) | `npx vitest run --config vitest.integration.config.ts` |

For integration tests, set `maxConcurrency: 1` and `testTimeout: 120_000` to serialize on-chain transactions and allow settlement time.

---

## 11. Test Utilities and Helpers

### Shared Test Fixtures

```typescript
// test/fixtures.ts
import type { Address, Hex } from 'viem';

export const TEST_EXECUTOR: Address = '0x1234567890abcdef1234567890abcdef12345678';
export const TEST_USER: Address = '0xabcdefabcdefabcdefabcdefabcdefabcdefabcd';

export const MOCK_HTTP_RESPONSE_SUCCESS = {
  statusCode: 200 as const,
  headers: { 'content-type': 'application/json' },
  body: new TextEncoder().encode('{"result": "ok"}'),
  errorMessage: '',
};

export const MOCK_HTTP_RESPONSE_ERROR = {
  statusCode: 0 as const,
  headers: {},
  body: new Uint8Array(),
  errorMessage: 'executor timeout',
};

export function makeJobId(seed: string): Hex {
  return `0x${Buffer.from(seed.padEnd(32, '\0')).toString('hex')}` as Hex;
}

export function makeMockHTTPResponseData(
  status: number,
  body: string,
  error = ''
): Hex {
  // Returns ABI-encoded HTTP response data for testing short-running async settlement decoding
  const { encodeAbiParameters, toHex } = require('viem');
  return encodeAbiParameters(
    [
      { type: 'uint16' },
      { type: 'string[]' },
      { type: 'string[]' },
      { type: 'bytes' },
      { type: 'string' },
    ],
    [status, [], [], toHex(body), error]
  );
}
```

### Test Timeouts and Retries

```typescript
// test/helpers.ts
export async function waitForCondition(
  check: () => Promise<boolean>,
  timeoutMs = 60_000,
  pollMs = 2000
): Promise<void> {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (await check()) return;
    await new Promise((r) => setTimeout(r, pollMs));
  }
  throw new Error(`Condition not met within ${timeoutMs}ms`);
}

export async function retryAsync<T>(
  fn: () => Promise<T>,
  retries = 3,
  delayMs = 1000
): Promise<T> {
  let lastError: Error | undefined;
  for (let i = 0; i < retries; i++) {
    try {
      return await fn();
    } catch (err) {
      lastError = err as Error;
      if (i < retries - 1) {
        await new Promise((r) => setTimeout(r, delayMs * (i + 1)));
      }
    }
  }
  throw lastError;
}
```

---

## Quick Reference

| Item | Value |
|------|-------|
| Foundry test command | `forge test -vvv` |
| Fork test command | `RITUAL_RPC_URL=... forge test --match-contract Fork -vvv` |
| Fuzz test command | `forge test --match-test testFuzz -vvv` |
| viem/unit tests | `npx vitest run` |
| Integration tests | `npx vitest run --config vitest.integration.config.ts` |
| Gas snapshot | `forge snapshot` |
| Coverage | `forge coverage` |
| Mock precompile | `vm.mockCall(address(0x0801), bytes(""), responseBytes)` |
| Etch precompile | `vm.etch(address(0x0801), mockContract.code)` |
| AsyncJobTracker | `0xf00385449fD961925A0B125F5f30b29B682D4bFb` |
| TEEServiceRegistry | `0xf4495DC72143D44A93AB0ecE4d6D63a216b27839` |
| RitualWallet | `0xF04076756d8129Baec46Dc0F1c526Baec490C393` |
| Chain ID | 784 |
| ABI encoding | `encodeAbiParameters` / `decodeAbiParameters` from viem |
| Executor query | `publicClient.readContract({ address: TEE_SERVICE_REGISTRY, ... })` |
| DA providers | Test with GCS (default), HuggingFace, and Pinata — see `ritual-dapp-da` for StorageRef format |

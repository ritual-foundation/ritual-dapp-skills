// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice Deploy this example contract directly; only its owner can submit paid jobs.
contract PersistentAgentConsumer {
    address public immutable owner;
    address public immutable asyncDelivery;
    mapping(bytes32 => bool) public pendingJobs;
    mapping(bytes32 => bytes) public results;

    event PersistentAgentResultDelivered(bytes32 indexed jobId, bytes result);

    constructor(address delivery) {
        require(delivery != address(0), "zero delivery address");
        owner = msg.sender;
        asyncDelivery = delivery;
    }

    modifier onlyOwner() {
        require(msg.sender == owner, "only owner");
        _;
    }

    function callPersistentAgent(uint256 agentId, uint64 revision, bytes calldata input)
        external
        onlyOwner
        returns (bytes memory output)
    {
        // Decode the flat envelope, not a dynamically wrapped Solidity struct.
        (, address sponsor,,, bool enabled, address target, bytes4 selector,,,, uint256 value, bytes32 context,) = abi.decode(
            input,
            (address, address, uint64, uint64, bool, address, bytes4, uint64, uint128, uint128, uint256, bytes32, bytes)
        );
        require(sponsor == owner, "invalid sponsor");
        require(enabled && target == address(this), "invalid callback target");
        require(selector == this.onPersistentAgentResult.selector && value == 0, "invalid callback terms");
        require(context == keccak256(abi.encode(agentId, revision)), "invalid identity context");
        (bool hashOk, bytes memory hashOutput) = address(0x0830).staticcall("");
        require(hashOk && hashOutput.length == 32, "transaction hash unavailable");
        bytes32 jobId = abi.decode(hashOutput, (bytes32));
        require(!pendingJobs[jobId], "job already pending");
        pendingJobs[jobId] = true;
        (bool ok, bytes memory raw) = address(0x0820).call(input);
        require(ok, "agent call failed");
        return raw;
    }

    function onPersistentAgentResult(bytes32 jobId, bytes calldata result) external {
        require(msg.sender == asyncDelivery, "unauthorized callback sender");
        require(pendingJobs[jobId], "unknown job");
        delete pendingJobs[jobId];
        results[jobId] = result;
        emit PersistentAgentResultDelivered(jobId, result);
    }
}

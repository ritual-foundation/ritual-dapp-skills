// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title Minimal Sovereign Agent Consumer
/// @notice Calls the 0x080C precompile and receives Phase 2 results via callback.
contract SovereignAgentConsumer {
    address constant SOVEREIGN_AGENT = address(0x080C);
    address constant ASYNC_DELIVERY = 0x5A16214fF555848411544b005f7Ac063742f39F6;

    error UnauthorizedCaller();
    error PrecompileCallFailed();

    address public immutable owner;
    bytes32 public lastJobId;

    bytes public lastResult;

    event SovereignAgentResultDelivered(bytes32 indexed jobId, bytes result);

    constructor() {
        owner = msg.sender;
    }

    modifier onlyOwner() {
        if (msg.sender != owner) revert UnauthorizedCaller();
        _;
    }

    function callSovereignAgent(bytes calldata input) external onlyOwner returns (bytes memory) {
        (bool ok, bytes memory output) = SOVEREIGN_AGENT.call(input);
        if (!ok) {
            if (output.length == 0) revert PrecompileCallFailed();
            assembly {
                revert(add(output, 0x20), mload(output))
            }
        }
        return output;
    }

    function onSovereignAgentResult(bytes32 jobId, bytes calldata result) external {
        require(msg.sender == ASYNC_DELIVERY, "unauthorized callback sender");
        lastJobId = jobId;
        lastResult = result;
        emit SovereignAgentResultDelivered(jobId, result);
    }
}

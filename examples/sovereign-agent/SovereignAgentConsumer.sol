// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title Minimal Sovereign Agent Consumer
/// @notice Calls the 0x080C precompile and receives Phase 2 results via callback.
/// @dev Precompile .call() may return ok=true with ABI-encoded error data.
///      Consumers should decode the return data or use a wrapper that
///      reverts on error selectors (0x08c379a0 for Error, 0x4e487b71 for Panic).
///      Consider adding a ReentrancyGuard from OpenZeppelin on the callback
///      if the contract handles external calls during callback processing.
contract SovereignAgentConsumer {
    address constant SOVEREIGN_AGENT = address(0x080C);

    address public immutable asyncDelivery;

    bytes32 public lastJobId;
    bytes public lastResult;

    event SovereignAgentResultDelivered(bytes32 indexed jobId, bytes result);

    /// @param _asyncDelivery Address of the AsyncDelivery system contract
    constructor(address _asyncDelivery) {
        require(_asyncDelivery != address(0), "invalid async delivery address");
        asyncDelivery = _asyncDelivery;
    }

    /// @notice Calls the Sovereign Agent precompile (0x080C)
    /// @dev Precompiles may return ok=true with encoded error data in `output`.
    ///      The output should be ABI-decoded and checked for error selectors.
    function callSovereignAgent(bytes calldata input) external returns (bytes memory) {
        (bool ok, bytes memory output) = SOVEREIGN_AGENT.call(input);
        require(ok, "precompile call failed");
        require(output.length > 0, "precompile returned empty output");
        return output;
    }

    /// @notice Callback invoked by AsyncDelivery with the agent's result
    /// @dev Consider adding nonReentrant modifier if external calls are made
    ///      during callback processing.
    function onSovereignAgentResult(bytes32 jobId, bytes calldata result) external {
        require(msg.sender == asyncDelivery, "unauthorized callback sender");
        require(result.length > 0, "empty callback result");
        lastJobId = jobId;
        lastResult = result;
        emit SovereignAgentResultDelivered(jobId, result);
    }
}

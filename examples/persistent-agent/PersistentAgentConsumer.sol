// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title Minimal Persistent Agent Consumer
/// @notice Calls the 0x0820 precompile, receives Phase 2 spawn results, and
///         also exposes a helper for the 0x081B DKMS key precompile.
/// @dev Precompile .call() may return ok=true with ABI-encoded error data.
///      Consumers should decode the return data or use a wrapper that
///      reverts on error selectors (0x08c379a0 for Error, 0x4e487b71 for Panic).
///      Consider adding a ReentrancyGuard from OpenZeppelin on the callback
///      if the contract handles external calls during callback processing.
contract PersistentAgentConsumer {
    address constant PERSISTENT_AGENT = address(0x0820);
    address constant DKMS_KEY = address(0x081B);

    address public immutable asyncDelivery;

    bytes32 public lastJobId;
    bytes public lastResult;
    bytes public lastDkmsResult;

    event PrecompileCalled(address indexed precompile, bytes input, bytes output);
    event PersistentAgentResultDelivered(bytes32 indexed jobId, bytes result);
    event DkmsKeyResult(bytes result);

    /// @param _asyncDelivery Address of the AsyncDelivery system contract
    constructor(address _asyncDelivery) {
        require(_asyncDelivery != address(0), "invalid async delivery address");
        asyncDelivery = _asyncDelivery;
    }

    /// @notice Calls the Persistent Agent precompile (0x0820)
    /// @dev Precompiles may return ok=true with encoded error data in `output`.
    ///      The output should be ABI-decoded and checked for error selectors.
    function callPersistentAgent(bytes calldata input) external returns (bytes memory) {
        (bool ok, bytes memory output) = PERSISTENT_AGENT.call(input);
        require(ok, "persistent precompile call failed");
        // Note: ok=true does not guarantee success — precompiles may return
        // ABI-encoded errors (selector 0x08c379a0 for Error(string)).
        // Production code should decode and validate output.
        require(output.length > 0, "precompile returned empty output");
        emit PrecompileCalled(PERSISTENT_AGENT, input, output);
        return output;
    }

    function callDKMSKey(bytes calldata input) external returns (bytes memory) {
        (bool ok, bytes memory output) = DKMS_KEY.call(input);
        require(ok, "dkms precompile call failed");
        require(output.length > 0, "dkms precompile returned empty output");
        lastDkmsResult = output;
        emit PrecompileCalled(DKMS_KEY, input, output);
        emit DkmsKeyResult(output);
        return output;
    }

    /// @notice Callback invoked by AsyncDelivery with the agent's result
    /// @dev Consider adding nonReentrant modifier if external calls are made
    ///      during callback processing.
    function onPersistentAgentResult(bytes32 jobId, bytes calldata result) external {
        require(msg.sender == asyncDelivery, "unauthorized callback sender");
        require(result.length > 0, "empty callback result");
        lastJobId = jobId;
        lastResult = result;
        emit PersistentAgentResultDelivered(jobId, result);
    }
}

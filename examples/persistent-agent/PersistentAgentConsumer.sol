// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title Minimal Persistent Agent Consumer
/// @notice Calls the 0x0820 precompile, receives Phase 2 spawn results, and
///         also exposes a helper for the 0x081B DKMS key precompile.
contract PersistentAgentConsumer {
    address constant PERSISTENT_AGENT = address(0x0820);
    address constant DKMS_KEY = address(0x081B);
    address constant ASYNC_DELIVERY = 0x5A16214fF555848411544b005f7Ac063742f39F6;

    error UnauthorizedCaller();
    error PrecompileCallFailed();

    address public immutable owner;
    bytes32 public lastJobId;
    bytes public lastResult;
    bytes public lastDkmsResult;

    event PrecompileCalled(address indexed precompile, bytes input, bytes output);

    event PersistentAgentResultDelivered(bytes32 indexed jobId, bytes result);
    event DkmsKeyResult(bytes result);

    constructor() {
        owner = msg.sender;
    }

    modifier onlyOwner() {
        if (msg.sender != owner) revert UnauthorizedCaller();
        _;
    }

    function callPersistentAgent(bytes calldata input) external onlyOwner returns (bytes memory) {
        return _callPrecompile(PERSISTENT_AGENT, input);
    }

    function callDKMSKey(bytes calldata input) external onlyOwner returns (bytes memory) {
        bytes memory output = _callPrecompile(DKMS_KEY, input);
        lastDkmsResult = output;
        emit DkmsKeyResult(output);
        return output;
    }

    function _callPrecompile(address precompile, bytes calldata input) internal returns (bytes memory) {
        (bool ok, bytes memory output) = precompile.call(input);
        if (!ok) {
            if (output.length == 0) revert PrecompileCallFailed();
            assembly {
                revert(add(output, 0x20), mload(output))
            }
        }
        emit PrecompileCalled(precompile, input, output);
        return output;
    }

    function onPersistentAgentResult(bytes32 jobId, bytes calldata result) external {
        require(msg.sender == ASYNC_DELIVERY, "unauthorized callback sender");
        lastJobId = jobId;
        lastResult = result;
        emit PersistentAgentResultDelivered(jobId, result);
    }
}

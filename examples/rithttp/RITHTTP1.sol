// SPDX-License-Identifier: BSD-3-Clause-Clear
pragma solidity ^0.8.28;

/// @title RITHTTP1
/// @notice Pure codecs for the executor-side HTTP extension carried inside the
/// existing HTTP and long-running HTTP precompile `body` field.
/// @dev This library does not change either outer precompile ABI.
library RITHTTP1 {
    bytes8 internal constant REQUEST_MAGIC = bytes8("RITHTTP1");
    bytes7 internal constant RESULT_MAGIC = bytes7("RITOUT1");

    uint32 internal constant AWAIT_RESPONSE = 1 << 0;
    uint32 internal constant STREAM_RESPONSE = 1 << 3;
    uint8 internal constant CONTRACT_ENCODING_PIPES = 4;
    uint8 internal constant CONTRACT = 0;
    uint8 internal constant STREAM = 1;
    uint8 internal constant DA = 2;
    uint8 internal constant JSON = 0;
    uint8 internal constant UTF8 = 1;

    struct StorageRef {
        string platform;
        string path;
        string keyRef;
    }

    struct InputRef {
        StorageRef ref;
        bytes32 sha256Digest;
    }

    struct OutputPipe {
        uint8 kind;
        string jq;
        uint8 encoding;
        bytes recipientPublicKey;
        StorageRef destination;
    }

    struct PipeResult {
        uint8 kind;
        uint8 encoding;
        bool encrypted;
        bool success;
        bytes data;
        string outputURI;
        bytes32 sha256Digest;
        uint64 sizeBytes;
        uint32 itemCount;
        bytes4 errorCode;
    }

    struct ArtifactReceipt {
        bool success;
        string outputUri;
        bytes32 sha256Digest;
        uint64 sizeBytes;
        bytes4 errorCode;
    }

    struct Result {
        bool hasError;
        uint16 upstreamStatus;
        uint8 contractEncoding;
        bytes contractOutput;
        ArtifactReceipt[] receipts;
        bytes4 errorCode;
    }

    error InvalidRITHTTP1Result();

    /// @dev Pure ABI codec, not a replacement for executor policy/selector validation.
    function encodeRequest(
        uint32 options,
        bytes memory jsonTemplate,
        InputRef[] memory inputRefs,
        OutputPipe[] memory outputs
    ) internal pure returns (bytes memory) {
        require((options & ~uint32(9)) == 0, "unknown options");
        return abi.encodePacked(REQUEST_MAGIC, abi.encode(options, jsonTemplate, inputRefs, outputs));
    }

    /// @notice The exact JSON object replaced by `inputRefs[slot]`.
    /// @dev This helper is useful when composing a template from raw JSON.
    function daSlot(uint256 slot) internal pure returns (bytes memory) {
        return abi.encodePacked('{"$ritual_da":', _uintToString(slot), "}");
    }

    function decodeResult(bytes memory encoded) internal pure returns (Result memory result) {
        if (!isResult(encoded) || encoded.length > 5 * 1024) {
            revert InvalidRITHTTP1Result();
        }
        (
            result.hasError,
            result.upstreamStatus,
            result.contractEncoding,
            result.contractOutput,
            result.receipts,
            result.errorCode
        ) = abi.decode(_tail(encoded, 7), (bool, uint16, uint8, bytes, ArtifactReceipt[], bytes4));
        if (
            result.receipts.length > 4
                || keccak256(_tail(encoded, 7))
                    != keccak256(
                        abi.encode(
                            result.hasError,
                            result.upstreamStatus,
                            result.contractEncoding,
                            result.contractOutput,
                            result.receipts,
                            result.errorCode
                        )
                    )
        ) revert InvalidRITHTTP1Result();
    }

    /// @notice Returns true when `encoded` is an executor-produced RITHTTP1 result.
    /// @dev Short-running async simulation may return a placeholder before settlement,
    ///      so consumers should use this guard before decoding.
    function isResult(bytes memory encoded) internal pure returns (bool) {
        return encoded.length >= 7 && _resultPrefix(encoded) == RESULT_MAGIC;
    }

    function decodePipeResults(bytes memory contractOutput) internal pure returns (PipeResult[] memory) {
        if (contractOutput.length > 5 * 1024) revert InvalidRITHTTP1Result();
        PipeResult[] memory results = abi.decode(contractOutput, (PipeResult[]));
        if (results.length > 6 || keccak256(contractOutput) != keccak256(abi.encode(results))) {
            revert InvalidRITHTTP1Result();
        }
        return results;
    }

    function _resultPrefix(bytes memory encoded) private pure returns (bytes7 prefix) {
        assembly ("memory-safe") {
            prefix := mload(add(encoded, 0x20))
        }
    }

    function _tail(bytes memory data, uint256 offset) private pure returns (bytes memory result) {
        result = new bytes(data.length - offset);
        for (uint256 i; i < result.length; ++i) {
            result[i] = data[i + offset];
        }
    }

    function _uintToString(uint256 value) private pure returns (string memory) {
        if (value == 0) {
            return "0";
        }
        uint256 digits;
        uint256 remaining = value;
        while (remaining != 0) {
            ++digits;
            remaining /= 10;
        }
        bytes memory buffer = new bytes(digits);
        while (value != 0) {
            --digits;
            buffer[digits] = bytes1(uint8(48 + (value % 10)));
            value /= 10;
        }
        return string(buffer);
    }
}

// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title FactChecker
/// @notice On-chain fact checker that uses the HTTP precompile (0x0801) to
///         fetch real-world data, then the LLM precompile (0x0802) to
///         evaluate whether a submitted claim is TRUE, FALSE, or UNCERTAIN.
/// @dev Two precompiles in one contract — first example of this pattern on Ritual Chain.
///      HTTP call fetches external data (e.g. CoinGecko price).
///      LLM call evaluates the claim against the fetched data.
///      Both results are stored on-chain and emitted as events.
contract FactChecker {
    // ── Precompile addresses ─────────────────────────────────────────────────
    address constant HTTP_PRECOMPILE = address(0x0801);
    address constant LLM_PRECOMPILE  = address(0x0802);
    address constant RITUAL_WALLET   = 0x532F0dF0896F353d8C3DD8cc134e8129DA2a3948;

    // ── Types ────────────────────────────────────────────────────────────────
    enum Verdict { PENDING, TRUE, FALSE, UNCERTAIN }

    struct Claim {
        address submitter;
        string  claim;          // The factual claim to verify
        string  dataUrl;        // URL to fetch supporting data from
        bytes   rawData;        // Raw HTTP response
        bytes   llmResponse;    // Raw LLM completion bytes
        Verdict verdict;        // Final on-chain verdict
        uint256 submittedAt;    // Block number of submission
        uint256 checkedAt;      // Block number when verdict was set
    }

    struct ConvoHistory {
        string storageType;
        string path;
        string secretsName;
    }

    // ── State ────────────────────────────────────────────────────────────────
    uint256 public nextClaimId = 1;
    mapping(uint256 => Claim) public claims;

    // ── Events ───────────────────────────────────────────────────────────────
    event ClaimSubmitted(uint256 indexed claimId, address indexed submitter, string claim, string dataUrl);
    event DataFetched(uint256 indexed claimId, bytes rawData);
    event VerdictReached(uint256 indexed claimId, Verdict verdict, bytes llmResponse);

    // ── Errors ───────────────────────────────────────────────────────────────
    error ClaimNotFound(uint256 claimId);
    error AlreadyChecked(uint256 claimId);
    error NoDataFetched(uint256 claimId);
    error HTTPCallFailed();
    error LLMCallFailed(string reason);
    error InvalidExecutor();
    error EmptyClaim();
    error EmptyUrl();

    // ── Fee management ───────────────────────────────────────────────────────

    /// @notice Deposit RITUAL fees into RitualWallet to fund precompile calls.
    ///         Deposit at least 0.5 RITUAL before calling checkFact().
    function depositFees(uint256 lockDuration) external payable {
        (bool ok,) = RITUAL_WALLET.call{value: msg.value}(
            abi.encodeWithSignature("deposit(uint256)", lockDuration)
        );
        require(ok, "deposit failed");
    }

    // ── Core flow ────────────────────────────────────────────────────────────

    /// @notice Submit a factual claim for verification.
    /// @param claim    The claim to verify (e.g. "BTC price is above $100,000")
    /// @param dataUrl  URL to fetch supporting data from
    ///                 (e.g. "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd")
    /// @return claimId The ID of the submitted claim
    function submitClaim(
        string calldata claim,
        string calldata dataUrl
    ) external returns (uint256 claimId) {
        if (bytes(claim).length == 0) revert EmptyClaim();
        if (bytes(dataUrl).length == 0) revert EmptyUrl();

        claimId = nextClaimId++;
        claims[claimId] = Claim({
            submitter:   msg.sender,
            claim:       claim,
            dataUrl:     dataUrl,
            rawData:     "",
            llmResponse: "",
            verdict:     Verdict.PENDING,
            submittedAt: block.number,
            checkedAt:   0
        });

        emit ClaimSubmitted(claimId, msg.sender, claim, dataUrl);
    }

    /// @notice Step 1: Fetch external data for a claim via HTTP precompile.
    ///         Must be called before checkFact(). One async tx per sender at a time.
    /// @param claimId   The claim to fetch data for
    /// @param executor  TEE executor address from TEEServiceRegistry.getServicesByCapability(0, true)
    /// @param ttl       Request TTL in blocks (recommended: 300)
    function fetchData(
        uint256 claimId,
        address executor,
        uint64  ttl
    ) external {
        if (claims[claimId].submitter == address(0)) revert ClaimNotFound(claimId);
        if (claims[claimId].verdict != Verdict.PENDING) revert AlreadyChecked(claimId);
        if (executor == address(0)) revert InvalidExecutor();

        Claim storage c = claims[claimId];

        // Encode HTTP precompile call (13-field ABI)
        bytes memory httpInput = abi.encode(
            executor,
            c.dataUrl,
            uint8(0),            // GET
            new string[](0),     // headerKeys
            new string[](0),     // headerValues
            bytes(""),           // body
            ttl == 0 ? uint64(300) : ttl
        );

        (bool ok, bytes memory result) = HTTP_PRECOMPILE.call(httpInput);
        if (!ok) revert HTTPCallFailed();

        // Short-running async: unwrap (simmedInput, actualOutput)
        (, bytes memory actualOutput) = abi.decode(result, (bytes, bytes));
        c.rawData = actualOutput;

        emit DataFetched(claimId, actualOutput);
    }

    /// @notice Step 2: Evaluate the claim against fetched data via LLM precompile.
    ///         fetchData() must be called first. One async tx per sender at a time.
    /// @param claimId   The claim to evaluate
    /// @param executor  TEE executor address from TEEServiceRegistry.getServicesByCapability(1, true)
    /// @param ttl       Request TTL in blocks (recommended: 300)
    function checkFact(
        uint256 claimId,
        address executor,
        uint64  ttl
    ) external {
        if (claims[claimId].submitter == address(0)) revert ClaimNotFound(claimId);
        if (claims[claimId].verdict != Verdict.PENDING) revert AlreadyChecked(claimId);
        if (claims[claimId].rawData.length == 0) revert NoDataFetched(claimId);
        if (executor == address(0)) revert InvalidExecutor();

        _runLlm(claimId, executor, ttl);
    }

    function _runLlm(uint256 claimId, address executor, uint64 ttl) internal {
        Claim storage c = claims[claimId];

        (bool ok, bytes memory result) = LLM_PRECOMPILE.call(
            _buildLlmInput(executor, _buildMessages(c.claim, c.rawData), ttl)
        );
        if (!ok) revert LLMCallFailed("precompile call failed");

        (, bytes memory actualOutput) = abi.decode(result, (bytes, bytes));

        (bool hasError, bytes memory completionData, , string memory errorMessage,) =
            abi.decode(actualOutput, (bool, bytes, bytes, string, ConvoHistory));

        if (hasError) revert LLMCallFailed(errorMessage);

        c.llmResponse = completionData;
        c.checkedAt   = block.number;
        c.verdict     = _parseVerdict(completionData);

        emit VerdictReached(claimId, c.verdict, completionData);
    }

    function _buildMessages(string memory claim, bytes memory rawData) internal pure returns (string memory) {
        return string.concat(
            "[{\"role\":\"user\",\"content\":\"Fact-check this claim: ",
            claim,
            ". Data: ",
            string(rawData),
            ". Reply only with JSON: {\"verdict\":\"TRUE|FALSE|UNCERTAIN\",\"reason\":\"one sentence\"}\"}]"
        );
    }

    // ── View helpers ─────────────────────────────────────────────────────────

    function getClaim(uint256 claimId) external view returns (Claim memory) {
        if (claims[claimId].submitter == address(0)) revert ClaimNotFound(claimId);
        return claims[claimId];
    }

    function getVerdict(uint256 claimId) external view returns (Verdict) {
        if (claims[claimId].submitter == address(0)) revert ClaimNotFound(claimId);
        return claims[claimId].verdict;
    }

    // ── Internal helpers ─────────────────────────────────────────────────────

    /// @dev Build LLM precompile input to avoid stack-too-deep in checkFact.
    function _buildLlmInput(
        address executor,
        string memory messages,
        uint64 ttl
    ) internal pure returns (bytes memory) {
        return abi.encode(
            executor,
            new bytes[](0),
            uint256(ttl == 0 ? 300 : ttl),
            new bytes[](0),
            bytes(""),
            messages,
            "zai-org/GLM-4.7-FP8",
            int256(0), "", false, int256(1024), "", "",
            uint256(1), false, int256(0), "low", bytes(""),
            int256(-1), "", "", false, int256(200),
            bytes(""), bytes(""), int256(-1), int256(1000), "",
            false,
            abi.encode("", "", "")
        );
    }

    /// @dev Parse verdict from LLM completion bytes.
    ///      Looks for "TRUE", "FALSE", or "UNCERTAIN" in the response.
    ///      Falls back to UNCERTAIN if parsing fails.
    function _parseVerdict(bytes memory data) internal pure returns (Verdict) {
        if (_contains(data, bytes("TRUE")))      return Verdict.TRUE;
        if (_contains(data, bytes("FALSE")))     return Verdict.FALSE;
        if (_contains(data, bytes("UNCERTAIN"))) return Verdict.UNCERTAIN;
        return Verdict.UNCERTAIN;
    }

    /// @dev Returns true if `haystack` contains `needle`.
    function _contains(bytes memory haystack, bytes memory needle) internal pure returns (bool) {
        if (needle.length == 0 || haystack.length < needle.length) return false;
        for (uint256 i = 0; i <= haystack.length - needle.length; i++) {
            bool found = true;
            for (uint256 j = 0; j < needle.length; j++) {
                if (haystack[i + j] != needle[j]) { found = false; break; }
            }
            if (found) return true;
        }
        return false;
    }

    receive() external payable {}
}

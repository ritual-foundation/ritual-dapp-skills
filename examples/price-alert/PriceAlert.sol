// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title PriceAlert
/// @notice Fetches a token price from CoinGecko via the HTTP precompile (0x0801)
///         and emits an alert when the price crosses a user-defined threshold.
/// @dev Uses Ritual Chain's short-running async HTTP precompile pattern.
///      One async call per transaction; results delivered via fulfilled replay.
contract PriceAlert {
    // ── Ritual precompile addresses ──────────────────────────────────────────
    address constant HTTP_PRECOMPILE  = address(0x0801);
    address constant RITUAL_WALLET    = 0x532F0dF0896F353d8C3DD8cc134e8129DA2a3948;

    // ── State ────────────────────────────────────────────────────────────────
    address public owner;
    address public executor;          // TEE executor from TEEServiceRegistry

    struct Alert {
        string  coinId;               // CoinGecko coin id (e.g. "bitcoin")
        uint256 thresholdUsd;         // price threshold in USD (integer, no decimals)
        bool    alertAbove;           // true = alert when price > threshold
        bool    triggered;            // true = alert has fired
        address recipient;            // who to notify
    }

    uint256 public nextAlertId;
    mapping(uint256 => Alert) public alerts;

    bytes public lastRawResponse;     // raw HTTP response for debugging
    uint256 public lastCheckedPrice;  // last parsed price (integer USD)

    // ── Events ───────────────────────────────────────────────────────────────
    event AlertCreated(uint256 indexed alertId, string coinId, uint256 thresholdUsd, bool alertAbove, address recipient);
    event PriceChecked(uint256 indexed alertId, uint256 price, bytes rawResponse);
    event AlertTriggered(uint256 indexed alertId, string coinId, uint256 price, uint256 threshold);
    event ExecutorUpdated(address indexed newExecutor);

    // ── Errors ───────────────────────────────────────────────────────────────
    error Unauthorized();
    error InvalidThreshold();
    error InvalidExecutor();
    error HTTPCallFailed();
    error AlertAlreadyTriggered(uint256 alertId);
    error AlertNotFound(uint256 alertId);

    // ── Constructor ──────────────────────────────────────────────────────────
    constructor(address _executor) {
        owner    = msg.sender;
        executor = _executor;
    }

    modifier onlyOwner() {
        if (msg.sender != owner) revert Unauthorized();
        _;
    }

    // ── Configuration ────────────────────────────────────────────────────────

    /// @notice Update the TEE executor address (e.g. after querying TEEServiceRegistry)
    function setExecutor(address _executor) external onlyOwner {
        if (_executor == address(0)) revert InvalidExecutor();
        executor = _executor;
        emit ExecutorUpdated(_executor);
    }

    /// @notice Deposit RITUAL fees into the RitualWallet to fund HTTP calls
    function depositFees(uint256 lockDuration) external payable onlyOwner {
        (bool ok,) = RITUAL_WALLET.call{value: msg.value}(
            abi.encodeWithSignature("deposit(uint256)", lockDuration)
        );
        require(ok, "deposit failed");
    }

    // ── Alert management ─────────────────────────────────────────────────────

    /// @notice Register a new price alert
    /// @param coinId       CoinGecko coin id (e.g. "bitcoin", "ethereum", "solana")
    /// @param thresholdUsd Price threshold in whole USD (e.g. 100000 for $100,000)
    /// @param alertAbove   If true, alert fires when price > threshold; else when price < threshold
    /// @param recipient    Address to record as the alert recipient
    function createAlert(
        string calldata coinId,
        uint256 thresholdUsd,
        bool alertAbove,
        address recipient
    ) external returns (uint256 alertId) {
        if (thresholdUsd == 0) revert InvalidThreshold();
        alertId = nextAlertId++;
        alerts[alertId] = Alert({
            coinId:       coinId,
            thresholdUsd: thresholdUsd,
            alertAbove:   alertAbove,
            triggered:    false,
            recipient:    recipient
        });
        emit AlertCreated(alertId, coinId, thresholdUsd, alertAbove, recipient);
    }

    // ── Price check via HTTP precompile ──────────────────────────────────────

    /// @notice Trigger an async HTTP call to CoinGecko to check the price for alertId.
    ///         The result is delivered in the same transaction via fulfilled replay.
    /// @param alertId The alert to check
    /// @param ttl     Number of blocks the job remains valid (default: 100)
    function checkPrice(uint256 alertId, uint64 ttl) external {
        Alert storage alert = alerts[alertId];
        if (bytes(alert.coinId).length == 0) revert AlertNotFound(alertId);
        if (alert.triggered) revert AlertAlreadyTriggered(alertId);

        // Build CoinGecko free-tier URL
        string memory url = string.concat(
            "https://api.coingecko.com/api/v3/simple/price?ids=",
            alert.coinId,
            "&vs_currencies=usd"
        );

        // Encode HTTP precompile calldata
        // Layout: executor (address) | url (string) | method (uint8=0 GET) |
        //         headerKeys[] | headerValues[] | body (bytes) | ttl (uint64)
        bytes memory callData = abi.encode(
            executor,
            url,
            uint8(0),        // GET
            new string[](0), // no extra headers
            new string[](0),
            bytes(""),       // no body
            ttl == 0 ? uint64(100) : ttl
        );

        (bool ok, bytes memory response) = HTTP_PRECOMPILE.call(callData);
        if (!ok) revert HTTPCallFailed();

        // Store raw response and parse price
        lastRawResponse  = response;
        uint256 price    = _parseUsdPrice(response);
        lastCheckedPrice = price;

        emit PriceChecked(alertId, price, response);

        // Evaluate threshold
        bool shouldTrigger = alert.alertAbove
            ? price > alert.thresholdUsd
            : price < alert.thresholdUsd;

        if (shouldTrigger) {
            alert.triggered = true;
            emit AlertTriggered(alertId, alert.coinId, price, alert.thresholdUsd);
        }
    }

    // ── Internal helpers ─────────────────────────────────────────────────────

    /// @dev Parses the integer USD price from a CoinGecko simple/price JSON response.
    ///      Expected format: {"bitcoin":{"usd":62000}} or similar.
    ///      Extracts the first numeric value after `"usd":`.
    function _parseUsdPrice(bytes memory data) internal pure returns (uint256 price) {
        bytes memory needle = bytes('"usd":');
        uint256 idx = _indexOf(data, needle);
        if (idx == type(uint256).max) return 0;

        idx += needle.length;
        // Skip whitespace
        while (idx < data.length && (data[idx] == 0x20 || data[idx] == 0x09)) idx++;

        // Parse digits (integer part only)
        while (idx < data.length) {
            uint8 c = uint8(data[idx]);
            if (c >= 48 && c <= 57) {
                price = price * 10 + (c - 48);
                idx++;
            } else {
                break; // stop at '.', ',', '}', etc.
            }
        }
    }

    /// @dev Returns the index of `needle` in `haystack`, or type(uint256).max if not found.
    function _indexOf(bytes memory haystack, bytes memory needle) internal pure returns (uint256) {
        if (needle.length == 0 || haystack.length < needle.length) return type(uint256).max;
        for (uint256 i = 0; i <= haystack.length - needle.length; i++) {
            bool found = true;
            for (uint256 j = 0; j < needle.length; j++) {
                if (haystack[i + j] != needle[j]) { found = false; break; }
            }
            if (found) return i;
        }
        return type(uint256).max;
    }

    // ── View helpers ─────────────────────────────────────────────────────────

    function getAlert(uint256 alertId) external view returns (Alert memory) {
        return alerts[alertId];
    }

    receive() external payable {}
}

// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title RagAgent
/// @notice On-chain RAG (Retrieval-Augmented Generation) agent for Ritual Chain.
///         Fetches a document via HTTP precompile (0x0801), then answers a question
///         about it using the LLM precompile (0x0802). Both the document and the
///         answer are stored on-chain.
/// @dev Two-step async flow: fetchDoc() then askQuestion(). One async tx per sender.
contract RagAgent {
    address public immutable HTTP_PRECOMPILE;
    address public immutable LLM_PRECOMPILE;
    address constant RITUAL_WALLET = 0x532F0dF0896F353d8C3DD8cc134e8129DA2a3948;

    constructor(address _http, address _llm) {
        HTTP_PRECOMPILE = _http == address(0) ? address(0x0801) : _http;
        LLM_PRECOMPILE  = _llm  == address(0) ? address(0x0802) : _llm;
    }

    struct Query {
        address submitter;
        string  docUrl;
        string  question;
        bytes   docContent;
        string  answer;
        bool    answered;
        uint256 submittedAt;
        uint256 answeredAt;
        string[] selectedChunks;  // Relevant chunks passed to LLM
        uint256  totalChunks;     // Total chunks found in document
    }

    struct ConvoHistory {
        string storageType;
        string path;
        string secretsName;
    }

    uint256 public nextQueryId = 1;
    mapping(uint256 => Query) public queries;

    event QuerySubmitted(uint256 indexed queryId, address indexed submitter, string docUrl, string question);
    event DocFetched(uint256 indexed queryId, uint256 docLength);
    event ChunksSelected(uint256 indexed queryId, uint256 totalChunks, uint256 selectedChunks);
    event AnswerReady(uint256 indexed queryId, string answer);

    error QueryNotFound(uint256 queryId);
    error AlreadyAnswered(uint256 queryId);
    error DocNotFetched(uint256 queryId);
    error HTTPFailed();
    error LLMFailed(string reason);
    error InvalidInput();

    function depositFees(uint256 lockDuration) external payable {
        (bool ok,) = RITUAL_WALLET.call{value: msg.value}(
            abi.encodeWithSignature("deposit(uint256)", lockDuration)
        );
        require(ok, "deposit failed");
    }

    /// @notice Submit a document URL and a question about it.
    function submitQuery(
        string calldata docUrl,
        string calldata question
    ) external returns (uint256 queryId) {
        if (bytes(docUrl).length == 0 || bytes(question).length == 0) revert InvalidInput();

        queryId = nextQueryId++;
        queries[queryId] = Query({
            submitter:     msg.sender,
            docUrl:        docUrl,
            question:      question,
            docContent:    "",
            answer:        "",
            answered:      false,
            submittedAt:   block.number,
            answeredAt:    0,
            selectedChunks: new string[](0),
            totalChunks:   0
        });

        emit QuerySubmitted(queryId, msg.sender, docUrl, question);
    }

    /// @notice Step 1: Fetch the document via HTTP precompile.
    function fetchDoc(
        uint256 queryId,
        address executor,
        uint64  ttl
    ) external {
        Query storage q = queries[queryId];
        if (q.submitter == address(0)) revert QueryNotFound(queryId);
        if (q.answered) revert AlreadyAnswered(queryId);

        bytes memory httpInput = abi.encode(
            executor,
            q.docUrl,
            uint8(0),
            new string[](0),
            new string[](0),
            bytes(""),
            ttl == 0 ? uint64(300) : ttl
        );

        (bool ok, bytes memory result) = HTTP_PRECOMPILE.call(httpInput);
        if (!ok) revert HTTPFailed();

        (, bytes memory actualOutput) = abi.decode(result, (bytes, bytes));
        q.docContent = actualOutput;

        emit DocFetched(queryId, actualOutput.length);
    }

    /// @notice Step 2: Ask the question using LLM precompile.
    function askQuestion(
        uint256 queryId,
        address executor,
        uint64  ttl
    ) external {
        Query storage q = queries[queryId];
        if (q.submitter == address(0)) revert QueryNotFound(queryId);
        if (q.answered) revert AlreadyAnswered(queryId);
        if (q.docContent.length == 0) revert DocNotFetched(queryId);

        _runLlm(queryId, executor, ttl);
    }

    function _runLlm(uint256 queryId, address executor, uint64 ttl) internal {
        Query storage q = queries[queryId];

        // Chunk document and select relevant sections
        (string[] memory chunks, uint256 totalChunks) = _chunkDocument(q.docContent, 20, 50);
        (string[] memory selected, uint256 selectedCount) = _selectRelevantChunks(chunks, totalChunks, q.question, 5);

        // Store selected chunks and emit event
        for (uint256 i = 0; i < selectedCount; i++) {
            q.selectedChunks.push(selected[i]);
        }
        q.totalChunks = totalChunks;
        emit ChunksSelected(queryId, totalChunks, selectedCount);

        // Build context from selected chunks only
        string memory context = _buildContext(selected, selectedCount);

        (bool ok, bytes memory result) = LLM_PRECOMPILE.call(
            _buildLlmInput(executor, _buildMessages(q.question, bytes(context)), ttl)
        );
        if (!ok) revert LLMFailed("precompile call failed");

        (, bytes memory actualOutput) = abi.decode(result, (bytes, bytes));

        (bool hasError, bytes memory completionData, , string memory errorMessage,) =
            abi.decode(actualOutput, (bool, bytes, bytes, string, ConvoHistory));

        if (hasError) revert LLMFailed(errorMessage);

        q.answer    = string(completionData);
        q.answered  = true;
        q.answeredAt = block.number;

        emit AnswerReady(queryId, q.answer);
    }

    function _buildMessages(string memory question, bytes memory docContent) internal pure returns (string memory) {
        return string.concat(
            "[{\"role\":\"system\",\"content\":\"You are a document assistant. Answer questions based only on the provided document chunks. Be concise and cite the relevant section.\"},",
            "{\"role\":\"user\",\"content\":\"Document chunks:\\n",
            string(docContent),
            "\\n\\nQuestion: ",
            question,
            "\\n\\nAnswer based only on the chunks above. If the answer is not in the chunks, say so.\"}]"
        );
    }

    /// @dev Split document into chunks by newline boundaries.
    ///      Returns up to maxChunks chunks of at least minChunkLen bytes.
    function _chunkDocument(
        bytes memory doc,
        uint256 maxChunks,
        uint256 minChunkLen
    ) internal pure returns (string[] memory chunks, uint256 count) {
        chunks = new string[](maxChunks);
        count = 0;
        uint256 start = 0;

        for (uint256 i = 0; i <= doc.length; i++) {
            bool boundary = (i == doc.length) ||
                (doc[i] == 0x0A) || // newline
                (i > 0 && doc[i] == 0x2E && (i + 1 == doc.length || doc[i + 1] == 0x20)); // period + space

            if (boundary && i > start) {
                uint256 chunkLen = i - start;
                if (chunkLen >= minChunkLen) {
                    bytes memory chunk = new bytes(chunkLen);
                    for (uint256 j = 0; j < chunkLen; j++) {
                        chunk[j] = doc[start + j];
                    }
                    chunks[count] = string(chunk);
                    count++;
                    if (count >= maxChunks) break;
                }
                start = i + 1;
            }
        }
    }

    /// @dev Select chunks that contain at least one word from the question.
    ///      Simple keyword matching — no embeddings needed on-chain.
    function _selectRelevantChunks(
        string[] memory chunks,
        uint256 chunkCount,
        string memory question,
        uint256 maxSelected
    ) internal pure returns (string[] memory selected, uint256 selectedCount) {
        selected = new string[](maxSelected);
        selectedCount = 0;
        bytes memory q = bytes(question);

        for (uint256 i = 0; i < chunkCount && selectedCount < maxSelected; i++) {
            bytes memory chunk = bytes(chunks[i]);
            if (_containsKeyword(chunk, q)) {
                selected[selectedCount] = chunks[i];
                selectedCount++;
            }
        }

        // Fallback: if no chunk matched, return first maxSelected chunks
        if (selectedCount == 0) {
            for (uint256 i = 0; i < chunkCount && i < maxSelected; i++) {
                selected[i] = chunks[i];
                selectedCount++;
            }
        }
    }

    /// @dev Returns true if haystack contains any 4+ char word from needle.
    function _containsKeyword(bytes memory haystack, bytes memory needle) internal pure returns (bool) {
        uint256 wordStart = 0;
        for (uint256 i = 0; i <= needle.length; i++) {
            bool wordEnd = (i == needle.length) || needle[i] == 0x20 || needle[i] == 0x3F;
            if (wordEnd && i > wordStart + 3) {
                uint256 wordLen = i - wordStart;
                // Search for this word in haystack
                for (uint256 j = 0; j + wordLen <= haystack.length; j++) {
                    bool isMatch = true;
                    for (uint256 k = 0; k < wordLen; k++) {
                        // Case-insensitive: lowercase both
                        bytes1 a = haystack[j + k];
                        bytes1 b = needle[wordStart + k];
                        if (a >= 0x41 && a <= 0x5A) a = bytes1(uint8(a) + 32);
                        if (b >= 0x41 && b <= 0x5A) b = bytes1(uint8(b) + 32);
                        if (a != b) { isMatch = false; break; }
                    }
                    if (isMatch) return true;
                }
            }
            if (wordEnd) wordStart = i + 1;
        }
        return false;
    }

    /// @dev Build context string from selected chunks with section markers.
    function _buildContext(string[] memory chunks, uint256 count) internal pure returns (string memory ctx) {
        ctx = "";
        for (uint256 i = 0; i < count; i++) {
            ctx = string.concat(ctx, "[Chunk ", _uint2str(i + 1), "]\n", chunks[i], "\n\n");
        }
    }

    function _uint2str(uint256 v) internal pure returns (string memory) {
        if (v == 0) return "0";
        uint256 tmp = v;
        uint256 len;
        while (tmp > 0) { len++; tmp /= 10; }
        bytes memory b = new bytes(len);
        while (v > 0) { b[--len] = bytes1(uint8(48 + v % 10)); v /= 10; }
        return string(b);
    }

    function _buildLlmInput(address executor, string memory messages, uint64 ttl) internal pure returns (bytes memory) {
        return abi.encode(
            executor,
            new bytes[](0),
            uint256(ttl == 0 ? 300 : ttl),
            new bytes[](0),
            bytes(""),
            messages,
            "zai-org/GLM-4.7-FP8",
            int256(0), "", false, int256(2048), "", "",
            uint256(1), false, int256(0), "low", bytes(""),
            int256(-1), "", "", false, int256(300),
            bytes(""), bytes(""), int256(-1), int256(1000), "",
            false,
            abi.encode("", "", "")
        );
    }

    function getQuery(uint256 queryId) external view returns (Query memory) {
        if (queries[queryId].submitter == address(0)) revert QueryNotFound(queryId);
        return queries[queryId];
    }

    function getAnswer(uint256 queryId) external view returns (string memory) {
        if (queries[queryId].submitter == address(0)) revert QueryNotFound(queryId);
        return queries[queryId].answer;
    }

    function getSelectedChunks(uint256 queryId) external view returns (string[] memory, uint256) {
        if (queries[queryId].submitter == address(0)) revert QueryNotFound(queryId);
        return (queries[queryId].selectedChunks, queries[queryId].totalChunks);
    }

    receive() external payable {}
}

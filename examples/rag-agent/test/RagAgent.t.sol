// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import "../RagAgent.sol";

/// @notice Mock HTTP precompile that returns a fake document
contract MockHTTP {
    bytes public response;
    bool public shouldFail;

    constructor(bytes memory _response) {
        response = _response;
    }

    function setFail(bool _fail) external { shouldFail = _fail; }

    fallback(bytes calldata) external returns (bytes memory) {
        if (shouldFail) revert("HTTP failed");
        // Wrap in short-running async envelope: (simmedInput, actualOutput)
        return abi.encode(bytes(""), response);
    }
}

/// @notice Mock LLM precompile that returns a fake answer
contract MockLLM {
    bytes public response;
    bool public shouldFail;
    bool public hasError;
    string public errorMessage;

    constructor(bytes memory _response) {
        response = _response;
    }

    function setFail(bool _fail) external { shouldFail = _fail; }
    function setError(bool _hasError, string memory _msg) external {
        hasError = _hasError;
        errorMessage = _msg;
    }

    fallback(bytes calldata) external returns (bytes memory) {
        if (shouldFail) revert("LLM failed");
        // ConvoHistory struct must match RagAgent.ConvoHistory
        bytes memory convoHistory = abi.encode(
            bytes32(0), // storageType as bytes
            bytes32(0), // path
            bytes32(0)  // secretsName
        );
        // Encode exactly as RagAgent._runLlm decodes:
        // abi.decode(actualOutput, (bool, bytes, bytes, string, ConvoHistory))
        bytes memory actualOutput = abi.encode(
            hasError,       // bool
            response,       // bytes completionData
            bytes(""),      // bytes modelMeta
            errorMessage,   // string errorMessage
            string(""),     // storageType
            string(""),     // path  
            string("")      // secretsName
        );
        return abi.encode(bytes(""), actualOutput);
    }
}

contract RagAgentTest is Test {
    RagAgent agent;
    MockHTTP  mockHttp;
    MockLLM   mockLlm;

    address constant USER = address(0x1234);
    string  constant DOC_URL  = "https://docs.ritualfoundation.org";
    string  constant QUESTION = "What is Ritual Chain?";
    bytes   constant DOC_CONTENT = bytes("Ritual Chain is a blockchain with AI precompiles.");
    bytes   constant LLM_ANSWER  = bytes("Ritual Chain is a blockchain that enables on-chain AI inference.");

    function setUp() public {
        mockHttp = new MockHTTP(DOC_CONTENT);
        mockLlm  = new MockLLM(LLM_ANSWER);

        // Deploy RagAgent with mocked precompile addresses
        // We use vm.etch to replace precompile bytecode with mock bytecode
        agent = new RagAgent(address(mockHttp), address(mockLlm));
    }

    // ── submitQuery ──────────────────────────────────────────────────────────

    function test_submitQuery_success() public {
        vm.prank(USER);
        uint256 queryId = agent.submitQuery(DOC_URL, QUESTION);

        assertEq(queryId, 1);
        assertEq(agent.nextQueryId(), 2);

        RagAgent.Query memory q = agent.getQuery(queryId);
        assertEq(q.submitter, USER);
        assertEq(q.docUrl, DOC_URL);
        assertEq(q.question, QUESTION);
        assertFalse(q.answered);
    }

    function test_submitQuery_emitsEvent() public {
        vm.expectEmit(true, true, false, true);
        emit RagAgent.QuerySubmitted(1, USER, DOC_URL, QUESTION);

        vm.prank(USER);
        agent.submitQuery(DOC_URL, QUESTION);
    }

    function test_submitQuery_revertsOnEmptyUrl() public {
        vm.prank(USER);
        vm.expectRevert(RagAgent.InvalidInput.selector);
        agent.submitQuery("", QUESTION);
    }

    function test_submitQuery_revertsOnEmptyQuestion() public {
        vm.prank(USER);
        vm.expectRevert(RagAgent.InvalidInput.selector);
        agent.submitQuery(DOC_URL, "");
    }

    // ── fetchDoc ─────────────────────────────────────────────────────────────

    function test_fetchDoc_success() public {
        vm.prank(USER);
        uint256 queryId = agent.submitQuery(DOC_URL, QUESTION);

        agent.fetchDoc(queryId, address(0xBEEF), 300);

        RagAgent.Query memory q = agent.getQuery(queryId);
        assertEq(q.docContent, DOC_CONTENT);
    }

    function test_fetchDoc_emitsEvent() public {
        vm.prank(USER);
        uint256 queryId = agent.submitQuery(DOC_URL, QUESTION);

        vm.expectEmit(true, false, false, true);
        emit RagAgent.DocFetched(queryId, DOC_CONTENT.length);

        agent.fetchDoc(queryId, address(0xBEEF), 300);
    }

    function test_fetchDoc_revertsOnInvalidQuery() public {
        vm.expectRevert(abi.encodeWithSelector(RagAgent.QueryNotFound.selector, 99));
        agent.fetchDoc(99, address(0xBEEF), 300);
    }

    function test_fetchDoc_revertsOnAlreadyAnswered() public {
        vm.prank(USER);
        uint256 queryId = agent.submitQuery(DOC_URL, QUESTION);
        agent.fetchDoc(queryId, address(0xBEEF), 300);
        agent.askQuestion(queryId, address(0xBEEF), 300);

        vm.expectRevert(abi.encodeWithSelector(RagAgent.AlreadyAnswered.selector, queryId));
        agent.fetchDoc(queryId, address(0xBEEF), 300);
    }

    // ── askQuestion ──────────────────────────────────────────────────────────

    function test_askQuestion_success() public {
        vm.prank(USER);
        uint256 queryId = agent.submitQuery(DOC_URL, QUESTION);
        agent.fetchDoc(queryId, address(0xBEEF), 300);
        agent.askQuestion(queryId, address(0xBEEF), 300);

        string memory answer = agent.getAnswer(queryId);
        assertEq(answer, string(LLM_ANSWER));

        RagAgent.Query memory q = agent.getQuery(queryId);
        assertTrue(q.answered);
        assertGt(q.answeredAt, 0);
    }

    function test_askQuestion_emitsEvent() public {
        vm.prank(USER);
        uint256 queryId = agent.submitQuery(DOC_URL, QUESTION);
        agent.fetchDoc(queryId, address(0xBEEF), 300);

        vm.expectEmit(true, false, false, false);
        emit RagAgent.AnswerReady(queryId, string(LLM_ANSWER));

        agent.askQuestion(queryId, address(0xBEEF), 300);
    }

    function test_askQuestion_revertsIfNoDoc() public {
        vm.prank(USER);
        uint256 queryId = agent.submitQuery(DOC_URL, QUESTION);

        vm.expectRevert(abi.encodeWithSelector(RagAgent.DocNotFetched.selector, queryId));
        agent.askQuestion(queryId, address(0xBEEF), 300);
    }

    function test_askQuestion_revertsOnDuplicateAnswer() public {
        vm.prank(USER);
        uint256 queryId = agent.submitQuery(DOC_URL, QUESTION);
        agent.fetchDoc(queryId, address(0xBEEF), 300);
        agent.askQuestion(queryId, address(0xBEEF), 300);

        vm.expectRevert(abi.encodeWithSelector(RagAgent.AlreadyAnswered.selector, queryId));
        agent.askQuestion(queryId, address(0xBEEF), 300);
    }

    function test_llmError_reverts() public {
        mockLlm.setError(true, "model unavailable");
        // Etch again with updated state
        vm.etch(address(0x0802), address(mockLlm).code);

        vm.prank(USER);
        uint256 queryId = agent.submitQuery(DOC_URL, QUESTION);
        agent.fetchDoc(queryId, address(0xBEEF), 300);

        vm.expectRevert(abi.encodeWithSelector(RagAgent.LLMFailed.selector, "model unavailable"));
        agent.askQuestion(queryId, address(0xBEEF), 300);
    }

    // ── Full flow ────────────────────────────────────────────────────────────

    function test_fullFlow() public {
        vm.prank(USER);
        uint256 queryId = agent.submitQuery(DOC_URL, QUESTION);
        assertEq(queryId, 1);

        agent.fetchDoc(queryId, address(0xBEEF), 300);

        RagAgent.Query memory q = agent.getQuery(queryId);
        assertEq(q.docContent, DOC_CONTENT);
        assertFalse(q.answered);

        agent.askQuestion(queryId, address(0xBEEF), 300);

        string memory answer = agent.getAnswer(queryId);
        assertEq(answer, string(LLM_ANSWER));
        assertTrue(agent.getQuery(queryId).answered);
    }

    function test_multipleQueries() public {
        vm.prank(USER);
        uint256 q1 = agent.submitQuery(DOC_URL, "Question 1");
        uint256 q2 = agent.submitQuery(DOC_URL, "Question 2");

        assertEq(q1, 1);
        assertEq(q2, 2);
        assertEq(agent.nextQueryId(), 3);
    }
}

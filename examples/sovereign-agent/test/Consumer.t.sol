// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import {SovereignAgentConsumer} from "../SovereignAgentConsumer.sol";

interface Vm {
    function prank(address) external;
    function mockCall(address, bytes calldata, bytes calldata) external;
    function expectRevert(bytes calldata) external;
}

contract SovereignAgentConsumerTest {
    Vm constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
    SovereignAgentConsumer consumer;
    address constant DELIVERY = address(0xD3);
    bytes32 constant JOB = bytes32(uint256(123));

    function setUp() public {
        consumer = new SovereignAgentConsumer(DELIVERY);
        vm.mockCall(address(0x0830), bytes(""), abi.encode(JOB));
        vm.mockCall(address(0x080C), bytes(""), abi.encode(bytes(""), bytes("phase1")));
    }

    function inputFor(address sponsor, address target, bytes32 context) internal view returns (bytes memory) {
        return abi.encode(
            address(0xE1),
            sponsor,
            uint64(500),
            uint64(6000),
            true,
            target,
            consumer.onSovereignAgentResult.selector,
            uint64(1000000),
            uint128(1000000000),
            uint128(100000000),
            uint256(0),
            context,
            bytes("payload")
        );
    }

    function submit() internal {
        bytes memory input = inputFor(address(this), address(consumer), bytes32(0));
        consumer.callSovereignAgent(input);
    }

    function testOwnerOnlySubmission() public {
        bytes memory input = inputFor(address(this), address(consumer), bytes32(0));
        vm.prank(address(0xBAD));
        vm.expectRevert(bytes("only owner"));
        consumer.callSovereignAgent(input);
    }

    function testSponsorAndCallbackBindings() public {
        bytes memory input = inputFor(address(0xBAD), address(consumer), bytes32(0));
        vm.expectRevert(bytes("invalid sponsor"));
        consumer.callSovereignAgent(input);
        input = inputFor(address(this), address(0xBAD), bytes32(0));
        vm.expectRevert(bytes("invalid callback target"));
        consumer.callSovereignAgent(input);
    }

    function testContextBinding() public {
        bytes memory input = inputFor(address(this), address(consumer), bytes32(uint256(1)));
        vm.expectRevert(bytes("unexpected application context"));
        consumer.callSovereignAgent(input);
    }

    function testExactJobCallbackAndReplayProtection() public {
        submit();
        require(consumer.pendingJobs(JOB), "origin not pending");
        vm.prank(address(0xBAD));
        vm.expectRevert(bytes("unauthorized callback sender"));
        consumer.onSovereignAgentResult(JOB, bytes("attack"));
        vm.prank(DELIVERY);
        vm.expectRevert(bytes("unknown job"));
        consumer.onSovereignAgentResult(bytes32(uint256(999)), bytes("foreign"));
        require(consumer.pendingJobs(JOB), "foreign callback changed pending job");
        vm.prank(DELIVERY);
        consumer.onSovereignAgentResult(JOB, bytes("result"));
        require(!consumer.pendingJobs(JOB), "job not cleared");
        require(keccak256(consumer.results(JOB)) == keccak256(bytes("result")), "wrong result");
        vm.prank(DELIVERY);
        vm.expectRevert(bytes("unknown job"));
        consumer.onSovereignAgentResult(JOB, bytes("replay"));
    }
}

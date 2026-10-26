// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import {PersistentAgentConsumer} from "../PersistentAgentConsumer.sol";

interface Vm {
    function prank(address) external;
    function mockCall(address, bytes calldata, bytes calldata) external;
    function expectRevert(bytes calldata) external;
}

contract PersistentAgentConsumerTest {
    Vm constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
    PersistentAgentConsumer consumer;
    address constant DELIVERY = address(0xD3);
    bytes32 constant JOB = bytes32(uint256(123));

    function setUp() public {
        consumer = new PersistentAgentConsumer(DELIVERY);
        vm.mockCall(address(0x0830), bytes(""), abi.encode(JOB));
        vm.mockCall(address(0x0820), bytes(""), abi.encode(bytes(""), bytes("phase1")));
    }

    function inputFor(address sponsor, address target, bytes32 context) internal view returns (bytes memory) {
        return abi.encode(
            address(0xE1),
            sponsor,
            uint64(500),
            uint64(6000),
            true,
            target,
            consumer.onPersistentAgentResult.selector,
            uint64(1000000),
            uint128(1000000000),
            uint128(100000000),
            uint256(0),
            context,
            bytes("payload")
        );
    }

    function submit() internal {
        bytes memory input = inputFor(address(this), address(consumer), keccak256(abi.encode(uint256(7), uint64(0))));
        consumer.callPersistentAgent(7, 0, input);
    }

    function testOwnerOnlySubmission() public {
        bytes memory input = inputFor(address(this), address(consumer), keccak256(abi.encode(uint256(7), uint64(0))));
        vm.prank(address(0xBAD));
        vm.expectRevert(bytes("only owner"));
        consumer.callPersistentAgent(7, 0, input);
    }

    function testSponsorAndCallbackBindings() public {
        bytes memory input = inputFor(address(0xBAD), address(consumer), keccak256(abi.encode(uint256(7), uint64(0))));
        vm.expectRevert(bytes("invalid sponsor"));
        consumer.callPersistentAgent(7, 0, input);
        input = inputFor(address(this), address(0xBAD), keccak256(abi.encode(uint256(7), uint64(0))));
        vm.expectRevert(bytes("invalid callback target"));
        consumer.callPersistentAgent(7, 0, input);
    }

    function testContextBinding() public {
        bytes memory input = inputFor(address(this), address(consumer), bytes32(uint256(1)));
        vm.expectRevert(bytes("invalid identity context"));
        consumer.callPersistentAgent(7, 0, input);
    }

    function testExactJobCallbackAndReplayProtection() public {
        submit();
        require(consumer.pendingJobs(JOB), "origin not pending");
        vm.prank(address(0xBAD));
        vm.expectRevert(bytes("unauthorized callback sender"));
        consumer.onPersistentAgentResult(JOB, bytes("attack"));
        vm.prank(DELIVERY);
        vm.expectRevert(bytes("unknown job"));
        consumer.onPersistentAgentResult(bytes32(uint256(999)), bytes("foreign"));
        require(consumer.pendingJobs(JOB), "foreign callback changed pending job");
        vm.prank(DELIVERY);
        consumer.onPersistentAgentResult(JOB, bytes("result"));
        require(!consumer.pendingJobs(JOB), "job not cleared");
        require(keccak256(consumer.results(JOB)) == keccak256(bytes("result")), "wrong result");
        vm.prank(DELIVERY);
        vm.expectRevert(bytes("unknown job"));
        consumer.onPersistentAgentResult(JOB, bytes("replay"));
    }
}

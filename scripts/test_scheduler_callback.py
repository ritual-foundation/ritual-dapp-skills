#!/usr/bin/env python3
"""Test the literal minimal scheduler callback with public forge.

Run: python3 scripts/test_scheduler_callback.py
This checks callback access/decoding with fixtures, not live scheduling.
"""
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]

if __name__ == '__main__':
    text = (ROOT / 'skills/ritual-dapp-scheduler/SKILL.md').read_text()
    source = next(block for block in re.findall(r'```solidity\n(.*?)\n```', text, re.S)
                  if 'contract MyScheduled ' in block)
    test = '''pragma solidity ^0.8.24;
import "./MyScheduled.sol";
interface Vm {
    function prank(address) external;
    function expectRevert(bytes calldata) external;
    function expectRevert() external;
}
contract CallbackTest {
    Vm constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
    MyScheduled consumer;
    address constant SCHEDULER = 0x4E0abeE2233D73E66382b45244F7459B34E1490E;
    function setUp() public { consumer = new MyScheduled(); }
    function testRejectsForeignCaller() public {
        vm.expectRevert(bytes("only scheduler"));
        consumer.onScheduledExecution(0, abi.encode(uint256(42)));
    }
    function testAcceptsSchedulerWithDocumentedPayload() public {
        vm.prank(SCHEDULER);
        consumer.onScheduledExecution(0, abi.encode(uint256(42)));
    }
    function testRejectsMalformedPayloadFromScheduler() public {
        vm.prank(SCHEDULER);
        vm.expectRevert();
        consumer.onScheduledExecution(0, "");
    }
}
'''
    with tempfile.TemporaryDirectory(prefix='ritual-scheduler-example-') as directory:
        path = Path(directory)
        (path / 'MyScheduled.sol').write_text(source + '\n')
        (path / 'Callback.t.sol').write_text(test)
        (path / 'foundry.toml').write_text('[profile.default]\nsrc="."\ntest="."\nsolc_version="0.8.28"\n')
        subprocess.run(['forge', 'test', '--root', directory, '-vv'], check=True)

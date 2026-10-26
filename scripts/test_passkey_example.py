#!/usr/bin/env python3
"""Compile and test the literal registered-key example with public Foundry tools.

Run: python3 scripts/test_passkey_example.py
Native responses are controlled fixtures; this does not claim a live-chain pass.
"""
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def source():
    document = (ROOT / 'skills/ritual-dapp-passkey/SKILL.md').read_text()
    return next(block for block in re.findall(r'```solidity\n(.*?)\n```', document, re.S)
                if 'contract PasskeyVerifier {' in block)


TEST = '''// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import "./PasskeyVerifier.sol";
interface Vm {
    function mockCall(address, bytes calldata, bytes calldata) external;
    function mockCallRevert(address, bytes calldata, bytes calldata) external;
    function expectRevert(bytes calldata) external;
}
contract PasskeyExampleTest {
    Vm constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
    PasskeyVerifier verifier;
    bytes key;
    function setUp() public {
        verifier = new PasskeyVerifier();
        key = new bytes(33);
        key[0] = 0x02;
        verifier.registerKey(key);
    }
    function response(bytes memory result) internal {
        vm.mockCall(address(0x0100), abi.encode(key, bytes("message"), bytes("signature")), result);
    }
    function testValidSignature() public {
        response(abi.encode(uint256(1)));
        require(verifier.verifyAction(address(this), "message", "signature"));
    }
    function testInvalidSignature() public {
        response(abi.encode(uint256(0)));
        require(!verifier.verifyAction(address(this), "message", "signature"));
    }
    function testEmptyAndMalformedResponses() public {
        response("");
        require(!verifier.verifyAction(address(this), "message", "signature"));
        response(hex"01");
        require(!verifier.verifyAction(address(this), "message", "signature"));
    }
    function testNativeRevert() public {
        vm.mockCallRevert(address(0x0100), abi.encode(key, bytes("message"), bytes("signature")), "");
        require(!verifier.verifyAction(address(this), "message", "signature"));
    }
    function testMissingRegistration() public {
        vm.expectRevert(bytes("No key registered"));
        verifier.verifyAction(address(123), "message", "signature");
    }
    function testRegistrationRejectsWrongLength() public {
        vm.expectRevert(bytes("Invalid compressed key"));
        verifier.registerKey(new bytes(32));
    }
}
'''


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='ritual-passkey-example-') as directory:
        path = Path(directory)
        (path / 'PasskeyVerifier.sol').write_text(source() + '\n')
        (path / 'PasskeyExample.t.sol').write_text(TEST)
        (path / 'foundry.toml').write_text('[profile.default]\nsrc="."\ntest="."\nsolc_version="0.8.28"\n')
        subprocess.run(['forge', 'test', '--root', directory, '-vv'], check=True)

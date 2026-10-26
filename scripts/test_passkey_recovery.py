#!/usr/bin/env python3
"""Test the literal application recovery registry; this cannot rotate a native EOA."""
from pathlib import Path
import re
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
TEST='''pragma solidity ^0.8.20;
import "./Registry.sol";
interface Vm {function prank(address) external;function warp(uint256) external;}
contract RecoveryTest {
 Vm constant vm=Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
 PasskeyRecoveryRegistry registry;
 function setUp() public {registry=new PasskeyRecoveryRegistry();vm.warp(10);registry.register(bytes32(uint256(1)),bytes32(uint256(2)),address(0x1234),100);}
 function begin() internal {vm.prank(address(0x1234));registry.initiateRecovery(address(this),bytes32(uint256(3)),bytes32(uint256(4)));}
 function testUnauthorizedRecoveryFails() public {
  (bool ok,)=address(registry).call(abi.encodeWithSelector(registry.initiateRecovery.selector,address(this),bytes32(uint256(3)),bytes32(uint256(4))));require(!ok);
 }
 function testRotationOnlyUpdatesRegistryAfterDelay() public {
  begin();(bool ok,)=address(registry).call(abi.encodeWithSelector(registry.executeRecovery.selector,address(this)));require(!ok);
  vm.warp(110);registry.executeRecovery(address(this));
  (bytes32 x,bytes32 y,,,,,)=registry.accounts(address(this));require(x==bytes32(uint256(3))&&y==bytes32(uint256(4)));
 }
 function testOwnerCancellationPreventsRotation() public {
  begin();registry.cancelRecovery();vm.warp(110);
  (bool ok,)=address(registry).call(abi.encodeWithSelector(registry.executeRecovery.selector,address(this)));require(!ok);
  (bytes32 x,bytes32 y,,,,,)=registry.accounts(address(this));require(x==bytes32(uint256(1))&&y==bytes32(uint256(2)));
 }
}
'''
if __name__=='__main__':
 text=(ROOT/'skills/ritual-dapp-passkey/SKILL.md').read_text()
 source=next(b for b in re.findall(r'```solidity\n(.*?)\n```',text,re.S) if 'contract PasskeyRecoveryRegistry {' in b)
 with tempfile.TemporaryDirectory(prefix='ritual-recovery-example-') as directory:
  p=Path(directory);(p/'Registry.sol').write_text(source);(p/'Recovery.t.sol').write_text(TEST)
  (p/'foundry.toml').write_text('[profile.default]\nsrc="."\ntest="."\nsolc_version="0.8.30"\n')
  subprocess.run(['forge','test','--root',directory,'-vv'],check=True)

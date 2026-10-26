#!/usr/bin/env python3
"""Execute literal HTTP/media consumers with controlled precompile and delivery fixtures."""
from pathlib import Path
import re
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parents[1]

def contract(skill, name):
    text = (ROOT / 'skills' / skill / 'SKILL.md').read_text()
    return next(b for b in re.findall(r'```solidity\n(.*?)\n```', text, re.S) if f'contract {name} {{' in b)

TEST = '''pragma solidity ^0.8.20;
import "./LongRunningHTTPConsumer.sol";
import "./MediaConsumer.sol";
import "./GenericConsumer.sol";
interface Vm {
 function mockCall(address,bytes calldata,bytes calldata) external;
 function mockCallRevert(address,bytes calldata,bytes calldata) external;
 function prank(address) external;
}
contract ProvenanceTest {
 Vm constant vm=Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
 address constant DELIVERY=0x508f57AE70967Da28AE0Ab6b95532878c4D0F440;
 bytes32 constant JOB=keccak256("origin");
 LongRunningHTTPConsumer http;
 MediaConsumer media;
 function setUp() public {
  http=new LongRunningHTTPConsumer(); media=new MediaConsumer();
  vm.mockCall(address(0x0830),"",abi.encode(JOB));
  vm.mockCall(address(0x0805),"",abi.encode(bytes(""),abi.encode("task-id")));
  vm.mockCall(address(0x0818),"",hex"00");
  vm.mockCall(address(0x0819),"",hex"00");
  vm.mockCall(address(0x081a),"",hex"00");
 }
 function httpResult() internal pure returns(bytes memory){return abi.encode(uint16(200),new string[](0),new string[](0),bytes("ok"),"");}
 function testGenericTransportAndJobChecks() public {
  GenericConsumer consumer=new GenericConsumer(); consumer.submit();
  vm.prank(DELIVERY);(bool ok,)=address(consumer).call(abi.encodeWithSelector(consumer.onResult.selector,bytes32(uint256(1)),bytes("")));require(!ok);
  (ok,)=address(consumer).call(abi.encodeWithSelector(consumer.onResult.selector,JOB,bytes("")));require(!ok);
  vm.prank(DELIVERY);consumer.onResult(JOB,"");require(!consumer.pendingJobs(JOB));
  vm.prank(DELIVERY);(ok,)=address(consumer).call(abi.encodeWithSelector(consumer.onResult.selector,JOB,bytes("")));require(!ok);
 }
 function testHTTPProvenanceAndReplay() public {
  http.initiateJob(hex"1234"); require(http.pendingJobs(JOB));
  (bool ok,)=address(http).call(abi.encodeWithSelector(http.onLongRunningResult.selector,JOB,httpResult())); require(!ok,"foreign sender");
  vm.prank(DELIVERY);
  (ok,)=address(http).call(abi.encodeWithSelector(http.onLongRunningResult.selector,bytes32(uint256(1)),httpResult())); require(!ok,"foreign job");
  vm.prank(DELIVERY); http.onLongRunningResult(JOB,httpResult()); require(!http.pendingJobs(JOB));
  require(http.getResult(JOB).statusCode==200);
  vm.prank(DELIVERY);
  (ok,)=address(http).call(abi.encodeWithSelector(http.onLongRunningResult.selector,JOB,httpResult())); require(!ok,"replayed callback");
 }
 function testHTTPSubmissionRevertRollsBackPending() public {
  vm.mockCallRevert(address(0x0805),"","");
  (bool ok,)=address(http).call(abi.encodeWithSelector(http.initiateJob.selector,bytes(hex"1234")));
  require(!ok);require(!http.pendingJobs(JOB));
 }
 function submitMedia(uint8 kind) internal {
  MediaConsumer.StorageRef memory ref=MediaConsumer.StorageRef("gcs","test/output","GCS_CREDS");
  if(kind==1)media.requestImage(address(1),60,"prompt","model",1024,768,ref,new bytes[](0),new address[](0),new bytes[](0));
  if(kind==2)media.requestAudio(address(1),60,"prompt","model",1000,ref,new bytes[](0),new address[](0),new bytes[](0));
  if(kind==3)media.requestVideo(address(1),60,"prompt","model",1024,768,1000,ref,new bytes[](0),new address[](0),new bytes[](0));
 }
 function mediaResult(uint8 kind) internal pure returns(bytes memory){
  if(kind==1)return abi.encode(false,bytes(""),"gcs://test/image",bytes32(0),false,uint32(10),uint32(20),uint32(1),"");
  if(kind==2)return abi.encode(false,bytes(""),"gcs://test/audio",bytes32(0),false,uint32(10),uint32(20),"");
  return abi.encode(false,bytes(""),"gcs://test/video",bytes32(0),false,uint32(10),uint32(20),uint32(30),uint32(40),"");
 }
 function mediaCallback(uint8 kind, bytes32 job,bytes memory result) internal pure returns(bytes memory){
  return abi.encodeWithSelector(kind==1?MediaConsumer.onImageReady.selector:kind==2?MediaConsumer.onAudioReady.selector:MediaConsumer.onVideoReady.selector,job,result);
 }
 function checkMedia(uint8 kind) internal {
  submitMedia(kind);require(media.pendingJobs(JOB));
  (bool ok,)=address(media).call(mediaCallback(kind,JOB,mediaResult(kind)));require(!ok,"foreign sender");
  vm.prank(DELIVERY);(ok,)=address(media).call(mediaCallback(kind,bytes32(uint256(1)),mediaResult(kind)));require(!ok,"foreign job");
  vm.prank(DELIVERY);(ok,)=address(media).call(mediaCallback(kind,JOB,hex"12"));require(!ok,"malformed result");require(media.pendingJobs(JOB));
  vm.prank(DELIVERY);(ok,)=address(media).call(mediaCallback(kind,JOB,mediaResult(kind)));require(ok,"expected callback");
  require(!media.pendingJobs(JOB));require(media.getResultCount()==1);
  vm.prank(DELIVERY);(ok,)=address(media).call(mediaCallback(kind,JOB,mediaResult(kind)));require(!ok,"replay");
  require(media.getResultCount()==1);
 }
 function testImageProvenanceAndReplay() public {checkMedia(1);}
 function testAudioProvenanceAndReplay() public {checkMedia(2);}
 function testVideoProvenanceAndReplay() public {checkMedia(3);}
 function testMissingTransactionHashFailsClosed() public {
  vm.mockCall(address(0x0830),"","");
  (bool ok,)=address(http).call(abi.encodeWithSelector(http.initiateJob.selector,bytes(hex"1234")));
  require(!ok);require(!http.pendingJobs(JOB));
 }
}
'''
if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='ritual-callback-provenance-') as directory:
        p = Path(directory)
        for skill, name in [('ritual-dapp-longrunning','LongRunningHTTPConsumer'),('ritual-dapp-multimodal','MediaConsumer')]:
            (p / f'{name}.sol').write_text(contract(skill,name))
        doc = (ROOT / 'skills/ritual-dapp-contracts/SKILL.md').read_text()
        fragment = next(b for b in re.findall(r'```solidity\n(.*?)\n```',doc,re.S) if 'function _trackCurrentJob()' in b and 'function onResult(' in b)
        (p / 'GenericConsumer.sol').write_text('pragma solidity ^0.8.20;\ncontract GenericConsumer {\n'+fragment+'\nfunction submit() external {_trackCurrentJob();}\n}')
        (p / 'Provenance.t.sol').write_text(TEST)
        (p / 'foundry.toml').write_text('[profile.default]\nsrc="."\ntest="."\nsolc_version="0.8.30"\noptimizer=true\nvia_ir=true\n')
        subprocess.run(['forge','test','--root',directory,'-vv'],check=True)

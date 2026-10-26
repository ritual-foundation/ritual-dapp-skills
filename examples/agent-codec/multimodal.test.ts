import { test, expect } from 'bun:test';
import { readFileSync, writeFileSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { encodeAbiParameters, decodeAbiParameters, parseAbiParameters, toFunctionSelector, type Hex } from 'viem';
const document = readFileSync(new URL('../../skills/ritual-dapp-multimodal/SKILL.md', import.meta.url), 'utf8');
const contract = [...document.matchAll(/```solidity\n([\s\S]*?)\n```/g)].map(m=>m[1]).find(code=>code.includes('contract MediaConsumer {'))!;
const schema = document.match(/const encoded = encodeAbiParameters\(\s*(\[[\s\S]*?\n  \]),/)!;
const types = new Function(`return (${schema[1]});`)();
// Canonical 20-field schema, independent of the documentation-defined types.
const canonicalTypes = parseAbiParameters('address,address,address[],bytes[],uint256,bytes[],bytes,uint64,uint64,string,address,bytes4,uint256,uint256,uint256,uint256,string,(uint8,bytes,string,bytes32,uint32,uint32,bool)[],(uint8,uint32,uint32,uint32,bool,uint16,uint16,uint32,uint8,string),(string,string,string)');

test('literal Solidity builder matches canonical 20-field viem ABI for image/audio/video', () => {
  expect(types.length).toBe(20);
  const executor='0x'+'11'.repeat(20), sponsor='0x'+'22'.repeat(20), owner='0x'+'33'.repeat(20);
  const encrypted=['0x123456'], signatures=['0xabcd'];
  const expected=[1,2,3].map(outputType=>encodeAbiParameters(canonicalTypes,[executor as Hex,sponsor as Hex,[owner as Hex],encrypted as Hex[],60n,signatures as Hex[],'0x',5n,1000n,
    ['IMAGE_TASK_ID','AUDIO_TASK_ID','VIDEO_TASK_ID'][outputType-1],sponsor,
    toFunctionSelector(['onImageReady(bytes32,bytes)','onAudioReady(bytes32,bytes)','onVideoReady(bytes32,bytes)'][outputType-1]),
    500_000n,1_000_000_000n,100_000_000n,0n,'test-model',
    [[0,'0x68656c6c6f','',('0x'+'00'.repeat(32)) as Hex,0,0,false]],
    [outputType,1024,768,1000,false,0,0,0,0,''],
    ['gcs','test/output','GCS_CREDS']]));
  for (const bytes of expected) expect(encodeAbiParameters(types, decodeAbiParameters(canonicalTypes, bytes))).toBe(bytes);
  const directory=mkdtempSync(join(tmpdir(),'ritual-media-codec-'));
  try {

    writeFileSync(join(directory,'foundry.toml'),'[profile.default]\nsrc="."\ntest="."\nsolc_version="0.8.30"\noptimizer=true\nvia_ir=true\n');
    const testSource=`pragma solidity ^0.8.20;
import "./MediaConsumer.sol";
interface Vm { function etch(address,bytes calldata) external; }
contract ExposedMedia {
 function build(uint8 kind, string calldata prompt, string calldata model, StorageRef calldata storageRef) external view returns(bytes memory) {
   bytes[] memory secrets=new bytes[](1); secrets[0]=hex"123456";
   bytes[] memory signatures=new bytes[](1); signatures[0]=hex"abcd";
   address[] memory owners=new address[](1); owners[0]=address(0x3333333333333333333333333333333333333333);
   return _buildMultiModalInput(address(0x1111111111111111111111111111111111111111),60,prompt,model,1024,768,1000,
    storageRef,secrets,owners,signatures,
    kind==1?"IMAGE_TASK_ID":kind==2?"AUDIO_TASK_ID":"VIDEO_TASK_ID",
    kind==1?this.onImageReady.selector:kind==2?this.onAudioReady.selector:this.onVideoReady.selector,kind);
 }
}
contract MediaCodecTest {
 Vm constant vm=Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
 ExposedMedia media=ExposedMedia(0x2222222222222222222222222222222222222222);
 function setUp() public { ExposedMedia implementation=new ExposedMedia(); vm.etch(address(media),address(implementation).code); }
 ${expected.map((hex,i)=>`function test${['Image','Audio','Video'][i]}CanonicalEncoding() public view { require(keccak256(media.build(${i+1},"hello","test-model",ExposedMedia.StorageRef("gcs","test/output","GCS_CREDS")))==keccak256(hex"${hex.slice(2)}"),"canonical 20-field ABI mismatch"); }`).join('\n')}
}`;
    const accessor=testSource.match(/contract ExposedMedia \{([\s\S]*?)\n\}\ncontract MediaCodecTest/)[1];
    writeFileSync(join(directory,'MediaConsumer.sol'),contract.replace('contract MediaConsumer {','contract ExposedMedia {').replace(/\}\s*$/,accessor+'\n}'));
    writeFileSync(join(directory,'MediaCodec.t.sol'),testSource.replace(/contract ExposedMedia \{[\s\S]*?\n\}\ncontract MediaCodecTest/,'contract MediaCodecTest'));
    const result=spawnSync('forge',['test','--root',directory,'-vv'],{encoding:'utf8'});
    if(result.error) throw result.error;
    console.log(result.stdout);
    if(result.status!==0) throw new Error(result.stderr+result.stdout);
    expect(result.status).toBe(0);
  } finally { rmSync(directory,{recursive:true,force:true}); }
},120_000);

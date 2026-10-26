import { test, expect } from 'bun:test';
import { readFileSync } from 'node:fs';
import React from 'react';
import { create, act } from 'react-test-renderer';
import { formatEther } from 'viem';
const text=readFileSync(new URL('../../skills/ritual-dapp-wallet/SKILL.md',import.meta.url),'utf8');
const block=[...text.matchAll(/```typescript\n([\s\S]*?)\n```/g)].map(m=>m[1]).find(b=>b.includes('function WalletBalance()'))!;
const source=block.replace(/^import[^;]+;\s*/gm,'');
const code=new Bun.Transpiler({loader:'tsx',tsconfig:{compilerOptions:{jsx:'react'}}}).transformSync(source);
for(const [name,address,available,reserved,expected] of [
  ['unloaded','0x11',undefined,undefined,['Available: ... RITUAL','Reserved: ... RITUAL']],
  ['zero','0x11',0n,0n,['Available: 0 RITUAL','Reserved: 0 RITUAL']],
  ['mixed','0x11',1000000000000000000n,0n,['Available: 1 RITUAL','Reserved: 0 RITUAL']],
  ['disconnected',undefined,undefined,undefined,['Connect wallet']],
] as const) test(`literal wallet component renders ${name}`,async()=>{
  const Component=new Function('React','useAccount','useReadContract','formatEther',code+'\nreturn WalletBalance;')(
    React,()=>({address}),({functionName}:any)=>({data:functionName==='availableBalance'?available:reserved}),formatEther);
  let view:any;await act(async()=>{view=create(<Component/>);});
  const flatten=(v:any):string=>typeof v==='string'?v:Array.isArray(v)?v.map(flatten).join(''):v?.children?flatten(v.children):'';
  const output=flatten(view.toJSON());for(const value of expected) expect(output).toContain(value);view.unmount();
});

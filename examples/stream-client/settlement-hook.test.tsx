import {test,expect} from 'bun:test';
import {readFileSync} from 'node:fs';
import React,{useEffect,useCallback} from 'react';import {create,act} from 'react-test-renderer';
import {create as createStore} from 'zustand';
import {encodeEventTopics,type Hex} from 'viem';
import {readShortSettlement,InvalidSettlement,JOB_REMOVED} from 'ritual-short-settlement';
const document=readFileSync(new URL('../../skills/ritual-dapp-frontend/SKILL.md',import.meta.url),'utf8');
const block=[...document.matchAll(/```typescript\n([\s\S]*?)\n```/g)].map(m=>m[1]).find(b=>b.includes('export function useAsyncJobEvents'))!;
const code=new Bun.Transpiler({loader:'ts'}).transformSync(block.replace(/^import[^;]+;\s*/gm,'').replace('export function','function'));
const hash=('0x'+'11'.repeat(32)) as Hex,settlement=('0x'+'22'.repeat(32)) as Hex;
const tracker='0xf00385449fD961925A0B125F5f30b29B682D4bFb',executor='0x'+'33'.repeat(20),precompile='0x0000000000000000000000000000000000000801';
async function fixture({completed=true,foreign=false,temporaryFailure=false,resume=false,replayOnly=false}={}){
 const initial=resume?{status:'PENDING_SETTLEMENT',txHash:hash,jobId:hash,deliveryTxHash:settlement}:{status:'COMMITTED',txHash:hash,jobId:hash,executor,committedBlock:1};
 const store=createStore<any>((set,get)=>({transactions:{test:{precompileType:'http',state:initial}},getTransaction:(id:string)=>get().transactions[id],updateState:(id:string,state:any)=>set({transactions:{...get().transactions,[id]:{...get().transactions[id],state}}})}));
 const handlers:any={},timers=new Map<number,()=>void>();let timerId=0,calls=0;
 const client={getContractEvents:async()=>replayOnly?[{args:{jobId:hash,completed:true},transactionHash:settlement}]:[],getTransactionReceipt:async()=>{
  calls++;if(temporaryFailure&&calls===1)throw Error('receipt not ready');
  return {transactionHash:settlement,status:'success',blockNumber:2n,gasUsed:7n,spcCalls:[{address:precompile,output:'0xabcd'}],logs:[{address:tracker,data:'0x',topics:encodeEventTopics({abi:[JOB_REMOVED],eventName:'JobRemoved',args:{executor:executor as Hex,jobId:hash,completed:true}})}]};
 }};
 const hook=new Function('useWatchContractEvent','useAccount','usePublicClient','useAsyncTxStore','useEffect','readShortSettlement','InvalidSettlement','useCallback','setInterval','clearInterval',code+'\nreturn useAsyncJobEvents;')(
  (options:any)=>{handlers[options.eventName]=options.onLogs;},()=>({address:executor}),()=>client,store,useEffect,readShortSettlement,InvalidSettlement,useCallback,
  (callback:()=>void)=>{timers.set(++timerId,callback);return timerId;},(id:number)=>timers.delete(id));
 function Probe(){hook({txId:'test'});return null;}
 let view:any;await act(async()=>{view=create(<Probe/>);});
 if(!resume&&!replayOnly)await act(async()=>{handlers.JobRemoved([{args:{jobId:foreign?'0x'+'99'.repeat(32):hash,completed},transactionHash:settlement}]);});
 return {store,handlers,tick:()=>{for(const fn of [...timers.values()])fn();},calls:()=>calls,unmount:()=>view.unmount()};
}
test('literal job hook consumes JobRemoved then verified receipt and ignores duplicate terminal events',async()=>{
 const f=await fixture();try{
  expect(f.store.getState().transactions.test.state).toMatchObject({status:'SETTLED',txHash:hash,settlementTxHash:settlement,result:{output:'0xabcd'}});
  await act(async()=>{f.handlers.JobRemoved([{args:{jobId:hash,completed:true},transactionHash:settlement}]);});expect(f.calls()).toBe(1);
 }finally{f.unmount();}
});
test('literal hook rejects foreign job events and handles failed cleanup without reading results',async()=>{
 for(const options of [{foreign:true},{completed:false}]){const f=await fixture(options);try{expect(f.store.getState().transactions.test.state.status).toBe(options.foreign?'COMMITTED':'FAILED');expect(f.calls()).toBe(0);}finally{f.unmount();}}
});
test('literal hook retries a temporarily unavailable receipt and resumes persisted settlement',async()=>{
 const f=await fixture({temporaryFailure:true});try{
  expect(f.store.getState().transactions.test.state.status).toBe('PENDING_SETTLEMENT');
  await act(async()=>{f.tick();await Promise.resolve();});expect(f.store.getState().transactions.test.state.status).toBe('SETTLED');
 }finally{f.unmount();}
 const resumed=await fixture({resume:true});try{expect(resumed.store.getState().transactions.test.state.status).toBe('SETTLED');}finally{resumed.unmount();}
});

test('literal hook replays a terminal event missed during unmount',async()=>{
 const f=await fixture({replayOnly:true});try{expect(f.store.getState().transactions.test.state.status).toBe('SETTLED');expect(f.calls()).toBe(1);}finally{f.unmount();}
});

test('literal HTTP submitter captures its replay block before sending',async()=>{
 const source=[...document.matchAll(/```typescript\n([\s\S]*?)\n```/g)].map(m=>m[1]).find(b=>b.includes('export function useHTTPCall'))!;
 const compiled=new Bun.Transpiler({loader:'ts'}).transformSync(source.replace(/^import[^;]+;\s*/gm,'').replace('export function','function'));
 const trace:string[]=[];let submitted:any;
 const store=createStore<any>((set,get)=>({transactions:{},addTransaction:(id:string)=>set({transactions:{...get().transactions,[id]:{state:{status:'SUBMITTING'}}}}),updateState:(id:string,state:any)=>{submitted=state;set({transactions:{...get().transactions,[id]:{state}}});}}));
 const client={getBlockNumber:async()=>{trace.push('block');return 12n;}},wallet={sendTransaction:async()=>{trace.push('send');return hash;}};
 const hook=new Function('useId','useCallback','useWalletClient','usePublicClient','useAsyncTxStore','useAsyncJobEvents','encodeHTTPCallRequest',compiled+'\nreturn useHTTPCall;')(
  React.useId,React.useCallback,()=>({data:wallet}),()=>client,store,()=>{},()=> '0x1234');
 let active:any,view:any;function Probe(){active=hook();return null;}
 await act(async()=>{view=create(<Probe/>);});
 try{await act(async()=>{await active.submit({executor,sponsor:executor,url:'https://example.com'});});expect(trace).toEqual(['block','send']);expect(submitted).toMatchObject({status:'PENDING_COMMITMENT',txHash:hash,submittedBlock:12n});}finally{view.unmount();}
});

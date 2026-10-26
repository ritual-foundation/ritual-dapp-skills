import { expect, test, afterEach } from 'bun:test';
import {readFileSync} from 'node:fs';
import React,{useState,useCallback,useRef} from 'react';
import {create,act} from 'react-test-renderer';
const text=readFileSync(new URL('../../skills/ritual-dapp-llm/SKILL.md',import.meta.url),'utf8');
const block=[...text.matchAll(/```typescript\n([\s\S]*?)\n```/g)].map(x=>x[1]).find(x=>x.includes('export function useStreamingLLM'))!;
const code=block.replace(/^import[^;]+;\s*/gm,'').replace('export function','function');
const output=new Bun.Transpiler({loader:'ts'}).transformSync(code);
const owner=`0x${'11'.repeat(20)}`;const hash=`0x${'33'.repeat(32)}`;
const wallet={sendTransaction:async()=>hash,signTypedData:async()=>`0x${'22'.repeat(65)}`};
const {useStreamingLLM}=new Function('useState','useCallback','useRef','useAccount','useWalletClient',output+'\nreturn {useStreamingLLM};')(useState,useCallback,useRef,()=>({address:owner}),()=>({data:wallet}));
const oldFetch=globalThis.fetch;
afterEach(()=>globalThis.fetch=oldFetch);
for(const [label,frames,expected] of [
 ['truncated EOF','data: {"token":"partial"}\n\n','error'],
 ['terminal marker','data: {"token":"answer"}\n\ndata: [DONE]\n\n','done'],
] as const){
 test('literal React streaming hook handles '+label,async()=>{
  globalThis.fetch=(async()=>new Response(new ReadableStream({start(c){c.enqueue(new TextEncoder().encode(frames));c.close();}}))) as typeof fetch;
  let hook:any;function Probe(){hook=useStreamingLLM({executor:owner,encryptedSecrets:['0xab'],secretOwners:[owner],secretSignatures:['0xcd'],streamingServiceUrl:'https://stream.invalid'});return null;}
  let renderer:any;await act(async()=>{renderer=create(<Probe/>);});
  await act(async()=>{await hook.submit('hello');});
  expect(hook.state.status).toBe(expected);
  if(expected==='error')expect(hook.state.error).toContain('completion');
  else expect(hook.state.text).toBe('answer');
  renderer.unmount();
 });
}

// The frontend skill has a separate streaming-only hook with the same EOF boundary.
const frontendDocument = readFileSync(new URL('../../skills/ritual-dapp-frontend/SKILL.md', import.meta.url), 'utf8');
const frontendBlock = [...frontendDocument.matchAll(/```typescript\n([\s\S]*?)\n```/g)]
  .map(match => match[1]).find(block => block.includes('export function useStreamingLLM'))!;
const frontendCode = frontendBlock.replace(/^import[^;]+;\s*/gm, '').replace('export function', 'function');
const frontendOutput = new Bun.Transpiler({ loader: 'ts' }).transformSync(frontendCode);
const frontendHook = new Function('useState', 'useCallback', 'useRef', 'useWalletClient',
  frontendOutput + '\nreturn useStreamingLLM;')(useState, useCallback, useRef, () => ({ data: wallet }));

for (const complete of [false, true]) {
  test(`literal frontend stream hook ${complete ? 'completes explicitly' : 'rejects premature EOF'}`, async () => {
    const frames = 'data: {"token":"answer"}\n\n' + (complete ? 'data: [DONE]\n\n' : '');
    globalThis.fetch = (async () => new Response(new ReadableStream({ start(controller) {
      controller.enqueue(new TextEncoder().encode(frames)); controller.close();
    } }))) as typeof fetch;
    let hook: any;
    function Probe() { hook = frontendHook('https://stream.invalid'); return null; }
    let renderer: any;
    await act(async () => { renderer = create(<Probe />); });
    await act(async () => {
      if (complete) await hook.stream(hash);
      else await expect(hook.stream(hash)).rejects.toThrow('completion');
    });
    expect(hook.state.status).toBe(complete ? 'done' : 'error');
    expect(hook.state.text).toBe('answer');
    renderer.unmount();
  });
}

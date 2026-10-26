import { test, expect } from 'bun:test';
import { readFileSync } from 'node:fs';
const text=readFileSync(new URL('../../site/index.html',import.meta.url),'utf8');
const start=text.indexOf('    let replayPromise = null;');
if(start<0)throw new Error('Replay singleton missing');
const source=text.slice(start,text.indexOf('\n  })();',start));
function fixture(fail=false){
  let cycles=0,attempts=0;const timers:Array<()=>void>=[];
  const el={set innerHTML(_v:string){cycles++;},appendChild:()=>{}};
  const element=()=>({style:{},appendChild:()=>{},remove:()=>{}});
  const window:any={};
  new Function('el','document','createSpinner','createCursor','streamText','deleteText','lines','setTimeout','window','console',source)(
    el,{createElement:element},()=>({el:element(),stop:()=>{}}),element,
    async()=>{attempts++;if(fail&&attempts===1)throw new Error('controlled replay error');},async()=>{},[],
    (f:()=>void)=>timers.push(f),window,{error:()=>{}});
  return {window,timers,cycles:()=>cycles};
}
const flush=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};
test('repeated slide entry shares one active replay promise',async()=>{
  const f=fixture();const first=f.window._startAgentReplay();expect(f.window._startAgentReplay()).toBe(first);
  await flush();expect(f.cycles()).toBe(1);expect(f.window._startAgentReplay()).toBe(first);
});
test('one loop continues iteratively across replay cycles',async()=>{
  const f=fixture();const first=f.window._startAgentReplay();await flush();
  for(let i=0;i<6;i++){f.timers.shift()!();await flush();}
  expect(f.cycles()).toBe(3);expect(f.window._startAgentReplay()).toBe(first);
});
test('an unexpected replay failure allows a later restart',async()=>{
  const f=fixture(true);const first=f.window._startAgentReplay();await first;
  const next=f.window._startAgentReplay();expect(next).not.toBe(first);await flush();expect(f.cycles()).toBe(2);
});

import { test, expect } from 'bun:test';
import { readFileSync } from 'node:fs';

for (const skill of ['frontend', 'deploy']) {
  const text=readFileSync(new URL(`../../skills/ritual-dapp-${skill}/SKILL.md`,import.meta.url),'utf8');
  const source=text.match(/```typescript\n(\/\/ app\/api\/rpc\/route.ts[\s\S]*?)\n```/)![1]
    .replace(/^import[^;]+;\s*/gm,'').replace('export async function POST','async function POST');
  function setup(impl: (...args:any[])=>Promise<Response> = async()=>Response.json({result:'0x310'})) {
    let calls:any[]=[];
    const fetcher=async(...args:any[])=>{calls.push(args);return impl(...args);};
    const code=new Bun.Transpiler({loader:'ts'}).transformSync(source);
    const POST=new Function('NextResponse','fetch','process',code+'\nreturn POST;')(Response,fetcher,{env:{RITUAL_RPC_URL:'http://rpc.invalid'}});
    return {POST,calls};
  }
  const request=(raw:string,headers:any={})=>new Request('http://app.invalid/api/rpc',{method:'POST',body:raw,headers});
  for (const [name,raw,status] of [
    ['malformed JSON','{',400],['batch','[]',400],['null','null',400],
    ['wrong version',JSON.stringify({jsonrpc:'1.0',method:'eth_chainId',id:1}),400],
    ['invalid id',JSON.stringify({jsonrpc:'2.0',method:'eth_chainId',id:{}}),400],
    ['invalid params',JSON.stringify({jsonrpc:'2.0',method:'eth_chainId',params:'bad',id:1}),400],
    ['privileged method',JSON.stringify({jsonrpc:'2.0',method:'admin_peers',id:1}),403],
    ['unlocked send',JSON.stringify({jsonrpc:'2.0',method:'eth_sendTransaction',id:1}),403],
    ['oversize body',' '.repeat(100001),413],
  ] as const) test(`${skill} proxy rejects ${name} without upstream forwarding`,async()=>{
    const {POST,calls}=setup();const response=await POST(request(raw));
    expect(response.status).toBe(status);expect(calls.length).toBe(0);
    expect(response.headers.get('cache-control')).toBe('no-store');
  });
  test(`${skill} proxy honors declared body limit`,async()=>{
    const {POST,calls}=setup();expect((await POST(request('{}',{'content-length':'100001'}))).status).toBe(413);expect(calls.length).toBe(0);
  });
  test(`${skill} proxy preserves upstream status, body and no-store`,async()=>{
    const raw=JSON.stringify({jsonrpc:'2.0',method:'eth_chainId',id:17});
    const {POST,calls}=setup(async()=>new Response('quota exceeded',{status:429,headers:{'content-type':'text/plain'}}));
    const response=await POST(request(raw));expect(response.status).toBe(429);expect(await response.text()).toBe('quota exceeded');
    expect(calls[0][1].body).toBe(raw);expect(calls[0][1].cache).toBe('no-store');
    expect(calls[0][1].signal).toBeInstanceOf(AbortSignal);expect(response.headers.get('cache-control')).toBe('no-store');
  });
  test(`${skill} proxy preserves an empty upstream response`,async()=>{
    const {POST}=setup(async()=>new Response(null,{status:204}));
    const response=await POST(request(JSON.stringify({jsonrpc:'2.0',method:'eth_chainId',id:1})));
    expect(response.status).toBe(204);expect(await response.text()).toBe('');
  });
  test(`${skill} proxy maps upstream timeout/error to correlated RPC error`,async()=>{
    const {POST}=setup(async()=>{throw new Error('secret-upstream-detail');});
    const response=await POST(request(JSON.stringify({jsonrpc:'2.0',method:'eth_chainId',id:'test'})));
    expect(response.status).toBe(504);expect(await response.json()).toEqual({jsonrpc:'2.0',id:'test',error:{code:-32000,message:'RPC upstream unavailable'}});
  });
}

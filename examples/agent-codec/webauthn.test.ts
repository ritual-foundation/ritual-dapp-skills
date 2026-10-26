import { test, expect } from 'bun:test';
import { readFileSync } from 'node:fs';
import { generateKeyPairSync, sign, verify, webcrypto } from 'node:crypto';
import { keccak256, concat, toHex, toBytes, getAddress } from 'viem';
const text=readFileSync(new URL('../../skills/ritual-dapp-passkey/SKILL.md',import.meta.url),'utf8');
const blocks=[...text.matchAll(/```typescript\n([\s\S]*?)\n```/g)].map(m=>m[1]);
const source=['function parseDerSignature','function normalizeS','async function passkeyLogin'].map(selector=>blocks.find(b=>b.includes(selector))!.replace(/^import[^;]+;\s*/gm,'').split('const { r, s, authenticatorData')[0]).join('\n');
const code=new Bun.Transpiler({loader:'ts'}).transformSync(source);
const key=generateKeyPairSync('ec',{namedCurve:'prime256v1'});
const jwk=key.publicKey.export({format:'jwk'});
const hex=(v:string)=>'0x'+Buffer.from(v,'base64url').toString('hex');
async function login(change:any={}) {
  const challenge=Buffer.alloc(32,7);
  const client={type:'webauthn.get',origin:'https://app.invalid',challenge:challenge.toString('base64url'),...change};
  const clientJSON=Buffer.from(JSON.stringify(client)), auth=Buffer.alloc(37,1);
  const hash=await webcrypto.subtle.digest('SHA-256',clientJSON);
  const message=Buffer.concat([auth,Buffer.from(hash)]);
  const signature=sign('sha256',message,key.privateKey);
  const navigator={credentials:{get:async()=>({id:'test',response:{clientDataJSON:clientJSON,authenticatorData:auth,signature}})}};
  const verifyOnChain=async(_pub:string,msg:string,sig:string)=>{
    expect(Buffer.from(msg.slice(2),'hex')).toEqual(message);
    expect(verify('sha256',challenge,{key:key.publicKey,dsaEncoding:'ieee-p1363'},Buffer.from(sig.slice(2),'hex'))).toBe(false);
    return verify('sha256',Buffer.from(msg.slice(2),'hex'),{key:key.publicKey,dsaEncoding:'ieee-p1363'},Buffer.from(sig.slice(2),'hex'));
  };
  const fn=new Function('keccak256','concat','toHex','toBytes','getAddress','navigator','crypto','window','localStorage','verifyP256OnChain',code+'\nreturn passkeyLogin;')(
    keccak256,concat,toHex,toBytes,getAddress,navigator,{getRandomValues:(a:Uint8Array)=>{a.fill(7);return a;},subtle:webcrypto.subtle},
    {location:{origin:'https://app.invalid'}},{getItem:()=>JSON.stringify({x:hex(jwk.x!),y:hex(jwk.y!)})},verifyOnChain);
  return fn();
}
test('literal login verifies complete generated WebAuthn signed message, not raw challenge',async()=>{expect((await login()).isValid).toBe(true);});
for(const [name,change] of [
  ['ceremony',{type:'webauthn.create'}],['origin',{origin:'https://other.invalid'}],
  ['challenge',{challenge:Buffer.alloc(32,8).toString('base64url')}],['short challenge',{challenge:'AA'}],
] as const) test(`literal login rejects signed but mismatched ${name}`,async()=>{await expect(login(change)).rejects.toThrow(name === 'ceremony' ? 'ceremony type' : name === 'origin' ? 'origin mismatch' : 'challenge mismatch');});
test('native address derivation changes with the P256 key',()=>{
  const other=generateKeyPairSync('ec',{namedCurve:'prime256v1'}).publicKey.export({format:'jwk'});
  const address=(k:any)=>getAddress(`0x${keccak256(concat([hex(k.x),hex(k.y)] as any)).slice(26)}`);
  expect(address(jwk)).not.toBe(address(other));
});

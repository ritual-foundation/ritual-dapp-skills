import { test, expect } from 'bun:test';
import { readFileSync } from 'node:fs';
import { parseAbiParameters, encodeAbiParameters, decodeAbiParameters, toHex } from 'viem';
const text=readFileSync(new URL('../../skills/ritual-dapp-secrets/SKILL.md',import.meta.url),'utf8');
const shared=text.match(/const HTTP_CALL_ABI = parseAbiParameters\(([\s\S]*?)\);/)![1];
const ABI=new Function('parseAbiParameters','return parseAbiParameters('+shared+');')(parseAbiParameters);
const calls=[...text.matchAll(/encodeAbiParameters\(HTTP_CALL_ABI,\s*(\[[\s\S]*?^\s*\])\);/gm)];
const address='0x'+'11'.repeat(20);
const context={executorAddress:address,account:{address},encryptedSecrets:['0x1234'],signature:'0xabcd',
  userPublicKey:'0x',zodiacSign:'aries',ownerAddress:address,ownerEncryptedSecrets:['0x5678'],ownerSignature:'0xabcd',toHex};
test('secrets shared HTTP ABI has canonical 16 fields and seven call sites',()=>{expect(ABI.length).toBe(16);expect(calls.length).toBe(7);});
for(const [index,call] of calls.entries()) test(`secrets literal shared HTTP argument list ${index+1} encodes and round-trips`,()=>{
  const code=new Bun.Transpiler({loader:'ts'}).transformSync('const values = '+call[1]+';');
  const values=new Function(...Object.keys(context),code+'\nreturn values;')(...Object.values(context));
  const bytes=encodeAbiParameters(ABI,values);const decoded=decodeAbiParameters(ABI,bytes);
  expect(decoded.length).toBe(16);expect(decoded[8]).toBeGreaterThanOrEqual(1);expect(decoded[8]).toBeLessThanOrEqual(5);
  expect(encodeAbiParameters(ABI,decoded)).toBe(bytes);expect(decoded.slice(12,15)).toEqual([0n,0,false]);
});

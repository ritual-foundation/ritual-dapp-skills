import { test, expect } from 'bun:test';
import { readFileSync } from 'node:fs';
import { encrypt, decrypt, PrivateKey, ECIES_CONFIG } from 'eciesjs';
const document = readFileSync(new URL('../../skills/ritual-dapp-agents/SKILL.md', import.meta.url), 'utf8');
const line = document.split('\n').find(line => line.startsWith('const encryptedSecret = encrypt('))!;
for (const compressed of [true, false]) {
  test(`literal sovereign encryption round-trips ${compressed ? 'compressed' : 'uncompressed'} registry key`, () => {
    ECIES_CONFIG.symmetricNonceLength = 12;
    const key = new PrivateKey();
    const executorPublicKey = `0x${key.publicKey.toHex(compressed)}`;
    const secretEnvelope = JSON.stringify({version:1, secret_owner:'0x'+'11'.repeat(20),
      secrets:{LLM_PROVIDER:'anthropic', ANTHROPIC_API_KEY:'test-only'}});
    const ciphertext = new Function('encrypt','executorPublicKey','secretEnvelope',`${line}\nreturn encryptedSecret;`)(encrypt, executorPublicKey, secretEnvelope);
    expect(Buffer.from(decrypt(key.secret, ciphertext)).toString()).toBe(secretEnvelope);
  });
}

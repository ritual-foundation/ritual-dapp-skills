import { afterEach, expect, test } from 'bun:test';
import { readFileSync } from 'node:fs';
const document = readFileSync(new URL('../../skills/ritual-dapp-llm/SKILL.md', import.meta.url), 'utf8');
const source = [...document.matchAll(/```typescript\n([\s\S]*?)\n```/g)]
  .map(match => match[1]).find(block => block.includes('class RitualStreamClient'));
if (!source) throw new Error('Missing documented stream client');
const executable = new Bun.Transpiler({ loader: 'ts' }).transformSync(source);
const { RitualStreamClient } = new Function(executable + '\nreturn { RitualStreamClient };')();
const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });
function fixture(chunks: string[], status = 200) {
  let request: any;
  globalThis.fetch = (async (url: any, init: any) => {
    request = { url, init };
    return new Response(new ReadableStream({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(new TextEncoder().encode(chunk));
        controller.close();
      },
    }), { status });
  }) as typeof fetch;
  return () => request;
}
const hash = `0x${'11'.repeat(32)}`;
const signature = `0x${'22'.repeat(65)}`;
test('streams split frames and completes on explicit DONE', async () => {
  const request = fixture(['data: {"tok', 'en":"hello"}\n\n', 'data: {"token":" world"}\n\ndata: [DONE]\n\n']);
  const tokens: string[] = []; let completed = 0;
  const result = await new RitualStreamClient('https://stream.invalid').connect(hash, signature, 123n,
    (token: string) => tokens.push(token), () => completed++);
  expect(result).toBe('hello world'); expect(tokens).toEqual(['hello', ' world']); expect(completed).toBe(1);
  expect(request().init.headers.Authorization).toBe(`Bearer ${signature}`);
  expect(request().init.headers['X-Timestamp']).toBe('123');
});
test('accepts explicit JSON completion', async () => {
  fixture(['data: {"token":"hello","done":true}\n\n']);
  expect(await new RitualStreamClient('https://stream.invalid').connect(hash, signature, 123n, () => {})).toBe('hello');
});
test('rejects truncated stream instead of returning a completed partial answer', async () => {
  fixture(['data: {"token":"partial"}\n\n']); let completed = false;
  await expect(new RitualStreamClient('https://stream.invalid').connect(hash, signature, 123n, () => {}, () => { completed = true; }))
    .rejects.toThrow('completion');
  expect(completed).toBe(false);
});
test('rejects authentication and upstream errors', async () => {
  fixture([], 401);
  await expect(new RitualStreamClient('https://stream.invalid').connect(hash, signature, 123n, () => {})).rejects.toThrow('401');
  fixture([], 503);
  await expect(new RitualStreamClient('https://stream.invalid').connect(hash, signature, 123n, () => {})).rejects.toThrow('503');
});

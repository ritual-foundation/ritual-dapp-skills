import { describe, expect, test } from 'bun:test';
import { readFileSync } from 'node:fs';
import { encodeAbiParameters, decodeAbiParameters, toHex } from 'viem';

// Execute the literal documentation declarations; no second codec implementation.
const document = readFileSync(new URL('../../skills/ritual-dapp-http/SKILL.md', import.meta.url), 'utf8');
const blocks = [...document.matchAll(/```typescript\n([\s\S]*?)\n```/g)].map(match => match[1]);
const selectors = ['const HTTP_RESPONSE_ABI =', 'type HTTPResult ='];
const source = selectors.map(selector => {
  const block = blocks.find(block => block.includes(selector));
  if (!block) throw new Error(`Missing documented example: ${selector}`);
  return block.replace(/^import[^;]+;\s*/gm, '');
}).join('\n');
const executable = new Bun.Transpiler({ loader: 'ts' }).transformSync(source);
const { decodeHTTPResponse, HTTP_RESPONSE_ABI } = new Function(
  'decodeAbiParameters', executable + '\nreturn { decodeHTTPResponse, HTTP_RESPONSE_ABI };',
)(decodeAbiParameters);

const inline = (status = 200, error = '') => encodeAbiParameters(
  HTTP_RESPONSE_ABI, [status, ['Content-Type'], ['application/json'], toHex('{"ok":true}'), error],
);
const wrapper = (output: `0x${string}`) => encodeAbiParameters(
  [{ type: 'bytes' }, { type: 'bytes' }], ['0x1234', output],
);

describe('literal HTTP decoder distinguishes receipt output and CALL return', () => {
  test('decodes bare receipt output', () => {
    expect(decodeHTTPResponse(inline())).toEqual({
      mode: 'settled', statusCode: 200, headerKeys: ['Content-Type'],
      headerValues: ['application/json'], body: toHex('{"ok":true}'), errorMessage: '',
    });
  });
  test('decodes an explicitly selected Solidity CALL return', () => {
    expect(decodeHTTPResponse(wrapper(inline()), 'call-return')).toEqual(decodeHTTPResponse(inline()));
  });
  test('retains simulation input when the CALL result is empty', () => {
    expect(decodeHTTPResponse(wrapper('0x'), 'call-return')).toEqual({ mode: 'simulation', simmedInput: '0x1234' });
  });
  test('preserves HTTP and executor error details', () => {
    expect(decodeHTTPResponse(inline(503)).statusCode).toBe(503);
    expect(decodeHTTPResponse(inline(0, 'upstream failed')).errorMessage).toBe('upstream failed');
  });
  test('rejects malformed response bytes', () => {
    expect(() => decodeHTTPResponse('0x1234')).toThrow();
  });
});

const submissionSelectors = ['const HTTP_PRECOMPILE =', 'const HTTP_REQUEST_ABI =',
  'interface HTTPRequestParams', 'async function submitHTTPRequest('];
const submissionBody = submissionSelectors.map(selector => {
  const block = blocks.find(block => block.includes(selector));
  if (!block) throw new Error(`Missing documented example: ${selector}`);
  return block.replace(/^import[^;]+;\s*/gm, '');
}).join('\n');
const submissionExecutable = new Bun.Transpiler({ loader: 'ts' }).transformSync(submissionBody);
const { submitHTTPRequest } = new Function('encodeAbiParameters',
  submissionExecutable + '\nreturn { submitHTTPRequest };')(encodeAbiParameters);
const address = `0x${'11'.repeat(20)}`;
const params = { executor: address, sponsor: address, url: 'https://example.com', method: 1 };
test('literal submission helper forwards its configured account and chain', async () => {
  let submitted: any;
  const client = { account: { address }, chain: { id: 784 }, sendTransaction: async (tx: any) => { submitted = tx; return '0x1234'; } };
  expect(await submitHTTPRequest(client, params)).toBe('0x1234');
  expect(submitted.account).toBe(client.account);
  expect(submitted.chain).toBe(client.chain);
  expect(submitted.to).toBe('0x0000000000000000000000000000000000000801');
});
test('literal submission helper rejects an unconfigured account before sending', async () => {
  await expect(submitHTTPRequest({ sendTransaction: () => { throw Error('must not send'); } }, params))
    .rejects.toThrow('account configured');
});
test('literal HTTP declarations pass strict TypeScript with the public viem types', async () => {
  const ts = await import('typescript');
  const path = await import('node:path');
  const file = path.join(import.meta.dir, 'literal-http.virtual.ts');
  const source = "import { encodeAbiParameters } from 'viem';\nimport type { Address, Hex, WalletClient } from 'viem';\n" + submissionBody;
  const options = { noEmit: true, strict: true, skipLibCheck: true, target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.ESNext, moduleResolution: ts.ModuleResolutionKind.Bundler, types: [] };
  const host = ts.createCompilerHost(options);
  const getSourceFile = host.getSourceFile.bind(host);
  host.getSourceFile = (name, version, ...rest) => name === file
    ? ts.createSourceFile(name, source, version, true) : getSourceFile(name, version, ...rest);
  const diagnostics = ts.getPreEmitDiagnostics(ts.createProgram([file], options, host));
  expect(diagnostics.map(diagnostic => ts.flattenDiagnosticMessageText(diagnostic.messageText, '\n'))).toEqual([]);
});

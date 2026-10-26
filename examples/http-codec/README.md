# Literal HTTP decoder regression tests

With public [Bun](https://bun.sh) installed:

```bash
cd examples/http-codec
bun install
bun test
```

The tests extract and execute the HTTP skill's actual TypeScript decoder and submission helper. They distinguish bare receipt `spcCalls.output` from wrapped Solidity CALL returns, cover simulation, error details and malformed data, and check configured-account handling and strict TypeScript compatibility with public viem types. These are controlled tests; live HTTP execution requires your selected Ritual deployment.

# Literal streaming example regression tests

With public Bun installed:

```bash
cd examples/stream-client
bun install
bun test
```

These tests extract the LLM skill's actual SSE client and React hook. Controlled fetch streams check split frames, explicit completion, premature EOF and upstream failures. The hook tests use real React with wallet and account hooks supplied as boundary fixtures. They do not execute a live LLM request or authenticate against a deployed streaming service.

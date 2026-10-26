# Persistent launch stages, evidence and recovery

Use this with the direct consumer launch guide when building a launch rail or diagnosing
an agent that never becomes usable. Progress must come from durable receipts,
events and runtime observations, not a timer-driven checklist.

## Before spending

Verify expected chain ID, RPC, deployment contract bytecode and compatible ABIs.
Do not silently use another deployment's default addresses. Read registry
`getServicesByCapability(HTTP_CALL, true)` and independently require valid status,
HTTP_CALL capability, nonempty encryption public key, deployment allowlist and
exclusions. A pinned address must pass those same rules. An empty endpoint is
valid: public `/health` reachability is not a product admission rule. Operator
health/capacity diagnostics can be useful through authorized infrastructure;
never silently substitute an executor after sealing its secrets.

Read heartbeat interval, fees and runway from the deployment. Keep consumer transaction gas,
fee-sponsor deposits, runtime native balance, revival RitualWallet reserve, provider
credits and application-specific credits separate. Check provider/DA credentials
without printing them. Do not treat a failed API key as launch success.

## Durable timeline and sad paths

| Stage / evidence | Failure diagnosis and next action |
| --- | --- |
| Relay payment received, request accepted | Persist payment hash and request idempotency key. Restart resumes this job; never charge again for a lost browser response. Direct-owner launches omit these relay-only stages. |
| Identity allocated, consumer authorized | Store chain-issued ID, owner, consumer address and receipts. A call simulation does not allocate identity. Verify ownership/operator authorization. |
| Executor selected/ready, credentials ready | Validate registry + deployment policy; seal to the chosen key and bind its signature. Grant consumer access to the ciphertext hash. Never log credentials or unredacted configuration. |
| Launch wallet funded/approved | Native funds, RitualWallet balance and spender allowance are distinct. Verify each against the configured sponsor and consumer. |
| Consumer deployed, request submitted | Verify the consumer bytecode and configured AsyncDelivery; store the origin transaction hash and job ID. |
| Executor job accepted, Phase 1 settled | Decode success/error, not only receipt status. No job: origin lock, reserve, expiry or encoding. Job without result: auth/grant/decode, executor or delivery issue. Capture runtime funding address. |
| Runtime funded | Fund the Phase-1 runtime address immediately inside the executor's funding window (currently 120 s). Confirm receipt. Missing it can permanently fail spawn. |
| Phase 2 settled | Decode instance ID/error. Capacity or queue failure is not solved by repeating the same launch. Diagnose executor capacity and explicit terminal status before a new launch with newly sealed secrets. |
| Heartbeat ACTIVE | Read agent-ID-keyed assignment, nonzero runtime address, bound executor and latest heartbeat. Phase 2 and heartbeat are separate observations. Check DA prefix/credentials, claim funding, RPC and deployment-reported errors if absent. |
| Connector connected | Verify matching agent/application session, pinned manifest, connector auth, egress and replay cursors. Heartbeat can be healthy while connector is broken. |
| Useful work completed | Send correlated canary; require expected output plus `turn.completed`. Distinguish approval wait, provider error, cancellation and timeout. Only then mark application launch succeeded. |
| Launch failed / observation timed out | Persist last verified stage, safe error family and evidence. A local observation timeout is not proof of on-chain failure. |

A phase-2 timeout should trigger parallel inspection of the existing consumer
logs, heartbeat assignment and connector presence. Do not ignore an ACTIVE slot
just because a callback is late, or claim success solely from a container ID.
For revival also verify checkpoint CID, agent RitualWallet balance/allowance and
current bound executor; native heartbeat runway alone does not pay revival.

## Resume contract

Persist `{chainId, deployment, owner, paymentHash?, requestId, agentId, revision,
executor, consumerAddress, txHashes, jobId,
runtimeAddress, runtimeFundingTx, lastVerifiedStage}` before progressing.
On restart, reconcile receipts/logs/assignment and continue the first unverified
stage. Do not allocate another ID, repeat a payment, or duplicate runtime funding
because a client lost its response. Preserve ambiguity as `indeterminate` until
resolved. The example shell script is not an automatic resume engine.

Publish redacted stage names, timestamps, transaction links, retryability and
next action. Do not expose request payloads containing hydrated config, bearer
tokens, provider/DA credentials or raw tool values. Keep this record in your
application or operator workspace so another agent can diagnose the same attempt
using the RPC and authenticated application observations.

## Runnable checks and remaining boundaries

The [direct consumer example](../../../examples/persistent-agent/README.md) supplies
`wait-phase1`, `wait-result`, and `wait-heartbeat` commands. Run them
through `uv run --with eciespy --with eth-abi --with web3` followed by
`examples/persistent-agent/helpers.py <command> --help` for required identifiers.
These are separate observation tools, not a durable `doctor` or automatic resume
engine. Preserve the identifiers above before spending.

For connector errors, read [Agent Link](../../ritual-dapp-agent-link/SKILL.md).
A connected session with rejected commands calls for actor/scope/version checks;
an accepted turn waiting on `interaction.requested` needs its matching response.
Output without a terminal turn event is still incomplete. After disconnect,
reconcile cursor/ACK and durable events before resending a command; an
indeterminate turn requires an explicit retry decision.

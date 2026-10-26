---
name: ritual-dapp-agent-link
description: Build or debug bidirectional application connections to persistent Ritual Hermes agents using Agent Link over HTTP long polling or WebSocket. Covers reactive launch configuration, streamed output, tool activity, approvals, cancellation, durable acknowledgements, and reconnects.
---

# Persistent-agent application connections

Use this skill when an application needs to send messages or controls to a persistent Hermes agent and receive live progress or results. Read [the protocol and integration reference](references/protocol.md) before implementing a connector.

The application hosts the public connector; Hermes connects outbound. Both HTTP and WebSocket carry `ritual.agent-link/1` commands and events. A digest-pinned `ritual.agent-connector/1` manifest selects the transport and application-owned endpoint paths. This interface is separate from chain RPC, RITHTTP1 asynchronous HTTP jobs, and fleet telemetry.

## Implementation sequence

1. Read the reference's ownership and capability sections. Check the connected runtime's registration capabilities and verify the required behavior through the connector. No executor or execution-client source checkout is required.
2. Implement manifest delivery, credential-authenticated registration, a durable command queue, and durable event ingestion. Pick HTTP or WebSocket using the wire examples in the reference.
3. Configure persistent runtime `2` with explicit UAHI `events`, `cadence`, or `hybrid` mode, a pinned application manifest, actor authorization, and an `APP_CONNECTOR_*` credential in encrypted launch secrets. Keep the ordinary persistent-agent launch, DA, and heartbeat configuration. Select `hermes.approvals.mode` (`off`, `smart`, or `manual`) in the same runtime config when your app needs an explicit tool approval policy; see the persistent-agent skill for defaults and deployment prerequisites.
4. Drive the UI from scoped commands and semantic events. Store the actual running turn ID for Stop; handle queued turns separately. Process text snapshots and completion as authoritative replacements for streamed deltas.
5. Verify idle behavior, real commands and output, cancellation, approval responses, duplicate delivery, disconnect/reconnect, expired sessions, and interrupted-process recovery using the reference's acceptance checklist.

## Constraints that affect design

- HTTP uses a held command GET plus a separate event POST. A `204` poll timeout does not invoke the model. WebSocket carries commands and event batches concurrently on one connection.
- Supported commands are `conversation.message`, `application.event`, `turn.cancel`, `interaction.respond`, and `session.reset`, all version 1. The bridge is a defined subset of Hermes capabilities, not a universal API tunnel.
- Persist event batches before acknowledging their highest sequence. Preserve command IDs, sequences, and payloads across retries. Transient deltas may be lost; durable snapshots/completion repair text state.
- Work waits for lifecycle readiness. Registration or socket readiness alone does not prove the agent can begin inference.
- A process interrupted during accepted work reports `turn.indeterminate`; it does not silently re-run the model or tool actions. DA recovery can lose changes newer than the verified snapshot.
- Workspace instructions shape behavior; authenticated application commands and runtime controls also govern reactive execution. The legacy `heartbeat_only` work loop is a different mode.

## Compatibility and related skills

Use the protocol versions and capabilities received at registration to select supported commands and events. Confirm behavior against the connected runtime using the reference's black-box acceptance checks. A runtime name or software release alone does not guarantee a particular capability.

For the on-chain launch, runtime configuration reference, encrypted secrets, and remote recovery storage, use [Persistent agents](../ritual-dapp-agents/SKILL.md), [Secrets](../ritual-dapp-secrets/SKILL.md), and [DA storage](../ritual-dapp-da/SKILL.md). This skill supplies the application protocol; it requires no private source repositories, container shell access, or internal test fixtures.

For chain-launch stage evidence and resumable failure diagnosis, see
[launch diagnostics](../ritual-dapp-agents/references/launch-diagnostics.md).
For external decision tools and secrets that are not connector credentials, see
[Hermes tools and secrets](../ritual-dapp-agents/references/hermes-tools-and-secrets.md).

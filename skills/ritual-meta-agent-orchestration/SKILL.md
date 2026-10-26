---
name: ritual-meta-agent-orchestration
description: How to make a launched Ritual agent actually do useful work — the orchestration layer above the launch. Use when deciding what a Persistent or Sovereign agent (one-shot, scheduled, or rolling-window) does after it boots: shaping behavior through the workspace md files, choosing a run mode, defining outcome proof, and rehearsing the loop locally before spending a launch. Runtime-agnostic; Hermes is one profile. For the launch mechanics themselves, see ritual-dapp-agents.
---

# Agent Orchestration

For application-driven Hermes work and live interaction, read [Agent Link](../ritual-dapp-agent-link/SKILL.md). Select `events`, `cadence`, or `hybrid` explicitly; HTTP and WebSocket share commands, output events, approvals, cancellation, and recovery semantics.

## Two planes

Launching an agent and having a *useful* agent are different achievements, and treating them as one thing is the root cause of the most common failure: the launch returns a container id, the heartbeat is green, and nothing ever happens at the target. Hold the two apart.

- The **launch plane** answers *does the agent exist?* — the application-owned consumer, on-chain spawn and heartbeat lifecycle. `ritual-dapp-agents` covers deployment and direct submission. It is mechanical and deterministic.
- The **orchestration plane** answers *is it doing useful work, and can I prove it?* — the agent's behaviour over time. Workspace files define standing behavior; reactive applications also supply authenticated commands, while runtime configuration selects wake sources and enforces control semantics.

Workspace files seed identity, policy, and context at launch. Legacy autonomous UAHI can use app onboarding; reactive Hermes instead receives application commands through Agent Link and dispatches them through normal gateway sessions. Revival uses the verified restored workspace rather than overwriting it with old launch seeds. Treat prose as operating guidance and runtime authorization, lifecycle readiness, wake selection, and controls as separate mechanisms.

## The workspace files carry different concerns

Behaviour is split across files because different concerns change at different rates and deserve different authority:

- **SOUL.md — identity and mission.** Who the agent is and the single bounded thing it exists to do. This rarely changes; keeping it separate stops day-to-day task detail from eroding purpose. When the agent is unsure, SOUL.md is the tie-breaker.
- **AGENTS.md — the operating loop.** The runbook: what the agent checks each time it wakes, how it decides what matters, the small set of things it is allowed to do, what it records as it goes, and when it stops until the next trigger. Written as instructions to a competent operator, in plain language — not a spec. This is the file you iterate on most.
- **HEARTBEAT.md — the legacy autonomous per-tick instruction.** Reactive Agent Link turns use their message/event input, or the configured cadence prompt; do not assume every wake reads HEARTBEAT.md. On Hermes the `heartbeat_only` loop prompts the agent each UAHI cycle to read HEARTBEAT.md and execute exactly one autonomous, idempotent cycle; without it the runtime falls back to a generic cycle guided by SOUL.md and memory. AGENTS.md is the standing operating policy; HEARTBEAT.md is the single bounded thing each tick actually does.
- **TOOLS.md — the action space.** The concrete things the actions in AGENTS.md actually call: which endpoints, contracts, or commands, and what each expects. Kept separate so you can repoint from staging to production without touching the loop.

Three more files carry context rather than behaviour: **USER.md** (who it serves and their preferences), **MEMORY.md** (what it has learned and done — the basis for not repeating work), and **IDENTITY.md** (its workspace identity, distinct from the on-chain `agentId`).

## The control loop

Every autonomous agent runs the same shape, whatever the task:

> a trigger arrives → it loads its context and state → it observes the target → it chooses one bounded thing to do → it acts, records what happened, and checkpoints → it verifies the effect → it stops or waits for the next trigger.

The trigger can be a user message, an app or chain event, a scheduler tick, or a heartbeat. Two different things are called a heartbeat, and only one of them is a trigger: the **in-container UAHI tick** (`UAHI_HEARTBEAT_EVERY`, default `30s`) wakes the agent and runs one cycle; the **on-chain `AgentHeartbeat` beat**, sent by the sidecar every `heartbeatIntervalBlocks()`, is a liveness signal that keeps the slot claimed and wakes nothing. The *proactive* part is what the agent does after the trigger without another human telling it to. For the simplest useful agents the whole loop collapses to **wake → do one bounded task → leave a visible result → sleep until the next tick.** Use that heartbeat-only shape for status, reporting, reminder, and canary agents; reach for a richer loop only when the work genuinely needs it.

## Modes

Name the shape of the work before you write the loop:

- **local_iteration** — a pre-launch dry run of the loop from your own machine (see *Test the loop locally before you spend a launch*, below).
- **bounded_objective** — a finite task with a clear finish line.
- **continuous_service** — an ongoing service where staying useful matters more than finishing.
- **scheduled_rolling** — repeated windowed runs via the Scheduler and your application-owned consumer. The consumer defines authorization, correlation, funding and retry behavior; scheduling is an application execution mode rather than a kind of agent.
- **human_supervised / hybrid** — a person in the loop for approval or escalation.

The mode decides the cadence, the stop condition, and what "healthy" means. Pick it first.

## Success is only what shows up at the target

Four layers succeed or fail independently, and only the last one is the point:

1. **launch** — the transaction/job exists and delivery worked.
2. **runtime** — the container booted, the sidecar is alive, and the on-chain `AgentHeartbeat` slot is claimed and beating. Whether the intended workspace loaded is not part of this layer.
3. **orchestration** — the loop is dispatching real work from the intended workspace and its progress markers advance.
4. **outcome** — the target app, contract, dashboard, channel, or user-visible flow contains the expected proof.

A green on-chain heartbeat proves only layer 2 — the sidecar is alive and the slot is claimed, not that the intended workspace loaded, and not that the agent did anything. So set the bar at **outcome**: a form submitted, a contract event emitted, a dashboard row written, a message delivered. A line of the agent's own dialogue is never the side effect. Whenever success requires a real write, name the action, who signs and pays for it, what it needs (balance, allowance, credential), and where the proof lands — in the md files, so the agent itself knows what "done" means.

## Where to trust the model, and where not to

The model is a *proposer*, not a controller. Workspace guidance helps bound autonomous work. Reactive integrations also enforce actor authorization, wake modes, lifecycle readiness, and explicit control commands in runtime machinery:

- **Keep each cycle to one bounded, recoverable action, and have the agent say what it intends before it acts.** The limits — what it may do, what it must never do, when to stop — live in the prose of AGENTS.md and SOUL.md. On Hermes the bound is also mechanical: each `heartbeat_only` cycle is one `hermes chat` invocation with a bounded number of turns, killed at a wall-clock timeout of four tick periods (120 s at the default `30s` tick), so work that does not fit in one cycle is lost, whatever the prose says. Bounding a cycle is how you make failures cheap and legible.
- **Let steady, repeated mechanics be done by dependable helpers the agent calls, not re-improvised each tick.** Polling, fetching, submitting, monitoring — describe these once, and let the model decide *when* to use them rather than reinvent *how* every time. The model creates plans, drafts, and choices; the helpers do the same mechanical thing the same way each time.

This is a judgment about trust, not a schema. State it as such.

## Test the loop locally before you spend a launch

A chain launch is slow, non-refundable, and takes a runtime slot — so prove the loop *before* you commit. The key idea: **"local" means the control loop runs on your machine; the target does not have to be local.** Run the same orchestration you wrote into the md files against the cheapest target that retires the next risk, climbing only as each rung passes:

| Rung | Proves | Move up when |
|---|---|---|
| offline fixture | the loop's structure, parsing, decision paths | it is structurally correct |
| recorded trace | behaviour against real past observations, no live writes | a replay/rehearsal passes |
| local service | app/API integration, no chain dependency | the target can run locally |
| remote read-only | live discovery and monitoring against the deployed system | before *any* write |
| sandbox write | the write/submit path, with a capped key or test namespace | write behaviour must be proven |
| live canary | a production-like run with a bounded budget and rollback | final gate before the real launch |

A local harness only needs to exercise the same loop with stand-ins: observe an input, choose an action, run it, advance a progress marker, inject a failure, and record what happened at each layer. Treat that record as the gate — **if the local run cannot produce outcome proof against a stand-in target, the launch will not either.** Only once the loop is proven do you repoint TOOLS.md from the stand-in to the real endpoint and launch.

## The recipe

To make an agent do X: put X's bounded mission in **SOUL.md**; write X as a per-tick loop in **AGENTS.md**, in plain language, doing one bounded thing per cycle; give those actions concrete targets in **TOOLS.md**; pick a **mode**; decide what the **outcome proof** is and where it is written; **rehearse the loop locally up the target ladder**; then launch through `ritual-dapp-agents` and check all four layers — treating anything short of outcome proof as *not done*.

The launch consumer gives the agent a body; the md files are its mind, written as prose; the runtime keeps that mind on its loop; and success is only what shows up at the target.

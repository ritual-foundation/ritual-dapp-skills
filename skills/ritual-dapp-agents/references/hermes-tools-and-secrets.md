# Hermes skills, Jev and launch secrets

Jev is an optional third-party integration example, not a prerequisite for
launching or debugging a persistent agent.

## A skill URL is not an installed runtime integration

Hermes remains the general-purpose agent using its supported conversational
provider. Jev is a separate TypeSafe typed decision API (choice, score, Noul),
not a replacement chat provider in Ritual's provider enum. Use Hermes to plan
and explain; use a tool to ask Jev bounded decision questions and validate the
answer in application code.

TypeSafe's official skill teaches developers to build integrations:
https://github.com/typesafe-ai/skills/tree/main/skills/typesafe-ai
A community executable Hermes skill exists at
https://github.com/shantanugoel/ask-jev-skill ; Hermes also has a community
`jev-typesafe` plugin catalog entry. Review and pin the exact source/version,
check runtime compatibility and install it into the actual Hermes skill/plugin
location. A URL in `TOOLS.md` does not install executable code or credentials.
Do not present community plugins as a built-in Ritual feature or vendor-backed.

Ensure the supported image/bootstrap can install the tool, dependencies and
skill metadata; verify discovery inside the launched agent. Verify files and
credential references after checkpoint/restore as well as initial launch.
Do not assume arbitrary filesystem mutations survive revival.

## Encryption, configuration and environment are different boundaries

The launch secret map accepts named encrypted values. Executor decryption,
owner signature/use-context and consumer access grant authorize their use.
That is not an arbitrary process-environment injection API.

For the supported application connector, `uahi.application_ref.credential_ref`
selects a named encrypted credential in the `APP_CONNECTOR_` namespace. Provide
that value in the launch secret map and verify authenticated registration at
your application backend. Model and DA credentials use their documented fields.
Adding `TYPESAFE_API_KEY` to the secret map alone does not establish a binding
to a custom tool.

Supported configuration fields may use named placeholders, such as
`"__TELEGRAM_BOT_TOKEN__"`. An arbitrary `env` block is not a documented custom
tool credential interface. Use a binding explicitly supported by your deployment.
Verify it through a bounded tool request that returns only success or a sanitized
error; never request that the agent print a credential. If no supported binding
is available, use an application-side adapter or ask the deployment operator
which tool integrations are supported. Private source access is unnecessary.

Never put API keys into SOUL/TOOLS/AGENTS text, inline public launch payloads,
chat commands, manifests, public URLs or diagnostic output. Hydrated config may
be persisted or logged: do not use arbitrary placeholder expansion as a secret
injection workaround without verifying every downstream boundary and recovery.

## Two explicit integration paths

1. **Application-side Jev adapter:** store the TypeSafe key in the application
   backend's secret store. The authenticated agent requests a bounded decision
   through a supported tool/connector adapter. The backend calls Jev and returns
   typed results. This needs an implemented decision route/tool; the existing
   conversation protocol does not automatically provide one. Authorize per-agent,
   rate-limit, cap cost and keep credentials out of event payloads.
2. **Supported runtime tool:** use a deployment-provided tool with a documented
   credential binding, installation method, and recovery policy. Verify tool
   discovery and a bounded authenticated request after launch and recovery.
   When that integration is unavailable, implementing it is an operator/runtime
   change; a skill URL or encrypted secret name alone cannot enable it.

Test without a key, with invalid key, timeout/429, malformed result and restored
runtime. Fail safely without submitting an application action. For financial
simulations keep deterministic exposure limits and feed freshness checks in
code; model confidence is not the probability a market bet pays out.

Current API contract: https://docs.typesafe.ai/introduction/quickstart
`POST https://api.typesafe.ai/v1/systemone`, bearer `TYPESAFE_API_KEY`, JSON
`{model: "jev-latest", state: {...}, questions: {...}}`. Pin a model/version when
reproducibility matters; preserve request/snapshot IDs and validated decisions,
not credentials, as evidence. A local API smoke test is not evidence that the
launched persistent runtime has that tool or secret.

#!/usr/bin/env python3
"""Standalone consumer deployment, request encoding and exact job observation."""


from __future__ import annotations

import argparse

import json

import os

import re

import sys

import time

import uuid

from urllib import request

from urllib.parse import urlparse

from ecies import PrivateKey
from ecies import decrypt as ecies_decrypt
from ecies import encrypt as ecies_encrypt

from ecies.config import ECIES_CONFIG

from eth_abi.abi import decode, encode

from eth_account import Account

from eth_account.messages import encode_defunct

from web3 import Web3
from requests.exceptions import ConnectionError as RPCConnectionError, Timeout as RPCTimeout

ECIES_CONFIG.symmetric_nonce_length = 12

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

TEE_SERVICE_REGISTRY_ABI = [
    {
        "name": "getServicesByCapability",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "capability", "type": "uint8"}, {"name": "checkValidity", "type": "bool"}],
        "outputs": [
            {
                "name": "",
                "type": "tuple[]",
                "components": [
                    {
                        "name": "node",
                        "type": "tuple",
                        "components": [
                            {"name": "paymentAddress", "type": "address"},
                            {"name": "teeAddress", "type": "address"},
                            {"name": "teeType", "type": "uint8"},
                            {"name": "executorSecretsAuthPublicKey", "type": "bytes"},
                            {"name": "endpoint", "type": "string"},
                            {"name": "mTlsSpkiHash", "type": "bytes32"},
                            {"name": "capability", "type": "uint8"},
                        ],
                    },
                    {"name": "isValid", "type": "bool"},
                    {"name": "workloadId", "type": "bytes32"},
                ],
            }
        ],
    }
]

AGENT_HEARTBEAT_GET_ASSIGNMENT_ABI = [
    {
        "inputs": [{"internalType": "uint256", "name": "agentId", "type": "uint256"}],
        "name": "getAssignment",
        "outputs": [
            {
                "components": [
                    {"internalType": "enum IAgentHeartbeat.SlotState", "name": "state", "type": "uint8"},
                    {"internalType": "enum IAgentHeartbeat.RevivalStatus", "name": "revivalStatus", "type": "uint8"},
                    {"internalType": "address", "name": "agentAddress", "type": "address"},
                    {"internalType": "bytes32", "name": "boundHolderKey", "type": "bytes32"},
                    {"internalType": "address", "name": "boundExecutor", "type": "address"},
                    {"internalType": "uint64", "name": "lastHeartbeat", "type": "uint64"},
                    {"internalType": "uint64", "name": "heartbeatTimeout", "type": "uint64"},
                    {"internalType": "uint64", "name": "cooldownEnd", "type": "uint64"},
                    {"internalType": "string", "name": "latestManifestCID", "type": "string"},
                    {"internalType": "bytes", "name": "encryptedDAConfig", "type": "bytes"},
                    {"internalType": "bytes", "name": "revivalExecutorPayload", "type": "bytes"},
                    {"internalType": "bytes32", "name": "revivalApplicationContext", "type": "bytes32"},
                ],
                "internalType": "struct IAgentHeartbeat.SlotAssignment",
                "name": "",
                "type": "tuple",
            }
        ],
        "stateMutability": "view",
        "type": "function",
    }
]

SECRETS_ACCESS_CONTROL_CHECK_ABI = [
    {
        "inputs": [
            {"name": "owner", "type": "address"},
            {"name": "delegate", "type": "address"},
            {"name": "secretsHash", "type": "bytes32"},
        ],
        "name": "checkAccess",
        "outputs": [
            {"name": "hasAccess", "type": "bool"},
            {
                "name": "policy",
                "type": "tuple",
                "components": [
                    {"name": "allowedDestinations", "type": "string[]"},
                    {"name": "allowedMethods", "type": "string[]"},
                    {"name": "allowedPaths", "type": "string[]"},
                    {"name": "allowedQueryParams", "type": "string[]"},
                    {"name": "allowedHeaders", "type": "string[]"},
                    {"name": "secretLocation", "type": "string"},
                    {"name": "bodyFormat", "type": "string"},
                ],
            },
        ],
        "stateMutability": "view",
        "type": "function",
    }
]

AGENT_ENVELOPE_TYPES = [
    "address",                    # 0  executor
    "address",                    # 1  sponsor — owner EOA with consumer allowance
    "uint64",                     # 2  ttl
    "uint64",                     # 3  phase2_ttl (max spawn block offset)
    "bool",                       # 4  callback_enabled
    "address",                    # 5  callback_target      == consumer when enabled (validated on-chain)
    "bytes4",                     # 6  callback_selector
    "uint64",                     # 7  callback_gas_limit
    "uint128",                    # 8  callback_max_fee_per_gas
    "uint128",                    # 9  callback_max_priority_fee_per_gas
    "uint256",                    # 10 callback_value
    "bytes32",                    # 11 application_context == keccak256(abi.encode(agent_id, revision))
    "bytes",                      # 12 executor_payload (opaque V1 payload below)
]

PERSISTENT_PAYLOAD_V1_TYPES = [
    "uint8",                      # 0  version (must be 1)
    "address[]",                  # 1  secret_owners        exactly ONE distinct owner
    "bytes[]",                    # 2  encrypted_secrets
    "bytes[]",                    # 3  secret_signature
    "bytes",                      # 4  user_public_key
    "uint8",                      # 5  provider
    "string",                     # 6  model
    "string",                     # 7  llm_api_key_ref
    "(string,string,string)",     # 8  da_config
    "(string,string,string)",     # 9  soul_ref
    "(string,string,string)",     # 10 agents_ref
    "(string,string,string)",     # 11 user_ref
    "(string,string,string)",     # 12 memory_ref
    "(string,string,string)",     # 13 identity_ref
    "(string,string,string)",     # 14 tools_ref
    "(string,string,string)",     # 15 openclaw_config_ref
    "string",                     # 16 restore_from_cid
    "string",                     # 17 rpc_urls
    "uint16",                     # 18 agent_runtime
    "uint256",                    # 19 agent_id (chain-issued, pre-allocated)
    "uint64",                     # 20 revision
]

PERSISTENT_RESPONSE_TYPES = [
    "string",  # instance_id
    "string",  # gateway_url
    "string",  # container_id
    "string",  # checkpoint_cid
    "string",  # error_message
    "string",  # gateway_token (Phase 1: prelaunch primary wallet address)
]

LLM_PROVIDER = {
    "anthropic": 0,
    "openai": 1,
    "gemini": 2,
    "xai": 3,
    "openrouter": 4,
}

AGENT_RUNTIME = {
    "zeroclaw": 0,
    "hermes": 2,
}

SECRET_AUTH_DOMAIN = b"RITUAL_SECRET_AUTHORIZATION_V1"

PERSISTENT_USE_CONTEXT = "precompile:0x0000000000000000000000000000000000000820"

EVT_AGENT_ID_ALLOCATED = "AgentIdAllocated(uint256,address,address)"

EVT_JOB_ADDED = (
    "JobAdded(address,bytes32,address,uint256,bytes,address,address,bytes32,uint256,uint256,uint256,uint256)"
)

GRANT_ACCESS_SIG = (
    "grantAccess(address,bytes32,uint256,(string[],string[],string[],string[],string[],string,string))"
)

MAX_UINT256 = 2**256 - 1

POLL_INTERVAL_S = 2

DEFAULT_CLAW_MAX_AGENTS = 10

def _to_hex(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value if value.startswith("0x") else f"0x{value}"
    if isinstance(value, (bytes, bytearray)):
        return "0x" + bytes(value).hex()
    if hasattr(value, "hex"):
        raw = value.hex()
        return raw if raw.startswith("0x") else f"0x{raw}"
    return ""

def _to_bytes(value) -> bytes:
    as_hex = _to_hex(value)
    if not as_hex or as_hex == "0x":
        return b""
    return bytes.fromhex(as_hex[2:])

def die(msg: str, code: int = 1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)

def _fetch_health(endpoint: str) -> dict:
    url = endpoint.rstrip("/") + "/health"
    req = request.Request(url, method="GET")
    with request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())

def _count(value) -> int:
    """Tolerate list-of-ids or plain-int shapes for capacity counters."""
    if isinstance(value, list):
        return len(value)
    if isinstance(value, (int, float)):
        return int(value)
    return 0

def _find_key_recursive(obj, key: str, max_depth: int = 4):
    if max_depth < 0 or not isinstance(obj, dict):
        return None
    if key in obj:
        return obj[key]
    for v in obj.values():
        if isinstance(v, dict):
            found = _find_key_recursive(v, key, max_depth - 1)
            if found is not None:
                return found
    return None

def _health_gate(health: dict, max_agents: int) -> tuple[bool, str]:
    """Return (ok, reason). Implements the CU-C persistent-launch health gate:
    - /health handlers must include the 0x0820 spawn handler
    - claw_spawner.payload.status == "healthy"
    - identity slots: max_agents - max(live_agent_ids, distinct_reserved_slots) >= 1
    - memory slots: (limit_budget_bytes - effective_limit_bytes) // startup_limit_bytes >= 1
    - capacity.accounting_available == true
    """
    handlers = _find_key_recursive(health, "handlers")
    if not isinstance(handlers, dict):
        return False, "no 'handlers' map in /health response"
    if not any(str(k).lower().replace("0x", "").lstrip("0").endswith("820") for k in handlers):
        return False, "no 0x...0820 spawn handler registered"

    claw = _find_key_recursive(health, "claw_spawner")
    if isinstance(claw, dict) and isinstance(claw.get("payload"), dict):
        claw = claw["payload"]
    if not isinstance(claw, dict):
        return False, "no claw_spawner payload in /health response"
    if str(claw.get("status", "")).lower() != "healthy":
        return False, f"claw_spawner status={claw.get('status')!r} (want 'healthy')"

    cap = claw.get("capacity")
    if not isinstance(cap, dict):
        return False, "no claw_spawner.capacity block"
    if not cap.get("accounting_available", False):
        return False, "capacity.accounting_available is false (admission fail-closed)"

    live = _count(cap.get("live_agent_ids"))
    reserved = _count(cap.get("distinct_reserved_slots"))
    identity_free = max_agents - max(live, reserved)
    if identity_free < 1:
        return False, f"no identity slots free (live={live} reserved={reserved} cap={max_agents})"

    try:
        budget = int(cap["limit_budget_bytes"])
        effective = int(cap["effective_limit_bytes"])
        startup = int(cap["startup_limit_bytes"])
    except (KeyError, TypeError, ValueError):
        return False, "capacity memory-budget fields missing/unparseable"
    if startup <= 0:
        return False, f"startup_limit_bytes={startup} unusable"
    memory_free = (budget - effective) // startup
    if memory_free < 1:
        return False, f"no memory slots free (budget={budget} effective={effective} startup={startup})"

    return True, f"healthy: identity_free={identity_free} memory_free={memory_free}"

def eligible_executor_nodes(services, allowed="", excluded=""):
    """Registry eligibility does not require a publicly reachable endpoint."""
    allow = {Web3.to_checksum_address(v.strip()) for v in allowed.split(",") if v.strip()}
    deny = {Web3.to_checksum_address(v.strip()) for v in excluded.split(",") if v.strip()}
    nodes = []
    for node, valid, *_ in services:
        tee, pub, endpoint = Web3.to_checksum_address(node[1]), bytes(node[3]), str(node[4])
        if valid and tee != ZERO_ADDRESS and int(node[6]) == 0 and pub and tee not in deny and (not allow or tee in allow):
            nodes.append((tee, pub, endpoint))
    return sorted(nodes, key=lambda node: node[0].lower())

def cmd_select_executor(args):
    w3 = Web3(Web3.HTTPProvider(args.rpc))
    registry = w3.eth.contract(address=Web3.to_checksum_address(args.registry), abi=TEE_SERVICE_REGISTRY_ABI)
    services = registry.functions.getServicesByCapability(0, True).call()
    nodes = eligible_executor_nodes(services, args.allowed_executors, args.excluded_executors)
    if args.executor_tee_address:
        target = Web3.to_checksum_address(args.executor_tee_address)
        nodes = [node for node in nodes if node[0] == target]
    if not nodes:
        die("No eligible HTTP_CALL executor: require valid registration, nonempty secrets key, "
            "and deployment allowlist/exclusions. An explicit pin never bypasses eligibility.")
    for tee, pub, endpoint in nodes:
        if args.require_health:
            try:
                ok, reason = _health_gate(_fetch_health(endpoint), args.max_agents)
            except Exception as exc:
                ok, reason = False, f"operator health probe failed: {exc}"
            if not ok:
                print(f"# rejected executor {tee}: {reason}", file=sys.stderr)
                continue
        print(f"EXECUTOR={tee}")
        print(f"EXECUTOR_PUBKEY=0x{pub.hex()}")
        print(f"EXECUTOR_ENDPOINT={endpoint}")
        return
    die("No eligible executor passed the explicitly requested operator health probe. "
        "A pin does not bypass this probe. Empty endpoints are valid for default registry selection.")

def build_secret_envelope(owner: str, secrets: dict[str, str]) -> bytes:
    envelope = {
        "secret_owner": Web3.to_checksum_address(owner),
        "secrets": secrets,
        "version": 1,
    }
    return json.dumps(envelope, separators=(",", ":")).encode()

def build_secret_authorization_payload(
    use_context: str, chain_id: int, executor: str, owner: str, encrypted_blob: bytes
) -> bytes:
    context = use_context.encode()
    return b"".join(
        [
            SECRET_AUTH_DOMAIN,
            len(context).to_bytes(2, "big"),
            context,
            int(chain_id).to_bytes(32, "big"),
            bytes.fromhex(Web3.to_checksum_address(executor)[2:]),
            bytes.fromhex(Web3.to_checksum_address(owner)[2:]),
            Web3.keccak(encrypted_blob),
        ]
    )

def create_secret_signature(
    use_context: str, chain_id: int, executor: str, owner: str, encrypted_blob: bytes, private_key: str
) -> bytes:
    payload = build_secret_authorization_payload(use_context, chain_id, executor, owner, encrypted_blob)
    return bytes(Account.from_key(private_key).sign_message(encode_defunct(primitive=payload)).signature)

def choose_provider_and_key() -> tuple[str, str, str]:
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic", "LLM_API_KEY", os.environ["ANTHROPIC_API_KEY"]
    if os.getenv("OPENAI_API_KEY"):
        return "openai", "LLM_API_KEY", os.environ["OPENAI_API_KEY"]
    if os.getenv("GEMINI_API_KEY"):
        return "gemini", "LLM_API_KEY", os.environ["GEMINI_API_KEY"]
    if os.getenv("OPENROUTER_API_KEY"):
        return "openrouter", "LLM_API_KEY", os.environ["OPENROUTER_API_KEY"]
    die("Missing LLM API key (set ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY / OPENROUTER_API_KEY).")

def default_model_for_provider(provider: str) -> str:
    return {
        "anthropic": "claude-haiku-4-5-20251001",
        "openai": "gpt-4o-mini",
        "gemini": "gemini-2.5-flash",
        "openrouter": "anthropic/claude-3.5-sonnet",
        "xai": "grok-2",
    }[provider]

def empty_ref():
    return ("", "", "")

def inline_ref(content: str):
    return ("inline", content, "") if content else empty_ref()

def build_da_config(da_provider: str, agent_id: int) -> tuple[tuple[str, str, str], dict[str, str]]:
    secrets: dict[str, str] = {}

    if da_provider == "hf":
        hf_token = os.getenv("HF_TOKEN", "")
        hf_repo_id = os.getenv("HF_REPO_ID", "")
        if not hf_token or not hf_repo_id:
            die("DA_PROVIDER=hf requires HF_TOKEN and HF_REPO_ID", 2)
        secrets["HF_TOKEN"] = hf_token
        return ("hf", hf_repo_id, "HF_TOKEN"), secrets

    if da_provider == "gcs":
        sa_json = os.getenv("GCS_DA_SERVICE_ACCOUNT_JSON", "")
        bucket = os.getenv("GCS_DA_BUCKET", "")
        if not sa_json or not bucket:
            die("DA_PROVIDER=gcs requires GCS_DA_SERVICE_ACCOUNT_JSON and GCS_DA_BUCKET", 2)
        # The GCS prefix is MANDATORY and must equal the canonical per-agent
        # prefix keyed by the chain-issued agentId — the spawner rejects any
        # other value ("gcs_prefix must equal the canonical per-agent prefix"),
        # and an empty prefix fails the sidecar recovery config closed (no
        # launch/revival). Revival reads/writes the same prefix as launch.
        canonical_prefix = f"persistent-agents/agent-{int(agent_id)}"
        prefix = os.getenv("GCS_DA_PREFIX", "")
        if prefix and prefix != canonical_prefix:
            die(f"GCS_DA_PREFIX={prefix!r} must equal the canonical per-agent prefix "
                f"{canonical_prefix!r} (or be unset to derive it)", 2)
        secrets["GCS_CREDENTIALS"] = json.dumps(
            {"service_account_json": sa_json, "bucket": bucket}
        )
        return ("gcs", canonical_prefix, "GCS_CREDENTIALS"), secrets

    if da_provider == "pinata":
        jwt = os.getenv("DA_PINATA_JWT", "")
        if not jwt:
            die("DA_PROVIDER=pinata requires DA_PINATA_JWT", 2)
        secrets["DA_PINATA_JWT"] = jwt
        gateway = os.getenv("DA_PINATA_GATEWAY", "")
        if gateway:
            secrets["DA_PINATA_GATEWAY"] = gateway
        return ("pinata", "", "DA_PINATA_JWT"), secrets

    die("DA_PROVIDER must be one of hf, gcs, pinata", 2)

def connector_configuration():
    """Validate non-secret configuration and return a separately sealed credential."""
    mode = os.getenv("UAHI_MODE", "autonomous").strip()
    if mode == "reactive":
        mode = "events"
    if mode not in {"autonomous", "off", "events", "cadence", "hybrid"}:
        die("UAHI_MODE must be autonomous, off, events, cadence, or hybrid")
    if mode in {"autonomous", "off"}:
        return {"enabled": mode != "off", "mode": mode, "onboard_mode": "off"}, {}
    app_id = os.getenv("UAHI_APP_ID", "")
    url = os.getenv("UAHI_MANIFEST_URL", "")
    digest = os.getenv("UAHI_MANIFEST_SHA256", "").removeprefix("sha256:").lower()
    ref = os.getenv("UAHI_CREDENTIAL_REF", "APP_CONNECTOR_TOKEN")
    parsed = urlparse(url)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}", app_id):
        die("UAHI_APP_ID must be a protocol identifier")
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        die("UAHI_MANIFEST_URL must be HTTPS without embedded credentials or fragment")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        die("UAHI_MANIFEST_SHA256 must be the SHA-256 of the served manifest bytes")
    if not re.fullmatch(r"APP_CONNECTOR_[A-Z0-9_]{1,111}", ref):
        die("UAHI_CREDENTIAL_REF must use the APP_CONNECTOR_ namespace")
    token = os.getenv(ref, "")
    if not token.strip():
        die("The referenced APP_CONNECTOR credential is missing")
    users = [v.strip() for v in os.getenv("UAHI_ALLOWED_USERS", "").split(",") if v.strip()]
    if not users or len(users) > 256 or any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}", v) for v in users):
        die("UAHI_ALLOWED_USERS must name the authenticated actors allowed to send commands")
    cfg = {"enabled": True, "mode": mode, "onboard_mode": "off",
           "application_ref": {"app_id": app_id, "manifest_url": url,
                               "manifest_sha256": digest, "credential_ref": ref},
           "authorization": {"allow_all_users": False, "allowed_users": users}}
    if mode in {"cadence", "hybrid"}:
        try:
            every = int(os.getenv("UAHI_CADENCE_EVERY_MS", "60000"))
        except ValueError:
            die("UAHI_CADENCE_EVERY_MS must be an integer")
        overlap = os.getenv("UAHI_CADENCE_OVERLAP", "coalesce")
        if not 1000 <= every <= 86400000 or overlap not in {"skip", "coalesce"}:
            die("Invalid cadence interval or overlap policy")
        cfg["wake"] = {"cadence": {"every_ms": every, "overlap": overlap}}
    return cfg, {ref: token}

def cmd_check_runtime_config(args):
    cfg, _ = connector_configuration()
    if args.agent_runtime != "hermes" and cfg["mode"] not in {"autonomous", "off"}:
        die("Agent Link requires the Hermes runtime")
    print("RUNTIME_CONFIG_VALID=1")

def build_runtime_config(args: argparse.Namespace) -> str:
    cfg: dict = {}

    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if tg_token:
        cfg["channels"] = {
            "telegram": {
                "enabled": True,
                "botToken": "__TELEGRAM_BOT_TOKEN__",
                "dmPolicy": os.getenv("TELEGRAM_DM_POLICY", "open"),
                "allowFrom": ["*"],
                "groups": {"*": {"requireMention": False}},
            }
        }

    # Hermes: explicit UAHI work-loop config. Omitting it would still default
    # ON (heartbeat_only) server-side, but explicit config keeps launches
    # deterministic across spawner versions.
    if AGENT_RUNTIME[args.agent_runtime] == 2:
        cfg["uahi"], _ = connector_configuration()
        if cfg["uahi"]["mode"] == "autonomous":
            cfg["uahi"].update({"tick_sec": int(os.getenv("UAHI_TICK_SEC", "3")),
                                "app_heartbeat_sec": int(os.getenv("UAHI_APP_HEARTBEAT_SEC", "10"))})

    # On-chain heartbeat loop. Server-managed default is also ON; explicit
    # config pins the contract address ONLY. Cadence is read on-chain from
    # heartbeatIntervalBlocks() exclusively (no env/config fallback) — the
    # spawner ignores interval/timeout keys.
    cfg["heartbeat_chain"] = {
        "enabled": True,
        "contract_address": args.heartbeat_chain_contract,
    }

    return json.dumps(cfg, separators=(",", ":"))

def cmd_build_request(args):
    w3 = Web3(Web3.HTTPProvider(args.rpc))
    executor = Web3.to_checksum_address(args.executor_tee_address)
    consumer = Web3.to_checksum_address(args.consumer)
    owner = Web3.to_checksum_address(args.owner)
    pub_key_hex = args.executor_pubkey[2:] if args.executor_pubkey.startswith("0x") else args.executor_pubkey

    provider_name, llm_key_ref, llm_key_value = choose_provider_and_key()
    model = os.getenv("MODEL", default_model_for_provider(provider_name))

    agent_id = int(args.agent_id)
    revision = int(args.revision)
    da_config, da_secrets = build_da_config(args.da_provider, agent_id)

    cmd_check_runtime_config(args)
    _, connector_secrets = connector_configuration()
    secrets = {llm_key_ref: llm_key_value, **da_secrets, **connector_secrets}
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if tg_token:
        secrets["TELEGRAM_BOT_TOKEN"] = tg_token

    # ONE encrypted blob, ONE distinct secret owner (the EOA). Multiple
    # distinct owners are a settled-with-error failure at Phase 1.
    encrypted_blob = ecies_encrypt(pub_key_hex, build_secret_envelope(owner, secrets))
    secret_signature = create_secret_signature(
        PERSISTENT_USE_CONTEXT, w3.eth.chain_id, executor, owner, encrypted_blob, args.private_key
    )

    runtime_config_json = build_runtime_config(args)

    # The output key stays local; create the file exclusively with private permissions.
    output_key = PrivateKey("secp256k1")
    descriptor = os.open(args.output_private_key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="ascii") as key_file:
        key_file.write(output_key.to_hex())
    user_public_key = output_key.public_key.to_bytes(compressed=False)

    soul = os.getenv("SOUL", "You are a helpful persistent agent on Ritual Chain.")
    agents_doc = os.getenv("AGENTS_DOC", "")
    user_doc = os.getenv("USER_DOC", "")
    memory_doc = os.getenv("MEMORY_DOC", "")
    identity_doc = os.getenv("IDENTITY_DOC", "")
    tools_doc = os.getenv("TOOLS_DOC", "")
    rpc_urls = json.dumps({"ritual": args.agent_rpc_url})

    delivery_selector = Web3.keccak(text="onPersistentAgentResult(bytes32,bytes)")[:4]

    # 21-field V1 executor payload (opaque to protocol contracts).
    payload_values = [
        1,                           # version (must be 1)
        [owner],
        [encrypted_blob],
        [secret_signature],
        user_public_key,             # encrypt Phase 1 and Phase 2 output to a local one-time key
        LLM_PROVIDER[provider_name],
        model,
        llm_key_ref,
        da_config,
        inline_ref(soul),
        inline_ref(agents_doc),
        inline_ref(user_doc),
        inline_ref(memory_doc),
        inline_ref(identity_doc),
        inline_ref(tools_doc),
        ("inline", runtime_config_json, "") if runtime_config_json else empty_ref(),
        "",                          # restore_from_cid
        rpc_urls,
        AGENT_RUNTIME[args.agent_runtime],
        agent_id,                    # chain-issued agentId (pre-allocated)
        revision,
    ]
    executor_payload = encode(PERSISTENT_PAYLOAD_V1_TYPES, payload_values)

    # applicationContext binds the identity: keccak256(abi.encode(agentId, revision)).
    # Enforced by the consumer (InvalidApplicationContext), the executor, and DKMS.
    application_context = bytes(
        Web3.keccak(encode(["uint256", "uint64"], [agent_id, revision]))
    )

    envelope_values = [
        executor,
        owner,                       # sponsor — EOA authorizes consumer in RitualWallet
        500,                         # ttl (async job TTL, blocks)
        6000,                        # phase2_ttl / max spawn block (matches chain revival constant)
        True,                        # callback_enabled (observability; target must be the consumer)
        consumer,                    # callback_target — consumer validates it == itself when enabled
        delivery_selector,
        1_000_000,                   # callback_gas_limit
        1_000_000_000,               # callback_max_fee_per_gas (1 gwei)
        100_000_000,                 # callback_max_priority_fee_per_gas (0.1 gwei)
        0,                           # callback_value
        application_context,
        executor_payload,
    ]

    request_input = encode(AGENT_ENVELOPE_TYPES, envelope_values)
    print(f"LLM_PROVIDER={provider_name}")
    print(f"MODEL={model}")
    print(f"REQUEST_INPUT=0x{request_input.hex()}")
    calldata = Web3.keccak(text="callPersistentAgent(uint256,uint64,bytes)")[:4] + encode(["uint256", "uint64", "bytes"], [agent_id, revision, request_input])
    print(f"CALLDATA=0x{calldata.hex()}")
    print(f"SECRETS_HASH={_to_hex(Web3.keccak(encrypted_blob))}")

def cmd_encode_grant_calldata(args):
    selector = Web3.keccak(text=GRANT_ACCESS_SIG)[:4]
    empty_policy = ([], [], [], [], [], "", "")
    payload = encode(
        ["address", "bytes32", "uint256", "(string[],string[],string[],string[],string[],string,string)"],
        [Web3.to_checksum_address(args.delegate), _to_bytes(args.secrets_hash), MAX_UINT256, empty_policy],
    )
    print(f"CALLDATA=0x{(selector + payload).hex()}")


def _receipt_logs_matching(receipt: dict, event_sig: str, address: str | None = None):
    topic0 = Web3.keccak(text=event_sig).hex().lower()
    if not topic0.startswith("0x"):
        topic0 = "0x" + topic0
    for log in receipt.get("logs", []):
        topics = log.get("topics") or []
        if not topics:
            continue
        t0 = str(topics[0]).lower()
        if not t0.startswith("0x"):
            t0 = "0x" + t0
        if t0 != topic0:
            continue
        if address and str(log.get("address", "")).lower() != address.lower():
            continue
        yield log

def receipt_succeeded(receipt):
    value = receipt.get("status")
    if isinstance(value, str):
        try:
            value = int(value, 16) if value.startswith("0x") else int(value)
        except ValueError:
            return False
    return value == 1

def cmd_check_receipt(_args):
    if not receipt_succeeded(json.load(sys.stdin)):
        die("Receipt status is reverted, missing, or invalid")
    print("RECEIPT_SUCCESS=1")

def cmd_parse_agent_id(_args):
    receipt = json.load(sys.stdin)
    for log in _receipt_logs_matching(receipt, EVT_AGENT_ID_ALLOCATED):
        print(f"AGENT_ID={int(str(log['topics'][1]), 16)}")
        return
    die("No AgentIdAllocated event found in receipt — allocateAgentId tx did not allocate.")

def cmd_find_tx(args):
    """Recover a tx hash by (sender, nonce) — used when a duplicate RPC
    submission made cast lose the hash. Scans recent blocks newest-first."""
    w3 = Web3(Web3.HTTPProvider(args.rpc))
    sender = Web3.to_checksum_address(args.sender)
    head = w3.eth.block_number
    for bn in range(head, max(head - args.lookback, 0) - 1, -1):
        block = w3.eth.get_block(bn, full_transactions=True)
        for tx in block.transactions:
            if tx["from"] == sender and tx["nonce"] == args.nonce:
                print(f"TX_HASH={tx['hash'].hex() if hasattr(tx['hash'], 'hex') else tx['hash']}")
                return
    die(f"no tx from {sender} with nonce {args.nonce} in last {args.lookback} blocks")


def cmd_wait_heartbeat(args):
    w3 = Web3(Web3.HTTPProvider(args.rpc))
    heartbeat = w3.eth.contract(
        address=Web3.to_checksum_address(args.heartbeat), abi=AGENT_HEARTBEAT_GET_ASSIGNMENT_ABI
    )
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        try:
            assignment = heartbeat.functions.getAssignment(int(args.agent_id)).call()
        except Exception:
            time.sleep(POLL_INTERVAL_S)
            continue
        state = int(assignment[0])
        agent_address = Web3.to_checksum_address(assignment[2])
        if state == 1 and agent_address != ZERO_ADDRESS:  # 1 == SlotState.ACTIVE
            print(f"AGENT_ADDRESS={agent_address}")
            print(f"BOUND_EXECUTOR={Web3.to_checksum_address(assignment[4])}")
            print(f"LAST_HEARTBEAT={int(assignment[5])}")
            print(f"HEARTBEAT_TIMEOUT_BLOCKS={int(assignment[6])}")
            print(f"LATEST_MANIFEST_CID={assignment[8]}")
            return
        time.sleep(POLL_INTERVAL_S)

    print("FAILURE_FAMILY=no-claim", file=sys.stderr)
    die(
        f"AgentHeartbeat slot for agentId={args.agent_id} did not become ACTIVE within {args.timeout}s. "
        "The container spawned but the runtime never claimed its slot. Common causes: "
        "runtime EOA balance < 0.1 RIT at claim time (fund the prelaunch wallet with more), "
        "DA sync failed inside the container (bad DA credentials), or the executor could not "
        "co-sign the claim. This is the launch success gate — the launch is NOT successful."
    )

AGENT_PRECOMPILE = "0x0000000000000000000000000000000000000820"
RESULT_EVENT = "PersistentAgentResultDelivered(bytes32,bytes)"
PHASE1_TYPES = PERSISTENT_RESPONSE_TYPES
RESULT_TYPES = PERSISTENT_RESPONSE_TYPES

def cmd_parse_deployment(_args):
    receipt = json.load(sys.stdin)
    if not receipt_succeeded(receipt) or not Web3.is_address(receipt.get("contractAddress", "")):
        die("Consumer deployment failed or returned no contract address")
    print(f"CONSUMER={Web3.to_checksum_address(receipt['contractAddress'])}")


def observation_logs(w3, params):
    """Retry transient read transport failures within the caller's polling deadline."""
    try:
        return w3.eth.get_logs(params)
    except (RPCConnectionError, RPCTimeout):
        return []


def job_documents(w3, args):
    # For an ordinary EOA request, the job ID is the original signed tx hash.
    # The commitment transaction can differ; match indexed jobId exactly.
    hashes = [args.tx_hash]
    logs = observation_logs(w3, {"address": Web3.to_checksum_address(args.tracker),
        "fromBlock": args.from_block, "toBlock": "latest",
        "topics": [Web3.keccak(text=EVT_JOB_ADDED), None, args.tx_hash]})
    for log in logs:
        value = _to_hex(log["transactionHash"])
        if value not in hashes:
            hashes.append(value)
    for tx_hash in hashes:
        try:
            receipt = w3.eth.get_transaction_receipt(tx_hash)
        except Exception:
            receipt = None
        if receipt is not None:
            if not receipt_succeeded(receipt):
                die("Agent transaction reverted; reconcile before retrying")
            yield receipt
        try:
            tx = w3.eth.get_transaction(tx_hash)
        except Exception:
            tx = None
        if tx and tx.get("blockNumber") is not None:
            yield tx


def decrypt_spawn_output(args, data):
    try:
        with open(args.output_private_key_file, encoding="ascii") as key_file:
            private_key = key_file.read().strip()
        return ecies_decrypt(private_key, data)
    except Exception:
        die("Cannot decrypt private spawn output; reconcile this job without resubmitting")


def cmd_wait_phase1(args):
    w3 = Web3(Web3.HTTPProvider(args.rpc))
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        for document in job_documents(w3, args):
            for call in document.get("spcCalls") or []:
                if str(call.get("address", "")).lower() != AGENT_PRECOMPILE.lower():
                    continue
                raw = _to_bytes(call.get("output") or "0x")
                if not raw:
                    continue
                # RPC spcCalls.output is the bare executor output. The
                # (bytes,bytes) wrapper belongs only to Solidity CALL returns.
                fields = decode(PHASE1_TYPES, decrypt_spawn_output(args, raw))
                print(f"JOB_ID={args.tx_hash}")
                instance, _gateway, _container, _checkpoint, error, prelaunch = fields
                if error:
                    die("Phase 1 failed; raw error output withheld")
                if not instance or not Web3.is_address(prelaunch):
                    die("Phase 1 returned no valid prelaunch wallet")
                print(f"PHASE1_INSTANCE_ID={instance}")
                print(f"PRELAUNCH_WALLET={Web3.to_checksum_address(prelaunch)}")
                return
        time.sleep(POLL_INTERVAL_S)
    die("No settled Phase-1 SPC output for this exact origin job; inspect authorization, ABI and executor logs before resubmitting")


def cmd_wait_result(args):
    w3 = Web3(Web3.HTTPProvider(args.rpc))
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        logs = observation_logs(w3, {"address": Web3.to_checksum_address(args.consumer),
            "fromBlock": args.from_block, "toBlock": "latest",
            "topics": [Web3.keccak(text=RESULT_EVENT), args.tx_hash]})
        for log in logs:
            # Match again so unit/RPC fixtures cannot accidentally select a foreign job.
            if _to_hex(log["topics"][1]).lower() != args.tx_hash.lower():
                continue
            (result,) = decode(["bytes"], _to_bytes(log["data"]))
            fields = decode(RESULT_TYPES, decrypt_spawn_output(args, result))
            instance, gateway, container, checkpoint, error, token = fields
            print(f"INSTANCE_ID={instance}")
            print(f"CONTAINER_ID={container}")
            print(f"CHECKPOINT_CID={checkpoint}")
            print(f"GATEWAY_URL_PRESENT={int(bool(gateway))}")
            print(f"GATEWAY_TOKEN_PRESENT={int(bool(token))}")
            success = bool(instance) and not error
            print(f"SUCCESS={int(bool(success))}")
            if not success:
                die("Agent result indicates failure; raw diagnostic output withheld")
            return
        time.sleep(POLL_INTERVAL_S)
    die("No callback result for this exact origin job; inspect settled Phase 1 and delivery status, do not blindly submit another agent")

def cmd_check_inputs(args):
    choose_provider_and_key()
    if args.da_provider == "gcs":
        raw = os.getenv("GCS_DA_SERVICE_ACCOUNT_JSON", "")
        if not raw or not os.getenv("GCS_DA_BUCKET"):
            die("GCS service account JSON and bucket required", 2)
        try:
            account = json.loads(raw)
        except ValueError:
            die("GCS service account must be JSON, not a path or base64 string", 2)
        if not isinstance(account, dict) or account.get("type") != "service_account":
            die("GCS credentials must be a service-account JSON object", 2)
    elif args.da_provider == "hf":
        if not os.getenv("HF_TOKEN") or "/" not in os.getenv("HF_REPO_ID", ""):
            die("HF_TOKEN and HF_REPO_ID (owner/repo) required", 2)
    elif args.da_provider == "pinata":
        if not os.getenv("DA_PINATA_JWT"):
            die("DA_PINATA_JWT required", 2)
    else:
        die("Unsupported DA_PROVIDER", 2)
    print("INPUTS_VALID=1")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("select-executor")
    p.add_argument("--rpc", required=True); p.add_argument("--registry", required=True)
    p.add_argument("--executor-tee-address", default="")
    p.add_argument("--allowed-executors", default=""); p.add_argument("--excluded-executors", default="")
    p.add_argument("--require-health", action="store_true"); p.add_argument("--max-agents", type=int, default=10)
    p.set_defaults(func=cmd_select_executor)
    p = sub.add_parser("find-tx")
    p.add_argument("--rpc", required=True); p.add_argument("--sender", required=True)
    p.add_argument("--nonce", type=int, required=True); p.add_argument("--lookback", type=int, default=60)
    p.set_defaults(func=cmd_find_tx)
    for name, fn in [("check-receipt", cmd_check_receipt), ("parse-deployment", cmd_parse_deployment)]:
        p = sub.add_parser(name); p.set_defaults(func=fn)
    p = sub.add_parser("build-request")
    for flag in ["rpc", "consumer", "owner", "executor-tee-address", "executor-pubkey", "da-provider"]:
        p.add_argument("--"+flag, required=True)
    p.add_argument("--output-private-key-file", required=True)
    p.set_defaults(func=cmd_build_request)
    p.add_argument("--agent-id", type=int, required=True); p.add_argument("--revision", type=int, default=0)
    p.add_argument("--agent-runtime", choices=["hermes", "zeroclaw"], default="hermes")
    p.add_argument("--agent-rpc-url", required=True); p.add_argument("--heartbeat-chain-contract", required=True)
    p = sub.add_parser("parse-agent-id"); p.set_defaults(func=cmd_parse_agent_id)
    p = sub.add_parser("check-runtime-config")
    p.add_argument("--agent-runtime", choices=["hermes", "zeroclaw"], default="hermes"); p.set_defaults(func=cmd_check_runtime_config)
    p = sub.add_parser("wait-heartbeat")
    p.add_argument("--rpc", required=True); p.add_argument("--heartbeat", required=True)
    p.add_argument("--agent-id", type=int, required=True); p.add_argument("--timeout", type=int, default=120)
    p.set_defaults(func=cmd_wait_heartbeat)
    p = sub.add_parser("encode-grant-calldata")
    p.add_argument("--delegate", required=True); p.add_argument("--secrets-hash", required=True)
    p.set_defaults(func=cmd_encode_grant_calldata)
    for name, fn in [("wait-phase1", cmd_wait_phase1), ("wait-result", cmd_wait_result)]:
        p = sub.add_parser(name)
        for flag in ["rpc", "consumer", "tracker", "tx-hash"]: p.add_argument("--"+flag, required=True)
        p.add_argument("--from-block", type=int, required=True); p.add_argument("--timeout", type=int, default=300)
        p.add_argument("--output-private-key-file", required=True)
        p.set_defaults(func=fn)
    p = sub.add_parser("check-inputs")
    p.add_argument("--da-provider", required=True); p.set_defaults(func=cmd_check_inputs)
    args = parser.parse_args()
    args.private_key = os.environ.get("PRIVATE_KEY", "")
    args.func(args)

if __name__ == "__main__":
    main()

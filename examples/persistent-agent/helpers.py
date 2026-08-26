#!/usr/bin/env python3
"""Helpers for the persistent-agent example.

Called by run.sh for:
1) Executor discovery
2) DKMS request encoding + result decode
3) Persistent agent request encoding
4) Phase 2 callback polling + decode
5) Optional relay verification
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
import subprocess
from urllib import error, request

from ecies import encrypt as ecies_encrypt
from ecies.config import ECIES_CONFIG
from eth_abi.abi import decode, encode
from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3

ECIES_CONFIG.symmetric_nonce_length = 12

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
                            {"name": "publicKey", "type": "bytes"},
                            {"name": "endpoint", "type": "string"},
                            {"name": "certPubKeyHash", "type": "bytes32"},
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

DKMS_REQUEST_TYPES = [
    "address",
    "bytes[]",
    "uint256",
    "bytes[]",
    "bytes",
    "address",
    "uint256",
    "uint8",
]

PERSISTENT_REQUEST_TYPES = [
    "address",
    "bytes[]",
    "uint256",
    "bytes[]",
    "bytes",
    "uint64",
    "address",
    "bytes4",
    "uint256",
    "uint256",
    "uint256",
    "uint256",
    "uint8",
    "string",
    "string",
    "(string,string,string)",
    "(string,string,string)",
    "(string,string,string)",
    "(string,string,string)",
    "(string,string,string)",
    "(string,string,string)",
    "(string,string,string)",
    "(string,string,string)",
    "string",
    "string",
    "uint16",
]

PERSISTENT_RESPONSE_TYPES = [
    "string",
    "string",
    "string",
    "string",
    "string",
    "string",
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


def get_executor(w3: Web3, registry_addr: str, explicit_executor: str = ""):
    registry = w3.eth.contract(address=Web3.to_checksum_address(registry_addr), abi=TEE_SERVICE_REGISTRY_ABI)
    services = registry.functions.getServicesByCapability(0, True).call()
    if not services:
        print("ERROR: No valid HTTP_CALL executors found in TEEServiceRegistry.", file=sys.stderr)
        sys.exit(1)

    if explicit_executor:
        target = Web3.to_checksum_address(explicit_executor)
        for service in services:
            node = service[0]
            tee_addr = Web3.to_checksum_address(node[1])
            if tee_addr == target:
                return tee_addr, bytes(node[3])
        print(f"ERROR: Requested executor {target} not found among valid HTTP_CALL services.", file=sys.stderr)
        sys.exit(1)

    node = services[0][0]
    return Web3.to_checksum_address(node[1]), bytes(node[3])


def build_dkms_request_input(executor: str, owner: str, key_index: int, ttl: int = 60) -> bytes:
    values = [
        Web3.to_checksum_address(executor),
        [],
        ttl,
        [],
        b"",
        Web3.to_checksum_address(owner),
        key_index,
        1,  # Eth format
    ]
    return encode(DKMS_REQUEST_TYPES, values)


def create_secret_signature(encrypted_blob: bytes) -> bytes:
    """
    Sign the encrypted secrets blob securely.
    Supports FOUNDRY_ACCOUNT (via cast shellout) to prevent raw PRIVATE_KEY exposure and signature divergence,
    or falls back to the raw PRIVATE_KEY for compatibility.
    """
    foundry_account = os.getenv("FOUNDRY_ACCOUNT")
    if foundry_account:
        # Securely sign via Foundry keystore to avoid raw private key exposure
        hex_blob = "0x" + encrypted_blob.hex()
        try:
            # cast wallet sign automatically applies the EIP-191 prefix
            cmd = ["cast", "wallet", "sign", "--account", foundry_account, hex_blob]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            sig_hex = result.stdout.strip()
            return bytes.fromhex(sig_hex[2:] if sig_hex.startswith("0x") else sig_hex)
        except subprocess.CalledProcessError as e:
            print(f"ERROR: Failed to sign secrets with FOUNDRY_ACCOUNT. {e.stderr}", file=sys.stderr)
            sys.exit(1)

    private_key = os.getenv("PRIVATE_KEY")
    if private_key:
        message = encode_defunct(encrypted_blob)
        account = Account.from_key(private_key)
        return bytes(account.sign_message(message).signature)
        
    raise ValueError("Must provide either FOUNDRY_ACCOUNT or PRIVATE_KEY for signing")


def choose_provider_and_key() -> tuple[str, str, str]:
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic", "LLM_API_KEY", os.environ["ANTHROPIC_API_KEY"]
    if os.getenv("OPENAI_API_KEY"):
        return "openai", "LLM_API_KEY", os.environ["OPENAI_API_KEY"]
    if os.getenv("GEMINI_API_KEY"):
        return "gemini", "LLM_API_KEY", os.environ["GEMINI_API_KEY"]
    if os.getenv("OPENROUTER_API_KEY"):
        return "openrouter", "LLM_API_KEY", os.environ["OPENROUTER_API_KEY"]
    print("ERROR: Missing LLM API key.", file=sys.stderr)
    sys.exit(1)


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


def build_da_config(da_provider: str) -> tuple[tuple[str, str, str], dict[str, str]]:
    secrets: dict[str, str] = {}

    if da_provider == "hf":
        hf_token = os.getenv("HF_TOKEN", "")
        hf_repo_id = os.getenv("HF_REPO_ID", "")
        if not hf_token or not hf_repo_id:
            print("ERROR: DA_PROVIDER=hf requires HF_TOKEN and HF_REPO_ID", file=sys.stderr)
            sys.exit(1)
        secrets["HF_TOKEN"] = hf_token
        return ("hf", hf_repo_id, "HF_TOKEN"), secrets

    if da_provider == "gcs":
        sa_json = os.getenv("GCS_DA_SERVICE_ACCOUNT_JSON", "")
        bucket = os.getenv("GCS_DA_BUCKET", "")
        prefix = os.getenv("GCS_DA_PREFIX", "")
        if not sa_json or not bucket:
            print("ERROR: DA_PROVIDER=gcs requires GCS_DA_SERVICE_ACCOUNT_JSON and GCS_DA_BUCKET", file=sys.stderr)
            sys.exit(1)
        secrets["GCS_CREDENTIALS"] = json.dumps(
            {
                "service_account_json": sa_json,
                "bucket": bucket,
            }
        )
        return ("gcs", prefix, "GCS_CREDENTIALS"), secrets

    if da_provider == "pinata":
        jwt = os.getenv("DA_PINATA_JWT", "")
        if not jwt:
            print("ERROR: DA_PROVIDER=pinata requires DA_PINATA_JWT", file=sys.stderr)
            sys.exit(1)
        secrets["DA_PINATA_JWT"] = jwt
        gateway = os.getenv("DA_PINATA_GATEWAY", "")
        if gateway:
            secrets["DA_PINATA_GATEWAY"] = gateway
        return ("pinata", "", "DA_PINATA_JWT"), secrets

    print("ERROR: DA_PROVIDER must be one of hf, gcs, pinata", file=sys.stderr)
    sys.exit(1)


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

    if args.heartbeat_interval:
        hb_cfg: dict[str, str] = {"every": args.heartbeat_interval, "target": "none"}
        if args.heartbeat_prompt:
            hb_cfg["prompt"] = args.heartbeat_prompt
        cfg["agents"] = {"defaults": {"heartbeat": hb_cfg}}

    cfg["heartbeat_chain"] = {
        "enabled": True,
        "contract_address": args.heartbeat_chain_contract,
        "rpc_url": args.agent_rpc_url,
        "interval_blocks": args.heartbeat_chain_interval_blocks,
        "heartbeat_timeout_blocks": args.heartbeat_chain_timeout_blocks,
    }

    return json.dumps(cfg) if cfg else ""


def build_persistent_request_input(
    w3: Web3,
    executor: str,
    pub_key_bytes: bytes,
    consumer: str,
    args: argparse.Namespace,
) -> tuple[bytes, str, str]:
    provider_name, llm_key_ref, llm_key_value = choose_provider_and_key()
    model = os.getenv("MODEL", default_model_for_provider(provider_name))

    da_config, da_secrets = build_da_config(args.da_provider)

    secrets = {llm_key_ref: llm_key_value, **da_secrets}
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if tg_token:
        secrets["TELEGRAM_BOT_TOKEN"] = tg_token

    secrets_json = json.dumps(secrets)
    encrypted_blob = ecies_encrypt(pub_key_bytes.hex(), secrets_json.encode())
    
    # Correctly call the refactored signature generation function
    secret_signature = create_secret_signature(encrypted_blob)

    runtime_config_json = build_runtime_config(args)

    soul = os.getenv("SOUL", "You are a helpful persistent agent on Ritual Chain.")
    agents_doc = os.getenv("AGENTS_DOC", "")
    user_doc = os.getenv("USER_DOC", "")
    memory_doc = os.getenv("MEMORY_DOC", "")
    identity_doc = os.getenv("IDENTITY_DOC", "")
    tools_doc = os.getenv("TOOLS_DOC", "")
    rpc_urls = json.dumps({"ritual": args.agent_rpc_url})

    delivery_selector = Web3.keccak(text="onPersistentAgentResult(bytes32,bytes)")[:4]

    values = [
        Web3.to_checksum_address(executor),
        [encrypted_blob],
        500,  # ttl
        [secret_signature],
        b"",  # user_public_key
        6000,  # max_spawn_block
        Web3.to_checksum_address(consumer),
        delivery_selector,
        500_000,
        1_000_000_000,
        100_000_000,
        0,
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
        "",
        rpc_urls,
        AGENT_RUNTIME[args.agent_runtime],
    ]

    return encode(PERSISTENT_REQUEST_TYPES, values), provider_name, model


def decode_outer_bytes(log_data: bytes) -> bytes:
    return decode(["bytes"], log_data)[0]


def poll_dkms_result(w3: Web3, consumer: str, tx_hash: str, timeout: int = 300):
    start = time.time()
    while time.time() - start < timeout:
        try:
            tx = w3.eth.get_transaction(tx_hash)
        except Exception:
            time.sleep(1)
            continue

        spc_calls = tx.get("spcCalls") or []
        for spc_call in spc_calls:
            if (spc_call.get("address") or "").lower() != "0x000000000000000000000000000000000000081b":
                continue
            output_hex = spc_call.get("output") or ""
            if not output_hex or output_hex == "0x":
                continue
            output_bytes = bytes.fromhex(output_hex[2:] if output_hex.startswith("0x") else output_hex)
            payment_address, public_key = decode(["address", "bytes"], output_bytes)
            print(f"PAYMENT_ADDRESS={Web3.to_checksum_address(payment_address)}")
            print(f"PUBLIC_KEY=0x{bytes(public_key).hex()}")
            return

        time.sleep(1)

    print(f"ERROR: timeout waiting for DKMS result after {timeout}s", file=sys.stderr)
    sys.exit(1)


def poll_phase2(w3: Web3, consumer: str, tx_hash: str, from_block: int, timeout: int = 300):
    event_sig = Web3.keccak(text="PersistentAgentResultDelivered(bytes32,bytes)")
    tx_hash_hex = tx_hash[2:] if tx_hash.startswith("0x") else tx_hash
    job_topic = "0x" + tx_hash_hex.rjust(64, "0")
    start = time.time()

    while time.time() - start < timeout:
        logs = w3.eth.get_logs(
            {
                "address": Web3.to_checksum_address(consumer),
                "topics": [event_sig, job_topic],
                "fromBlock": int(from_block),
                "toBlock": "latest",
            }
        )
        if logs:
            result_bytes = decode_outer_bytes(bytes(logs[-1]["data"]))
            instance_id, gateway_url, container_id, checkpoint_cid, error_message, gateway_token = decode(
                PERSISTENT_RESPONSE_TYPES, result_bytes
            )
            print(f"PHASE2_SECONDS={time.time() - start:.1f}")
            print(f"INSTANCE_ID={instance_id}")
            print(f"GATEWAY_URL={gateway_url}")
            print(f"CONTAINER_ID={container_id}")
            print(f"CHECKPOINT_CID={checkpoint_cid}")
            print(f"ERROR_MESSAGE={error_message}")
            print(f"GATEWAY_TOKEN={gateway_token}")
            if error_message:
                sys.exit(1)
            return
        time.sleep(1)

    print(f"ERROR: timeout waiting for PersistentAgentResultDelivered after {timeout}s", file=sys.stderr)
    sys.exit(1)


def _http_json(method: str, url: str, body: dict | None = None) -> dict:
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = request.Request(url, method=method, data=data, headers=headers)
    with request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def verify_relay(relay_url: str, agent_address: str, timeout: int = 60):
    relay = relay_url.rstrip("/")
    # Wait until the agent is visible
    start = time.time()
    while time.time() - start < timeout:
        health = _http_json("GET", f"{relay}/health")
        if any(a["id"].lower() == agent_address.lower() for a in health.get("agents", [])):
            break
        time.sleep(2)
    else:
        print("ERROR: agent never appeared on relay", file=sys.stderr)
        sys.exit(1)

    token = f"persistent-example-{uuid.uuid4().hex[:8]}"
    message = f"Reply with the exact token {token} and also tell me your address."
    _http_json("POST", f"{relay}/send/{agent_address}", {"message": message})

    start = time.time()
    while time.time() - start < timeout:
        replies = _http_json("GET", f"{relay}/replies/{agent_address}")
        for msg in replies.get("messages", []):
            content = msg.get("content", "")
            if "HEARTBEAT_OK" in content:
                continue
            if token in content:
                print(f"RELAY_VERIFIED=1")
                print(f"RELAY_REPLY={content}")
                return
        time.sleep(2)

    print("ERROR: relay verification timed out waiting for agent reply", file=sys.stderr)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("build-dkms-request")
    p1.add_argument("--rpc", required=True)
    p1.add_argument("--registry", required=True)
    p1.add_argument("--owner", required=True)
    p1.add_argument("--key-index", type=int, default=0)
    p1.add_argument("--executor-tee-address", default="")

    p2 = sub.add_parser("poll-dkms")
    p2.add_argument("--rpc", required=True)
    p2.add_argument("--consumer", required=True)
    p2.add_argument("--tx-hash", required=True)
    p2.add_argument("--timeout", type=int, default=300)

    p3 = sub.add_parser("build-persistent-request")
    p3.add_argument("--rpc", required=True)
    p3.add_argument("--registry", required=True)
    p3.add_argument("--consumer", required=True)
    p3.add_argument("--executor-tee-address", required=True)
    p3.add_argument("--da-provider", required=True)
    p3.add_argument("--agent-rpc-url", required=True)
    p3.add_argument("--heartbeat-chain-contract", required=True)
    p3.add_argument("--heartbeat-chain-interval-blocks", type=int, required=True)
    p3.add_argument("--heartbeat-chain-timeout-blocks", type=int, required=True)
    p3.add_argument("--heartbeat-interval", default="")
    p3.add_argument("--heartbeat-prompt", default="")
    p3.add_argument("--agent-runtime", choices=["zeroclaw", "hermes"], default="zeroclaw")

    p4 = sub.add_parser("poll-phase2")
    p4.add_argument("--rpc", required=True)
    p4.add_argument("--consumer", required=True)
    p4.add_argument("--tx-hash", required=True)
    p4.add_argument("--from-block", required=True)
    p4.add_argument("--timeout", type=int, default=300)

    p5 = sub.add_parser("verify-relay")
    p5.add_argument("--relay-url", required=True)
    p5.add_argument("--agent-address", required=True)
    p5.add_argument("--timeout", type=int, default=60)

    args = parser.parse_args()

    if args.cmd == "verify-relay":
        verify_relay(args.relay_url, args.agent_address, timeout=args.timeout)
        return

    w3 = Web3(Web3.HTTPProvider(args.rpc))

    if args.cmd == "build-dkms-request":
        executor, _ = get_executor(w3, args.registry, args.executor_tee_address)
        request_input = build_dkms_request_input(executor, args.owner, args.key_index)
        print(f"EXECUTOR={executor}")
        print(f"REQUEST_INPUT=0x{request_input.hex()}")
        return

    if args.cmd == "poll-dkms":
        poll_dkms_result(w3, args.consumer, args.tx_hash, timeout=args.timeout)
        return

    if args.cmd == "build-persistent-request":
        executor, pub_key = get_executor(w3, args.registry, args.executor_tee_address)
        request_input, provider_name, model = build_persistent_request_input(
            w3=w3,
            executor=executor,
            pub_key_bytes=pub_key,
            consumer=args.consumer,
            args=args,
        )
        print(f"EXECUTOR={executor}")
        print(f"LLM_PROVIDER={provider_name}")
        print(f"MODEL={model}")
        print(f"AGENT_RUNTIME={args.agent_runtime}")
        print(f"REQUEST_INPUT=0x{request_input.hex()}")
        return

    if args.cmd == "poll-phase2":
        poll_phase2(w3, args.consumer, args.tx_hash, int(args.from_block), timeout=args.timeout)
        return


if __name__ == "__main__":
    main()

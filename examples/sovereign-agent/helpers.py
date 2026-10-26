#!/usr/bin/env python3
"""Standalone sovereign request encoder and exact job observer."""

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

from ecies import encrypt as ecies_encrypt

from ecies.config import ECIES_CONFIG

from eth_abi.abi import decode, encode

from eth_account import Account

from eth_account.messages import encode_defunct

from web3 import Web3

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

SECRET_AUTH_DOMAIN = b"RITUAL_SECRET_AUTHORIZATION_V1"

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
        die("No eligible registered HTTP executor; an explicit pin is never substituted")
    tee, pub, _endpoint = nodes[0]
    print(f"EXECUTOR={tee}")
    print(f"EXECUTOR_PUBKEY=0x{pub.hex()}")


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

def cmd_encode_grant_calldata(args):
    selector = Web3.keccak(text=GRANT_ACCESS_SIG)[:4]
    empty_policy = ([], [], [], [], [], "", "")
    payload = encode(
        ["address", "bytes32", "uint256", "(string[],string[],string[],string[],string[],string,string)"],
        [Web3.to_checksum_address(args.delegate), _to_bytes(args.secrets_hash), MAX_UINT256, empty_policy],
    )
    print(f"CALLDATA=0x{(selector + payload).hex()}")


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

SOVEREIGN_USE_CONTEXT = "precompile:0x000000000000000000000000000000000000080c"

SOVEREIGN_V1_PAYLOAD_TYPES = [
    "uint8",                      # version (must be 1)
    "address[]",                  # secret owners
    "bytes[]",                    # encrypted secrets
    "bytes[]",                    # secret signatures
    "bytes",                      # user public key
    "uint16",                     # agent (CLI) type
    "string",                     # prompt
    "(string,string,string)",     # convoHistory ref
    "(string,string,string)",     # output ref
    "(string,string,string)[]",   # skills
    "(string,string,string)",     # systemPrompt ref
    "string",                     # model
    "string[]",                   # tools
    "uint16",                     # maxTurns
    "uint32",                     # maxTokens
    "string",                     # rpcUrls
]

SOVEREIGN_RESULT_TYPES = [
    "bool",                        # success
    "string",                      # error
    "string",                      # text response
    "(string,string,string)",      # convoHistory ref
    "(string,string,string)",      # output ref
    "(string,string,string)[]",    # artifacts
]

def _validate_hf_repo_id(value: str) -> str:
    if not value or value.strip() != value:
        die("--hf-repo-id is required and must be a HuggingFace dataset ID in 'user/repo' form.", 2)
    if "<" in value or ">" in value or "YOUR_" in value or "YOUR-" in value:
        die(f"--hf-repo-id looks like an unfilled placeholder ({value!r}).", 2)
    if not _HF_REPO_ID_PATTERN.match(value):
        die(f"--hf-repo-id ({value!r}) is not a valid 'user/repo' HuggingFace dataset ID.", 2)
    return value

def _storage_refs(args) -> tuple:
    if args.da_provider == "hf":
        hf_repo_id = _validate_hf_repo_id(args.hf_repo_id)
        convo_ref = ("hf", f"{hf_repo_id}/sessions/session-001.jsonl", "HF_TOKEN")
        output_ref = ("hf", f"{hf_repo_id}/artifacts/", "HF_TOKEN")
        system_ref = ("hf", f"{hf_repo_id}/prompts/default-system.md", "")
    elif args.da_provider == "gcs":
        prefix = (args.gcs_prefix or "sovereign-agent").rstrip("/")
        convo_ref = ("gcs", f"{prefix}/sessions/session-001.jsonl", "GCS_CREDENTIALS")
        output_ref = ("gcs", f"{prefix}/artifacts/", "GCS_CREDENTIALS")
        system_ref = ("", "", "")
    else:
        die("--da-provider must be one of: hf, gcs", 2)
    return convo_ref, output_ref, system_ref

AGENT_PRECOMPILE = "0x000000000000000000000000000000000000080c"
RESULT_EVENT = "SovereignAgentResultDelivered(bytes32,bytes)"
PHASE1_TYPES = ["string"]
RESULT_TYPES = SOVEREIGN_RESULT_TYPES

def cmd_parse_deployment(_args):
    receipt = json.load(sys.stdin)
    if not receipt_succeeded(receipt) or not Web3.is_address(receipt.get("contractAddress", "")):
        die("Consumer deployment failed or returned no contract address")
    print(f"CONSUMER={Web3.to_checksum_address(receipt['contractAddress'])}")


def job_documents(w3, args):
    # For an ordinary EOA request, the job ID is the original signed tx hash.
    # The commitment transaction can differ; match indexed jobId exactly.
    hashes = [args.tx_hash]
    logs = w3.eth.get_logs({"address": Web3.to_checksum_address(args.tracker),
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
                fields = decode(PHASE1_TYPES, raw)
                print(f"JOB_ID={args.tx_hash}")
                print(f"TASK_ID={fields[0]}")
                return
        time.sleep(POLL_INTERVAL_S)
    die("No settled Phase-1 SPC output for this exact origin job; inspect authorization, ABI and executor logs before resubmitting")


def cmd_wait_result(args):
    w3 = Web3(Web3.HTTPProvider(args.rpc))
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        logs = w3.eth.get_logs({"address": Web3.to_checksum_address(args.consumer),
            "fromBlock": args.from_block, "toBlock": "latest",
            "topics": [Web3.keccak(text=RESULT_EVENT), args.tx_hash]})
        for log in logs:
            # Match again so unit/RPC fixtures cannot accidentally select a foreign job.
            if _to_hex(log["topics"][1]).lower() != args.tx_hash.lower():
                continue
            (result,) = decode(["bytes"], _to_bytes(log["data"]))
            fields = decode(RESULT_TYPES, result)
            success, error, text, _convo, _out, artifacts = fields
            print(f"TEXT_RESPONSE={text}")
            print(f"ARTIFACT_COUNT={len(artifacts)}")
            print(f"SUCCESS={int(bool(success))}")
            if not success:
                die("Agent result indicates failure; raw diagnostic output withheld")
            return
        time.sleep(POLL_INTERVAL_S)
    die("No callback result for this exact origin job; inspect settled Phase 1 and delivery status, do not blindly submit another agent")

def cmd_build_request(args):
    w3 = Web3(Web3.HTTPProvider(args.rpc))
    owner = Web3.to_checksum_address(args.owner)
    consumer = Web3.to_checksum_address(args.consumer)
    executor = Web3.to_checksum_address(args.executor_tee_address)
    provider, _ref, key = choose_provider_and_key()
    key_name = {"anthropic":"ANTHROPIC_API_KEY", "openai":"OPENAI_API_KEY", "gemini":"GEMINI_API_KEY", "openrouter":"OPENROUTER_API_KEY"}[provider]
    secrets = {"LLM_PROVIDER": provider, key_name: key}
    if args.da_provider == "gcs":
        credentials = os.environ.get("GCS_DA_SERVICE_ACCOUNT_JSON", "")
        bucket = os.environ.get("GCS_DA_BUCKET", "")
        if not credentials or not bucket:
            die("GCS credentials and bucket required")
        secrets["GCS_CREDENTIALS"] = json.dumps({"service_account_json": credentials, "bucket": bucket})
    else:
        secrets["HF_TOKEN"] = os.environ["HF_TOKEN"]
    blob = ecies_encrypt(args.executor_pubkey.removeprefix("0x"), build_secret_envelope(owner, secrets))
    signature = create_secret_signature(SOVEREIGN_USE_CONTEXT, w3.eth.chain_id, executor, owner, blob, args.private_key)
    convo, output, system = _storage_refs(args)
    payload = encode(SOVEREIGN_V1_PAYLOAD_TYPES, [1, [owner], [blob], [signature], b"", args.cli_type,
        args.prompt, convo, output, [], system, args.model, [], args.max_turns, args.max_tokens, ""])
    envelope = encode(AGENT_ENVELOPE_TYPES, [executor, owner, 500, 6000, True, consumer,
        Web3.keccak(text="onSovereignAgentResult(bytes32,bytes)")[:4], 3_000_000, 1_000_000_000,
        100_000_000, 0, b"\x00"*32, payload])
    calldata = Web3.keccak(text="callSovereignAgent(bytes)")[:4] + encode(["bytes"], [envelope])
    print(f"REQUEST_INPUT=0x{envelope.hex()}")
    print(f"CALLDATA=0x{calldata.hex()}")
    print(f"SECRETS_HASH={_to_hex(Web3.keccak(blob))}")

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
    p.set_defaults(func=cmd_build_request)
    p.add_argument("--cli-type", type=int, choices=[0,5,6], default=5)
    p.add_argument("--model", required=True); p.add_argument("--prompt", default="Say hello world")
    p.add_argument("--hf-repo-id", default=""); p.add_argument("--gcs-prefix", default="sovereign-agent")
    p.add_argument("--max-turns", type=int, default=50); p.add_argument("--max-tokens", type=int, default=8192)
    p = sub.add_parser("encode-grant-calldata")
    p.add_argument("--delegate", required=True); p.add_argument("--secrets-hash", required=True)
    p.set_defaults(func=cmd_encode_grant_calldata)
    for name, fn in [("wait-phase1", cmd_wait_phase1), ("wait-result", cmd_wait_result)]:
        p = sub.add_parser(name)
        for flag in ["rpc", "consumer", "tracker", "tx-hash"]: p.add_argument("--"+flag, required=True)
        p.add_argument("--from-block", type=int, required=True); p.add_argument("--timeout", type=int, default=300)
        p.set_defaults(func=fn)
    p = sub.add_parser("check-inputs")
    p.add_argument("--da-provider", required=True); p.set_defaults(func=cmd_check_inputs)
    args = parser.parse_args()
    args.private_key = os.environ.get("PRIVATE_KEY", "")
    args.func(args)

if __name__ == "__main__":
    main()

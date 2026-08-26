#!/usr/bin/env python3
"""Helpers for the sovereign-agent example.

Called by run.sh for:
1) Executor discovery + request encoding
2) Phase 2 event polling + decode
"""

import argparse
import json
import re
import sys
import time

from ecies import encrypt as ecies_encrypt
from ecies.config import ECIES_CONFIG
from eth_abi.abi import decode, encode
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

SOVEREIGN_REQUEST_TYPES = [
    "address",
    "uint256",
    "bytes",
    "uint64",
    "uint64",
    "string",
    "address",
    "bytes4",
    "uint256",
    "uint256",
    "uint256",
    "uint16",
    "string",
    "bytes",
    "(string,string,string)",
    "(string,string,string)",
    "(string,string,string)[]",
    "(string,string,string)",
    "string",
    "string[]",
    "uint16",
    "uint32",
    "string",
]


def _normalize_hex(value: str) -> str:
    return value if value.startswith("0x") else f"0x{value}"


# HuggingFace repo IDs must be `user/repo`. We explicitly reject anything that
# looks like an unfilled placeholder (angle brackets, "YOUR_", whitespace) so
# that agents or users who skip the setup step fail loudly here instead of
# silently ABI-encoding garbage into the on-chain request.
_HF_REPO_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")


def _validate_hf_repo_id(value: str) -> str:
    if not value or value.strip() != value:
        print(
            "ERROR: --hf-repo-id is required and must be a non-empty HuggingFace "
            "dataset ID in the form 'user/repo' (e.g. 'alice/my-agent-workspace').",
            file=sys.stderr,
        )
        sys.exit(2)
    if "<" in value or ">" in value or "YOUR_" in value or "YOUR-" in value:
        print(
            f"ERROR: --hf-repo-id looks like an unfilled placeholder ({value!r}). "
            "Set HF_REPO_ID to a real HuggingFace dataset you own, in 'user/repo' form.",
            file=sys.stderr,
        )
        sys.exit(2)
    if not _HF_REPO_ID_PATTERN.match(value):
        print(
            f"ERROR: --hf-repo-id ({value!r}) is not a valid 'user/repo' HuggingFace "
            "dataset ID. Expected two slash-separated segments, each starting with "
            "an alphanumeric character and containing only letters, digits, '.', "
            "'_', or '-'.",
            file=sys.stderr,
        )
        sys.exit(2)
    return value


def get_executor(w3: Web3, registry_addr: str, explicit_executor: str = ""):
    """Find a valid HTTP_CALL executor and return (teeAddress, publicKeyBytes)."""
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
        print(
            f"ERROR: Requested executor {target} was not found among valid HTTP_CALL services.",
            file=sys.stderr,
        )
        sys.exit(1)

    node = services[0][0]
    return Web3.to_checksum_address(node[1]), bytes(node[3])


def canonicalize_secrets_json(raw: str) -> str:
    """Validate and compact a JSON object before encrypting it for the executor."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"--secrets must be valid JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise ValueError("--secrets must contain a JSON object")
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def build_request_input(

    executor: str,
    pub_key_bytes: bytes,
    consumer: str,
    secrets_json: str,
    cli_type: int,
    model: str,
    prompt: str,
    hf_repo_id: str,
) -> bytes:
    """ABI-encode the 23-field SovereignAgentRequest payload."""
    if cli_type not in {0, 5, 6}:
        print(
            "ERROR: --cli-type must be one of 0 (claude_code), 5 (crush), or 6 (zeroclaw).",
            file=sys.stderr,
        )
        sys.exit(1)

    hf_repo_id = _validate_hf_repo_id(hf_repo_id)

    encrypted = ecies_encrypt(pub_key_bytes.hex(), secrets_json.encode())
    delivery_selector = Web3.keccak(text="onSovereignAgentResult(bytes32,bytes)")[:4]

    values = [
        Web3.to_checksum_address(executor),
        500,
        b"",
        5,
        6000,
        "SOVEREIGN_AGENT_TASK",
        Web3.to_checksum_address(consumer),
        delivery_selector,
        3_000_000,
        1_000_000_000,
        100_000_000,
        cli_type,
        prompt,
        encrypted,
        ("hf", f"{hf_repo_id}/sessions/session-001.jsonl", "HF_TOKEN"),  # convoHistory
        ("hf", f"{hf_repo_id}/artifacts/", "HF_TOKEN"),                  # output
        [],                                                              # skills
        ("hf", f"{hf_repo_id}/prompts/default-system.md", ""),           # systemPrompt
        model,
        [],
        50,
        8192,
        "",
    ]
    return encode(SOVEREIGN_REQUEST_TYPES, values)


def build_consumer_calldata(request_input: bytes) -> bytes:
    """Encode callSovereignAgent(bytes)."""
    func_sig = Web3.keccak(text="callSovereignAgent(bytes)")[:4]
    return func_sig + encode(["bytes"], [request_input])


def poll_phase2(w3: Web3, consumer: str, tx_hash: str, from_block: int, timeout: int = 300):
    """Poll SovereignAgentResultDelivered and decode response payload."""
    event_sig = Web3.keccak(text="SovereignAgentResultDelivered(bytes32,bytes)")
    tx_hash = tx_hash[2:] if tx_hash.startswith("0x") else tx_hash
    job_topic = "0x" + tx_hash.rjust(64, "0")
    start = time.time()

    while time.time() - start < timeout:
        try:
            logs = w3.eth.get_logs(
                {
                    "address": Web3.to_checksum_address(consumer),
                    "topics": [event_sig, job_topic],
                    "fromBlock": int(from_block),
                    "toBlock": "latest",
                }
            )
        except Exception as exc:
            print(
                f"WARN: Phase 2 log polling failed ({type(exc).__name__}); retrying.",
                file=sys.stderr,
            )
            time.sleep(1)
            continue
        if logs:

            raw_data = bytes(logs[0]["data"])
            (result_bytes,) = decode(["bytes"], raw_data)
            success, error, text, _, _, artifacts = decode(
                [
                    "bool",
                    "string",
                    "string",
                    "(string,string,string)",
                    "(string,string,string)",
                    "(string,string,string)[]",
                ],
                result_bytes,
            )
            print(f"\n{'=' * 68}")
            print(f"Phase 2 delivered in {time.time() - start:.1f}s")
            print(f"Success: {success}")
            if error:
                print(f"Error: {error}")
            print(f"Text response: {text if text else '(empty)'}")
            print(f"Artifacts: {len(artifacts)}")
            print(f"{'=' * 68}")
            if not success:
                sys.exit(1)
            return
        time.sleep(1)

    print(f"TIMEOUT: no Phase 2 delivery after {timeout}s", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rpc", required=True)
    parser.add_argument("--registry", default="")
    parser.add_argument("--consumer", default="")
    secrets_group = parser.add_mutually_exclusive_group()
    secrets_group.add_argument("--secrets")
    secrets_group.add_argument(
        "--secrets-stdin",
        action="store_true",
        help="Read the secrets JSON from stdin instead of exposing it in process arguments.",
    )

    parser.add_argument("--executor-tee-address", default="")
    parser.add_argument("--cli-type", type=int, default=5, help="0=claude_code, 5=crush, 6=zeroclaw")
    parser.add_argument("--model", default="")
    parser.add_argument("--prompt", default="Say hello world")
    parser.add_argument(
        "--hf-repo-id",
        default="",
        help="HuggingFace dataset ID in 'user/repo' form for convo/artifacts/system-prompt storage. Required when building a request.",
    )

    parser.add_argument("--poll-phase2", action="store_true")
    parser.add_argument("--tx-hash", default="")
    parser.add_argument("--from-block", default="0")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()

    if args.poll_phase2:
        w3 = Web3(Web3.HTTPProvider(args.rpc))
        poll_phase2(w3, args.consumer, args.tx_hash, int(args.from_block), timeout=args.timeout)
        sys.exit(0)

    if not args.registry:
        print("ERROR: --registry is required when building request input", file=sys.stderr)
        sys.exit(1)
    if not args.model:
        print("ERROR: --model is required when building request input", file=sys.stderr)
        sys.exit(1)
    if args.secrets is None and not args.secrets_stdin:
        print("ERROR: provide --secrets or --secrets-stdin", file=sys.stderr)
        sys.exit(2)
    raw_secrets = sys.stdin.read() if args.secrets_stdin else args.secrets
    try:
        secrets_json = canonicalize_secrets_json(raw_secrets)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)

    # Fail-fast: --hf-repo-id must be a real user/repo, not a placeholder.
    # Otherwise the invalid value would be ABI-encoded and fail only inside the executor.
    _validate_hf_repo_id(args.hf_repo_id)

    w3 = Web3(Web3.HTTPProvider(args.rpc))

    executor, pub_key = get_executor(w3, args.registry, args.executor_tee_address)
    request_input = build_request_input(
        executor=executor,

        pub_key_bytes=pub_key,
        consumer=args.consumer,
        secrets_json=secrets_json,
        cli_type=args.cli_type,

        model=args.model,
        prompt=args.prompt,
        hf_repo_id=args.hf_repo_id,
    )
    calldata = build_consumer_calldata(request_input)
    print(f"EXECUTOR={executor}")
    print(f"REQUEST_INPUT=0x{request_input.hex()}")
    print(f"CALLDATA=0x{calldata.hex()}")

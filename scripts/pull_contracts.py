#!/usr/bin/env python3
"""Pull contract source, ABI, and bytecode from Ritual Chain.

Works in three modes:
  1. Registry mode (default): pull all contracts from examples/registry.json
  2. Named mode: pull a specific contract from the registry by name
  3. Address mode: pull any contract by address (no registry entry needed)

Source resolution priority:
  1. Explorer API (verified source) — best quality, includes ABI
  2. GitHub PR/repo (if configured in registry) — fallback for unverified contracts
  3. Bytecode-only + selector extraction — always available

Usage:
    # Pull all registry contracts
    python3 scripts/pull_contracts.py

    # Pull a specific registry entry
    python3 scripts/pull_contracts.py --name TweetRegistry

    # Pull any contract by address (ad-hoc, no registry entry needed)
    python3 scripts/pull_contracts.py --address 0x1234...

    # Pull by address and save to registry for future use
    python3 scripts/pull_contracts.py --address 0x1234... --register MyContract

    # Custom output directory
    python3 scripts/pull_contracts.py --output-dir /tmp/contracts

    # Faster (skip 4byte.directory lookup)
    python3 scripts/pull_contracts.py --skip-4byte

    # Use a specific RPC endpoint
    python3 scripts/pull_contracts.py --rpc https://rpc.ritualfoundation.org

    # Pull contracts deployed at a specific block (discovers via eth_getBlockByNumber)
    python3 scripts/pull_contracts.py --block 2215742
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
REGISTRY_PATH = REPO_ROOT / "examples" / "registry.json"
DEFAULT_OUTPUT = REPO_ROOT / "examples" / "contracts"

DEFAULT_RPC = "https://rpc.ritualfoundation.org"
EXPLORER_API = "https://explorer.ritualfoundation.org/api/v2/smart-contracts"


# ---------------------------------------------------------------------------
# RPC
# ---------------------------------------------------------------------------


class RPC:
    """Minimal JSON-RPC client with endpoint failover."""

    def __init__(self, endpoints: list[str]):
        self.endpoints = endpoints

    def call(self, method: str, params: list) -> dict:
        last_err = None
        for url in self.endpoints:
            try:
                resp = requests.post(
                    url,
                    json={"jsonrpc": "2.0", "method": method, "params": params, "id": 1},
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
                if "error" in data:
                    last_err = RuntimeError(f"RPC error ({url}): {data['error']}")
                    continue
                return data["result"]
            except requests.RequestException as e:
                last_err = e
                continue
        raise last_err or RuntimeError("All RPC endpoints failed")

    def get_code(self, address: str, block: str = "latest") -> str:
        return self.call("eth_getCode", [address, block])

    def get_storage(self, address: str, slot: str, block: str = "latest") -> str:
        return self.call("eth_getStorageAt", [address, slot, block])

    def get_block(self, block_num: int) -> dict:
        return self.call("eth_getBlockByNumber", [hex(block_num), True])


# ---------------------------------------------------------------------------
# Bytecode analysis
# ---------------------------------------------------------------------------


def extract_selectors(bytecode: str) -> list[str]:
    """Extract 4-byte function selectors from EVM bytecode."""
    if bytecode.startswith("0x"):
        bytecode = bytecode[2:]
    raw = bytes.fromhex(bytecode)
    selectors = set()
    i = 0
    while i < len(raw) - 4:
        op = raw[i]
        if op == 0x63:  # PUSH4
            sel = raw[i + 1 : i + 5].hex()
            if sel not in ("00000000", "ffffffff"):
                selectors.add(sel)
            i += 5
        elif 0x60 <= op <= 0x7f:  # PUSH1..PUSH32 — skip immediate data
            i += 1 + (op - 0x5f)
        else:
            i += 1
    return sorted(selectors)


def resolve_selectors(
    selectors: list[str], skip: bool = False
) -> dict[str, str]:
    """Resolve selectors to signatures via 4byte.directory."""
    if skip:
        return {s: f"unknown_0x{s}" for s in selectors}

    resolved = {}
    for sel in selectors:
        try:
            resp = requests.get(
                f"https://www.4byte.directory/api/v1/signatures/?hex_signature=0x{sel}",
                timeout=5,
            )
            if resp.ok:
                results = resp.json().get("results", [])
                resolved[sel] = results[0]["text_signature"] if results else f"unknown_0x{sel}"
            else:
                resolved[sel] = f"unknown_0x{sel}"
        except requests.RequestException:
            resolved[sel] = f"unknown_0x{sel}"
    return resolved


# ---------------------------------------------------------------------------
# Source fetchers
# ---------------------------------------------------------------------------


def fetch_explorer_source(address: str) -> dict | None:
    """Fetch verified source from the Ritual Chain explorer (Blockscout V2 API)."""
    try:
        resp = requests.get(f"{EXPLORER_API}/{address}", timeout=10)
        if resp.ok:
            data = resp.json()
            if data.get("source_code"):
                return {
                    "source_code": data["source_code"],
                    "compiler_version": data.get("compiler_version", "unknown"),
                    "abi": data.get("abi", []),
                    "name": data.get("name", "Unknown"),
                    "origin": "explorer",
                }
    except requests.RequestException:
        pass
    return None


def fetch_github_file(repo: str, ref: str, path: str) -> str | None:
    """Fetch a file from GitHub. `ref` can be a branch, tag, or 'pr/N'."""
    try:
        # Resolve PR ref to branch name
        if ref.startswith("pr/"):
            pr_num = ref.split("/")[1]
            result = subprocess.run(
                ["gh", "pr", "view", pr_num, "--repo", repo,
                 "--json", "headRefName,headRepositoryOwner,headRepository"],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode != 0:
                return None
            pr_info = json.loads(result.stdout)
            branch = pr_info["headRefName"]
            owner = pr_info.get("headRepositoryOwner", {}).get("login", repo.split("/")[0])
            repo_name = pr_info.get("headRepository", {}).get("name", repo.split("/")[1])
            repo = f"{owner}/{repo_name}"
            ref = branch

        result = subprocess.run(
            ["gh", "api", f"repos/{repo}/contents/{path}?ref={ref}", "--jq", ".content"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return None
        return base64.b64decode(result.stdout.strip()).decode("utf-8")
    except Exception as e:
        print(f"  warn: GitHub fetch failed ({path}): {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Block-level contract discovery
# ---------------------------------------------------------------------------


def discover_contracts_at_block(rpc: RPC, block_num: int) -> list[dict]:
    """Find contracts deployed in a specific block by scanning for contract creations."""
    block = rpc.get_block(block_num)
    if not block:
        return []

    contracts = []
    for tx in block.get("transactions", []):
        # Contract creation: to is null, receipt has contractAddress
        if tx.get("to") is None or tx.get("to") == "0x":
            try:
                receipt = rpc.call("eth_getTransactionReceipt", [tx["hash"]])
                if receipt and receipt.get("contractAddress"):
                    addr = receipt["contractAddress"]
                    contracts.append({
                        "address": addr,
                        "deploy_block": block_num,
                        "tx_hash": tx["hash"],
                        "deployer": tx.get("from", "unknown"),
                    })
            except Exception:
                continue
    return contracts


# ---------------------------------------------------------------------------
# Core pull logic
# ---------------------------------------------------------------------------


def pull_one(
    rpc: RPC,
    address: str,
    output_dir: Path,
    name: str | None = None,
    github: dict | None = None,
    skip_4byte: bool = False,
) -> dict:
    """Pull all available data for a single contract address."""
    label = name or address[:10] + "..."
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"  Address: {address}")
    print(f"{'='*60}")

    safe_name = name or address
    contract_dir = output_dir / safe_name
    contract_dir.mkdir(parents=True, exist_ok=True)

    result = {"name": name, "address": address}

    # 1. Bytecode
    print("\n[1/4] Fetching bytecode...")
    bytecode = None
    try:
        bytecode = rpc.get_code(address)
        size = (len(bytecode) - 2) // 2
        print(f"  {size} bytes")
        (contract_dir / "bytecode.hex").write_text(bytecode)
        result["bytecode_size"] = size
        if size == 0:
            print("  Warning: no bytecode at this address (EOA or self-destructed)")
    except Exception as e:
        print(f"  Error: {e}")
        result["bytecode_size"] = 0

    # 2. Selectors
    print("\n[2/4] Extracting function selectors...")
    if bytecode and result.get("bytecode_size", 0) > 0:
        selectors = extract_selectors(bytecode)
        print(f"  {len(selectors)} selectors found")
        signatures = resolve_selectors(selectors, skip=skip_4byte)
        abi_list = [
            {"selector": f"0x{s}", "signature": sig}
            for s, sig in sorted(signatures.items(), key=lambda x: x[1])
        ]
        (contract_dir / "selectors.json").write_text(json.dumps(abi_list, indent=2) + "\n")
        result["selectors"] = abi_list
        if not skip_4byte:
            for item in abi_list:
                print(f"    {item['selector']} -> {item['signature']}")
    else:
        result["selectors"] = []

    # 3. Verified source (explorer)
    print("\n[3/4] Fetching verified source from explorer...")
    explorer = fetch_explorer_source(address)
    if explorer:
        print(f"  Found: {explorer['name']} (compiler {explorer['compiler_version']})")
        (contract_dir / "source.sol").write_text(explorer["source_code"])
        if explorer["abi"]:
            (contract_dir / "abi.json").write_text(json.dumps(explorer["abi"], indent=2) + "\n")
        result["source"] = "explorer"
    else:
        print("  Not available")
        result["source"] = None

    # 4. GitHub fallback
    if not explorer and github:
        print(f"\n[4/4] Pulling from GitHub ({github['repo']})...")
        repo = github["repo"]
        ref = github["ref"]
        paths = github.get("paths", {})

        src = paths.get("source")
        if src:
            content = fetch_github_file(repo, ref, src)
            if content:
                (contract_dir / "source.sol").write_text(content)
                print(f"  source: {src} ({len(content)} chars)")
                result["source"] = "github"

        ifaces = paths.get("interfaces", [])
        if ifaces:
            iface_dir = contract_dir / "interfaces"
            iface_dir.mkdir(exist_ok=True)
            for ipath in ifaces:
                fname = Path(ipath).name
                content = fetch_github_file(repo, ref, ipath)
                if content:
                    (iface_dir / fname).write_text(content)
                    print(f"  interface: {fname} ({len(content)} chars)")
    elif not explorer:
        print("\n[4/4] No GitHub source configured, skipping")

    # Storage slot 0 (often owner or linked contract)
    try:
        slot0 = rpc.get_storage(address, "0x0")
        result["storage_slot_0"] = slot0
    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------


def load_registry() -> dict:
    if REGISTRY_PATH.exists():
        return json.loads(REGISTRY_PATH.read_text())
    return {"chain_id": 1979, "rpc_endpoints": [DEFAULT_RPC], "explorer_api": EXPLORER_API, "contracts": []}


def save_registry(reg: dict):
    REGISTRY_PATH.write_text(json.dumps(reg, indent=2) + "\n")


def add_to_registry(reg: dict, name: str, address: str, block: int | None, features: list[str] | None):
    """Add or update a contract in the registry."""
    for c in reg["contracts"]:
        if c["address"].lower() == address.lower():
            c["name"] = name
            if block:
                c["deploy_block"] = block
            if features:
                c["features"] = features
            save_registry(reg)
            return
    reg["contracts"].append({
        "name": name,
        "address": address,
        "deploy_block": block,
        "features": features or [],
        "github": None,
    })
    save_registry(reg)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Pull contract source and ABI from Ritual Chain",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                              Pull all registry contracts
  %(prog)s --name TweetRegistry         Pull one registry entry
  %(prog)s --address 0xABC...           Pull any address (ad-hoc)
  %(prog)s --address 0xABC... --register MyDApp   Pull + add to registry
  %(prog)s --block 2215742              Discover contracts deployed at block
        """,
    )

    source = parser.add_mutually_exclusive_group()
    source.add_argument("--name", help="Pull a specific contract from the registry")
    source.add_argument("--address", help="Pull any contract by address (ad-hoc)")
    source.add_argument("--block", type=int, help="Discover and pull contracts deployed at a block")

    parser.add_argument("--register", metavar="NAME", help="Save ad-hoc address to registry with this name")
    parser.add_argument("--features", nargs="*", help="Features list when registering (e.g., Scheduler HTTP)")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT, help="Output directory")
    parser.add_argument("--rpc", help="Override RPC endpoint")
    parser.add_argument("--skip-4byte", action="store_true", help="Skip 4byte.directory (faster)")

    args = parser.parse_args()

    # Build RPC client
    reg = load_registry()
    endpoints = [args.rpc] if args.rpc else reg.get("rpc_endpoints", [DEFAULT_RPC])
    if DEFAULT_RPC not in endpoints:
        endpoints.append(DEFAULT_RPC)
    rpc = RPC(endpoints)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    results = []

    if args.block:
        # Discover mode
        print(f"Discovering contracts at block {args.block}...")
        found = discover_contracts_at_block(rpc, args.block)
        if not found:
            print("No contract deployments found in this block")
            sys.exit(0)
        print(f"Found {len(found)} contract(s)")
        for info in found:
            r = pull_one(rpc, info["address"], args.output_dir, skip_4byte=args.skip_4byte)
            r["deploy_block"] = args.block
            r["tx_hash"] = info.get("tx_hash")
            results.append(r)

    elif args.address:
        # Ad-hoc mode
        r = pull_one(rpc, args.address, args.output_dir,
                      name=args.register, skip_4byte=args.skip_4byte)
        results.append(r)
        if args.register:
            add_to_registry(reg, args.register, args.address, None, args.features)
            print(f"\n  Registered as '{args.register}' in {REGISTRY_PATH}")

    elif args.name:
        # Named registry lookup
        entry = next((c for c in reg["contracts"] if c["name"] == args.name), None)
        if not entry:
            print(f"Error: '{args.name}' not found in registry. Available: "
                  + ", ".join(c["name"] for c in reg["contracts"]))
            sys.exit(1)
        if entry["address"] == "TBD":
            print(f"Error: '{args.name}' address is TBD — not yet deployed")
            sys.exit(1)
        r = pull_one(rpc, entry["address"], args.output_dir,
                      name=entry["name"], github=entry.get("github"),
                      skip_4byte=args.skip_4byte)
        r["deploy_block"] = entry.get("deploy_block")
        r["features"] = entry.get("features", [])
        results.append(r)

    else:
        # Pull all registry contracts
        for entry in reg["contracts"]:
            if entry["address"] == "TBD":
                print(f"\nSkipping {entry['name']} (address TBD)")
                continue
            r = pull_one(rpc, entry["address"], args.output_dir,
                          name=entry["name"], github=entry.get("github"),
                          skip_4byte=args.skip_4byte)
            r["deploy_block"] = entry.get("deploy_block")
            r["features"] = entry.get("features", [])
            results.append(r)

    # Write summary
    summary = {
        "chain_id": 1979,
        "pull_count": len(results),
        "contracts": results,
    }
    summary_path = args.output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")

    print(f"\n{'='*60}")
    print(f"  Done — {len(results)} contract(s) pulled to {args.output_dir}/")
    print(f"{'='*60}")
    for r in results:
        src = r.get("source", "none")
        sels = len(r.get("selectors", []))
        print(f"  {r.get('name') or r['address'][:10]}: "
              f"{r.get('bytecode_size', 0)} bytes, {sels} selectors, source: {src}")


if __name__ == "__main__":
    main()

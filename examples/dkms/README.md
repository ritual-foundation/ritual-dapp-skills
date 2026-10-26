# Standalone DKMS derivation

This example sends a complete ten-field request directly to `0x081B`, then checks the settled `(address paymentAddress, bytes daPublicKey)` response. It requires public Bun/viem/eciesjs only. It does not launch an agent or deploy a factory/consumer.

```bash
cd examples/dkms
bun install
bun run typecheck
bun test
export RPC_URL='<target RPC>' EXPECTED_CHAIN_ID='<target chain ID>'
export RITUAL_WALLET='<verified wallet address>' ASYNC_JOB_TRACKER='<verified tracker address>'
export EXECUTOR_ADDRESS='<registered eligible executor with working DKMS configuration>'
export PRIVATE_KEY='<funded test EOA private key>'
export KEY_INDEX=1
# Optional explicit RitualWallet deposit in wei; otherwise use its existing balance.
export DEPOSIT_WEI=0
bun run derive
```

Verify deployment addresses and select an eligible executor using the registry guidance before running. The script checks chain ID, system bytecode and nonzero wallet balance; executor registration alone does not prove DKMS health or sufficient fee funding. Fund the EOA for gas and its RitualWallet for the selected executor's fee. This direct EOA call has sponsor=owner=sender and needs no consumer allowance. Receipt failure, malformed/empty output or observation timeout stops the run; reconcile the printed origin hash before trying again.

The response exposes public material, with no user output encryption requested. Payment and DA keys have separate derivation domains: the DA public key is not the payment address's key. No private derived key is returned. Tests exercise canonical encoding, response validation, exact job/commitment correlation and receipt failures with generated keys/RPC fixtures; a passing test is not a live DKMS executor pass.

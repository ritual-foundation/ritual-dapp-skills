# PriceAlert — On-Chain Price Alert via HTTP Precompile

A minimal Ritual Chain contract that fetches live token prices from CoinGecko
using the HTTP precompile (0x0801) and emits an on-chain alert when a
user-defined threshold is crossed.

## What It Demonstrates

- HTTP precompile (0x0801) usage for fetching external API data
- Short-running async execution pattern (fulfilled replay)
- RitualWallet fee deposit pattern
- On-chain JSON parsing in Solidity (integer extraction)
- Alert state management with threshold logic

## Quick Start

### 1. Deploy

forge create examples/price-alert/PriceAlert.sol:PriceAlert \
  --rpc-url https://rpc.ritualfoundation.org \
  --private-key $PRIVATE_KEY \
  --constructor-args $EXECUTOR_ADDRESS

### 2. Deposit Fees

cast send $CONTRACT_ADDRESS "depositFees(uint256)" 5000 \
  --value 0.01ether \
  --rpc-url https://rpc.ritualfoundation.org \
  --private-key $PRIVATE_KEY

### 3. Create an Alert (BTC above $100k)

cast send $CONTRACT_ADDRESS \
  "createAlert(string,uint256,bool,address)" \
  "bitcoin" 100000 true $YOUR_ADDRESS \
  --rpc-url https://rpc.ritualfoundation.org \
  --private-key $PRIVATE_KEY

### 4. Check Price

cast send $CONTRACT_ADDRESS "checkPrice(uint256,uint64)" 0 100 \
  --rpc-url https://rpc.ritualfoundation.org \
  --private-key $PRIVATE_KEY

### 5. Read Last Price

cast call $CONTRACT_ADDRESS "lastCheckedPrice()" \
  --rpc-url https://rpc.ritualfoundation.org

## Precompile Reference

| Item | Value |
|------|-------|
| HTTP precompile | 0x0000000000000000000000000000000000000801 |
| RitualWallet | 0x532F0dF0896F353d8C3DD8cc134e8129DA2a3948 |
| TEEServiceRegistry | 0x9644e8562cE0Fe12b4deeC4163c064A8862Bf47F |
| Chain ID | 1979 |

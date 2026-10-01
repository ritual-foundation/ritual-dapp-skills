---
name: ritual-meta-verification
description: Non-interactive verification protocols for every Ritual skill. Per-skill checks, cross-skill integration checks, and unified E2E user journey verification. Load only the protocols for skills this project uses.
---

# Non-Interactive Verification Protocol (v2)

## Purpose

After the agent builds or modifies code, verify correctness without asking the user. Each skill has a verification protocol using static analysis, compilation, simulation, and on-chain queries. The agent runs only the protocols for skills this project uses.

## Architecture (v2 Changes)

### Just-In-Time Loading

Same as v1: load protocols only for loaded skills. 5 skills = 5 protocols.

### Execution Tiers

Each check is tagged by what it needs to run:

| Tier | Needs | Run When | Examples |
|------|-------|----------|----------|
| **T1: Static** | Source code only | After every code change | grep, tsc, forge build, ESLint |
| **T2: Simulated** | Chain RPC (eth_call) | After compilation passes | forge script --fork-url, cast call |
| **T3: Deployed** | Contract on-chain | After deployment | cast code, cast call against deployed address |
| **T4: Runtime** | Server running | After server startup | curl health endpoint, Playwright |

Run T1 always. Run T2 only if RPC is available. Run T3 only after deployment. Run T4 only after startup. Never report a T3 failure when the contract hasn't been deployed yet.

### Check Dependencies

Within each protocol, checks are either **blocking** (later checks depend on it) or **independent** (can run in parallel after prerequisites pass).

```
BLOCKING:    Check 1 → Check 2 → [Check 3, Check 4, Check 5] independent
                                         ↓
                              Report ALL failures at once
```

If a blocking check fails, skip its dependents. If an independent check fails, still run the other independent checks and report all failures together. This prevents the "fix one, discover another, fix that, discover a third" loop.

### Confidence Levels

| Level | Meaning | Agent Behavior |
|-------|---------|---------------|
| **HIGH** | Binary pass/fail, no false positives (compiler, runtime) | Treat failure as definitive |
| **MEDIUM** | Pattern match, possible false positives (grep-based structural checks) | Flag as "likely issue — verify manually if uncertain" |
| **LOW** | Heuristic, often matches non-issues (keyword scanning) | Flag as "possible concern" — never block on it |

### Automated Fixes

For checks with deterministic fixes, the protocol specifies the exact transformation. The agent applies the fix and re-runs the check without asking.

---

## Per-Skill Protocols

### CONTRACTS

**Blocking checks (sequential):**

| # | Check | Tier | Confidence | Command | Auto-Fix |
|---|-------|------|-----------|---------|----------|
| 1 | Compilation | T1 | HIGH | `forge build 2>&1` | Fix compiler errors |
| 2 | via_ir for large ABIs | T1 | HIGH | `grep -q 'via_ir.*=.*true' foundry.toml` | Insert `via_ir = true` under `[profile.default]` in foundry.toml |

**Independent checks (parallel after blocking pass):**

| # | Check | Tier | Confidence | Command | Auto-Fix |
|---|-------|------|-----------|---------|----------|
| 3 | Callback auth | T1 | MEDIUM | For each `function on*Result` in *.sol, check that the function body contains `ASYNC_DELIVERY` or `0x5A16` | Insert `require(msg.sender == 0x5A16214fF555848411544b005f7Ac063742f39F6)` as first line of callback |
| 4 | Precompile addresses | T1 | MEDIUM | Extract all `address(0x08...)` values, compare against canonical: HTTP=0x0801, LLM=0x0802, Sovereign Agent=0x080C, Image=0x0818, Audio=0x0819, Video=0x081A, LongHTTP=0x0805, ZK=0x0806, Persistent=0x0820, DKMS=0x081B | Replace with canonical address |
| 5 | ABI + DA field shape (if LLM/multimodal/agents) | T1 | MEDIUM | Count `abi.encode` parameters in LLM precompile call — must be 30 (5 base + 25 LLM including convoHistory). For DA fields, verify StorageRef tuple `(string,string,string)` and reject stale patterns like `storageType` / `encryptedStoragePayment`. | Consult `ritual-dapp-precompiles` and `ritual-dapp-da` |
| 6 | Static analysis | T1 | MEDIUM | `slither . --filter-paths "lib/" 2>&1 \| grep -E "High\|Medium"` (if Slither installed) | Review findings |
| 7 | Unit tests | T1 | HIGH | `forge test -vv 2>&1` | Fix failing tests |
| 8 | Deployment simulation | T2 | HIGH | `forge script script/Deploy.s.sol --fork-url $RITUAL_RPC_URL -vv` | Fix deployment script |
| 9 | Bytecode verification | T3 | HIGH | `cast code $CONTRACT_ADDRESS --rpc-url $RITUAL_RPC_URL` — must not be `0x` | Redeploy |

**Pass condition:** Checks 1-4 must pass. Check 7 should pass. Checks 5-6 are medium-confidence warnings. Checks 8-9 require T2/T3 availability.

---

### FRONTEND

**Blocking checks:**

| # | Check | Tier | Confidence | Command | Auto-Fix |
|---|-------|------|-----------|---------|----------|
| 1 | TypeScript compilation | T1 | HIGH | `npx tsc --noEmit 2>&1` | Fix type errors |
| 2 | Next.js build | T1 | HIGH | `npx next build 2>&1` | Fix build errors |

**Independent checks:**

| # | Check | Tier | Confidence | Command | Auto-Fix |
|---|-------|------|-----------|---------|----------|
| 3 | No writeContractAsync for async precompiles | T1 | MEDIUM | Files containing both `writeContractAsync`/`useWriteContract` AND precompile references (`0x080`, `HTTP_PRECOMPILE`, `LLM_PRECOMPILE`) | Replace with `useSendTransaction` + `encodeFunctionData` |
| 4 | spcCalls handling for short-running async precompiles | T1 | MEDIUM | Files that call `waitForTransactionReceipt` in short-running async context must access `spcCalls` | Add `(receipt as RitualReceipt).spcCalls` |
| 5 | All 9 async states handled | T1 | MEDIUM | Grep for each: SUBMITTING, PENDING_COMMITMENT, COMMITTED, EXECUTOR_PROCESSING, RESULT_READY, PENDING_SETTLEMENT, SETTLED, FAILED, EXPIRED | Add missing state handlers |
| 6 | Chain ID 1979 | T1 | HIGH | `grep -r 'id:.*1979\|chainId.*1979' src/ lib/` | Change to 1979 |
| 7 | Sender lock check | T1 | LOW | Files with submit buttons should reference `hasPendingJobForSender` or `useSenderLock` | Add sender lock check |
| 8 | RitualWallet deposit gate | T1 | LOW | Files with async submit should check `balanceOf` before enabling | Add deposit gate |
| 9 | Accessibility: focus states | T1 | MEDIUM | Count files with `<button`/`<input` vs files with `focus-visible` | Add `focus-visible:ring-2 focus-visible:ring-ritual-green/50` |
| 10 | Browser smoke test | T4 | HIGH | `npx playwright test --grep smoke` — page loads, no console errors | Fix render issues |
| 11 | Accessibility audit | T4 | MEDIUM | `npx playwright test --grep accessibility` or axe-core | Fix a11y violations |

**Pass condition:** Checks 1-6 must pass. Checks 7-8 are low-confidence suggestions. Checks 9-11 depend on Playwright.

---

### BACKEND

**Blocking checks:**

| # | Check | Tier | Confidence | Command | Auto-Fix |
|---|-------|------|-----------|---------|----------|
| 1 | TypeScript compilation | T1 | HIGH | `npx tsc --noEmit` | Fix type errors |

**Independent checks:**

| # | Check | Tier | Confidence | Command | Auto-Fix |
|---|-------|------|-----------|---------|----------|
| 2 | AsyncJobTracker address | T1 | HIGH | Grep for `C069FFCa0389f44eCA2C626e55491b0ab045AEF5` | Replace with correct address |
| 3 | Event names | T1 | HIGH | Grep for JobAdded, Phase1Settled, ResultDelivered, JobRemoved | Add missing event watchers |
| 4 | Canonical lifecycle status names | T1 | MEDIUM | Grep for SUBMITTING, PENDING_COMMITMENT, COMMITTED, etc. | Replace custom names with canonical ones |
| 5 | spcCalls extraction for short-running async precompiles | T1 | MEDIUM | If code references 0x0801/0x0802/0x081B, must also reference `spcCalls` | Add spcCalls extraction logic |
| 6 | Checkpoint persistence | T1 | MEDIUM | Grep for `lastIndexedBlock`/`checkpoint`/`setCheckpoint` | Add checkpoint save after each batch |
| 7 | Sender lock handling | T1 | LOW | If backend submits transactions, must serialize per EOA | Add sender lock serialization |
| 8 | Health endpoint exists | T1 | MEDIUM | Grep for `health` route | Add health endpoint |
| 9 | Health endpoint responds | T4 | HIGH | `curl -sf http://${APP_HOST:-127.0.0.1}:${PORT:-3001}/api/health \| jq .status` | Fix server startup |
| 10 | Indexer lag | T4 | MEDIUM | Health endpoint returns lag < 500 blocks | Investigate indexer performance |

**Pass condition:** Checks 1-6 must pass. Checks 7-10 are recommended.

---

### DEPLOY

**Blocking checks (sequential by tier):**

| # | Check | Tier | Confidence | Command | Auto-Fix |
|---|-------|------|-----------|---------|----------|
| 1 | RPC connectivity | T2 | HIGH | `cast block-number --rpc-url $RITUAL_RPC_URL` | Check RPC URL |
| 2 | Chain ID | T2 | HIGH | `cast chain-id --rpc-url $RITUAL_RPC_URL` — must be 1979 | Fix RPC URL (wrong chain) |
| 3 | Deployed bytecode | T3 | HIGH | `cast code $ADDR --rpc-url $RITUAL_RPC_URL` — must not be `0x` per deployed address | Redeploy |
| 4 | System contracts accessible | T3 | HIGH | `cast call 0x532F...3948 "balanceOf(address)(uint256)" 0x0...0 --rpc-url $RITUAL_RPC_URL` | RPC issue — system contracts are always deployed |

**Independent checks (after blocking pass):**

| # | Check | Tier | Confidence | Command | Auto-Fix |
|---|-------|------|-----------|---------|----------|
| 5 | Contract source verified | T3 | HIGH | `forge verify-contract --chain 1979 --watch --verifier custom --verifier-url "$RITUAL_VERIFIER_URL" --verifier-api-key unused $ADDR src/Contract.sol:Contract` — must end with `Pass - Verified` | Re-run with correct compiler settings from foundry.toml |

**Pass condition:** Checks 1-4 must pass (at the appropriate tier). Check 5 should pass — if verification fails, the contract still works but source is not browsable on the explorer.

---

### WALLET

| # | Check | Tier | Confidence | Command | Auto-Fix |
|---|-------|------|-----------|---------|----------|
| 1 | Balance > 0 | T3 | HIGH | `cast call 0x532F...3948 "balanceOf(address)(uint256)" $USER --rpc-url $RITUAL_RPC_URL` | Prompt deposit |
| 2 | Lock duration adequate | T3 | MEDIUM | `cast call 0x532F...3948 "lockUntil(address)(uint256)" $USER` — must be > current block + expected TTL | Re-deposit with longer lock |
| 3 | Fee sufficiency | T3 | MEDIUM | Compare balance against: HTTP=2.5e12+byte_fees, LLM=5e12+token_fees per planned call | Deposit more RITUAL |

**Pass condition:** Check 1 must pass. Checks 2-3 are warnings.

---

### LLM

| # | Check | Tier | Confidence | Command | Auto-Fix |
|---|-------|------|-----------|---------|----------|
| 1 | Model exists in registry | T2 | HIGH | `cast call 0x7A85...4f "modelExists(string)(bool)" "$MODEL" --rpc-url $RITUAL_RPC_URL` | Use a registered model (query `getAllModels()`) |
| 2 | ABI field count = 30 | T1 | MEDIUM | Count type parameters in LLM encoding block (must be 30 including convoHistory tuple) | Consult precompiles skill for correct fields |
| 3 | Float scaling ×1000 | T1 | LOW | Grep for temperature/topP values — warn if decimal found | Multiply by 1000 |
| 4 | Executor availability | T2 | HIGH | `cast call 0x9644...Bf47F "getServicesByCapability(uint8,bool)" 1 true --rpc-url $RITUAL_RPC_URL` | Wait or use different capability |
| 5 | Empty completion handled | T1 | MEDIUM | In each `.sol` file that decodes `choicesData` / message `content`, check that a zero `choicesCount` **and** an empty or whitespace-only `content` (after stripping `<think>…</think>`) lead to an explicit error branch. Flag code that passes the decoded content straight into parsing, storage or a verdict. | Insert a blank check right after extracting content, e.g. `if (_isBlank(bytes(content))) { /* record as error, do not parse */ }` |

**Pass condition:** Checks 1 and 4 must pass (at T2). Check 2 is medium. Check 3 is low. Check 5 is medium.

> **Why check 5:** GLM-4.7-FP8 can spend its whole `maxCompletionTokens` budget inside `<think>` and return empty `content` with `finish_reason: "length"` (see `ritual-dapp-llm`, "Reasoning-budget exhaustion"). `hasError` is `false` in that case, so a consumer that only checks `hasError` will treat an empty string as a real answer: a blank value gets stored, or a verdict or parser silently falls back to its default.

---

### HTTP

| # | Check | Tier | Confidence | Command | Auto-Fix |
|---|-------|------|-----------|---------|----------|
| 1 | ABI field count = 13 (including dkmsKeyIndex, dkmsKeyFormat, piiEnabled) | T1 | MEDIUM | Count type parameters in HTTP encoding | Add missing `{ type: 'uint256' }`, `{ type: 'uint8' }`, `{ type: 'bool' }` for dkmsKeyIndex, dkmsKeyFormat, piiEnabled |
| 2 | Method code mapping | T1 | MEDIUM | Verify GET→1, POST→2, PUT→3, DELETE→4, PATCH→5 | Fix mapping |
| 3 | piiEnabled + secret templates consistency | T1 | HIGH | If `{{SECRET}}` templates found, piiEnabled must be true | Set piiEnabled to true |
| 4 | Executor availability | T2 | HIGH | `cast call TEEServiceRegistry.getServicesByCapability(0, true)` | Wait or check RPC |

**Pass condition:** Checks 1, 3, 4 must pass.

---

### AGENTS

| # | Check | Tier | Confidence | Command | Auto-Fix |
|---|-------|------|-----------|---------|----------|
| 1 | Correct precompile for use case | T1 | HIGH | If code has persistence/memory/soul concepts AND uses 0x080C (not 0x0820), FAIL | Switch to Persistent Agent (0x0820) |
| 2 | Delivery selector matches callback | T1 | HIGH | Compute `cast sig "onAgentResult(bytes32,bytes)"` and compare to encoded selector | Recompute with `cast sig` |
| 3 | Delivery gas ≥ 200,000 | T1 | MEDIUM | Extract deliveryGasLimit value | Increase to 3,000,000 for state-writing callbacks |
| 4 | Executor availability (capability 0) | T2 | HIGH | `cast call TEEServiceRegistry.getServicesByCapability(0, true)` | Wait or check RPC |

**Pass condition:** Checks 1-2 must pass. Check 4 at T2.

---

### PASSKEY

| # | Check | Tier | Confidence | Command | Auto-Fix |
|---|-------|------|-----------|---------|----------|
| 1 | Precompile address 0x0100 | T1 | HIGH | Grep for `address(0x100)` or full padded address | Fix address |
| 2 | S-normalization present | T1 | HIGH | Grep for `normalizeS`/`P256_HALF_N`/`halfN` | Add normalizeS function from passkey skill |
| 3 | Address derivation: hash(x\|\|y) NOT hash(04\|\|x\|\|y) | T1 | MEDIUM | Check that keccak256 input is concat of x,y without 0x04 prefix | Remove 0x04 from hash input |
| 4 | Verification roundtrip | T2 | HIGH | eth_call to 0x0100 with known test vector | Debug encoding |

**Pass condition:** Checks 1-3 must pass. Check 4 at T2.

---

### SECRETS

| # | Check | Tier | Confidence | Command | Auto-Fix |
|---|-------|------|-----------|---------|----------|
| 1 | eciesjs present | T1 | HIGH | Grep in source and package.json | `npm install eciesjs` |
| 2 | Template syntax {{CAPS}} | T1 | MEDIUM | Grep for `{{[A-Z_]+}}` patterns | Fix template format |
| 3 | piiEnabled = true when templates used | T1 | HIGH | If templates found, piiEnabled must be true | Set to true |
| 4 | No plaintext secrets | T1 | HIGH | Grep for `sk-`, `sk_live`, private key hex patterns | Move to encrypted secrets |

**Pass condition:** All must pass.

---

### DESIGN

All checks are T1/LOW or T1/MEDIUM. Design is subjective — all are warnings, never blockers.

| # | Check | Tier | Confidence | What |
|---|-------|------|-----------|------|
| 1 | No non-Ritual colors (#6366f1, #3b82f6, bg-blue-500) | T1 | MEDIUM | Warn |
| 2 | No non-Ritual fonts (Inter, Roboto, Arial) | T1 | MEDIUM | Warn |
| 3 | Focus states on interactive elements | T1 | MEDIUM | Warn |
| 4 | Dark background present (bg-black) | T1 | LOW | Warn |

---

### SCHEDULER, MEDIA, LONGRUNNING, X402

These share the long-running async delivery pattern. Merged checks:

| # | Check | Tier | Confidence | Applies To | What |
|---|-------|------|-----------|------------|------|
| 1 | Correct system/precompile address | T1 | HIGH | All | Grep for canonical address |
| 2 | Delivery config present (deliveryTarget + deliverySelector) | T1 | HIGH | Multimodal, LongRunning, Scheduler (if async) | Grep |
| 3 | Polling config (pollIntervalBlocks, maxPollBlock) | T1 | HIGH | LongRunning | Grep |
| 4 | Task ID marker defined | T1 | MEDIUM | LongRunning | Grep for taskIdMarker |
| 5 | ECIES encryption for payment credentials | T1 | HIGH | X402 | Grep for eciesjs + encrypt |
| 6 | HTTP precompile used (X402 flows through HTTP) | T1 | HIGH | X402 | Grep for 0x0801 |
| 7 | Executor availability for capability | T2 | HIGH | Multimodal (7/8/9), Scheduler (depends on target) | cast call TEEServiceRegistry |
| 8 | Lock duration covers interval × maxExecutions | T1 | MEDIUM | Scheduler | Compute and compare |

---

### TESTING

| # | Check | Tier | Confidence | What | Auto-Fix |
|---|-------|------|-----------|------|----------|
| 1 | Test files exist | T1 | HIGH | `find . -name "*.test.*" -o -name "*.spec.*" \| wc -l` > 0 | Generate test stubs |
| 2 | Solidity tests pass | T1 | HIGH | `forge test` | Fix tests |
| 3 | TypeScript tests pass | T1 | HIGH | `npx vitest run` | Fix tests |

---

## Cross-Skill Integration Checks

Run AFTER all individual skill checks pass. These catch mismatches between skills.

| # | Skills Involved | Check | Tier | Confidence |
|---|----------------|-------|------|-----------|
| 1 | contracts + frontend | Callback selector in contract matches deliverySelector in frontend encoding | T1 | HIGH |
| 2 | contracts + frontend | ABI field count in Solidity `abi.encode` matches TypeScript `encodeAbiParameters` | T1 | MEDIUM |
| 3 | contracts + frontend | Contract addresses in Solidity constants match TypeScript address constants | T1 | HIGH |
| 4 | contracts + backend | Event names in contract `emit` statements match backend `watchEvent` subscriptions | T1 | HIGH |
| 5 | backend + frontend | Job status names in backend match status names in frontend state machine | T1 | MEDIUM |
| 6 | wallet + (any async skill) | RitualWallet deposit exists and covers estimated fees for all planned async calls | T3 | HIGH |
| 7 | deploy + (all) | Chain ID in deploy config matches chain ID in frontend wagmi config and backend viem config | T1 | HIGH |
| 8 | frontend + backend | API base URL in frontend matches backend server port/host | T1 | MEDIUM |

---

## Regression Protocol

After any code modification during a fix:

1. **Always re-run T1 (static) checks** for ALL loaded skills — not just the modified skill. This catches cross-skill regressions from simple edits. T1 checks are cheap (grep + compile).
2. **Re-run T2+ checks** only for the skill whose code was modified.
3. **Re-run cross-skill integration checks** if the modification touches a shared interface (addresses, selectors, status names, ABI encoding).

---

## Unified End-to-End Verification — User Journey Emulation

The per-skill and cross-skill checks verify components in isolation and at interfaces. This section verifies the **complete user journey** from start to finish — emulating exactly what a real user would do, in order, with each step gated on the previous step's success. If this passes, the application works. Period.

This is the strong-typing equivalent for the full stack: every state transition is verified, every data flow is traced end-to-end, and no step is skipped. The individual skill checks are unit tests. The cross-skill checks are interface tests. This is the integration test.

### Preconditions

The unified protocol runs AFTER all per-skill checks and cross-skill checks pass. It requires:
- T3 tier: contracts deployed on-chain
- T4 tier: frontend and backend (if applicable) running
- A funded test EOA with RitualWallet deposit

If any precondition is not met, the unified protocol CANNOT run. Report which precondition is missing and skip.

### The Journey

The protocol emulates 12 steps a real user takes. Each step has an **assertion** — a concrete, verifiable condition that must be true before proceeding. If any assertion fails, the journey stops and the failure is reported with the exact step, expected outcome, and actual outcome.

```
Step 1 ──assert──► Step 2 ──assert──► Step 3 ──assert──► ... ──assert──► Step 12
   │                  │                  │                                   │
   FAIL               FAIL               FAIL                               PASS
   ↓                  ↓                  ↓                                   ↓
   Report             Report             Report                          "Journey verified"
```

---

#### Step 1: Chain Reachable

**Action:** Query the RPC endpoint.
**Assert:** `cast block-number --rpc-url $RITUAL_RPC_URL` returns a positive integer.
**Assert:** `cast chain-id --rpc-url $RITUAL_RPC_URL` returns `1979`.
**Fail means:** Wrong RPC URL, network unreachable, or wrong chain. Nothing else will work.

```bash
BLOCK=$(cast block-number --rpc-url $RITUAL_RPC_URL 2>/dev/null)
CHAIN=$(cast chain-id --rpc-url $RITUAL_RPC_URL 2>/dev/null)
[ -n "$BLOCK" ] && [ "$CHAIN" = "1979" ] || exit 1
```

---

#### Step 2: Wallet Funded

**Action:** Check the test EOA's native RITUAL balance and RitualWallet deposit.
**Assert:** Native balance > 0 (can pay gas).
**Assert:** `RitualWallet.balanceOf(testEOA)` > 0 (can pay executor fees).
**Assert:** `RitualWallet.lockUntil(testEOA)` > current block + 5000 (lock covers operations).
**Fail means:** The user can't submit any async transaction. Must deposit first.

```bash
NATIVE_BAL=$(cast balance $TEST_EOA --rpc-url $RITUAL_RPC_URL)
WALLET_BAL=$(cast call $RITUAL_WALLET "balanceOf(address)(uint256)" $TEST_EOA --rpc-url $RITUAL_RPC_URL)
LOCK_UNTIL=$(cast call $RITUAL_WALLET "lockUntil(address)(uint256)" $TEST_EOA --rpc-url $RITUAL_RPC_URL)
CURRENT_BLOCK=$(cast block-number --rpc-url $RITUAL_RPC_URL)
[ "$NATIVE_BAL" != "0" ] && [ "$WALLET_BAL" != "0" ] && [ "$LOCK_UNTIL" -gt "$((CURRENT_BLOCK + 5000))" ] || exit 2
```

---

#### Step 3: Executor Available

**Action:** Query TEEServiceRegistry for the capability the dApp uses.
**Assert:** At least one executor returned with `isValid=true`.
**Fail means:** No executor can process the request. The transaction will submit but never settle.

```bash
CAPABILITY=0  # 0=HTTP, 1=LLM, 7=Image, etc. — set based on project
EXECUTORS=$(cast call $TEE_REGISTRY "getServicesByCapability(uint8,bool)" $CAPABILITY true --rpc-url $RITUAL_RPC_URL)
[ -n "$EXECUTORS" ] && [ "$EXECUTORS" != "0x" ] || exit 3
```

---

#### Step 4: Consumer Contract Deployed and Callable

**Action:** Verify the dApp's consumer contract has bytecode and its key functions are callable via `eth_call`.
**Assert:** `cast code $CONTRACT_ADDRESS` returns non-empty bytecode.
**Assert:** A view function on the contract returns without revert (e.g., `owner()`, `results(bytes32)`, or any read function).
**Fail means:** Contract not deployed, wrong address, or constructor reverted.

```bash
CODE=$(cast code $CONTRACT_ADDRESS --rpc-url $RITUAL_RPC_URL)
[ "$CODE" != "0x" ] || exit 4
# Call a view function to verify the contract is functional
cast call $CONTRACT_ADDRESS "owner()(address)" --rpc-url $RITUAL_RPC_URL 2>/dev/null || exit 4
```

---

#### Step 5: Sender Not Locked

**Action:** Check that the test EOA does NOT have a pending async job.
**Assert:** `AsyncJobTracker.hasPendingJobForSender(testEOA)` returns `false`.
**Fail means:** A previous test or operation left a pending job. Wait for settlement or use a different EOA.

```bash
IS_LOCKED=$(cast call $ASYNC_JOB_TRACKER "hasPendingJobForSender(address)(bool)" $TEST_EOA --rpc-url $RITUAL_RPC_URL)
[ "$IS_LOCKED" = "false" ] || exit 5
```

---

#### Step 6: Precompile Call Simulates Successfully

**Action:** Encode the precompile request (using the exact parameters the dApp would use) and run `eth_call` against the precompile address.
**Assert for short-running async precompiles (HTTP, LLM):** `eth_call` returns non-empty data (the simulation envelope). Note: `actualOutput` may be `0x` in simulation — this is expected. The simulation envelope itself being non-empty is the pass condition.
**Assert for long-running async precompiles (Sovereign Agent, Image):** `eth_call` returns non-empty data.
**Assert for synchronous precompiles (ONNX, JQ, SECP256R1):** `eth_call` returns the actual result.
**Fail means:** ABI encoding is wrong, precompile address is wrong, or executor address is invalid.

```bash
ENCODED=$(cast abi-encode "f(...)" $PARAMS)  # project-specific encoding
RESULT=$(cast call $PRECOMPILE_ADDRESS $ENCODED --rpc-url $RITUAL_RPC_URL 2>/dev/null)
[ -n "$RESULT" ] && [ "$RESULT" != "0x" ] || exit 6
```

---

#### Step 7: Transaction Submits and Mines

**Action:** Submit the actual precompile call (or consumer contract call) as a real transaction with the test EOA.
**Assert:** `cast send` returns a transaction hash.
**Assert:** `cast receipt $TX_HASH` returns a receipt with `status: 1` (success).
**Assert for short-running async:** The receipt contains `spcCalls` field with at least one entry.
**Assert for long-running async:** The receipt is status 1 (Phase 1 mined). The result arrives later via callback.
**Fail means:** Insufficient gas, encoding error, contract revert, executor rejection, or insufficient RitualWallet deposit.

```bash
TX_HASH=$(cast send $TARGET $ENCODED --rpc-url $RITUAL_RPC_URL --private-key $TEST_PRIVATE_KEY --gas-limit 3000000)
RECEIPT_STATUS=$(cast receipt $TX_HASH --rpc-url $RITUAL_RPC_URL | grep "status" | awk '{print $2}')
[ "$RECEIPT_STATUS" = "1" ] || exit 7

# For short-running async precompiles: verify spcCalls present
# (Requires custom RPC call or viem script since cast doesn't expose spcCalls)
```

---

#### Step 8: Result Delivered (short-running async) or Callback Fires (long-running async)

**For short-running async precompiles (HTTP, LLM, DKMS):**
**Action:** Extract `spcCalls[0].output` from the transaction receipt.
**Assert:** Output is non-empty hex.
**Assert:** Decoded output matches the expected schema (e.g., HTTP: uint16 + string[] + string[] + bytes + string).

**For long-running async precompiles (Sovereign Agent, Image, Long HTTP):**
**Action:** Poll `AsyncJobTracker.isPhase1Settled(jobId)` until it returns `true`, or check that current block exceeds `commitBlock + ttl`. Then watch for your consumer contract's callback event (e.g., `SovereignAgentResultDelivered`, `LongRunningResultReceived`).
**Assert:** Phase 1 settles within TTL. Callback fires after Phase 2 delivery.
**Assert:** The consumer contract's callback was invoked (check for emitted events).

```bash
# For long-running async: poll Phase 1 settlement
for i in $(seq 1 60); do
  P1=$(cast call $ASYNC_JOB_TRACKER "isPhase1Settled(bytes32)(bool)" $JOB_ID --rpc-url $RITUAL_RPC_URL)
  [ "$P1" = "true" ] && break
  sleep 5
done
[ "$P1" = "true" ] || exit 8
# Then watch for your consumer contract's result event for Phase 2
```

---

#### Step 9: Result Decodable and Semantically Valid

**Action:** Decode the result using the precompile-specific ABI.
**Assert for HTTP:** `statusCode` is in range 100-599. `errorMessage` is empty (or matches expected API error).
**Assert for LLM:** `hasError` is false. `completionData` parses as valid JSON with `choices[0].message.content` non-empty.
**Assert for Sovereign Agent:** `success` is true. `response` is non-empty. `stoppedReason` is "completed" or "max_iterations."
**Assert for Image/Audio/Video:** `outputUri` is a valid URL. `outputContentHash` is non-zero.
**Fail means:** Executor returned corrupt or unexpected data. ABI mismatch between encoding and decoding.

```bash
# Decode and validate (project-specific)
# For HTTP:
STATUS_CODE=$(... decode uint16 from output ...)
[ "$STATUS_CODE" -ge 100 ] && [ "$STATUS_CODE" -lt 600 ] || exit 9

# For LLM:
HAS_ERROR=$(... decode bool from output ...)
[ "$HAS_ERROR" = "false" ] || exit 9
```

---

#### Step 10: Consumer Contract State Updated

**Action:** Read the consumer contract's state to verify the result was persisted.
**Assert:** If the contract stores results (e.g., `results[jobId]`), the stored value is non-empty.
**Assert:** If the contract emits events, the expected event was emitted in the settlement transaction.
**Fail means:** Callback didn't fire (wrong selector, wrong deliveryTarget, insufficient delivery gas), or callback reverted silently.

```bash
STORED_RESULT=$(cast call $CONTRACT_ADDRESS "getResult(bytes32)(string)" $JOB_ID --rpc-url $RITUAL_RPC_URL)
[ -n "$STORED_RESULT" ] || exit 10
```

---

#### Step 11: Frontend Renders Result (if frontend exists)

**Action:** Using Playwright (or equivalent), load the dApp in a browser, connect the test wallet, and verify the result is displayed.
**Assert:** The page loads without console errors.
**Assert:** The wallet connects and shows the correct address.
**Assert:** The result from Step 9 appears in the UI (match text content, or verify a result container is non-empty).
**Assert:** The async status indicator shows SETTLED (not stuck on PENDING or PROCESSING).
**Fail means:** Frontend is not connected to the correct contract, spcCalls parsing is broken, state machine didn't transition, or rendering error.

```typescript
// Playwright test (conceptual)
import { test, expect } from '@playwright/test';

test('E2E: result renders after settlement', async ({ page }) => {
  await page.goto(process.env.APP_URL || 'http://127.0.0.1:3000');

  // Wallet should connect (via test fixture or mock)
  await expect(page.locator('[data-testid="wallet-address"]')).toContainText(TEST_EOA.slice(0, 6));

  // Result should be visible
  const resultContainer = page.locator('[data-testid="result"]');
  await expect(resultContainer).not.toBeEmpty({ timeout: 120_000 });

  // Status should be SETTLED
  await expect(page.locator('[data-testid="status"]')).toContainText('Settled');

  // No console errors
  const errors: string[] = [];
  page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
  expect(errors).toHaveLength(0);
});
```

---

#### Step 12: Backend Indexed (if backend exists)

**Action:** Query the backend API for the job that was just submitted.
**Assert:** `GET /api/jobs/:jobId` returns 200 with status `SETTLED`.
**Assert:** The `result` field is non-null and matches the decoded result from Step 9.
**Assert:** The backend health endpoint shows `indexerLag < 500` blocks.
**Fail means:** Backend event watcher missed the event, database write failed, or indexer is lagging.

```bash
API_BASE="${API_BASE:-http://127.0.0.1:3001}"
JOB_RESPONSE=$(curl -sf "$API_BASE/api/jobs/$JOB_ID")
STATUS=$(echo $JOB_RESPONSE | jq -r '.status')
RESULT=$(echo $JOB_RESPONSE | jq -r '.result')
[ "$STATUS" = "SETTLED" ] && [ "$RESULT" != "null" ] || exit 12

HEALTH=$(curl -sf "$API_BASE/api/health" | jq -r '.indexerLag.blocks')
[ "$HEALTH" -lt 500 ] || echo "WARN: Indexer lag is $HEALTH blocks"
```

---

### Journey Invariants

These conditions must hold at EVERY step, not just at the end:

| Invariant | Checked At | What It Means |
|-----------|-----------|---------------|
| Chain ID = 1979 | Steps 1, 6, 7 | Every RPC call targets the correct chain |
| Sender not locked | Steps 5, 7 | Only one async job per EOA at a time |
| All addresses checksum-valid | Steps 4, 6, 7, 10 | No truncated or malformed addresses |
| Gas limit explicit (never estimated for async) | Step 7 | Async precompile gas estimation fails — always set explicitly |
| Receipt status = 1 | Steps 7, 8 | No silent reverts |
| spcCalls accessed for short-running async precompiles | Steps 8, 9 | Result is in the receipt extension, not in logs |
| Callback auth = AsyncDelivery | Step 10 | Only the system can invoke callbacks |

### Failure Diagnosis

When a step fails, the unified protocol produces a structured failure report:

```
UNIFIED VERIFICATION FAILED

Step:     [N] — [Step Name]
Expected: [What should have happened]
Actual:   [What actually happened]
TX Hash:  [If applicable]

Likely root cause:
  If Step 1-2 failed:  Infrastructure (RPC, funding)
  If Step 3 failed:    Executor availability
  If Step 4-5 failed:  Deployment or sender lock
  If Step 6 failed:    ABI encoding or address mismatch
  If Step 7 failed:    Transaction-level error (gas, revert, deposit)
  If Step 8-9 failed:  Executor processing or result decoding
  If Step 10 failed:   Callback configuration (selector, gas, auth)
  If Step 11 failed:   Frontend rendering or state machine
  If Step 12 failed:   Backend indexing or API

Next action: Run the per-skill verification protocol for the implicated skill.
```

### The Strong-Typing Guarantee

If all 12 steps pass:

- The chain is reachable and correct (Step 1)
- The user can pay for operations (Step 2)
- An executor exists to process the request (Step 3)
- The contract is deployed and functional (Step 4)
- No sender lock blocks the submission (Step 5)
- The precompile encoding is correct (Step 6)
- The transaction submits and mines successfully (Step 7)
- The result is delivered (Step 8)
- The result is decodable and semantically valid (Step 9)
- The on-chain state reflects the result (Step 10)
- The user can see the result in the browser (Step 11)
- The backend has indexed the result (Step 12)

**There are no gaps.** Every data flow — from user wallet to chain to executor to receipt to contract state to frontend display to backend index — has been verified. The application works end-to-end. The probability of a user encountering a failure that this protocol did not catch is bounded by: (a) non-deterministic executor behavior, or (b) race conditions in high-throughput block production (use `ritual-dapp-block-time` to estimate current block cadence on your target deployment).

---

## Running the Full Protocol

```
1. Determine which skills are loaded for this project.
2. For each loaded skill, run BLOCKING checks in order.
     If a blocking check fails → fix (auto-fix if available) → re-run.
3. Run all INDEPENDENT checks in parallel.
     Collect ALL failures at once.
4. Fix all independent failures. Re-run failed checks.
5. Run cross-skill integration checks (if multiple skills loaded).
6. On any fix: run regression protocol (T1 for all skills).
7. Run unified E2E journey verification (Steps 1-12, skip steps for missing components).
     If Step 11 requires Playwright and it's not configured: skip, note as unverified.
     If Step 12 requires a backend and there is none: skip.
8. Report to user only if there were failures that required non-trivial fixes.
   Silent on all-pass. On unified journey pass: "End-to-end verified."
```

## Tooling Requirements

| Tool | Tier | Required For | Install |
|------|------|-------------|---------|
| `forge` | T1/T2 | Contract compilation, testing, deployment sim | `curl -L https://foundry.paradigm.xyz \| bash` |
| `cast` | T2/T3 | On-chain queries, ABI encoding | Included with Foundry |
| `slither` | T1 | Static analysis (optional, enhances contracts checks) | `pip install slither-analyzer` |
| `tsc` | T1 | TypeScript type checking | Included with TypeScript |
| `next build` | T1 | Next.js build verification | Included with Next.js |
| `playwright` | T4 | Browser testing, accessibility | `npx playwright install` |
| `vitest` | T1 | TypeScript unit tests | `npm install -D vitest` |
| `curl` / `jq` | T4 | API health checks | Usually pre-installed |

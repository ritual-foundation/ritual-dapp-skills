# ritual-dapp-security

Security patterns, anti-patterns, and audit checklist for Sovereign Agents and dApps on Ritual Chain.

## When to load this skill

Load this skill when:
- Building a Sovereign Agent that handles funds or sensitive prompts
- Auditing an existing Ritual contract before mainnet deployment
- Implementing access control on precompile callbacks
- Designing commit-reveal schemes for private bounty/voting systems

---

## 1. Sovereign Agent Security Model

### Threat Surface

A Sovereign Agent on Ritual has a unique threat surface compared to a standard EVM contract:

| Vector | Risk | Mitigation |
|---|---|---|
| Prompt stored on-chain | Anyone can read agent strategy | Use ECIES encryption (Secrets precompile 0x080B) |
| Wake schedule public | Front-running of agent actions | Randomize execution timing or use private mempools |
| Callback not authenticated | Fake results injected | Verify `msg.sender == ASYNC_DELIVERY_ADDRESS` |
| Executor selection predictable | Biased TEE selection | Use VRF seed, not block.number |
| RitualWallet balance public | DoS by draining | Set minimum balance checks |

### Critical: Callback Authentication

Every precompile callback MUST verify the caller. A missing check allows anyone to inject arbitrary results:

```solidity
// ❌ WRONG — anyone can call this
function rawReceive(bytes calldata output, bytes calldata) external {
    _processResult(output);
}

// ✅ CORRECT — only AsyncDelivery can deliver results
address constant ASYNC_DELIVERY = 0x5a16214ff555848411544b005f7ac063742f39f6;

function rawReceive(bytes calldata output, bytes calldata) external {
    require(msg.sender == ASYNC_DELIVERY, "unauthorized callback");
    _processResult(output);
}
```

### Critical: Reentrancy in Wake Callbacks

Agents that transfer funds in callbacks are vulnerable to reentrancy:

```solidity
// ❌ WRONG — state updated after external call
function rawReceive(bytes calldata output, bytes calldata) external {
    address winner = abi.decode(output, (address));
    winner.call{value: prize}("");  // reentrant!
    finalized = true;
}

// ✅ CORRECT — Checks-Effects-Interactions
function rawReceive(bytes calldata output, bytes calldata) external {
    require(msg.sender == ASYNC_DELIVERY, "unauthorized");
    address winner = abi.decode(output, (address));
    finalized = true;          // state first
    uint256 amount = prize;
    prize = 0;                 // zero before transfer
    (bool ok,) = winner.call{value: amount}("");
    require(ok, "transfer failed");
}
```

---

## 2. Prompt Privacy

### Problem

By default, agent prompts are stored in contract storage and readable by anyone:

```bash
# Anyone can read your agent's prompt:
cast call <AGENT_ADDRESS> "0x0679825b" --rpc-url https://rpc.ritualfoundation.org
# Returns: plaintext prompt, model ID, financial parameters
```

This directly contradicts the privacy guarantee for agents with proprietary strategies.

### Solution A — Encrypt prompt with Secrets precompile (0x080B)

```solidity
// Store only encrypted prompt on-chain
// Decrypt inside TEE at execution time
bytes public encryptedPrompt;

function setPrompt(bytes calldata ciphertext) external onlyOwner {
    // ciphertext = ECIES(prompt, TEE_pubkey)
    encryptedPrompt = ciphertext;
}
```

### Solution B — Commit-Reveal for Bounty Systems

For bounty/voting systems where answers must stay private until judging:

```solidity
// Participants commit a hash, not the plaintext
function submitCommitment(uint256 bountyId, bytes32 commitment) external {
    // commitment = keccak256(answer, salt, msg.sender, bountyId)
    // answer stays hidden until reveal phase
}

function revealAnswer(uint256 bountyId, string calldata answer, bytes32 salt) external {
    bytes32 expected = keccak256(abi.encodePacked(answer, salt, msg.sender, bountyId));
    require(expected == commitments[bountyId][msg.sender], "InvalidReveal");
    // Only valid reveals are eligible for AI judging
}
```

The salt MUST be:
- At least 128 bits of entropy (256 recommended)
- Kept secret until reveal
- Bound to `msg.sender` and `bountyId` to prevent replay attacks

---

## 3. Access Control Patterns

### Owner-only admin functions

```solidity
error NotOwner();
address public immutable owner;

modifier onlyOwner() {
    if (msg.sender != owner) revert NotOwner();
    _;
}

constructor() { owner = msg.sender; }
```

### Scheduler-only wake

```solidity
address constant SCHEDULER = 0x56e776BAE2DD60664b69Bd5F865F1180ffB7D58B;

modifier onlyScheduler() {
    require(msg.sender == SCHEDULER, "only scheduler");
    _;
}
```

### Phased access (commit-reveal pattern)

```solidity
uint256 public commitDeadline;
uint256 public revealDeadline;

modifier duringCommitPhase() {
    require(block.timestamp <= commitDeadline, "CommitPhaseOver");
    _;
}

modifier duringRevealPhase() {
    require(block.timestamp > commitDeadline, "CommitPhaseNotOver");
    require(block.timestamp <= revealDeadline, "RevealPhaseOver");
    _;
}

modifier afterRevealPhase() {
    require(block.timestamp > revealDeadline, "RevealPhaseNotOver");
    _;
}
```

---

## 4. Financial Safety

### RitualWallet minimum balance check

```solidity
uint256 constant MIN_BALANCE = 0.01 ether;

function _beforeWake() internal view {
    require(address(ritualWallet).balance >= MIN_BALANCE, "InsufficientBalance");
}
```

### CEI pattern for prize payouts

Always: Check → Effect → Interact

```solidity
function finalizeWinner(uint256 winnerIndex) external onlyOwner {
    // Check
    require(!finalized, "AlreadyFinalized");
    require(winnerIndex < submissions.length, "InvalidIndex");
    // Effect
    finalized = true;
    uint256 amount = prize;
    prize = 0;
    address winner = submissions[winnerIndex].participant;
    // Interact
    (bool ok,) = winner.call{value: amount}("");
    require(ok, "TransferFailed");
}
```

---

## 5. Audit Checklist

Before deploying a Sovereign Agent to mainnet:

### Callbacks
- [ ] All `rawReceive` / callback functions check `msg.sender == ASYNC_DELIVERY`
- [ ] No state changes after external calls in callbacks
- [ ] Empty/malformed precompile output handled gracefully (don't treat error as success)

### Prompt & Config
- [ ] Sensitive prompts encrypted with Secrets precompile, not stored plaintext
- [ ] No API keys, credentials, or strategies in plaintext storage
- [ ] If prompt must be on-chain, accept the disclosure and design accordingly

### Financial
- [ ] CEI pattern on all fund transfers
- [ ] No reentrancy vectors in wake callbacks
- [ ] Minimum balance guard before scheduling next wake
- [ ] Prize/reward zeroed before transfer

### Access Control
- [ ] `onlyOwner` on all admin functions
- [ ] Callback callers verified against system contract addresses
- [ ] Phase gates enforced with custom errors (not string reverts — saves gas)

### Upgradeability
- [ ] If UUPS: `_authorizeUpgrade` has `onlyOwner`
- [ ] If upgradeable: storage layout documented and collision-checked

### Testing
- [ ] Valid and invalid callback injection tested
- [ ] Time-based phase transitions tested with `vm.warp`
- [ ] Reentrancy attack vector tested
- [ ] Front-running scenario documented

---

## 6. Known Testnet Issues (June 2026)

- **Phase 2 callbacks not delivered**: `0x080C` (Sovereign Agent precompile) callbacks are not consistently delivered on testnet. `nextSeriesId` increments but no on-chain event is emitted. Track issue #7 on ritual-dapp-skills.
- **EIP-1559 tx rejection**: Some RPC nodes on Ritual testnet reject type-2 transactions from browser wallets. Use `cast send` with explicit `--gas-price` for reliable tx submission.
- **Legacy tx only via cast**: Wallet integrations (MetaMask, Rabby) may fail with "transaction type not supported". Use `cast send` for testnet interactions.

---

## 7. Example: Privacy-Preserving AI Bounty Judge

A complete reference implementation combining commit-reveal privacy with Ritual AI judging:

**Contract**: Participants commit `keccak256(answer, salt, sender, bountyId)` during the submission phase. After deadline, they reveal plaintext. The contract verifies the hash. Owner calls `judgeAll()` which emits a `BatchJudgeRequested` event. A Ritual TEE node receives all revealed answers, runs batch LLM inference, and calls `finalizeWinner()` via authenticated callback.

**Key properties**:
- Answers hidden during submission (no front-running)
- Salt binding prevents cross-bounty replay
- Sender binding prevents front-running of valid commitments
- AI judges all answers in one batch call (not N separate LLM calls)
- Prize transfer uses CEI pattern

**Reference implementation**: `https://github.com/lau90eth/ritual-chain-workshop`

---

## System Contract Addresses (Testnet, chainId 1979)

| Contract | Address |
|---|---|
| SovereignAgentFactory | `0x9dC4C054e53bCc4Ce0A0Ff09E890A7a8e817f304` |
| Scheduler | `0x56e776BAE2DD60664b69Bd5F865F1180ffB7D58B` |
| AsyncDelivery (Executor) | `0x5a16214ff555848411544b005f7ac063742f39f6` |
| RitualWallet | `0x532f0df0896f353d8c3dd8cc134e8129da2a3948` |
| ServiceRegistry | `0x9644e8562ce0fe12b4deec4163c064a8862bf47f` |
| Sovereign Agent precompile | `0x080C` |
| Secrets precompile | `0x080B` |


# Escrow V2: Per-Challenge Independent Fund Distribution — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rewrite ChallengeEscrow contract and backend to support per-challenge independent arbiter rewards, upheld 100% deposit refund (arbiter reward from incentive), and original winner compensation from failed deposits.

**Architecture:** Smart contract resolveChallenge rewritten with new Verdict struct (includes per-challenge arbiters). Backend scheduler builds per-challenge arbiter lists and passes to contract. All fund calculation logic lives in the contract (Option B).

**Tech Stack:** Solidity 0.8.20 (Foundry), Python/FastAPI, web3.py, SQLAlchemy

---

### Task 1: Rewrite ChallengeEscrow.sol

**Files:**
- Modify: `contracts/src/ChallengeEscrow.sol`

**Step 1: Update Verdict struct and add constants**

In `contracts/src/ChallengeEscrow.sol`, replace the existing `Verdict` struct (line 27-30) and add new constant:

```solidity
uint256 public constant WINNER_COMPENSATION_BPS = 1000; // 10% of deposit → original winner

struct Verdict {
    address challenger;
    uint8   result;      // 0=upheld, 1=rejected, 2=malicious
    address[] arbiters;  // per-challenge majority arbiter addresses
}
```

**Step 2: Add _splitAmong internal helper**

Add before `resolveChallenge`:

```solidity
/// @dev Split amount equally among addresses. Returns actual amount sent (may be less due to rounding).
function _splitAmong(address[] memory addrs, uint256 amount) internal returns (uint256 sent) {
    if (addrs.length == 0 || amount == 0) return 0;
    uint256 per = amount / addrs.length;
    for (uint256 i = 0; i < addrs.length; i++) {
        require(usdc.transfer(addrs[i], per), "Arbiter transfer failed");
    }
    return per * addrs.length;
}
```

**Step 3: Rewrite resolveChallenge**

Replace the entire `resolveChallenge` function (lines 111-174) with:

```solidity
/// @notice Resolve challenge: distribute bounty + deposits per new V2 rules.
/// @param winnerPayout Amount from main bounty for finalWinner (backend-computed by trust tier).
///        When hasUpheld: must be <= bounty - incentive (incentive reserved for arbiter + winner bonus).
///        When !hasUpheld: must be <= bounty.
function resolveChallenge(
    bytes32 taskId,
    address finalWinner,
    uint256 winnerPayout,
    Verdict[] memory verdicts
) external onlyOwner {
    ChallengeInfo storage info = challenges[taskId];
    require(info.bounty > 0, "Challenge not found");
    require(!info.resolved, "Already resolved");

    // Detect if any verdict is upheld
    bool hasUpheld = false;
    for (uint256 i = 0; i < verdicts.length; i++) {
        if (verdicts[i].result == 0) { hasUpheld = true; break; }
    }

    // Validate payout cap
    if (hasUpheld) {
        require(winnerPayout <= info.bounty - info.incentive, "Payout exceeds main bounty");
    } else {
        require(winnerPayout <= info.bounty, "Payout exceeds bounty");
    }

    uint256 totalFunds = info.bounty + info.totalDeposits + info.serviceFee * info.challengerCount;
    uint256 totalSent = 0;

    // 1. Main bounty → finalWinner
    if (winnerPayout > 0) {
        require(usdc.transfer(finalWinner, winnerPayout), "Bounty transfer failed");
        totalSent += winnerPayout;
    }

    uint256 incentiveUsed = 0;
    uint256 winnerBonus = 0;

    // 2. Per-verdict deposit distribution
    for (uint256 i = 0; i < verdicts.length; i++) {
        require(challengers[taskId][verdicts[i].challenger], "Not a challenger");
        uint256 dep = challengerDeposits[taskId][verdicts[i].challenger];

        if (verdicts[i].result == 0) {
            // UPHELD: 100% deposit refund to challenger
            require(usdc.transfer(verdicts[i].challenger, dep), "Deposit refund failed");
            totalSent += dep;
            // Arbiter reward from incentive
            uint256 arbReward = dep * ARBITER_DEPOSIT_BPS / 10000;
            incentiveUsed += arbReward;
            totalSent += _splitAmong(verdicts[i].arbiters, arbReward);
        } else {
            // REJECTED or MALICIOUS
            uint256 arbShare = dep * ARBITER_DEPOSIT_BPS / 10000;
            totalSent += _splitAmong(verdicts[i].arbiters, arbShare);
            if (!hasUpheld) {
                // 10% winner compensation
                uint256 comp = dep * WINNER_COMPENSATION_BPS / 10000;
                winnerBonus += comp;
            }
            // Remaining goes to platform (via totalFunds - totalSent)
        }
    }

    // 3. Incentive remainder → winner bonus (only when upheld)
    if (hasUpheld && info.incentive > incentiveUsed) {
        winnerBonus += info.incentive - incentiveUsed;
    }

    // 4. Send accumulated winner bonus
    if (winnerBonus > 0) {
        require(usdc.transfer(finalWinner, winnerBonus), "Winner bonus transfer failed");
        totalSent += winnerBonus;
    }

    // 5. Platform gets everything remaining (service fees + forfeited deposits + rounding)
    uint256 platformAmount = totalFunds - totalSent;
    if (platformAmount > 0) {
        require(usdc.transfer(owner(), platformAmount), "Platform transfer failed");
    }

    info.resolved = true;
    emit ChallengeResolved(taskId, finalWinner);
}
```

**Step 4: Run forge build to verify compilation**

Run: `cd contracts && forge build`
Expected: Compilation successful

**Step 5: Commit**

```bash
git add contracts/src/ChallengeEscrow.sol
git commit -m "feat(contract): Escrow V2 逐挑战独立分配 + upheld 全退 + winner 补偿"
```

---

### Task 2: Rewrite Contract Tests

**Files:**
- Modify: `contracts/test/ChallengeEscrow.t.sol`

**Step 1: Update test constants and helpers**

Replace the constants at lines 53-60 with:

```solidity
// Default amounts: task bounty = 10 USDC
uint256 constant TASK_BOUNTY = 10 * 1e6;
uint256 constant BOUNTY = 9_500_000;     // 95% locked
uint256 constant INCENTIVE = 1_000_000;  // 10% incentive (was 0 in V1)
uint256 constant DEPOSIT = 1 * 1e6;
uint256 constant PAYOUT_A = 8 * 1e6;             // A-tier: 80%
uint256 constant PAYOUT_A_CHALLENGE = 8_500_000;  // A-tier challenger: min(90%, mainBounty=85%)=85%
```

Update `_createChallenge` to use the new INCENTIVE value:

```solidity
function _createChallenge(bytes32 taskId) internal {
    usdc.approve(address(escrow), BOUNTY);
    escrow.createChallenge(taskId, winner, BOUNTY, INCENTIVE);
}
```

Replace Verdict construction helpers — the new `Verdict` includes `address[] arbiters`. Add helper:

```solidity
function _verdict(address challenger, uint8 result, address[] memory arbiters)
    internal pure returns (ChallengeEscrow.Verdict memory)
{
    return ChallengeEscrow.Verdict(challenger, result, arbiters);
}
```

Remove the old `_noArbiters()` since arbiters are now per-verdict.

Update `resolveChallenge` calls everywhere — remove the last `address[] arbiters` parameter. Each Verdict now contains its own arbiters.

**Step 2: Rewrite all resolve tests**

Key test cases that must exist:

1. **test_resolve_no_challengers**: Empty verdicts, no incentive used. Winner gets PAYOUT_A from main bounty. Platform gets BOUNTY - PAYOUT_A.

2. **test_resolve_rejected_no_upheld**: Single rejected verdict. Arbiter gets deposit×30%. Winner gets deposit×10% compensation. Platform gets remainder.

3. **test_resolve_upheld**: Single upheld verdict. Challenger gets 100% deposit refund. Arbiter reward = deposit×30% from incentive. Winner gets winnerPayout + incentive remainder. Platform gets mainBounty - winnerPayout + serviceFee.

4. **test_resolve_upheld_plus_rejected**: One upheld + one rejected (hasUpheld=true). Upheld gets full refund. Rejected: arbiter 30% + platform 70% (no winner compensation). Each challenge has independent arbiters.

5. **test_resolve_multiple_rejected_no_upheld**: Two rejected challengers, no upheld. Each: 30% arbiter + 10% winner comp + 60% platform. Winner total = payout + sum of compensations.

6. **test_resolve_dynamic_deposits_v2**: B-tier dep=1.5 USDC upheld + A-tier dep=0.5 USDC rejected. Verify all balances match design doc Example 1.

7. **test_resolve_payout_capped_with_upheld**: When upheld, winnerPayout must be <= bounty - incentive.

**Step 3: Run forge test**

Run: `cd contracts && forge test -vv`
Expected: All tests pass

**Step 4: Commit**

```bash
git add contracts/test/ChallengeEscrow.t.sol
git commit -m "test(contract): 更新 Escrow V2 测试用例"
```

---

### Task 3: Update Backend escrow.py

**Files:**
- Modify: `app/services/escrow.py` (lines 181-212)

**Step 1: Update resolve_challenge_onchain signature and logic**

Replace the function at lines 181-212:

```python
def resolve_challenge_onchain(
    task_id: str,
    final_winner_wallet: str,
    winner_payout: float,
    verdicts: list[dict],
) -> str:
    """Call ChallengeEscrow.resolveChallenge() V2 with per-challenge arbiter lists.
    verdicts: [{"challenger": "0x...", "result": 0|1|2, "arbiters": ["0x...", ...]}, ...]
    Returns tx hash."""
    w3, contract = _get_w3_and_contract()
    task_bytes = _task_id_to_bytes32(task_id)
    winner_payout_wei = int(winner_payout * 10**6)

    verdict_tuples = [
        (
            Web3.to_checksum_address(v["challenger"]),
            v["result"],
            [Web3.to_checksum_address(a) for a in v.get("arbiters", [])],
        )
        for v in verdicts
    ]

    fn = contract.functions.resolveChallenge(
        task_bytes,
        Web3.to_checksum_address(final_winner_wallet),
        winner_payout_wei,
        verdict_tuples,
    )
    return _send_tx(w3, fn, f"resolveChallenge({task_id})")
```

**Step 2: Update fallback minimal ABI**

The minimal ABI for `resolveChallenge` (around line 65-85) needs to be updated to match the new V2 signature. The Verdict struct now has 3 fields (address, uint8, address[]). Update the ABI tuple type from `(address,uint8)[]` to `(address,uint8,address[])[]` and remove the last `address[]` parameter.

**Step 3: Commit**

```bash
git add app/services/escrow.py
git commit -m "feat(escrow): resolve_challenge_onchain V2 签名，per-challenge arbiters"
```

---

### Task 4: Update Scheduler

**Files:**
- Modify: `app/scheduler.py` (lines 17-45 and 370-399)

**Step 1: Update _resolve_via_contract**

Replace lines 17-45:

```python
def _resolve_via_contract(
    db: Session, task: Task, verdicts: list,
) -> None:
    """Call resolveChallenge on-chain to distribute bounty + deposits."""
    from .models import User, PayoutStatus
    from .services.trust import get_winner_payout_rate
    try:
        winner_sub = db.query(Submission).filter(
            Submission.id == task.winner_submission_id
        ).first()
        winner_user = db.query(User).filter(
            User.id == winner_sub.worker_id
        ).first() if winner_sub else None
        if winner_user:
            has_upheld = any(v.get("result") == 0 for v in verdicts)
            try:
                rate = get_winner_payout_rate(winner_user.trust_tier, is_challenger_win=has_upheld)
            except ValueError:
                rate = 0.80
            payout_amount = round(task.bounty * rate, 6)
            # When upheld: cap at mainBounty (= locked - incentive = 85% of task bounty)
            if has_upheld:
                main_bounty = round(task.bounty * 0.85, 6)
                payout_amount = min(payout_amount, main_bounty)
            tx_hash = resolve_challenge_onchain(
                task.id, winner_user.wallet, payout_amount, verdicts,
            )
            task.payout_status = PayoutStatus.paid
            task.payout_tx_hash = tx_hash
            task.payout_amount = payout_amount
    except Exception as e:
        task.payout_status = PayoutStatus.failed
        print(f"[scheduler] resolveChallenge failed for {task.id}: {e}", flush=True)
```

**Step 2: Update _settle_after_arbitration verdict building**

Replace the verdict building block (lines 370-399) in `_settle_after_arbitration`:

```python
    # Resolve on-chain: distribute bounty + deposits + arbiter rewards
    if task.bounty and task.bounty > 0:
        verdicts = []
        for c in challenges:
            if c.challenger_wallet:
                result_map = {
                    ChallengeVerdict.upheld: 0,
                    ChallengeVerdict.rejected: 1,
                    ChallengeVerdict.malicious: 2,
                }
                # Per-challenge arbiter wallets
                jury_votes = db.query(ArbiterVote).filter_by(challenge_id=c.id).all()
                is_deadlock = any(v.coherence_status == "neutral" for v in jury_votes)
                if is_deadlock:
                    arbiter_ids = [v.arbiter_user_id for v in jury_votes if v.vote is not None]
                else:
                    arbiter_ids = [v.arbiter_user_id for v in jury_votes
                                   if v.coherence_status == "coherent"]
                arbiter_users = db.query(User).filter(User.id.in_(arbiter_ids)).all() if arbiter_ids else []
                arbiter_wallets = [u.wallet for u in arbiter_users if u.wallet]

                verdicts.append({
                    "challenger": c.challenger_wallet,
                    "result": result_map.get(c.verdict, 1),
                    "arbiters": arbiter_wallets,
                })
        _resolve_via_contract(db, task, verdicts)
```

Remove the old flat arbiter collection block (the old lines 384-398 that collected arbiter_wallet_ids across all challenges).

**Step 3: Commit**

```bash
git add app/scheduler.py
git commit -m "feat(scheduler): V2 per-challenge arbiter lists + winnerPayout cap"
```

---

### Task 5: Update Backend Tests

**Files:**
- Modify: `tests/test_scheduler.py`
- Modify: `tests/test_e2e_oracle_v3.py`

**Step 1: Update test_scheduler.py mocks**

In `tests/test_scheduler.py`, the mock for `_resolve_via_contract` is patched at the module level:
```python
with patch("app.scheduler._resolve_via_contract"):
```
This still works since we only changed the signature (removed `arbiter_wallets` param). But verify that `test_settle_triggers_payout` (line 120+) still passes, since it asserts `_resolve_via_contract` was called.

**Step 2: Update test_e2e_oracle_v3.py mocks**

Mocks of `resolve_challenge_onchain` need to accept the new signature (no `arbiter_wallets`). The mock `return_value="0xresolve"` should still work since mock doesn't validate args by default.

However, any `assert_called_with` or `call_args` checks need updating. Check for:
```python
assert call_args[0][3] == []  # verdicts=[]
```
This pattern should still work since verdicts is still positional arg [3].

**Step 3: Run all tests**

Run: `pytest -v -k "challenge or scheduler" --tb=short`
Expected: All pass (except pre-existing e2e failures)

**Step 4: Commit**

```bash
git add tests/
git commit -m "test: 更新 mock 匹配 Escrow V2 签名"
```

---

### Task 6: Deploy and Verify

**Step 1: Deploy new contract to Base Sepolia**

```bash
cd contracts
source ../.env
forge create --rpc-url $BASE_SEPOLIA_RPC_URL \
  --private-key $PLATFORM_PRIVATE_KEY \
  src/ChallengeEscrow.sol:ChallengeEscrow \
  --constructor-args $USDC_CONTRACT
```

**Step 2: Approve USDC for new contract**

The platform wallet needs to approve the new contract to spend USDC:

```bash
cast send $USDC_CONTRACT "approve(address,uint256)" \
  <NEW_CONTRACT_ADDRESS> 0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff \
  --rpc-url $BASE_SEPOLIA_RPC_URL --private-key $PLATFORM_PRIVATE_KEY
```

**Step 3: Update .env and frontend/.env.local**

Replace `ESCROW_CONTRACT_ADDRESS` and `NEXT_PUBLIC_ESCROW_CONTRACT_ADDRESS` with new address.

**Step 4: Restart backend and frontend**

```bash
# Kill existing processes
taskkill //IM python.exe //F
taskkill //IM node.exe //F

# Restart
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
cd frontend && npm run dev
```

**Step 5: Manual verification**

Test the 3 scenarios from the design doc:
1. B-tier upheld + A-tier rejected → verify balances match Example 1
2. Two rejected, no upheld → verify original winner gets 10% compensation
3. No challengers → verify normal payout

**Step 6: Commit .env updates**

```bash
git add .env frontend/.env.local
git commit -m "deploy: Escrow V2 合约部署到 Base Sepolia"
```

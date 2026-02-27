// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/extensions/IERC20Permit.sol";

contract ChallengeEscrow is Ownable {
    IERC20 public immutable usdc;
    IERC20Permit public immutable usdcPermit;

    uint256 public constant SERVICE_FEE = 10_000; // 0.01 USDC (6 decimals)
    uint256 public constant EMERGENCY_TIMEOUT = 30 days;
    uint256 public constant ARBITER_DEPOSIT_BPS = 3000; // 30% of each deposit → arbiters
    uint256 public constant WINNER_COMPENSATION_BPS = 1000; // 10% of deposit → original winner

    struct ChallengeInfo {
        address winner;
        uint256 bounty;           // Total locked (90% of task bounty)
        uint256 incentive;        // Challenge incentive (10% of task bounty)
        uint256 serviceFee;
        uint8   challengerCount;
        bool    resolved;
        uint256 createdAt;
        uint256 totalDeposits;    // Sum of all challenger deposits (for emergencyWithdraw)
    }

    struct Verdict {
        address challenger;
        uint8   result;      // 0=upheld, 1=rejected, 2=malicious
        address[] arbiters;  // per-challenge majority arbiter addresses
    }

    mapping(bytes32 => ChallengeInfo) public challenges;
    mapping(bytes32 => mapping(address => bool)) public challengers;
    mapping(bytes32 => mapping(address => uint256)) public challengerDeposits;

    event ChallengeCreated(bytes32 indexed taskId, address winner, uint256 bounty);
    event ChallengerJoined(bytes32 indexed taskId, address challenger);
    event ChallengeResolved(bytes32 indexed taskId, address finalWinner);

    constructor(address _usdc) Ownable(msg.sender) {
        usdc = IERC20(_usdc);
        usdcPermit = IERC20Permit(_usdc);
    }

    /// @notice Lock bounty (90%) into escrow at start of challenge window.
    /// @param incentive The 10% challenge incentive portion (included in bounty).
    function createChallenge(
        bytes32 taskId,
        address winner_,
        uint256 bounty,
        uint256 incentive
    ) external onlyOwner {
        require(challenges[taskId].bounty == 0, "Challenge already exists");
        require(bounty > 0, "Bounty must be positive");
        require(incentive <= bounty, "Incentive exceeds bounty");

        challenges[taskId] = ChallengeInfo({
            winner: winner_,
            bounty: bounty,
            incentive: incentive,
            serviceFee: SERVICE_FEE,
            challengerCount: 0,
            resolved: false,
            createdAt: block.timestamp,
            totalDeposits: 0
        });

        require(
            usdc.transferFrom(msg.sender, address(this), bounty),
            "Bounty transfer failed"
        );

        emit ChallengeCreated(taskId, winner_, bounty);
    }

    function joinChallenge(
        bytes32 taskId,
        address challenger,
        uint256 depositAmount,
        uint256 deadline,
        uint8 v,
        bytes32 r,
        bytes32 s
    ) external onlyOwner {
        ChallengeInfo storage info = challenges[taskId];
        require(info.bounty > 0, "Challenge not found");
        require(!info.resolved, "Already resolved");
        require(!challengers[taskId][challenger], "Already joined");

        uint256 totalAmount = depositAmount + info.serviceFee;

        // try/catch: permit may fail if token doesn't support EIP-2612,
        // or signature was frontrun, or user pre-approved via approve().
        try usdcPermit.permit(challenger, address(this), totalAmount, deadline, v, r, s) {} catch {}
        require(
            usdc.transferFrom(challenger, address(this), totalAmount),
            "Deposit transfer failed"
        );

        challengers[taskId][challenger] = true;
        challengerDeposits[taskId][challenger] = depositAmount;
        info.totalDeposits += depositAmount;
        info.challengerCount++;

        emit ChallengerJoined(taskId, challenger);
    }

    /// @dev Split amount equally among addresses. Returns actual amount sent (may be less due to rounding).
    function _splitAmong(address[] memory addrs, uint256 amount) internal returns (uint256 sent) {
        if (addrs.length == 0 || amount == 0) return 0;
        uint256 per = amount / addrs.length;
        for (uint256 i = 0; i < addrs.length; i++) {
            require(usdc.transfer(addrs[i], per), "Arbiter transfer failed");
        }
        return per * addrs.length;
    }

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

    function emergencyWithdraw(bytes32 taskId) external onlyOwner {
        ChallengeInfo storage info = challenges[taskId];
        require(info.bounty > 0, "Challenge not found");
        require(!info.resolved, "Already resolved");
        require(
            block.timestamp >= info.createdAt + EMERGENCY_TIMEOUT,
            "Too early for emergency withdrawal"
        );

        uint256 balance = usdc.balanceOf(address(this));
        uint256 taskFunds = info.bounty +
            info.totalDeposits + info.serviceFee * info.challengerCount;
        uint256 amount = taskFunds > balance ? balance : taskFunds;

        require(usdc.transfer(owner(), amount), "Emergency transfer failed");
        info.resolved = true;
    }
}

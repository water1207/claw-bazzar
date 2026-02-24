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

    struct ChallengeInfo {
        address winner;
        uint256 bounty;           // Total locked (90% of task bounty)
        uint256 incentive;        // Challenge incentive (10% of task bounty)
        uint256 depositAmount;    // Per-challenger deposit
        uint256 serviceFee;
        uint8   challengerCount;
        bool    resolved;
        uint256 createdAt;
    }

    struct Verdict {
        address challenger;
        uint8   result;      // 0=upheld, 1=rejected, 2=malicious
    }

    mapping(bytes32 => ChallengeInfo) public challenges;
    mapping(bytes32 => mapping(address => bool)) public challengers;

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
        uint256 incentive,
        uint256 depositAmount
    ) external onlyOwner {
        require(challenges[taskId].bounty == 0, "Challenge already exists");
        require(bounty > 0, "Bounty must be positive");
        require(incentive <= bounty, "Incentive exceeds bounty");

        challenges[taskId] = ChallengeInfo({
            winner: winner_,
            bounty: bounty,
            incentive: incentive,
            depositAmount: depositAmount,
            serviceFee: SERVICE_FEE,
            challengerCount: 0,
            resolved: false,
            createdAt: block.timestamp
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
        uint256 deadline,
        uint8 v,
        bytes32 r,
        bytes32 s
    ) external onlyOwner {
        ChallengeInfo storage info = challenges[taskId];
        require(info.bounty > 0, "Challenge not found");
        require(!info.resolved, "Already resolved");
        require(!challengers[taskId][challenger], "Already joined");

        uint256 totalAmount = info.depositAmount + info.serviceFee;

        // try/catch: permit may fail if token doesn't support EIP-2612,
        // or signature was frontrun, or user pre-approved via approve().
        try usdcPermit.permit(challenger, address(this), totalAmount, deadline, v, r, s) {} catch {}
        require(
            usdc.transferFrom(challenger, address(this), totalAmount),
            "Deposit transfer failed"
        );

        challengers[taskId][challenger] = true;
        info.challengerCount++;

        emit ChallengerJoined(taskId, challenger);
    }

    /// @notice Resolve challenge: distribute bounty + deposits + arbiter rewards.
    /// @param arbiters Addresses that judged this challenge (receive deposit share).
    function resolveChallenge(
        bytes32 taskId,
        address finalWinner,
        Verdict[] calldata verdicts,
        address[] calldata arbiters
    ) external onlyOwner {
        ChallengeInfo storage info = challenges[taskId];
        require(info.bounty > 0, "Challenge not found");
        require(!info.resolved, "Already resolved");

        uint256 platformTotal = 0;

        // 1. Bounty distribution
        bool hasUpheld = false;
        for (uint256 i = 0; i < verdicts.length; i++) {
            if (verdicts[i].result == 0) { hasUpheld = true; break; }
        }

        if (hasUpheld) {
            // Challenger won: full bounty (90%) to challenger
            require(usdc.transfer(finalWinner, info.bounty), "Bounty transfer failed");
        } else {
            // No challenger won: base payout to original winner, incentive back to platform
            uint256 basePayout = info.bounty - info.incentive;
            require(usdc.transfer(finalWinner, basePayout), "Bounty transfer failed");
            platformTotal += info.incentive;
        }

        // 2. Deposit distribution: 30% of each deposit → arbiters, rest by verdict
        uint256 arbiterPool = 0;
        for (uint256 i = 0; i < verdicts.length; i++) {
            require(challengers[taskId][verdicts[i].challenger], "Not a challenger");

            uint256 arbiterShare = info.depositAmount * ARBITER_DEPOSIT_BPS / 10000;
            arbiterPool += arbiterShare;
            uint256 remaining = info.depositAmount - arbiterShare;

            if (verdicts[i].result == 0) {
                // upheld: remaining 70% back to challenger
                require(
                    usdc.transfer(verdicts[i].challenger, remaining),
                    "Deposit refund failed"
                );
            } else {
                // rejected / malicious: remaining 70% to platform
                platformTotal += remaining;
            }
        }

        // 3. Split arbiter pool equally among arbiters
        if (arbiters.length > 0 && arbiterPool > 0) {
            uint256 perArbiter = arbiterPool / arbiters.length;
            for (uint256 i = 0; i < arbiters.length; i++) {
                require(usdc.transfer(arbiters[i], perArbiter), "Arbiter transfer failed");
            }
            // Rounding remainder → platform
            platformTotal += arbiterPool - perArbiter * arbiters.length;
        } else {
            // No arbiters specified → pool goes to platform
            platformTotal += arbiterPool;
        }

        // 4. Service fees + forfeited amounts → platform
        platformTotal += info.serviceFee * info.challengerCount;
        if (platformTotal > 0) {
            require(usdc.transfer(owner(), platformTotal), "Platform transfer failed");
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
            (info.depositAmount + info.serviceFee) * info.challengerCount;
        uint256 amount = taskFunds > balance ? balance : taskFunds;

        require(usdc.transfer(owner(), amount), "Emergency transfer failed");
        info.resolved = true;
    }
}

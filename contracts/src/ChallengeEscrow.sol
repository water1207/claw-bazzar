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
    uint256 public constant ARBITER_DEPOSIT_BPS = 3000; // 30% of forfeited deposits → arbiters

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

    struct ChallengerRefund {
        address challenger;
        bool refund;  // true = return deposit, false = forfeit (malicious)
    }

    mapping(bytes32 => ChallengeInfo) public challenges;
    mapping(bytes32 => mapping(address => bool)) public challengers;
    mapping(bytes32 => mapping(address => uint256)) public challengerDeposits;
    mapping(bytes32 => address[]) public challengerList;

    event ChallengeCreated(bytes32 indexed taskId, address winner, uint256 bounty);
    event ChallengerJoined(bytes32 indexed taskId, address challenger);
    event ChallengeResolved(bytes32 indexed taskId, address finalWinner, uint8 verdict);

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
        challengerList[taskId].push(challenger);

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

    /// @notice Resolve challenge: unified pool distribution.
    /// @param winnerPayout Backend-computed amount for finalWinner (bounty*rate + incentive remainder).
    /// @param refunds Per-challenger refund decisions (true=refund deposit, false=forfeit to pool).
    /// @param arbiters Majority arbiter addresses (or all if deadlock) to split reward.
    /// @param arbiterReward Total arbiter reward (backend-computed: 30% of forfeited pool + incentive subsidy).
    function resolveChallenge(
        bytes32 taskId,
        address finalWinner,
        uint256 winnerPayout,
        ChallengerRefund[] calldata refunds,
        address[] calldata arbiters,
        uint256 arbiterReward
    ) external onlyOwner {
        ChallengeInfo storage info = challenges[taskId];
        require(info.bounty > 0, "Challenge not found");
        require(!info.resolved, "Already resolved");

        uint256 totalFunds = info.bounty + info.totalDeposits + info.serviceFee * info.challengerCount;
        uint256 totalSent = 0;

        // 1. Process challenger refunds/forfeits
        (uint256 refunded, ) = _processRefunds(taskId, refunds);
        totalSent += refunded;

        // 2. Winner payout (bounty portion + incentive remainder)
        if (winnerPayout > 0) {
            require(usdc.transfer(finalWinner, winnerPayout), "Winner payout failed");
            totalSent += winnerPayout;
        }

        // 3. Arbiter reward (from forfeited pool 30% + incentive subsidy)
        totalSent += _splitAmong(arbiters, arbiterReward);

        // 4. Platform gets remainder (service fees + forfeited deposit remainder + rounding)
        uint256 platformAmount = totalFunds - totalSent;
        if (platformAmount > 0) {
            require(usdc.transfer(owner(), platformAmount), "Platform transfer failed");
        }

        info.resolved = true;
        emit ChallengeResolved(taskId, finalWinner, refunded > 0 ? 0 : 1);
    }

    /// @dev Process challenger deposit refunds/forfeits. Returns (totalRefunded, totalArbiterBonus).
    function _processRefunds(
        bytes32 taskId,
        ChallengerRefund[] calldata refunds
    ) internal returns (uint256 totalRefunded, uint256 totalArbiterBonus) {
        for (uint256 i = 0; i < refunds.length; i++) {
            address chAddr = refunds[i].challenger;
            uint256 dep = challengerDeposits[taskId][chAddr];
            if (dep == 0) continue;

            if (refunds[i].refund) {
                require(usdc.transfer(chAddr, dep), "Deposit refund failed");
                totalRefunded += dep;
            } else {
                totalArbiterBonus += (dep * ARBITER_DEPOSIT_BPS) / 10000;
            }
            challengerDeposits[taskId][chAddr] = 0;
        }
    }

    /// @notice Void a challenge: refund publisher, handle challenger deposits, pay arbiters.
    function voidChallenge(
        bytes32 taskId,
        address publisher,
        uint256 publisherRefund,
        ChallengerRefund[] calldata refunds,
        address[] calldata arbiters,
        uint256 arbiterReward
    ) external onlyOwner {
        ChallengeInfo storage info = challenges[taskId];
        require(info.bounty > 0, "Challenge not found");
        require(!info.resolved, "Already resolved");

        uint256 totalFunds = info.bounty + info.totalDeposits + info.serviceFee * info.challengerCount;
        uint256 totalSent = 0;

        // 1. Process each challenger
        (uint256 refunded, uint256 arbiterBonus) = _processRefunds(taskId, refunds);
        totalSent += refunded;

        // 2. Refund publisher
        if (publisherRefund > 0) {
            require(usdc.transfer(publisher, publisherRefund), "Publisher refund failed");
            totalSent += publisherRefund;
        }

        // 3. Pay arbiters (base reward + bonus from malicious deposits)
        totalSent += _splitAmong(arbiters, arbiterReward + arbiterBonus);

        // 4. Platform gets remainder (service fees + forfeited deposit remainder + rounding)
        uint256 platformAmount = totalFunds - totalSent;
        if (platformAmount > 0) {
            require(usdc.transfer(owner(), platformAmount), "Platform transfer failed");
        }

        info.resolved = true;
        emit ChallengeResolved(taskId, address(0), 3); // 3 = voided
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

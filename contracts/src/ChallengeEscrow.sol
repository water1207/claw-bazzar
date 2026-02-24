// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/extensions/IERC20Permit.sol";

contract ChallengeEscrow is Ownable {
    IERC20 public immutable usdc;
    IERC20Permit public immutable usdcPermit;

    uint256 public constant SERVICE_FEE = 10_000; // 0.01 USDC = 10000 wei (6 decimals)

    struct ChallengeInfo {
        address winner;
        uint256 bounty;
        uint256 depositAmount;
        uint256 serviceFee;
        uint8   challengerCount;
        bool    resolved;
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

    function createChallenge(
        bytes32 taskId,
        address winner_,
        uint256 bounty,
        uint256 depositAmount
    ) external onlyOwner {
        require(challenges[taskId].bounty == 0, "Challenge already exists");
        require(bounty > 0, "Bounty must be positive");

        challenges[taskId] = ChallengeInfo({
            winner: winner_,
            bounty: bounty,
            depositAmount: depositAmount,
            serviceFee: SERVICE_FEE,
            challengerCount: 0,
            resolved: false
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

        // Use EIP-2612 permit to approve escrow, then transferFrom
        usdcPermit.permit(challenger, address(this), totalAmount, deadline, v, r, s);
        require(
            usdc.transferFrom(challenger, address(this), totalAmount),
            "Deposit transfer failed"
        );

        challengers[taskId][challenger] = true;
        info.challengerCount++;

        emit ChallengerJoined(taskId, challenger);
    }
}

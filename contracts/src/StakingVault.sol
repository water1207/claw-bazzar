// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";

interface IERC20Permit {
    function permit(
        address owner, address spender, uint256 value,
        uint256 deadline, uint8 v, bytes32 r, bytes32 s
    ) external;
}

contract StakingVault is Ownable {
    IERC20 public immutable usdc;
    IERC20Permit public immutable usdcPermit;

    uint256 public constant EMERGENCY_TIMEOUT = 30 days;

    struct Stake {
        uint256 amount;
        uint256 timestamp;
        bool slashed;
    }

    mapping(address => Stake) public stakes;

    event Staked(address indexed user, uint256 amount);
    event Unstaked(address indexed user, uint256 amount);
    event Slashed(address indexed user, uint256 amount);

    constructor(address _usdc) Ownable(msg.sender) {
        usdc = IERC20(_usdc);
        usdcPermit = IERC20Permit(_usdc);
    }

    function stake(
        address user, uint256 amount,
        uint256 deadline, uint8 v, bytes32 r, bytes32 s
    ) external onlyOwner {
        require(amount > 0, "Amount must be > 0");
        require(!stakes[user].slashed, "User is slashed");
        try usdcPermit.permit(user, address(this), amount, deadline, v, r, s) {} catch {}
        require(usdc.transferFrom(user, address(this), amount), "Transfer failed");
        stakes[user].amount += amount;
        if (stakes[user].timestamp == 0) {
            stakes[user].timestamp = block.timestamp;
        }
        emit Staked(user, amount);
    }

    function unstake(address user, uint256 amount) external onlyOwner {
        require(stakes[user].amount >= amount, "Insufficient stake");
        require(!stakes[user].slashed, "User is slashed");
        stakes[user].amount -= amount;
        require(usdc.transfer(user, amount), "Transfer failed");
        emit Unstaked(user, amount);
    }

    function slash(address user) external onlyOwner {
        uint256 amount = stakes[user].amount;
        require(amount > 0, "Nothing to slash");
        stakes[user].amount = 0;
        stakes[user].slashed = true;
        require(usdc.transfer(owner(), amount), "Transfer failed");
        emit Slashed(user, amount);
    }

    function emergencyWithdraw(address user) external onlyOwner {
        require(block.timestamp >= stakes[user].timestamp + EMERGENCY_TIMEOUT, "Too early");
        uint256 amount = stakes[user].amount;
        require(amount > 0, "Nothing to withdraw");
        stakes[user].amount = 0;
        require(usdc.transfer(user, amount), "Transfer failed");
        emit Unstaked(user, amount);
    }
}

// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "../src/StakingVault.sol";
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";

contract MockUSDC is ERC20 {
    constructor() ERC20("USDC", "USDC") {
        _mint(msg.sender, 1_000_000e6);
    }
    function decimals() public pure override returns (uint8) { return 6; }
    function mint(address to, uint256 amount) external { _mint(to, amount); }
}

contract StakingVaultTest is Test {
    StakingVault vault;
    MockUSDC usdc;
    address owner = address(this);
    address user1 = address(0x1);
    address user2 = address(0x2);

    function setUp() public {
        usdc = new MockUSDC();
        vault = new StakingVault(address(usdc));
        usdc.mint(user1, 1000e6);
        usdc.mint(user2, 1000e6);
        vm.prank(user1);
        usdc.approve(address(vault), type(uint256).max);
        vm.prank(user2);
        usdc.approve(address(vault), type(uint256).max);
    }

    function test_stake() public {
        vault.stake(user1, 100e6, 0, 0, bytes32(0), bytes32(0));
        (uint256 amount,,) = vault.stakes(user1);
        assertEq(amount, 100e6);
        assertEq(usdc.balanceOf(address(vault)), 100e6);
    }

    function test_stake_accumulates() public {
        vault.stake(user1, 50e6, 0, 0, bytes32(0), bytes32(0));
        vault.stake(user1, 50e6, 0, 0, bytes32(0), bytes32(0));
        (uint256 amount,,) = vault.stakes(user1);
        assertEq(amount, 100e6);
    }

    function test_unstake() public {
        vault.stake(user1, 100e6, 0, 0, bytes32(0), bytes32(0));
        vault.unstake(user1, 50e6);
        (uint256 amount,,) = vault.stakes(user1);
        assertEq(amount, 50e6);
        assertEq(usdc.balanceOf(user1), 950e6);
    }

    function test_unstake_insufficient() public {
        vault.stake(user1, 50e6, 0, 0, bytes32(0), bytes32(0));
        vm.expectRevert("Insufficient stake");
        vault.unstake(user1, 100e6);
    }

    function test_slash() public {
        vault.stake(user1, 100e6, 0, 0, bytes32(0), bytes32(0));
        uint256 ownerBefore = usdc.balanceOf(owner);
        vault.slash(user1);
        (uint256 amount,, bool slashed) = vault.stakes(user1);
        assertEq(amount, 0);
        assertTrue(slashed);
        assertEq(usdc.balanceOf(owner), ownerBefore + 100e6);
    }

    function test_slash_prevents_restake() public {
        vault.stake(user1, 100e6, 0, 0, bytes32(0), bytes32(0));
        vault.slash(user1);
        vm.expectRevert("User is slashed");
        vault.stake(user1, 50e6, 0, 0, bytes32(0), bytes32(0));
    }

    function test_emergency_withdraw_too_early() public {
        vault.stake(user1, 100e6, 0, 0, bytes32(0), bytes32(0));
        vm.expectRevert("Too early");
        vault.emergencyWithdraw(user1);
    }

    function test_emergency_withdraw_after_timeout() public {
        vault.stake(user1, 100e6, 0, 0, bytes32(0), bytes32(0));
        vm.warp(block.timestamp + 31 days);
        vault.emergencyWithdraw(user1);
        (uint256 amount,,) = vault.stakes(user1);
        assertEq(amount, 0);
        assertEq(usdc.balanceOf(user1), 1000e6);
    }

    function test_only_owner() public {
        vm.prank(user1);
        vm.expectRevert();
        vault.stake(user1, 100e6, 0, 0, bytes32(0), bytes32(0));
    }

    function test_slash_nothing() public {
        vm.expectRevert("Nothing to slash");
        vault.slash(user1);
    }
}

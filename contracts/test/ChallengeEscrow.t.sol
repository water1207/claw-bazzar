// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "../src/ChallengeEscrow.sol";
import "@openzeppelin/contracts/token/ERC20/ERC20.sol";

// Mock USDC with permit support
contract MockUSDC is ERC20 {
    mapping(address => uint256) private _nonces;

    constructor() ERC20("USD Coin", "USDC") {
        _mint(msg.sender, 1_000_000 * 1e6);
    }

    function decimals() public pure override returns (uint8) { return 6; }

    function mint(address to, uint256 amount) external {
        _mint(to, amount);
    }

    // Simplified permit (no signature verification for unit tests)
    function permit(
        address owner_,
        address spender,
        uint256 value,
        uint256 /*deadline*/,
        uint8 /*v*/,
        bytes32 /*r*/,
        bytes32 /*s*/
    ) external {
        _approve(owner_, spender, value);
        _nonces[owner_]++;
    }

    function nonces(address owner_) external view returns (uint256) {
        return _nonces[owner_];
    }

    function DOMAIN_SEPARATOR() external pure returns (bytes32) {
        return bytes32(0);
    }
}

contract ChallengeEscrowTest is Test {
    ChallengeEscrow public escrow;
    MockUSDC public usdc;
    address public platform;
    address public winner = address(0x1);

    function setUp() public {
        platform = address(this);
        usdc = new MockUSDC();
        escrow = new ChallengeEscrow(address(usdc));
    }

    function test_createChallenge() public {
        bytes32 taskId = keccak256("task-1");
        uint256 bounty = 8 * 1e6; // 8 USDC (bounty * 80%)
        uint256 deposit = 1 * 1e6; // 1 USDC (bounty * 10%)

        // Approve escrow to pull bounty from platform
        usdc.approve(address(escrow), bounty);

        escrow.createChallenge(taskId, winner, bounty, deposit);

        (
            address w, uint256 b, uint256 d, uint256 sf,
            uint8 cc, bool resolved
        ) = escrow.challenges(taskId);

        assertEq(w, winner);
        assertEq(b, bounty);
        assertEq(d, deposit);
        assertEq(sf, escrow.SERVICE_FEE());
        assertEq(cc, 0);
        assertFalse(resolved);
        assertEq(usdc.balanceOf(address(escrow)), bounty);
    }

    function test_createChallenge_reverts_duplicate() public {
        bytes32 taskId = keccak256("task-1");
        usdc.approve(address(escrow), 16 * 1e6);
        escrow.createChallenge(taskId, winner, 8 * 1e6, 1 * 1e6);

        vm.expectRevert("Challenge already exists");
        escrow.createChallenge(taskId, winner, 8 * 1e6, 1 * 1e6);
    }

    function test_createChallenge_reverts_nonowner() public {
        bytes32 taskId = keccak256("task-1");
        vm.prank(address(0x999));
        vm.expectRevert();
        escrow.createChallenge(taskId, winner, 8 * 1e6, 1 * 1e6);
    }

    function test_joinChallenge() public {
        bytes32 taskId = keccak256("task-1");
        uint256 bounty = 8 * 1e6;
        uint256 deposit = 1 * 1e6;
        address challenger = address(0x2);

        // Setup: create challenge and fund challenger
        usdc.approve(address(escrow), bounty);
        escrow.createChallenge(taskId, winner, bounty, deposit);
        usdc.mint(challenger, 10 * 1e6);

        uint256 totalRequired = deposit + escrow.SERVICE_FEE();

        // joinChallenge with permit params (mock permit doesn't verify sig)
        escrow.joinChallenge(
            taskId, challenger,
            block.timestamp + 1 hours,
            0, bytes32(0), bytes32(0)
        );

        (, , , , uint8 count, ) = escrow.challenges(taskId);
        assertEq(count, 1);
        assertTrue(escrow.challengers(taskId, challenger));
        assertEq(usdc.balanceOf(address(escrow)), bounty + totalRequired);
    }

    function test_joinChallenge_reverts_duplicate() public {
        bytes32 taskId = keccak256("task-1");
        address challenger = address(0x2);

        usdc.approve(address(escrow), 8 * 1e6);
        escrow.createChallenge(taskId, winner, 8 * 1e6, 1 * 1e6);
        usdc.mint(challenger, 10 * 1e6);

        escrow.joinChallenge(taskId, challenger, block.timestamp + 1 hours, 0, bytes32(0), bytes32(0));

        vm.expectRevert("Already joined");
        escrow.joinChallenge(taskId, challenger, block.timestamp + 1 hours, 0, bytes32(0), bytes32(0));
    }

    function test_joinChallenge_reverts_no_challenge() public {
        bytes32 taskId = keccak256("nonexistent");
        vm.expectRevert("Challenge not found");
        escrow.joinChallenge(taskId, address(0x2), block.timestamp + 1 hours, 0, bytes32(0), bytes32(0));
    }
}

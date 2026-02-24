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
            uint8 cc, bool resolved,
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

        (, , , , uint8 count, ,) = escrow.challenges(taskId);
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

    function test_resolveChallenge_no_upheld() public {
        // Setup: 1 challenger, verdict = rejected
        bytes32 taskId = keccak256("task-1");
        uint256 bounty = 8 * 1e6;
        uint256 deposit = 1 * 1e6;
        address challenger = address(0x2);

        usdc.approve(address(escrow), bounty);
        escrow.createChallenge(taskId, winner, bounty, deposit);
        usdc.mint(challenger, 10 * 1e6);
        escrow.joinChallenge(taskId, challenger, block.timestamp + 1 hours, 0, bytes32(0), bytes32(0));

        // Resolve: rejected (result=1) -> 70% deposit back, 30% + serviceFee to platform
        ChallengeEscrow.Verdict[] memory verdicts = new ChallengeEscrow.Verdict[](1);
        verdicts[0] = ChallengeEscrow.Verdict(challenger, 1);

        uint256 winnerBefore = usdc.balanceOf(winner);
        uint256 platformBefore = usdc.balanceOf(platform);
        uint256 challengerBefore = usdc.balanceOf(challenger);

        escrow.resolveChallenge(taskId, winner, verdicts);

        // Winner gets bounty
        assertEq(usdc.balanceOf(winner) - winnerBefore, bounty);
        // Challenger gets 70% of deposit
        assertEq(usdc.balanceOf(challenger) - challengerBefore, deposit * 70 / 100);
        // Platform gets 30% of deposit + service fee
        uint256 platformExpected = deposit * 30 / 100 + escrow.SERVICE_FEE();
        assertEq(usdc.balanceOf(platform) - platformBefore, platformExpected);

        (, , , , , bool resolved,) = escrow.challenges(taskId);
        assertTrue(resolved);
    }

    function test_resolveChallenge_upheld() public {
        bytes32 taskId = keccak256("task-1");
        uint256 bounty = 8 * 1e6;
        uint256 deposit = 1 * 1e6;
        address challenger = address(0x2);

        usdc.approve(address(escrow), bounty);
        escrow.createChallenge(taskId, winner, bounty, deposit);
        usdc.mint(challenger, 10 * 1e6);
        escrow.joinChallenge(taskId, challenger, block.timestamp + 1 hours, 0, bytes32(0), bytes32(0));

        // Resolve: upheld (result=0) -> bounty to challenger, 100% deposit back
        ChallengeEscrow.Verdict[] memory verdicts = new ChallengeEscrow.Verdict[](1);
        verdicts[0] = ChallengeEscrow.Verdict(challenger, 0);

        uint256 challengerBefore = usdc.balanceOf(challenger);

        escrow.resolveChallenge(taskId, challenger, verdicts);

        // Challenger (now finalWinner) gets bounty + full deposit
        assertEq(usdc.balanceOf(challenger) - challengerBefore, bounty + deposit);
    }

    function test_resolveChallenge_malicious() public {
        bytes32 taskId = keccak256("task-1");
        uint256 bounty = 8 * 1e6;
        uint256 deposit = 1 * 1e6;
        address challenger = address(0x2);

        usdc.approve(address(escrow), bounty);
        escrow.createChallenge(taskId, winner, bounty, deposit);
        usdc.mint(challenger, 10 * 1e6);
        escrow.joinChallenge(taskId, challenger, block.timestamp + 1 hours, 0, bytes32(0), bytes32(0));

        // Resolve: malicious (result=2) -> 0% deposit, all to platform
        ChallengeEscrow.Verdict[] memory verdicts = new ChallengeEscrow.Verdict[](1);
        verdicts[0] = ChallengeEscrow.Verdict(challenger, 2);

        uint256 platformBefore = usdc.balanceOf(platform);
        uint256 challengerBefore = usdc.balanceOf(challenger);

        escrow.resolveChallenge(taskId, winner, verdicts);

        // Challenger gets nothing
        assertEq(usdc.balanceOf(challenger), challengerBefore);
        // Platform gets full deposit + service fee
        assertEq(usdc.balanceOf(platform) - platformBefore, deposit + escrow.SERVICE_FEE());
    }

    function test_resolveChallenge_multiple_challengers() public {
        bytes32 taskId = keccak256("task-1");
        uint256 bounty = 8 * 1e6;
        uint256 deposit = 1 * 1e6;
        address c1 = address(0x2);
        address c2 = address(0x3);

        usdc.approve(address(escrow), bounty);
        escrow.createChallenge(taskId, winner, bounty, deposit);
        usdc.mint(c1, 10 * 1e6);
        usdc.mint(c2, 10 * 1e6);
        escrow.joinChallenge(taskId, c1, block.timestamp + 1 hours, 0, bytes32(0), bytes32(0));
        escrow.joinChallenge(taskId, c2, block.timestamp + 1 hours, 0, bytes32(0), bytes32(0));

        // c1 upheld, c2 rejected. finalWinner = c1
        ChallengeEscrow.Verdict[] memory verdicts = new ChallengeEscrow.Verdict[](2);
        verdicts[0] = ChallengeEscrow.Verdict(c1, 0); // upheld
        verdicts[1] = ChallengeEscrow.Verdict(c2, 1); // rejected

        uint256 c1Before = usdc.balanceOf(c1);
        uint256 c2Before = usdc.balanceOf(c2);

        escrow.resolveChallenge(taskId, c1, verdicts);

        // c1 gets bounty + full deposit
        assertEq(usdc.balanceOf(c1) - c1Before, bounty + deposit);
        // c2 gets 70% deposit
        assertEq(usdc.balanceOf(c2) - c2Before, deposit * 70 / 100);
    }

    function test_resolveChallenge_reverts_already_resolved() public {
        bytes32 taskId = keccak256("task-1");
        address challenger = address(0x2);

        usdc.approve(address(escrow), 8 * 1e6);
        escrow.createChallenge(taskId, winner, 8 * 1e6, 1 * 1e6);
        usdc.mint(challenger, 10 * 1e6);
        escrow.joinChallenge(taskId, challenger, block.timestamp + 1 hours, 0, bytes32(0), bytes32(0));

        ChallengeEscrow.Verdict[] memory verdicts = new ChallengeEscrow.Verdict[](1);
        verdicts[0] = ChallengeEscrow.Verdict(challenger, 1);
        escrow.resolveChallenge(taskId, winner, verdicts);

        vm.expectRevert("Already resolved");
        escrow.resolveChallenge(taskId, winner, verdicts);
    }

    function test_emergencyWithdraw() public {
        bytes32 taskId = keccak256("task-1");
        uint256 bounty = 8 * 1e6;

        usdc.approve(address(escrow), bounty);
        escrow.createChallenge(taskId, winner, bounty, 1 * 1e6);

        // Warp forward 31 days
        vm.warp(block.timestamp + 31 days);

        uint256 platformBefore = usdc.balanceOf(platform);
        escrow.emergencyWithdraw(taskId);

        assertEq(usdc.balanceOf(platform) - platformBefore, bounty);
        (, , , , , bool resolved,) = escrow.challenges(taskId);
        assertTrue(resolved);
    }

    function test_emergencyWithdraw_reverts_too_early() public {
        bytes32 taskId = keccak256("task-1");
        usdc.approve(address(escrow), 8 * 1e6);
        escrow.createChallenge(taskId, winner, 8 * 1e6, 1 * 1e6);

        vm.expectRevert("Too early for emergency withdrawal");
        escrow.emergencyWithdraw(taskId);
    }
}

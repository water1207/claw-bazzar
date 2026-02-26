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
    address public arbiter1 = address(0xA1);
    address public arbiter2 = address(0xA2);

    // Default amounts: task bounty = 10 USDC
    // escrow gets 95% = 9.5 USDC, incentive = 0 (no longer used in resolve)
    uint256 constant BOUNTY = 9_500_000;     // 95% of task bounty locked in contract
    uint256 constant INCENTIVE = 0;          // kept for struct compat, unused in resolve
    uint256 constant DEPOSIT = 1 * 1e6;      // per-challenger deposit
    // Payout amounts by tier (base task bounty = 10 USDC)
    uint256 constant PAYOUT_A = 8 * 1e6;             // A-tier: 80%
    uint256 constant PAYOUT_A_CHALLENGE = 9 * 1e6;   // A-tier challenger win: 80%+10%=90%

    function setUp() public {
        platform = address(this);
        usdc = new MockUSDC();
        escrow = new ChallengeEscrow(address(usdc));
    }

    function _createChallenge(bytes32 taskId) internal {
        usdc.approve(address(escrow), BOUNTY);
        escrow.createChallenge(taskId, winner, BOUNTY, INCENTIVE, DEPOSIT);
    }

    function _joinChallenger(bytes32 taskId, address challenger) internal {
        usdc.mint(challenger, 10 * 1e6);
        escrow.joinChallenge(taskId, challenger, block.timestamp + 1 hours, 0, bytes32(0), bytes32(0));
    }

    function _noArbiters() internal pure returns (address[] memory) {
        return new address[](0);
    }

    function _singleArbiter(address a) internal pure returns (address[] memory) {
        address[] memory arr = new address[](1);
        arr[0] = a;
        return arr;
    }

    function _twoArbiters() internal view returns (address[] memory) {
        address[] memory arr = new address[](2);
        arr[0] = arbiter1;
        arr[1] = arbiter2;
        return arr;
    }

    // --- createChallenge tests ---

    function test_createChallenge() public {
        bytes32 taskId = keccak256("task-1");
        usdc.approve(address(escrow), BOUNTY);
        escrow.createChallenge(taskId, winner, BOUNTY, INCENTIVE, DEPOSIT);

        (
            address w, uint256 b, uint256 inc, uint256 d, uint256 sf,
            uint8 cc, bool resolved,
        ) = escrow.challenges(taskId);

        assertEq(w, winner);
        assertEq(b, BOUNTY);
        assertEq(inc, INCENTIVE);
        assertEq(d, DEPOSIT);
        assertEq(sf, escrow.SERVICE_FEE());
        assertEq(cc, 0);
        assertFalse(resolved);
        assertEq(usdc.balanceOf(address(escrow)), BOUNTY);
    }

    function test_createChallenge_reverts_duplicate() public {
        bytes32 taskId = keccak256("task-1");
        usdc.approve(address(escrow), BOUNTY * 2);
        escrow.createChallenge(taskId, winner, BOUNTY, INCENTIVE, DEPOSIT);

        vm.expectRevert("Challenge already exists");
        escrow.createChallenge(taskId, winner, BOUNTY, INCENTIVE, DEPOSIT);
    }

    function test_createChallenge_reverts_nonowner() public {
        bytes32 taskId = keccak256("task-1");
        vm.prank(address(0x999));
        vm.expectRevert();
        escrow.createChallenge(taskId, winner, BOUNTY, INCENTIVE, DEPOSIT);
    }

    // --- joinChallenge tests ---

    function test_joinChallenge() public {
        bytes32 taskId = keccak256("task-1");
        address challenger = address(0x2);

        _createChallenge(taskId);
        _joinChallenger(taskId, challenger);

        (, , , , , uint8 count, ,) = escrow.challenges(taskId);
        assertEq(count, 1);
        assertTrue(escrow.challengers(taskId, challenger));
        uint256 totalRequired = DEPOSIT + escrow.SERVICE_FEE();
        assertEq(usdc.balanceOf(address(escrow)), BOUNTY + totalRequired);
    }

    function test_joinChallenge_reverts_duplicate() public {
        bytes32 taskId = keccak256("task-1");
        address challenger = address(0x2);

        _createChallenge(taskId);
        _joinChallenger(taskId, challenger);

        vm.expectRevert("Already joined");
        escrow.joinChallenge(taskId, challenger, block.timestamp + 1 hours, 0, bytes32(0), bytes32(0));
    }

    // --- resolveChallenge: no challengers (empty verdicts) ---

    function test_resolve_no_challengers() public {
        bytes32 taskId = keccak256("task-1");
        _createChallenge(taskId);

        uint256 winnerBefore = usdc.balanceOf(winner);
        uint256 platformBefore = usdc.balanceOf(platform);

        ChallengeEscrow.Verdict[] memory verdicts = new ChallengeEscrow.Verdict[](0);
        escrow.resolveChallenge(taskId, winner, PAYOUT_A, verdicts, _noArbiters());

        // Winner gets 80% of original = 8 USDC (A-tier, no challenge bonus)
        assertEq(usdc.balanceOf(winner) - winnerBefore, PAYOUT_A);
        // Platform gets locked - payout = 9.5 - 8 = 1.5 USDC
        assertEq(usdc.balanceOf(platform) - platformBefore, BOUNTY - PAYOUT_A);
    }

    // --- resolveChallenge: rejected (no upheld) ---

    function test_resolve_rejected() public {
        bytes32 taskId = keccak256("task-1");
        address challenger = address(0x2);

        _createChallenge(taskId);
        _joinChallenger(taskId, challenger);

        ChallengeEscrow.Verdict[] memory verdicts = new ChallengeEscrow.Verdict[](1);
        verdicts[0] = ChallengeEscrow.Verdict(challenger, 1); // rejected

        uint256 winnerBefore = usdc.balanceOf(winner);
        uint256 platformBefore = usdc.balanceOf(platform);
        uint256 challengerBefore = usdc.balanceOf(challenger);

        escrow.resolveChallenge(taskId, winner, PAYOUT_A, verdicts, _singleArbiter(arbiter1));

        // Winner gets 80% = 8 USDC (A-tier, no challenge bonus)
        assertEq(usdc.balanceOf(winner) - winnerBefore, PAYOUT_A);
        // Challenger gets nothing (rejected: 30% to arbiter, 70% to platform)
        assertEq(usdc.balanceOf(challenger), challengerBefore);
        // Arbiter gets 30% of deposit
        uint256 arbiterShare = DEPOSIT * 30 / 100;
        assertEq(usdc.balanceOf(arbiter1), arbiterShare);
        // Platform gets: (locked - payout) + 70% deposit + service fee
        uint256 remaining = DEPOSIT - arbiterShare;
        uint256 platformExpected = (BOUNTY - PAYOUT_A) + remaining + escrow.SERVICE_FEE();
        assertEq(usdc.balanceOf(platform) - platformBefore, platformExpected);
    }

    // --- resolveChallenge: upheld (challenger wins) ---

    function test_resolve_upheld() public {
        bytes32 taskId = keccak256("task-1");
        address challenger = address(0x2);

        _createChallenge(taskId);
        _joinChallenger(taskId, challenger);

        ChallengeEscrow.Verdict[] memory verdicts = new ChallengeEscrow.Verdict[](1);
        verdicts[0] = ChallengeEscrow.Verdict(challenger, 0); // upheld

        uint256 challengerBefore = usdc.balanceOf(challenger);

        // Challenger is the finalWinner (A-tier + 10% challenge bonus = 90%)
        escrow.resolveChallenge(taskId, challenger, PAYOUT_A_CHALLENGE, verdicts, _singleArbiter(arbiter1));

        // Challenger gets 90% = 9 USDC + 70% deposit back
        uint256 arbiterShare = DEPOSIT * 30 / 100;
        uint256 depositBack = DEPOSIT - arbiterShare;
        assertEq(usdc.balanceOf(challenger) - challengerBefore, PAYOUT_A_CHALLENGE + depositBack);
        // Arbiter gets 30% of deposit
        assertEq(usdc.balanceOf(arbiter1), arbiterShare);
    }

    // --- resolveChallenge: malicious ---

    function test_resolve_malicious() public {
        bytes32 taskId = keccak256("task-1");
        address challenger = address(0x2);

        _createChallenge(taskId);
        _joinChallenger(taskId, challenger);

        ChallengeEscrow.Verdict[] memory verdicts = new ChallengeEscrow.Verdict[](1);
        verdicts[0] = ChallengeEscrow.Verdict(challenger, 2); // malicious

        uint256 platformBefore = usdc.balanceOf(platform);
        uint256 challengerBefore = usdc.balanceOf(challenger);

        escrow.resolveChallenge(taskId, winner, PAYOUT_A, verdicts, _singleArbiter(arbiter1));

        // Challenger gets nothing
        assertEq(usdc.balanceOf(challenger), challengerBefore);
        // Arbiter gets 30% of deposit
        uint256 arbiterShare = DEPOSIT * 30 / 100;
        assertEq(usdc.balanceOf(arbiter1), arbiterShare);
        // Platform gets: (locked - payout) + 70% deposit + service fee
        uint256 remaining = DEPOSIT - arbiterShare;
        assertEq(usdc.balanceOf(platform) - platformBefore, (BOUNTY - PAYOUT_A) + remaining + escrow.SERVICE_FEE());
    }

    // --- resolveChallenge: multiple challengers, mixed verdicts ---

    function test_resolve_multiple_challengers() public {
        bytes32 taskId = keccak256("task-1");
        address c1 = address(0x2);
        address c2 = address(0x3);

        _createChallenge(taskId);
        _joinChallenger(taskId, c1);
        _joinChallenger(taskId, c2);

        // c1 upheld, c2 rejected. finalWinner = c1
        ChallengeEscrow.Verdict[] memory verdicts = new ChallengeEscrow.Verdict[](2);
        verdicts[0] = ChallengeEscrow.Verdict(c1, 0); // upheld
        verdicts[1] = ChallengeEscrow.Verdict(c2, 1); // rejected

        uint256 c1Before = usdc.balanceOf(c1);
        uint256 c2Before = usdc.balanceOf(c2);

        escrow.resolveChallenge(taskId, c1, PAYOUT_A_CHALLENGE, verdicts, _singleArbiter(arbiter1));

        uint256 arbiterSharePer = DEPOSIT * 30 / 100;

        // c1 (finalWinner): gets 90% (A-tier + 10% bonus) + 70% deposit
        assertEq(usdc.balanceOf(c1) - c1Before, PAYOUT_A_CHALLENGE + (DEPOSIT - arbiterSharePer));
        // c2 (rejected): gets nothing
        assertEq(usdc.balanceOf(c2), c2Before);
        // Arbiter gets 30% * 2 deposits
        assertEq(usdc.balanceOf(arbiter1), arbiterSharePer * 2);
    }

    // --- resolveChallenge: arbiter reward split ---

    function test_resolve_arbiter_split() public {
        bytes32 taskId = keccak256("task-1");
        address challenger = address(0x2);

        _createChallenge(taskId);
        _joinChallenger(taskId, challenger);

        ChallengeEscrow.Verdict[] memory verdicts = new ChallengeEscrow.Verdict[](1);
        verdicts[0] = ChallengeEscrow.Verdict(challenger, 1); // rejected

        escrow.resolveChallenge(taskId, winner, PAYOUT_A, verdicts, _twoArbiters());

        uint256 arbiterTotal = DEPOSIT * 30 / 100;
        uint256 perArbiter = arbiterTotal / 2;
        assertEq(usdc.balanceOf(arbiter1), perArbiter);
        assertEq(usdc.balanceOf(arbiter2), perArbiter);
    }

    // --- resolveChallenge: no arbiters → pool to platform ---

    function test_resolve_no_arbiters_pool_to_platform() public {
        bytes32 taskId = keccak256("task-1");
        address challenger = address(0x2);

        _createChallenge(taskId);
        _joinChallenger(taskId, challenger);

        ChallengeEscrow.Verdict[] memory verdicts = new ChallengeEscrow.Verdict[](1);
        verdicts[0] = ChallengeEscrow.Verdict(challenger, 1); // rejected

        uint256 platformBefore = usdc.balanceOf(platform);

        escrow.resolveChallenge(taskId, winner, PAYOUT_A, verdicts, _noArbiters());

        // Platform gets: (locked - payout) + full deposit (no arbiters) + service fee
        uint256 platformExpected = (BOUNTY - PAYOUT_A) + DEPOSIT + escrow.SERVICE_FEE();
        assertEq(usdc.balanceOf(platform) - platformBefore, platformExpected);
    }

    // --- double resolve reverts ---

    function test_resolve_reverts_already_resolved() public {
        bytes32 taskId = keccak256("task-1");
        address challenger = address(0x2);

        _createChallenge(taskId);
        _joinChallenger(taskId, challenger);

        ChallengeEscrow.Verdict[] memory verdicts = new ChallengeEscrow.Verdict[](1);
        verdicts[0] = ChallengeEscrow.Verdict(challenger, 1);
        escrow.resolveChallenge(taskId, winner, PAYOUT_A, verdicts, _noArbiters());

        vm.expectRevert("Already resolved");
        escrow.resolveChallenge(taskId, winner, PAYOUT_A, verdicts, _noArbiters());
    }

    // --- resolveChallenge: winnerPayout exceeds bounty ---

    function test_resolve_reverts_payout_exceeds_bounty() public {
        bytes32 taskId = keccak256("task-1");
        _createChallenge(taskId);

        ChallengeEscrow.Verdict[] memory verdicts = new ChallengeEscrow.Verdict[](0);
        vm.expectRevert("Payout exceeds bounty");
        escrow.resolveChallenge(taskId, winner, BOUNTY + 1, verdicts, _noArbiters());
    }

    // --- resolveChallenge: dynamic tier split (B-tier winner gets 75%) ---

    function test_resolve_dynamic_tier_split() public {
        bytes32 taskId = keccak256("task-1");
        _createChallenge(taskId);

        uint256 winnerBefore = usdc.balanceOf(winner);
        uint256 platformBefore = usdc.balanceOf(platform);

        // B-tier winner: 75% of 10 USDC = 7.5 USDC
        uint256 bTierPayout = 7_500_000;
        ChallengeEscrow.Verdict[] memory verdicts = new ChallengeEscrow.Verdict[](0);
        escrow.resolveChallenge(taskId, winner, bTierPayout, verdicts, _noArbiters());

        assertEq(usdc.balanceOf(winner) - winnerBefore, bTierPayout);
        // Platform gets locked - payout = 9.5 - 7.5 = 2.0 USDC
        assertEq(usdc.balanceOf(platform) - platformBefore, BOUNTY - bTierPayout);
    }

    // --- emergencyWithdraw ---

    function test_emergencyWithdraw() public {
        bytes32 taskId = keccak256("task-1");
        _createChallenge(taskId);

        vm.warp(block.timestamp + 31 days);

        uint256 platformBefore = usdc.balanceOf(platform);
        escrow.emergencyWithdraw(taskId);

        assertEq(usdc.balanceOf(platform) - platformBefore, BOUNTY);
        (, , , , , , bool resolved,) = escrow.challenges(taskId);
        assertTrue(resolved);
    }

    function test_emergencyWithdraw_reverts_too_early() public {
        bytes32 taskId = keccak256("task-1");
        _createChallenge(taskId);

        vm.expectRevert("Too early for emergency withdrawal");
        escrow.emergencyWithdraw(taskId);
    }
}

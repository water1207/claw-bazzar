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
    uint256 constant TASK_BOUNTY = 10 * 1e6;
    uint256 constant BOUNTY = 9_500_000;     // 95% locked
    uint256 constant INCENTIVE = 500_000;    // 5% incentive
    uint256 constant DEPOSIT = 1 * 1e6;
    uint256 constant PAYOUT_A = 8 * 1e6;    // A-tier: 80%

    function setUp() public {
        platform = address(this);
        usdc = new MockUSDC();
        escrow = new ChallengeEscrow(address(usdc));
    }

    function _createChallenge(bytes32 taskId) internal {
        usdc.approve(address(escrow), BOUNTY);
        escrow.createChallenge(taskId, winner, BOUNTY, INCENTIVE);
    }

    function _joinChallenger(bytes32 taskId, address challenger) internal {
        _joinChallengerWithDeposit(taskId, challenger, DEPOSIT);
    }

    function _joinChallengerWithDeposit(bytes32 taskId, address challenger, uint256 deposit) internal {
        usdc.mint(challenger, 10 * 1e6);
        escrow.joinChallenge(taskId, challenger, deposit, block.timestamp + 1 hours, 0, bytes32(0), bytes32(0));
    }

    function _refund(address challenger, bool doRefund)
        internal pure returns (ChallengeEscrow.ChallengerRefund memory)
    {
        return ChallengeEscrow.ChallengerRefund(challenger, doRefund);
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

    function _noArbitersArr() internal pure returns (address[] memory) {
        return new address[](0);
    }

    function _noRefunds() internal pure returns (ChallengeEscrow.ChallengerRefund[] memory) {
        return new ChallengeEscrow.ChallengerRefund[](0);
    }

    // --- createChallenge tests ---

    function test_createChallenge() public {
        bytes32 taskId = keccak256("task-1");
        usdc.approve(address(escrow), BOUNTY);
        escrow.createChallenge(taskId, winner, BOUNTY, INCENTIVE);

        (
            address w, uint256 b, uint256 inc, uint256 sf,
            uint8 cc, bool resolved, , uint256 td
        ) = escrow.challenges(taskId);

        assertEq(w, winner);
        assertEq(b, BOUNTY);
        assertEq(inc, INCENTIVE);
        assertEq(sf, escrow.SERVICE_FEE());
        assertEq(cc, 0);
        assertFalse(resolved);
        assertEq(td, 0);
        assertEq(usdc.balanceOf(address(escrow)), BOUNTY);
    }

    function test_createChallenge_reverts_duplicate() public {
        bytes32 taskId = keccak256("task-1");
        usdc.approve(address(escrow), BOUNTY * 2);
        escrow.createChallenge(taskId, winner, BOUNTY, INCENTIVE);

        vm.expectRevert("Challenge already exists");
        escrow.createChallenge(taskId, winner, BOUNTY, INCENTIVE);
    }

    function test_createChallenge_reverts_nonowner() public {
        bytes32 taskId = keccak256("task-1");
        vm.prank(address(0x999));
        vm.expectRevert();
        escrow.createChallenge(taskId, winner, BOUNTY, INCENTIVE);
    }

    // --- joinChallenge tests ---

    function test_joinChallenge() public {
        bytes32 taskId = keccak256("task-1");
        address challenger = address(0x2);

        _createChallenge(taskId);
        _joinChallenger(taskId, challenger);

        (, , , , uint8 count, , ,) = escrow.challenges(taskId);
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
        escrow.joinChallenge(taskId, challenger, DEPOSIT, block.timestamp + 1 hours, 0, bytes32(0), bytes32(0));
    }

    // --- resolveChallenge: no challengers ---

    function test_resolve_no_challengers() public {
        bytes32 taskId = keccak256("task-1");
        _createChallenge(taskId);

        uint256 winnerBefore = usdc.balanceOf(winner);
        uint256 platformBefore = usdc.balanceOf(platform);

        // No challengers: empty refunds, no arbiters, no arbiter reward
        escrow.resolveChallenge(taskId, winner, PAYOUT_A, _noRefunds(), _noArbitersArr(), 0);

        // Winner gets 80% of original = 8 USDC (A-tier)
        assertEq(usdc.balanceOf(winner) - winnerBefore, PAYOUT_A);
        // Platform gets locked - payout = 9.5 - 8 = 1.5 USDC
        assertEq(usdc.balanceOf(platform) - platformBefore, BOUNTY - PAYOUT_A);
    }

    // --- resolveChallenge: PW maintained, 1 rejected challenger (pool model) ---

    function test_resolve_pw_maintained_one_rejected() public {
        bytes32 taskId = keccak256("task-1");
        address challenger = address(0x2);

        _createChallenge(taskId);
        _joinChallenger(taskId, challenger);

        // Refund: challenger forfeited (refund=false)
        ChallengeEscrow.ChallengerRefund[] memory refunds = new ChallengeEscrow.ChallengerRefund[](1);
        refunds[0] = _refund(challenger, false);

        uint256 winnerBefore = usdc.balanceOf(winner);
        uint256 platformBefore = usdc.balanceOf(platform);
        uint256 challengerBefore = usdc.balanceOf(challenger);

        // Arbiter reward = DEPOSIT * 30% = 300_000
        uint256 arbiterReward = DEPOSIT * 30 / 100;

        escrow.resolveChallenge(taskId, winner, PAYOUT_A, refunds, _singleArbiter(arbiter1), arbiterReward);

        // Arbiter gets 30% of deposit
        assertEq(usdc.balanceOf(arbiter1), arbiterReward);
        // Challenger gets nothing (forfeited)
        assertEq(usdc.balanceOf(challenger), challengerBefore);
        // Winner gets payout
        assertEq(usdc.balanceOf(winner) - winnerBefore, PAYOUT_A);
        // Platform gets everything remaining
        uint256 totalFunds = BOUNTY + DEPOSIT + escrow.SERVICE_FEE();
        uint256 totalSent = PAYOUT_A + arbiterReward;
        assertEq(usdc.balanceOf(platform) - platformBefore, totalFunds - totalSent);
    }

    // --- resolveChallenge: challenger wins (upheld), deposit refunded ---

    function test_resolve_challenger_wins() public {
        bytes32 taskId = keccak256("task-1");
        address challenger = address(0x2);

        _createChallenge(taskId);
        _joinChallenger(taskId, challenger);

        // Upheld: challenger deposit refunded
        ChallengeEscrow.ChallengerRefund[] memory refunds = new ChallengeEscrow.ChallengerRefund[](1);
        refunds[0] = _refund(challenger, true);

        uint256 challengerBefore = usdc.balanceOf(challenger);
        uint256 winnerBefore = usdc.balanceOf(winner);
        uint256 platformBefore = usdc.balanceOf(platform);

        // Backend calculates: arbiterReward = upheld_deposit * 30% = 300_000 (from incentive)
        // winnerPayout = bounty*rate + incentive_remainder
        uint256 arbiterReward = DEPOSIT * 30 / 100;  // 300_000
        uint256 winnerPayout = PAYOUT_A;  // 8_000_000

        escrow.resolveChallenge(taskId, challenger, winnerPayout, refunds, _singleArbiter(arbiter1), arbiterReward);

        // Challenger: deposit refunded
        assertEq(usdc.balanceOf(challenger) - challengerBefore, DEPOSIT + winnerPayout);
        // Arbiter reward
        assertEq(usdc.balanceOf(arbiter1), arbiterReward);
        // Winner (original PW) gets nothing (finalWinner is challenger)
        assertEq(usdc.balanceOf(winner), winnerBefore);
        // Platform gets remainder
        uint256 totalFunds = BOUNTY + DEPOSIT + escrow.SERVICE_FEE();
        uint256 totalSent = DEPOSIT + winnerPayout + arbiterReward;
        assertEq(usdc.balanceOf(platform) - platformBefore, totalFunds - totalSent);
    }

    // --- resolveChallenge: 1 upheld + 1 rejected (mixed pool) ---

    function test_resolve_upheld_plus_rejected() public {
        bytes32 taskId = keccak256("task-1");
        address c1 = address(0x2); // upheld
        address c2 = address(0x3); // rejected

        _createChallenge(taskId);
        _joinChallenger(taskId, c1);
        _joinChallenger(taskId, c2);

        ChallengeEscrow.ChallengerRefund[] memory refunds = new ChallengeEscrow.ChallengerRefund[](2);
        refunds[0] = _refund(c1, true);   // upheld → refund
        refunds[1] = _refund(c2, false);  // rejected → forfeit

        uint256 c1Before = usdc.balanceOf(c1);
        uint256 c2Before = usdc.balanceOf(c2);
        uint256 platformBefore = usdc.balanceOf(platform);

        // Arbiter reward = pool(30%) + incentive(30% of upheld deposit)
        // = DEPOSIT*30% + DEPOSIT*30% = 600_000
        uint256 arbiterReward = (DEPOSIT * 30 / 100) * 2;
        uint256 winnerPayout = PAYOUT_A;

        escrow.resolveChallenge(taskId, c1, winnerPayout, refunds, _twoArbiters(), arbiterReward);

        // c1 (upheld): deposit refund + winner payout
        assertEq(usdc.balanceOf(c1) - c1Before, DEPOSIT + winnerPayout);
        // c2 (rejected): nothing
        assertEq(usdc.balanceOf(c2), c2Before);
        // Arbiters split reward equally
        uint256 perArbiter = arbiterReward / 2;
        assertEq(usdc.balanceOf(arbiter1), perArbiter);
        assertEq(usdc.balanceOf(arbiter2), perArbiter);
        // Platform gets remainder
        uint256 totalFunds = BOUNTY + DEPOSIT * 2 + escrow.SERVICE_FEE() * 2;
        uint256 totalSent = DEPOSIT + winnerPayout + arbiterReward;
        assertEq(usdc.balanceOf(platform) - platformBefore, totalFunds - totalSent);
    }

    // --- resolveChallenge: 2 rejected, no upheld (PW maintained) ---

    function test_resolve_two_rejected_pw_maintained() public {
        bytes32 taskId = keccak256("task-1");
        address c1 = address(0x2);
        address c2 = address(0x3);

        _createChallenge(taskId);
        _joinChallenger(taskId, c1);
        _joinChallenger(taskId, c2);

        ChallengeEscrow.ChallengerRefund[] memory refunds = new ChallengeEscrow.ChallengerRefund[](2);
        refunds[0] = _refund(c1, false);
        refunds[1] = _refund(c2, false);

        uint256 winnerBefore = usdc.balanceOf(winner);
        uint256 platformBefore = usdc.balanceOf(platform);

        // Both deposits forfeited → pool = 2 USDC, arbiterReward = 2*30% = 600_000
        uint256 arbiterReward = DEPOSIT * 2 * 30 / 100;

        escrow.resolveChallenge(taskId, winner, PAYOUT_A, refunds, _twoArbiters(), arbiterReward);

        // Arbiters split reward
        uint256 perArbiter = arbiterReward / 2;
        assertEq(usdc.balanceOf(arbiter1), perArbiter);
        assertEq(usdc.balanceOf(arbiter2), perArbiter);
        // Winner gets payout
        assertEq(usdc.balanceOf(winner) - winnerBefore, PAYOUT_A);
        // Platform gets remainder (70% of pool + service fees + platform fee)
        uint256 totalFunds = BOUNTY + DEPOSIT * 2 + escrow.SERVICE_FEE() * 2;
        uint256 totalSent = PAYOUT_A + arbiterReward;
        assertEq(usdc.balanceOf(platform) - platformBefore, totalFunds - totalSent);
    }

    // --- resolveChallenge: dynamic deposits (different deposit amounts) ---

    function test_resolve_dynamic_deposits() public {
        bytes32 taskId = keccak256("task-dyn");
        address c1 = address(0x2); // B-tier: dep=1.5 USDC, upheld
        address c2 = address(0x3); // A-tier: dep=0.5 USDC, rejected

        uint256 dep1 = 1_500_000;  // 1.5 USDC
        uint256 dep2 = 500_000;    // 0.5 USDC

        _createChallenge(taskId);
        _joinChallengerWithDeposit(taskId, c1, dep1);
        _joinChallengerWithDeposit(taskId, c2, dep2);

        ChallengeEscrow.ChallengerRefund[] memory refunds = new ChallengeEscrow.ChallengerRefund[](2);
        refunds[0] = _refund(c1, true);   // upheld
        refunds[1] = _refund(c2, false);  // rejected

        uint256 c1Before = usdc.balanceOf(c1);
        uint256 c2Before = usdc.balanceOf(c2);
        uint256 platformBefore = usdc.balanceOf(platform);

        // arbiterReward = losing pool 30% + upheld incentive 30%
        // = dep2*30% + dep1*30% = 150_000 + 450_000 = 600_000
        uint256 arbiterReward = dep2 * 30 / 100 + dep1 * 30 / 100;

        escrow.resolveChallenge(taskId, c1, PAYOUT_A, refunds, _singleArbiter(arbiter1), arbiterReward);

        // c1 (upheld): deposit refund + payout
        assertEq(usdc.balanceOf(c1) - c1Before, dep1 + PAYOUT_A);
        // c2 (rejected): nothing
        assertEq(usdc.balanceOf(c2), c2Before);
        // Arbiter reward
        assertEq(usdc.balanceOf(arbiter1), arbiterReward);
        // Platform: totalFunds - totalSent
        uint256 totalFunds = BOUNTY + dep1 + dep2 + escrow.SERVICE_FEE() * 2;
        uint256 totalSent = dep1 + PAYOUT_A + arbiterReward;
        assertEq(usdc.balanceOf(platform) - platformBefore, totalFunds - totalSent);
    }

    // --- resolveChallenge: B-tier winner gets 75% payout ---

    function test_resolve_dynamic_tier_split() public {
        bytes32 taskId = keccak256("task-1");
        _createChallenge(taskId);

        uint256 winnerBefore = usdc.balanceOf(winner);
        uint256 platformBefore = usdc.balanceOf(platform);

        // B-tier winner: 75% of 10 USDC = 7.5 USDC
        uint256 bTierPayout = 7_500_000;
        escrow.resolveChallenge(taskId, winner, bTierPayout, _noRefunds(), _noArbitersArr(), 0);

        assertEq(usdc.balanceOf(winner) - winnerBefore, bTierPayout);
        // Platform gets locked - payout = 9.5 - 7.5 = 2.0 USDC
        assertEq(usdc.balanceOf(platform) - platformBefore, BOUNTY - bTierPayout);
    }

    // --- resolveChallenge: double resolve reverts ---

    function test_resolve_reverts_already_resolved() public {
        bytes32 taskId = keccak256("task-1");
        _createChallenge(taskId);

        escrow.resolveChallenge(taskId, winner, PAYOUT_A, _noRefunds(), _noArbitersArr(), 0);

        vm.expectRevert("Already resolved");
        escrow.resolveChallenge(taskId, winner, PAYOUT_A, _noRefunds(), _noArbitersArr(), 0);
    }

    // --- resolveChallenge: reverts for non-owner ---

    function test_resolve_reverts_nonowner() public {
        bytes32 taskId = keccak256("task-1");
        _createChallenge(taskId);

        vm.prank(address(0x999));
        vm.expectRevert();
        escrow.resolveChallenge(taskId, winner, PAYOUT_A, _noRefunds(), _noArbitersArr(), 0);
    }

    // --- resolveChallenge: deadlock (all forfeited, all arbiters paid) ---

    function test_resolve_deadlock_all_arbiters() public {
        bytes32 taskId = keccak256("task-dl");
        address c1 = address(0x2);
        address c2 = address(0x3);

        _createChallenge(taskId);
        _joinChallenger(taskId, c1);
        _joinChallenger(taskId, c2);

        // Deadlock: PW maintained, all challengers forfeited, all 2 arbiters paid
        ChallengeEscrow.ChallengerRefund[] memory refunds = new ChallengeEscrow.ChallengerRefund[](2);
        refunds[0] = _refund(c1, false);
        refunds[1] = _refund(c2, false);

        // arbiterReward = pool 30% = 2*DEPOSIT*30% = 600_000
        uint256 arbiterReward = DEPOSIT * 2 * 30 / 100;

        escrow.resolveChallenge(taskId, winner, PAYOUT_A, refunds, _twoArbiters(), arbiterReward);

        // Both arbiters get equal share
        assertEq(usdc.balanceOf(arbiter1), arbiterReward / 2);
        assertEq(usdc.balanceOf(arbiter2), arbiterReward / 2);

        (, , , , , bool resolved, ,) = escrow.challenges(taskId);
        assertTrue(resolved);
    }

    // --- resolveChallenge: single winner, no losers (pool=0, arbiter from incentive) ---

    function test_resolve_single_winner_no_losers() public {
        bytes32 taskId = keccak256("task-sw");
        address challenger = address(0x2);

        _createChallenge(taskId);
        _joinChallenger(taskId, challenger);

        // Single challenger wins, no losers → pool=0
        ChallengeEscrow.ChallengerRefund[] memory refunds = new ChallengeEscrow.ChallengerRefund[](1);
        refunds[0] = _refund(challenger, true);

        uint256 challengerBefore = usdc.balanceOf(challenger);

        // arbiterReward = upheld_deposit * 30% from incentive = 300_000
        uint256 arbiterReward = DEPOSIT * 30 / 100;

        escrow.resolveChallenge(taskId, challenger, PAYOUT_A, refunds, _singleArbiter(arbiter1), arbiterReward);

        // Challenger: deposit refund + payout
        assertEq(usdc.balanceOf(challenger) - challengerBefore, DEPOSIT + PAYOUT_A);
        // Arbiter gets reward from incentive
        assertEq(usdc.balanceOf(arbiter1), arbiterReward);
    }

    // --- emergencyWithdraw ---

    function test_emergencyWithdraw() public {
        bytes32 taskId = keccak256("task-1");
        _createChallenge(taskId);

        vm.warp(block.timestamp + 31 days);

        uint256 platformBefore = usdc.balanceOf(platform);
        escrow.emergencyWithdraw(taskId);

        assertEq(usdc.balanceOf(platform) - platformBefore, BOUNTY);
        (, , , , , bool resolved, ,) = escrow.challenges(taskId);
        assertTrue(resolved);
    }

    function test_emergencyWithdraw_reverts_too_early() public {
        bytes32 taskId = keccak256("task-1");
        _createChallenge(taskId);

        vm.expectRevert("Too early for emergency withdrawal");
        escrow.emergencyWithdraw(taskId);
    }

    function test_emergency_with_dynamic_deposits() public {
        bytes32 taskId = keccak256("task-emg-dyn");
        address c1 = address(0x2);
        address c2 = address(0x3);

        uint256 dep1 = 500_000;
        uint256 dep2 = 3_000_000;

        _createChallenge(taskId);
        _joinChallengerWithDeposit(taskId, c1, dep1);
        _joinChallengerWithDeposit(taskId, c2, dep2);

        vm.warp(block.timestamp + 31 days);

        uint256 platformBefore = usdc.balanceOf(platform);
        escrow.emergencyWithdraw(taskId);

        // Platform gets: bounty + totalDeposits + serviceFee * 2
        uint256 expected = BOUNTY + dep1 + dep2 + escrow.SERVICE_FEE() * 2;
        assertEq(usdc.balanceOf(platform) - platformBefore, expected);
    }

    // --- challengerList tests ---

    function test_challengerList_populated() public {
        bytes32 taskId = keccak256("task-list");
        address c1 = address(0x2);
        address c2 = address(0x3);

        _createChallenge(taskId);
        _joinChallenger(taskId, c1);
        _joinChallenger(taskId, c2);

        assertEq(escrow.challengerList(taskId, 0), c1);
        assertEq(escrow.challengerList(taskId, 1), c2);
    }

    // --- voidChallenge: all challengers refunded (happy path) ---

    function test_voidChallenge_all_refunded() public {
        bytes32 taskId = keccak256("task-void-1");
        address publisher = address(0xBB);
        address c1 = address(0x2);
        address c2 = address(0x3);

        _createChallenge(taskId);
        _joinChallenger(taskId, c1);
        _joinChallenger(taskId, c2);

        ChallengeEscrow.ChallengerRefund[] memory refunds = new ChallengeEscrow.ChallengerRefund[](2);
        refunds[0] = ChallengeEscrow.ChallengerRefund(c1, true);
        refunds[1] = ChallengeEscrow.ChallengerRefund(c2, true);

        uint256 c1Before = usdc.balanceOf(c1);
        uint256 c2Before = usdc.balanceOf(c2);
        uint256 publisherBefore = usdc.balanceOf(publisher);
        uint256 platformBefore = usdc.balanceOf(platform);

        escrow.voidChallenge(taskId, publisher, BOUNTY, refunds, _twoArbiters(), 0);

        // Both challengers get full deposit refund
        assertEq(usdc.balanceOf(c1) - c1Before, DEPOSIT);
        assertEq(usdc.balanceOf(c2) - c2Before, DEPOSIT);
        // Publisher gets bounty refund
        assertEq(usdc.balanceOf(publisher) - publisherBefore, BOUNTY);
        // Arbiters get nothing (arbiterReward=0, no malicious forfeit bonus)
        assertEq(usdc.balanceOf(arbiter1), 0);
        assertEq(usdc.balanceOf(arbiter2), 0);
        // Platform gets service fees only
        assertEq(
            usdc.balanceOf(platform) - platformBefore,
            BOUNTY + DEPOSIT * 2 + escrow.SERVICE_FEE() * 2 - BOUNTY - DEPOSIT * 2
        );
    }

    // --- voidChallenge: mixed refund/forfeit ---

    function test_voidChallenge_mixed_refund_forfeit() public {
        bytes32 taskId = keccak256("task-void-2");
        address publisher = address(0xBB);
        address c1 = address(0x2); // justified - refund
        address c2 = address(0x3); // malicious - forfeit

        _createChallenge(taskId);
        _joinChallenger(taskId, c1);
        _joinChallenger(taskId, c2);

        ChallengeEscrow.ChallengerRefund[] memory refunds = new ChallengeEscrow.ChallengerRefund[](2);
        refunds[0] = ChallengeEscrow.ChallengerRefund(c1, true);   // refund
        refunds[1] = ChallengeEscrow.ChallengerRefund(c2, false);  // forfeit (malicious)

        uint256 c1Before = usdc.balanceOf(c1);
        uint256 c2Before = usdc.balanceOf(c2);
        uint256 publisherBefore = usdc.balanceOf(publisher);
        uint256 platformBefore = usdc.balanceOf(platform);

        // arbiterReward = 500_000 (0.5 USDC base reward)
        escrow.voidChallenge(taskId, publisher, BOUNTY, refunds, _twoArbiters(), 500_000);

        // c1 (justified): gets full deposit refund
        assertEq(usdc.balanceOf(c1) - c1Before, DEPOSIT);
        // c2 (malicious): gets nothing
        assertEq(usdc.balanceOf(c2), c2Before);
        // Publisher gets bounty refund
        assertEq(usdc.balanceOf(publisher) - publisherBefore, BOUNTY);

        // Arbiters: base 500_000 + 30% of c2's deposit 300_000 = 800_000 / 2 = 400_000 each
        uint256 perArbiter = (500_000 + DEPOSIT * 30 / 100) / 2;
        assertEq(usdc.balanceOf(arbiter1), perArbiter);
        assertEq(usdc.balanceOf(arbiter2), perArbiter);

        // Platform gets remainder
        uint256 totalFunds = BOUNTY + DEPOSIT * 2 + escrow.SERVICE_FEE() * 2;
        uint256 totalSent = BOUNTY + DEPOSIT + perArbiter * 2;
        assertEq(usdc.balanceOf(platform) - platformBefore, totalFunds - totalSent);
    }

    // --- voidChallenge: reverts if already resolved ---

    function test_voidChallenge_reverts_already_resolved() public {
        bytes32 taskId = keccak256("task-void-3");
        address publisher = address(0xBB);

        _createChallenge(taskId);

        ChallengeEscrow.ChallengerRefund[] memory refunds = new ChallengeEscrow.ChallengerRefund[](0);
        address[] memory arbiters = new address[](0);

        // First void succeeds
        escrow.voidChallenge(taskId, publisher, BOUNTY, refunds, arbiters, 0);

        // Second void reverts
        vm.expectRevert("Already resolved");
        escrow.voidChallenge(taskId, publisher, BOUNTY, refunds, arbiters, 0);
    }

    // --- voidChallenge: reverts for non-owner ---

    function test_voidChallenge_reverts_nonowner() public {
        bytes32 taskId = keccak256("task-void-4");
        _createChallenge(taskId);

        ChallengeEscrow.ChallengerRefund[] memory refunds = new ChallengeEscrow.ChallengerRefund[](0);
        address[] memory arbiters = new address[](0);

        vm.prank(address(0x999));
        vm.expectRevert();
        escrow.voidChallenge(taskId, address(0xBB), BOUNTY, refunds, arbiters, 0);
    }
}

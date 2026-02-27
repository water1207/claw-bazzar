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
    uint256 constant INCENTIVE = 1_000_000;  // 10% incentive (was 0 in V1)
    uint256 constant DEPOSIT = 1 * 1e6;
    uint256 constant PAYOUT_A = 8 * 1e6;             // A-tier: 80%
    uint256 constant PAYOUT_A_CHALLENGE = 8_500_000;  // A-tier challenger: min(90%, mainBounty=85%)=85%

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

    function _verdict(address challenger, uint8 result, address[] memory arbiters)
        internal pure returns (ChallengeEscrow.Verdict memory)
    {
        return ChallengeEscrow.Verdict(challenger, result, arbiters);
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

    // --- resolveChallenge: no challengers (empty verdicts) ---

    function test_resolve_no_challengers() public {
        bytes32 taskId = keccak256("task-1");
        _createChallenge(taskId);

        uint256 winnerBefore = usdc.balanceOf(winner);
        uint256 platformBefore = usdc.balanceOf(platform);

        ChallengeEscrow.Verdict[] memory verdicts = new ChallengeEscrow.Verdict[](0);
        escrow.resolveChallenge(taskId, winner, PAYOUT_A, verdicts);

        // Winner gets 80% of original = 8 USDC (A-tier, no challenge bonus)
        assertEq(usdc.balanceOf(winner) - winnerBefore, PAYOUT_A);
        // Platform gets locked - payout = 9.5 - 8 = 1.5 USDC
        assertEq(usdc.balanceOf(platform) - platformBefore, BOUNTY - PAYOUT_A);
    }

    // --- resolveChallenge: rejected (no upheld) --- winner gets 10% compensation ---

    function test_resolve_rejected_no_upheld() public {
        bytes32 taskId = keccak256("task-1");
        address challenger = address(0x2);

        _createChallenge(taskId);
        _joinChallenger(taskId, challenger);

        ChallengeEscrow.Verdict[] memory verdicts = new ChallengeEscrow.Verdict[](1);
        verdicts[0] = _verdict(challenger, 1, _singleArbiter(arbiter1)); // rejected

        uint256 winnerBefore = usdc.balanceOf(winner);
        uint256 platformBefore = usdc.balanceOf(platform);
        uint256 challengerBefore = usdc.balanceOf(challenger);

        escrow.resolveChallenge(taskId, winner, PAYOUT_A, verdicts);

        // Arbiter gets 30% of deposit = 300_000
        uint256 arbiterShare = DEPOSIT * 30 / 100;
        assertEq(usdc.balanceOf(arbiter1), arbiterShare);
        // Challenger gets nothing (rejected)
        assertEq(usdc.balanceOf(challenger), challengerBefore);
        // Winner gets payout + 10% deposit compensation = 8_000_000 + 100_000
        uint256 winnerComp = DEPOSIT * 10 / 100;
        assertEq(usdc.balanceOf(winner) - winnerBefore, PAYOUT_A + winnerComp);
        // Platform gets everything remaining
        // totalFunds = BOUNTY + DEPOSIT + SERVICE_FEE = 9_500_000 + 1_000_000 + 10_000
        // totalSent = PAYOUT_A + arbiterShare + winnerComp = 8_000_000 + 300_000 + 100_000
        uint256 totalFunds = BOUNTY + DEPOSIT + escrow.SERVICE_FEE();
        uint256 totalSent = PAYOUT_A + arbiterShare + winnerComp;
        assertEq(usdc.balanceOf(platform) - platformBefore, totalFunds - totalSent);
    }

    // --- resolveChallenge: upheld --- 100% deposit refund, arbiter from incentive ---

    function test_resolve_upheld() public {
        bytes32 taskId = keccak256("task-1");
        address challenger = address(0x2);

        _createChallenge(taskId);
        _joinChallenger(taskId, challenger);

        ChallengeEscrow.Verdict[] memory verdicts = new ChallengeEscrow.Verdict[](1);
        verdicts[0] = _verdict(challenger, 0, _singleArbiter(arbiter1)); // upheld

        uint256 challengerBefore = usdc.balanceOf(challenger);
        uint256 winnerBefore = usdc.balanceOf(winner);
        uint256 platformBefore = usdc.balanceOf(platform);

        // finalWinner = winner (original), winnerPayout = PAYOUT_A_CHALLENGE (85% of task bounty, capped at mainBounty)
        escrow.resolveChallenge(taskId, winner, PAYOUT_A_CHALLENGE, verdicts);

        // Challenger gets 100% deposit refund
        assertEq(usdc.balanceOf(challenger) - challengerBefore, DEPOSIT);
        // Arbiter reward = deposit * 30% = 300_000 (from incentive)
        uint256 arbReward = DEPOSIT * 30 / 100;
        assertEq(usdc.balanceOf(arbiter1), arbReward);
        // Winner gets winnerPayout + incentive remainder = 8_500_000 + (1_000_000 - 300_000) = 9_200_000
        uint256 incentiveRemainder = INCENTIVE - arbReward;
        assertEq(usdc.balanceOf(winner) - winnerBefore, PAYOUT_A_CHALLENGE + incentiveRemainder);
        // Platform gets: totalFunds - totalSent
        // totalFunds = BOUNTY + DEPOSIT + SERVICE_FEE = 9_500_000 + 1_000_000 + 10_000
        // totalSent = PAYOUT_A_CHALLENGE + DEPOSIT + arbReward + incentiveRemainder
        //           = 8_500_000 + 1_000_000 + 300_000 + 700_000 = 10_500_000
        uint256 totalFunds = BOUNTY + DEPOSIT + escrow.SERVICE_FEE();
        uint256 totalSent = PAYOUT_A_CHALLENGE + DEPOSIT + arbReward + incentiveRemainder;
        assertEq(usdc.balanceOf(platform) - platformBefore, totalFunds - totalSent);
    }

    // --- resolveChallenge: upheld + rejected (hasUpheld=true) ---

    function test_resolve_upheld_plus_rejected() public {
        bytes32 taskId = keccak256("task-1");
        address c1 = address(0x2); // upheld
        address c2 = address(0x3); // rejected

        _createChallenge(taskId);
        _joinChallenger(taskId, c1);
        _joinChallenger(taskId, c2);

        // Each challenge has independent arbiters
        ChallengeEscrow.Verdict[] memory verdicts = new ChallengeEscrow.Verdict[](2);
        verdicts[0] = _verdict(c1, 0, _singleArbiter(arbiter1)); // upheld, arbiter1
        verdicts[1] = _verdict(c2, 1, _singleArbiter(arbiter2)); // rejected, arbiter2

        uint256 c1Before = usdc.balanceOf(c1);
        uint256 c2Before = usdc.balanceOf(c2);
        uint256 winnerBefore = usdc.balanceOf(winner);
        uint256 platformBefore = usdc.balanceOf(platform);

        // hasUpheld=true so winnerPayout must be <= bounty - incentive = 8_500_000
        escrow.resolveChallenge(taskId, winner, PAYOUT_A_CHALLENGE, verdicts);

        // c1 (upheld): gets 100% deposit refund
        assertEq(usdc.balanceOf(c1) - c1Before, DEPOSIT);
        // c2 (rejected): gets nothing
        assertEq(usdc.balanceOf(c2), c2Before);

        // arbiter1 (upheld challenge): reward from incentive = DEPOSIT * 30% = 300_000
        uint256 arbRewardUpheld = DEPOSIT * 30 / 100;
        assertEq(usdc.balanceOf(arbiter1), arbRewardUpheld);
        // arbiter2 (rejected challenge): reward from deposit = DEPOSIT * 30% = 300_000
        uint256 arbShareRejected = DEPOSIT * 30 / 100;
        assertEq(usdc.balanceOf(arbiter2), arbShareRejected);

        // Winner gets winnerPayout + incentive remainder (no winner compensation when hasUpheld)
        uint256 incentiveRemainder = INCENTIVE - arbRewardUpheld;
        assertEq(usdc.balanceOf(winner) - winnerBefore, PAYOUT_A_CHALLENGE + incentiveRemainder);

        // Platform gets totalFunds - totalSent
        uint256 totalFunds = BOUNTY + DEPOSIT * 2 + escrow.SERVICE_FEE() * 2;
        uint256 totalSent = PAYOUT_A_CHALLENGE + DEPOSIT + arbRewardUpheld + arbShareRejected + incentiveRemainder;
        assertEq(usdc.balanceOf(platform) - platformBefore, totalFunds - totalSent);
    }

    // --- resolveChallenge: multiple rejected, no upheld --- winner compensation ---

    function test_resolve_multiple_rejected_no_upheld() public {
        bytes32 taskId = keccak256("task-1");
        address c1 = address(0x2);
        address c2 = address(0x3);

        _createChallenge(taskId);
        _joinChallenger(taskId, c1);
        _joinChallenger(taskId, c2);

        ChallengeEscrow.Verdict[] memory verdicts = new ChallengeEscrow.Verdict[](2);
        verdicts[0] = _verdict(c1, 1, _singleArbiter(arbiter1)); // rejected
        verdicts[1] = _verdict(c2, 1, _singleArbiter(arbiter2)); // rejected

        uint256 winnerBefore = usdc.balanceOf(winner);
        uint256 platformBefore = usdc.balanceOf(platform);

        escrow.resolveChallenge(taskId, winner, PAYOUT_A, verdicts);

        // Each deposit: 30% arbiter + 10% winner comp + 60% platform
        uint256 arbiterShare = DEPOSIT * 30 / 100;
        uint256 winnerComp = DEPOSIT * 10 / 100;

        assertEq(usdc.balanceOf(arbiter1), arbiterShare);
        assertEq(usdc.balanceOf(arbiter2), arbiterShare);
        // Winner gets payout + sum of compensations
        assertEq(usdc.balanceOf(winner) - winnerBefore, PAYOUT_A + winnerComp * 2);
        // Platform gets remainder
        uint256 totalFunds = BOUNTY + DEPOSIT * 2 + escrow.SERVICE_FEE() * 2;
        uint256 totalSent = PAYOUT_A + arbiterShare * 2 + winnerComp * 2;
        assertEq(usdc.balanceOf(platform) - platformBefore, totalFunds - totalSent);
    }

    // --- resolveChallenge: dynamic deposits V2 (design doc Example 1) ---

    function test_resolve_dynamic_deposits_v2() public {
        bytes32 taskId = keccak256("task-dyn");
        address c1 = address(0x2); // B-tier: dep=1.5 USDC, upheld
        address c2 = address(0x3); // A-tier: dep=0.5 USDC, rejected

        uint256 dep1 = 1_500_000;  // 1.5 USDC
        uint256 dep2 = 500_000;    // 0.5 USDC

        _createChallenge(taskId);
        _joinChallengerWithDeposit(taskId, c1, dep1);
        _joinChallengerWithDeposit(taskId, c2, dep2);

        ChallengeEscrow.Verdict[] memory verdicts = new ChallengeEscrow.Verdict[](2);
        verdicts[0] = _verdict(c1, 0, _singleArbiter(arbiter1)); // upheld
        verdicts[1] = _verdict(c2, 1, _singleArbiter(arbiter2)); // rejected

        uint256 c1Before = usdc.balanceOf(c1);
        uint256 c2Before = usdc.balanceOf(c2);
        uint256 winnerBefore = usdc.balanceOf(winner);
        uint256 platformBefore = usdc.balanceOf(platform);

        // hasUpheld=true; winnerPayout capped at bounty - incentive = 8_500_000
        escrow.resolveChallenge(taskId, winner, PAYOUT_A_CHALLENGE, verdicts);

        // c1 (upheld): 100% deposit refund = 1_500_000
        assertEq(usdc.balanceOf(c1) - c1Before, dep1);
        // c2 (rejected): nothing
        assertEq(usdc.balanceOf(c2), c2Before);

        // arbiter1 (upheld): reward from incentive = dep1 * 30% = 450_000
        uint256 arb1Reward = dep1 * 30 / 100;
        assertEq(usdc.balanceOf(arbiter1), arb1Reward);
        // arbiter2 (rejected): reward from deposit = dep2 * 30% = 150_000
        uint256 arb2Reward = dep2 * 30 / 100;
        assertEq(usdc.balanceOf(arbiter2), arb2Reward);

        // Winner: winnerPayout + incentive remainder
        uint256 incentiveRemainder = INCENTIVE - arb1Reward;
        assertEq(usdc.balanceOf(winner) - winnerBefore, PAYOUT_A_CHALLENGE + incentiveRemainder);

        // Platform: totalFunds - totalSent
        uint256 totalFunds = BOUNTY + dep1 + dep2 + escrow.SERVICE_FEE() * 2;
        uint256 totalSent = PAYOUT_A_CHALLENGE + dep1 + arb1Reward + arb2Reward + incentiveRemainder;
        assertEq(usdc.balanceOf(platform) - platformBefore, totalFunds - totalSent);
    }

    // --- resolveChallenge: payout capped with upheld ---

    function test_resolve_payout_capped_with_upheld() public {
        bytes32 taskId = keccak256("task-1");
        address challenger = address(0x2);

        _createChallenge(taskId);
        _joinChallenger(taskId, challenger);

        ChallengeEscrow.Verdict[] memory verdicts = new ChallengeEscrow.Verdict[](1);
        verdicts[0] = _verdict(challenger, 0, _singleArbiter(arbiter1)); // upheld

        // When upheld, winnerPayout must be <= bounty - incentive = 8_500_000
        // Try with bounty - incentive + 1 (should revert)
        uint256 mainBounty = BOUNTY - INCENTIVE;
        vm.expectRevert("Payout exceeds main bounty");
        escrow.resolveChallenge(taskId, winner, mainBounty + 1, verdicts);
    }

    // --- double resolve reverts ---

    function test_resolve_reverts_already_resolved() public {
        bytes32 taskId = keccak256("task-1");
        _createChallenge(taskId);

        ChallengeEscrow.Verdict[] memory verdicts = new ChallengeEscrow.Verdict[](0);
        escrow.resolveChallenge(taskId, winner, PAYOUT_A, verdicts);

        vm.expectRevert("Already resolved");
        escrow.resolveChallenge(taskId, winner, PAYOUT_A, verdicts);
    }

    // --- resolveChallenge: winnerPayout exceeds bounty (no upheld) ---

    function test_resolve_reverts_payout_exceeds_bounty() public {
        bytes32 taskId = keccak256("task-1");
        _createChallenge(taskId);

        ChallengeEscrow.Verdict[] memory verdicts = new ChallengeEscrow.Verdict[](0);
        vm.expectRevert("Payout exceeds bounty");
        escrow.resolveChallenge(taskId, winner, BOUNTY + 1, verdicts);
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
        escrow.resolveChallenge(taskId, winner, bTierPayout, verdicts);

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

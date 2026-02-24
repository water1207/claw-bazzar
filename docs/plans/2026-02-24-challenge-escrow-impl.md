# ChallengeEscrow 智能合约托管实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 quality_first 任务的挑战阶段资金流从链下直转改为链上 ChallengeEscrow 合约托管，使用 EIP-2612 Permit + Relayer 免 gas 模式。

**Architecture:** 单一 ChallengeEscrow Solidity 合约管理所有挑战的赏金锁定、押金收取和结算。平台后端同时充当 Relayer（代付 gas 帮挑战者调 joinChallenge）和 Oracle（仲裁后调 resolveChallenge 分配资金）。无挑战时沿用现有 pay_winner() 直接 ERC-20 transfer。

**Tech Stack:** Foundry (Solidity 0.8.20+), OpenZeppelin Contracts, web3.py, FastAPI, Base Sepolia

**Design Doc:** `docs/plans/2026-02-24-challenge-escrow-design.md`

---

## Task 1: Foundry 项目初始化

**Files:**
- Create: `contracts/foundry.toml`
- Create: `contracts/src/ChallengeEscrow.sol` (placeholder)
- Create: `contracts/test/ChallengeEscrow.t.sol` (placeholder)
- Create: `contracts/script/Deploy.s.sol` (placeholder)

**Step 1: 初始化 Foundry 项目**

```bash
cd /Users/nicholas/PycharmProjects/claw-bazzar
mkdir -p contracts
cd contracts
forge init --no-commit --no-git
```

**Step 2: 安装 OpenZeppelin 依赖**

```bash
cd /Users/nicholas/PycharmProjects/claw-bazzar/contracts
forge install OpenZeppelin/openzeppelin-contracts --no-commit --no-git
```

**Step 3: 配置 foundry.toml**

替换 `contracts/foundry.toml` 内容为：

```toml
[profile.default]
src = "src"
out = "out"
libs = ["lib"]
solc = "0.8.20"
optimizer = true
optimizer_runs = 200

[rpc_endpoints]
base_sepolia = "https://sepolia.base.org"
```

**Step 4: 创建合约骨架**

在 `contracts/src/ChallengeEscrow.sol` 写入空合约：

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/extensions/IERC20Permit.sol";

contract ChallengeEscrow is Ownable {
    IERC20 public immutable usdc;
    IERC20Permit public immutable usdcPermit;

    constructor(address _usdc) Ownable(msg.sender) {
        usdc = IERC20(_usdc);
        usdcPermit = IERC20Permit(_usdc);
    }
}
```

**Step 5: 验证编译通过**

```bash
cd /Users/nicholas/PycharmProjects/claw-bazzar/contracts
forge build
```

Expected: 编译成功，无错误。

**Step 6: Commit**

```bash
git add contracts/
git commit -m "feat: init Foundry project with ChallengeEscrow skeleton"
```

---

## Task 2: ChallengeEscrow 合约 — createChallenge

**Files:**
- Modify: `contracts/src/ChallengeEscrow.sol`
- Modify: `contracts/test/ChallengeEscrow.t.sol`

**Step 1: 写失败测试**

在 `contracts/test/ChallengeEscrow.t.sol`：

```solidity
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
}
```

**Step 2: 运行测试确认失败**

```bash
cd /Users/nicholas/PycharmProjects/claw-bazzar/contracts
forge test -vv --match-test "test_createChallenge"
```

Expected: FAIL — `createChallenge` 函数不存在。

**Step 3: 实现 createChallenge**

在 `contracts/src/ChallengeEscrow.sol` 中添加：

```solidity
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
}
```

**Step 4: 运行测试确认通过**

```bash
cd /Users/nicholas/PycharmProjects/claw-bazzar/contracts
forge test -vv --match-test "test_createChallenge"
```

Expected: 3 tests PASS。

**Step 5: Commit**

```bash
git add contracts/
git commit -m "feat(contract): implement createChallenge with tests"
```

---

## Task 3: ChallengeEscrow 合约 — joinChallenge

**Files:**
- Modify: `contracts/src/ChallengeEscrow.sol`
- Modify: `contracts/test/ChallengeEscrow.t.sol`

**Step 1: 写失败测试**

在 `ChallengeEscrowTest` 中追加：

```solidity
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
```

**Step 2: 运行测试确认失败**

```bash
cd /Users/nicholas/PycharmProjects/claw-bazzar/contracts
forge test -vv --match-test "test_joinChallenge"
```

Expected: FAIL — `joinChallenge` 不存在。

**Step 3: 实现 joinChallenge**

在 `ChallengeEscrow.sol` 的 `createChallenge` 后追加：

```solidity
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
```

**Step 4: 运行测试确认通过**

```bash
cd /Users/nicholas/PycharmProjects/claw-bazzar/contracts
forge test -vv --match-test "test_joinChallenge"
```

Expected: 3 tests PASS。

**Step 5: Commit**

```bash
git add contracts/
git commit -m "feat(contract): implement joinChallenge with EIP-2612 permit"
```

---

## Task 4: ChallengeEscrow 合约 — resolveChallenge

**Files:**
- Modify: `contracts/src/ChallengeEscrow.sol`
- Modify: `contracts/test/ChallengeEscrow.t.sol`

**Step 1: 写失败测试**

```solidity
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

    // Resolve: rejected (result=1) → 70% deposit back, 30% + serviceFee to platform
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

    (, , , , , bool resolved) = escrow.challenges(taskId);
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

    // Resolve: upheld (result=0) → bounty to challenger, 100% deposit back
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

    // Resolve: malicious (result=2) → 0% deposit, all to platform
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
```

**Step 2: 运行测试确认失败**

```bash
cd /Users/nicholas/PycharmProjects/claw-bazzar/contracts
forge test -vv --match-test "test_resolveChallenge"
```

Expected: FAIL — `resolveChallenge` 和 `Verdict` 不存在。

**Step 3: 实现 resolveChallenge**

在 `ChallengeEscrow.sol` 中添加 Verdict 结构体和 resolveChallenge 函数：

```solidity
struct Verdict {
    address challenger;
    uint8   result;      // 0=upheld, 1=rejected, 2=malicious
}

function resolveChallenge(
    bytes32 taskId,
    address finalWinner,
    Verdict[] calldata verdicts
) external onlyOwner {
    ChallengeInfo storage info = challenges[taskId];
    require(info.bounty > 0, "Challenge not found");
    require(!info.resolved, "Already resolved");

    // 1. Bounty → final winner
    require(usdc.transfer(finalWinner, info.bounty), "Bounty transfer failed");

    // 2. Process each challenger's deposit
    uint256 platformTotal = 0;
    for (uint256 i = 0; i < verdicts.length; i++) {
        require(challengers[taskId][verdicts[i].challenger], "Not a challenger");

        if (verdicts[i].result == 0) {
            // upheld: 100% deposit back
            require(
                usdc.transfer(verdicts[i].challenger, info.depositAmount),
                "Deposit refund failed"
            );
        } else if (verdicts[i].result == 1) {
            // rejected: 70% back, 30% to platform
            uint256 refund = info.depositAmount * 70 / 100;
            require(
                usdc.transfer(verdicts[i].challenger, refund),
                "Partial refund failed"
            );
            platformTotal += info.depositAmount - refund;
        } else {
            // malicious: 0% back, all to platform
            platformTotal += info.depositAmount;
        }
    }

    // 3. Service fees + forfeited deposits → platform
    platformTotal += info.serviceFee * info.challengerCount;
    if (platformTotal > 0) {
        require(usdc.transfer(owner(), platformTotal), "Platform transfer failed");
    }

    info.resolved = true;
    emit ChallengeResolved(taskId, finalWinner);
}
```

**Step 4: 运行测试确认通过**

```bash
cd /Users/nicholas/PycharmProjects/claw-bazzar/contracts
forge test -vv --match-test "test_resolveChallenge"
```

Expected: 5 tests PASS。

**Step 5: 运行全部合约测试**

```bash
cd /Users/nicholas/PycharmProjects/claw-bazzar/contracts
forge test -vv
```

Expected: 全部 PASS。

**Step 6: Commit**

```bash
git add contracts/
git commit -m "feat(contract): implement resolveChallenge with verdict-based settlement"
```

---

## Task 5: ChallengeEscrow 合约 — emergencyWithdraw

**Files:**
- Modify: `contracts/src/ChallengeEscrow.sol`
- Modify: `contracts/test/ChallengeEscrow.t.sol`

**Step 1: 写失败测试**

```solidity
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
    (, , , , , bool resolved) = escrow.challenges(taskId);
    assertTrue(resolved);
}

function test_emergencyWithdraw_reverts_too_early() public {
    bytes32 taskId = keccak256("task-1");
    usdc.approve(address(escrow), 8 * 1e6);
    escrow.createChallenge(taskId, winner, 8 * 1e6, 1 * 1e6);

    vm.expectRevert("Too early for emergency withdrawal");
    escrow.emergencyWithdraw(taskId);
}
```

**Step 2: 运行测试确认失败**

```bash
cd /Users/nicholas/PycharmProjects/claw-bazzar/contracts
forge test -vv --match-test "test_emergencyWithdraw"
```

Expected: FAIL。

**Step 3: 实现 emergencyWithdraw**

在 ChallengeInfo 中添加 `createdAt` 字段，在 `createChallenge` 中设置。然后添加：

```solidity
uint256 public constant EMERGENCY_TIMEOUT = 30 days;

function emergencyWithdraw(bytes32 taskId) external onlyOwner {
    ChallengeInfo storage info = challenges[taskId];
    require(info.bounty > 0, "Challenge not found");
    require(!info.resolved, "Already resolved");
    require(
        block.timestamp >= info.createdAt + EMERGENCY_TIMEOUT,
        "Too early for emergency withdrawal"
    );

    // Transfer all remaining USDC back to platform
    uint256 balance = usdc.balanceOf(address(this));
    // Only transfer what belongs to this task: bounty + (deposit+fee)*challengerCount
    uint256 taskFunds = info.bounty +
        (info.depositAmount + info.serviceFee) * info.challengerCount;
    // Cap at contract balance in case of rounding
    uint256 amount = taskFunds > balance ? balance : taskFunds;

    require(usdc.transfer(owner(), amount), "Emergency transfer failed");
    info.resolved = true;
}
```

同时更新 ChallengeInfo 结构体加入 `uint256 createdAt`，在 `createChallenge` 中设 `createdAt: block.timestamp`。

**Step 4: 运行测试确认通过**

```bash
cd /Users/nicholas/PycharmProjects/claw-bazzar/contracts
forge test -vv
```

Expected: 全部 PASS。

**Step 5: Commit**

```bash
git add contracts/
git commit -m "feat(contract): add emergencyWithdraw safety valve (30-day timeout)"
```

---

## Task 6: 部署脚本

**Files:**
- Create: `contracts/script/Deploy.s.sol`

**Step 1: 写部署脚本**

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Script.sol";
import "../src/ChallengeEscrow.sol";

contract DeployScript is Script {
    function run() external {
        uint256 deployerPrivateKey = vm.envUint("PLATFORM_PRIVATE_KEY");
        address usdcAddress = vm.envAddress("USDC_CONTRACT");

        vm.startBroadcast(deployerPrivateKey);
        ChallengeEscrow escrow = new ChallengeEscrow(usdcAddress);
        vm.stopBroadcast();

        console.log("ChallengeEscrow deployed at:", address(escrow));
    }
}
```

**Step 2: 验证脚本编译**

```bash
cd /Users/nicholas/PycharmProjects/claw-bazzar/contracts
forge build
```

Expected: 编译成功。

**Step 3: Commit**

```bash
git add contracts/script/
git commit -m "feat(contract): add deployment script for ChallengeEscrow"
```

---

## Task 7: 后端 — Model 和 Schema 变更

**Files:**
- Modify: `app/models.py:108-121` (Challenge model)
- Modify: `app/schemas.py:104-121` (Challenge schemas)

**Step 1: 写失败测试**

在 `tests/test_challenge_api.py` 追加（不修改已有测试）：

```python
def test_create_challenge_with_wallet_and_permit(client):
    """New escrow fields are accepted and returned."""
    task = make_quality_task(client)
    s1 = submit(client, task["id"], "w1", "winner")
    s2 = submit(client, task["id"], "w2", "challenger")
    setup_challenge_window(client, task["id"], s1["id"])

    resp = client.post(f"/tasks/{task['id']}/challenges", json={
        "challenger_submission_id": s2["id"],
        "reason": "better solution",
        "challenger_wallet": "0x1234567890abcdef1234567890abcdef12345678",
        "permit_deadline": 9999999999,
        "permit_v": 27,
        "permit_r": "0x" + "ab" * 32,
        "permit_s": "0x" + "cd" * 32,
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["challenger_wallet"] == "0x1234567890abcdef1234567890abcdef12345678"
```

**Step 2: 运行测试确认失败**

```bash
cd /Users/nicholas/PycharmProjects/claw-bazzar
pytest tests/test_challenge_api.py::test_create_challenge_with_wallet_and_permit -v
```

Expected: FAIL — ChallengeCreate 不接受新字段。

**Step 3: 更新 Model**

在 `app/models.py`，Challenge 类（line 108-121）添加字段：

```python
class Challenge(Base):
    __tablename__ = "challenges"

    id = Column(String, primary_key=True, default=_uuid)
    task_id = Column(String, nullable=False)
    challenger_submission_id = Column(String, nullable=False)
    target_submission_id = Column(String, nullable=False)
    reason = Column(Text, nullable=False)
    verdict = Column(Enum(ChallengeVerdict), nullable=True)
    arbiter_feedback = Column(Text, nullable=True)
    arbiter_score = Column(Float, nullable=True)
    status = Column(Enum(ChallengeStatus), nullable=False, default=ChallengeStatus.pending)
    # New escrow fields
    challenger_wallet = Column(String, nullable=True)
    deposit_tx_hash = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
```

**Step 4: 更新 Schema**

在 `app/schemas.py`，修改 ChallengeCreate（line 104-106）和 ChallengeOut（line 109-121）：

```python
class ChallengeCreate(BaseModel):
    challenger_submission_id: str
    reason: str
    challenger_wallet: Optional[str] = None
    permit_deadline: Optional[int] = None
    permit_v: Optional[int] = None
    permit_r: Optional[str] = None
    permit_s: Optional[str] = None


class ChallengeOut(BaseModel):
    id: str
    task_id: str
    challenger_submission_id: str
    target_submission_id: str
    reason: str
    verdict: Optional[ChallengeVerdict] = None
    arbiter_feedback: Optional[str] = None
    arbiter_score: Optional[float] = None
    status: ChallengeStatus
    challenger_wallet: Optional[str] = None
    deposit_tx_hash: Optional[str] = None
    created_at: UTCDatetime

    model_config = {"from_attributes": True}
```

**Step 5: 更新 Router 保存新字段**

在 `app/routers/challenges.py` 的 create_challenge（line 50-58），在创建 Challenge 时传入 `challenger_wallet`：

```python
challenge = Challenge(
    task_id=task_id,
    challenger_submission_id=data.challenger_submission_id,
    target_submission_id=task.winner_submission_id,
    reason=data.reason,
    challenger_wallet=data.challenger_wallet,
)
```

**Step 6: 运行测试确认通过**

```bash
cd /Users/nicholas/PycharmProjects/claw-bazzar
pytest tests/test_challenge_api.py -v
```

Expected: 全部 PASS（包括新旧测试），旧测试不传新字段也能通过（Optional 默认 None）。

**Step 7: Commit**

```bash
git add app/models.py app/schemas.py app/routers/challenges.py tests/test_challenge_api.py
git commit -m "feat: add escrow fields to Challenge model and schemas"
```

---

## Task 8: 后端 — escrow.py 服务

**Files:**
- Create: `app/services/escrow.py`
- Create: `tests/test_escrow_service.py`

**Step 1: 写失败测试**

创建 `tests/test_escrow_service.py`：

```python
"""Tests for the escrow service layer (chain calls mocked)."""
from unittest.mock import patch, MagicMock
from app.services.escrow import (
    check_usdc_balance,
    create_challenge_onchain,
    join_challenge_onchain,
    resolve_challenge_onchain,
)


def test_check_usdc_balance():
    """Should return float USDC balance from RPC."""
    mock_w3 = MagicMock()
    mock_contract = MagicMock()
    # 5 USDC = 5_000_000 in 6-decimal wei
    mock_contract.functions.balanceOf.return_value.call.return_value = 5_000_000
    mock_w3.eth.contract.return_value = mock_contract

    with patch("app.services.escrow.Web3", return_value=mock_w3):
        balance = check_usdc_balance("0xabc")
    assert balance == 5.0


def test_create_challenge_onchain():
    """Should call contract.createChallenge and return tx hash."""
    mock_w3 = MagicMock()
    mock_account = MagicMock()
    mock_account.address = "0xPlatform"
    mock_w3.eth.account.from_key.return_value = mock_account
    mock_w3.eth.get_transaction_count.return_value = 0
    mock_w3.eth.gas_price = 1000
    mock_w3.eth.send_raw_transaction.return_value = b"\x01" * 32
    mock_w3.eth.wait_for_transaction_receipt.return_value = {"status": 1}

    mock_contract = MagicMock()
    mock_w3.eth.contract.return_value = mock_contract

    with patch("app.services.escrow.Web3", return_value=mock_w3):
        with patch("app.services.escrow._get_w3_and_contract", return_value=(mock_w3, mock_contract)):
            tx = create_challenge_onchain("task-1", "0xWinner", 8.0, 1.0)
    assert tx is not None


def test_join_challenge_onchain():
    """Should call contract.joinChallenge with permit params."""
    mock_w3 = MagicMock()
    mock_account = MagicMock()
    mock_account.address = "0xPlatform"
    mock_w3.eth.account.from_key.return_value = mock_account
    mock_w3.eth.get_transaction_count.return_value = 0
    mock_w3.eth.gas_price = 1000
    mock_w3.eth.send_raw_transaction.return_value = b"\x02" * 32
    mock_w3.eth.wait_for_transaction_receipt.return_value = {"status": 1}

    mock_contract = MagicMock()

    with patch("app.services.escrow._get_w3_and_contract", return_value=(mock_w3, mock_contract)):
        tx = join_challenge_onchain(
            "task-1", "0xChallenger", 9999999999, 27, "0x" + "ab" * 32, "0x" + "cd" * 32
        )
    assert tx is not None


def test_resolve_challenge_onchain():
    """Should call contract.resolveChallenge with verdicts."""
    mock_w3 = MagicMock()
    mock_account = MagicMock()
    mock_account.address = "0xPlatform"
    mock_w3.eth.account.from_key.return_value = mock_account
    mock_w3.eth.get_transaction_count.return_value = 0
    mock_w3.eth.gas_price = 1000
    mock_w3.eth.send_raw_transaction.return_value = b"\x03" * 32
    mock_w3.eth.wait_for_transaction_receipt.return_value = {"status": 1}

    mock_contract = MagicMock()

    with patch("app.services.escrow._get_w3_and_contract", return_value=(mock_w3, mock_contract)):
        tx = resolve_challenge_onchain(
            "task-1",
            "0xWinner",
            [{"challenger": "0xC1", "result": 0}, {"challenger": "0xC2", "result": 1}],
        )
    assert tx is not None
```

**Step 2: 运行测试确认失败**

```bash
cd /Users/nicholas/PycharmProjects/claw-bazzar
pytest tests/test_escrow_service.py -v
```

Expected: FAIL — `app.services.escrow` 不存在。

**Step 3: 实现 escrow.py**

创建 `app/services/escrow.py`：

```python
"""ChallengeEscrow contract interaction layer."""
import json
import os
from pathlib import Path
from web3 import Web3

PLATFORM_PRIVATE_KEY = os.environ.get("PLATFORM_PRIVATE_KEY", "")
RPC_URL = os.environ.get("BASE_SEPOLIA_RPC_URL", "https://sepolia.base.org")
USDC_CONTRACT = os.environ.get("USDC_CONTRACT", "0x036CbD53842c5426634e7929541eC2318f3dCF7e")
ESCROW_CONTRACT_ADDRESS = os.environ.get("ESCROW_CONTRACT_ADDRESS", "")

# Minimal ERC-20 ABI for balanceOf
ERC20_BALANCE_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function",
    }
]


def _load_escrow_abi() -> list:
    """Load ChallengeEscrow ABI from Foundry output."""
    abi_path = Path(__file__).parent.parent.parent / "contracts" / "out" / "ChallengeEscrow.sol" / "ChallengeEscrow.json"
    if abi_path.exists():
        with open(abi_path) as f:
            return json.load(f)["abi"]
    # Fallback: minimal ABI for the 4 functions we use
    return _MINIMAL_ESCROW_ABI


# Minimal ABI fallback (used when Foundry artifacts not available, e.g. in tests)
_MINIMAL_ESCROW_ABI = [
    {
        "inputs": [
            {"name": "taskId", "type": "bytes32"},
            {"name": "winner_", "type": "address"},
            {"name": "bounty", "type": "uint256"},
            {"name": "depositAmount", "type": "uint256"},
        ],
        "name": "createChallenge",
        "outputs": [],
        "type": "function",
    },
    {
        "inputs": [
            {"name": "taskId", "type": "bytes32"},
            {"name": "challenger", "type": "address"},
            {"name": "deadline", "type": "uint256"},
            {"name": "v", "type": "uint8"},
            {"name": "r", "type": "bytes32"},
            {"name": "s", "type": "bytes32"},
        ],
        "name": "joinChallenge",
        "outputs": [],
        "type": "function",
    },
    {
        "inputs": [
            {"name": "taskId", "type": "bytes32"},
            {"name": "finalWinner", "type": "address"},
            {
                "name": "verdicts",
                "type": "tuple[]",
                "components": [
                    {"name": "challenger", "type": "address"},
                    {"name": "result", "type": "uint8"},
                ],
            },
        ],
        "name": "resolveChallenge",
        "outputs": [],
        "type": "function",
    },
    {
        "inputs": [{"name": "taskId", "type": "bytes32"}],
        "name": "emergencyWithdraw",
        "outputs": [],
        "type": "function",
    },
]


def _get_w3_and_contract():
    """Create web3 instance and contract object. Separated for mocking."""
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    abi = _load_escrow_abi()
    contract = w3.eth.contract(
        address=Web3.to_checksum_address(ESCROW_CONTRACT_ADDRESS), abi=abi
    )
    return w3, contract


def _task_id_to_bytes32(task_id: str) -> bytes:
    """Convert task UUID string to bytes32 via keccak256."""
    return Web3.keccak(text=task_id)


def _send_tx(w3, contract_fn, description: str) -> str:
    """Build, sign, send a contract transaction. Returns tx hash hex."""
    account = w3.eth.account.from_key(PLATFORM_PRIVATE_KEY)
    tx = contract_fn.build_transaction({
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "gas": 300_000,
        "gasPrice": w3.eth.gas_price,
    })
    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
    print(f"[escrow] {description} tx={tx_hash.hex()}", flush=True)
    return tx_hash.hex()


def check_usdc_balance(wallet_address: str) -> float:
    """Check USDC balance of a wallet. Returns amount in USDC (not wei)."""
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    contract = w3.eth.contract(
        address=Web3.to_checksum_address(USDC_CONTRACT), abi=ERC20_BALANCE_ABI
    )
    balance_wei = contract.functions.balanceOf(
        Web3.to_checksum_address(wallet_address)
    ).call()
    return balance_wei / 10**6


def create_challenge_onchain(
    task_id: str, winner_wallet: str, bounty: float, deposit_amount: float
) -> str:
    """Call ChallengeEscrow.createChallenge(). Platform must have approved USDC.
    Returns tx hash."""
    w3, contract = _get_w3_and_contract()
    task_bytes = _task_id_to_bytes32(task_id)
    bounty_wei = int(bounty * 10**6)
    deposit_wei = int(deposit_amount * 10**6)

    fn = contract.functions.createChallenge(
        task_bytes,
        Web3.to_checksum_address(winner_wallet),
        bounty_wei,
        deposit_wei,
    )
    return _send_tx(w3, fn, f"createChallenge({task_id})")


def join_challenge_onchain(
    task_id: str,
    challenger_wallet: str,
    deadline: int,
    v: int,
    r: str,
    s: str,
) -> str:
    """Call ChallengeEscrow.joinChallenge() with EIP-2612 permit params.
    Returns tx hash."""
    w3, contract = _get_w3_and_contract()
    task_bytes = _task_id_to_bytes32(task_id)

    fn = contract.functions.joinChallenge(
        task_bytes,
        Web3.to_checksum_address(challenger_wallet),
        deadline,
        v,
        bytes.fromhex(r[2:]) if r.startswith("0x") else bytes.fromhex(r),
        bytes.fromhex(s[2:]) if s.startswith("0x") else bytes.fromhex(s),
    )
    return _send_tx(w3, fn, f"joinChallenge({task_id}, {challenger_wallet})")


def resolve_challenge_onchain(
    task_id: str,
    final_winner_wallet: str,
    verdicts: list[dict],
) -> str:
    """Call ChallengeEscrow.resolveChallenge() with verdict array.
    verdicts: [{"challenger": "0x...", "result": 0|1|2}, ...]
    Returns tx hash."""
    w3, contract = _get_w3_and_contract()
    task_bytes = _task_id_to_bytes32(task_id)

    verdict_tuples = [
        (Web3.to_checksum_address(v["challenger"]), v["result"])
        for v in verdicts
    ]

    fn = contract.functions.resolveChallenge(
        task_bytes,
        Web3.to_checksum_address(final_winner_wallet),
        verdict_tuples,
    )
    return _send_tx(w3, fn, f"resolveChallenge({task_id})")
```

**Step 4: 运行测试确认通过**

```bash
cd /Users/nicholas/PycharmProjects/claw-bazzar
pytest tests/test_escrow_service.py -v
```

Expected: 4 tests PASS。

**Step 5: Commit**

```bash
git add app/services/escrow.py tests/test_escrow_service.py
git commit -m "feat: add escrow service layer for ChallengeEscrow contract interaction"
```

---

## Task 9: 后端 — Router 集成（余额校验 + 频率限制 + Relayer 调用）

**Files:**
- Modify: `app/routers/challenges.py:12-59`
- Modify: `tests/test_challenge_api.py`

**Step 1: 写失败测试**

在 `tests/test_challenge_api.py` 追加：

```python
def test_challenge_rejected_insufficient_balance(client):
    """Reject if challenger's USDC balance is too low."""
    task = make_quality_task(client, bounty=10.0)
    s1 = submit(client, task["id"], "w1")
    s2 = submit(client, task["id"], "w2")
    setup_challenge_window(client, task["id"], s1["id"])

    with patch("app.routers.challenges.check_usdc_balance", return_value=0.5):
        resp = client.post(f"/tasks/{task['id']}/challenges", json={
            "challenger_submission_id": s2["id"],
            "reason": "test",
            "challenger_wallet": "0x" + "ab" * 20,
            "permit_deadline": 9999999999,
            "permit_v": 27,
            "permit_r": "0x" + "ab" * 32,
            "permit_s": "0x" + "cd" * 32,
        })
    assert resp.status_code == 400
    assert "余额不足" in resp.json()["detail"] or "balance" in resp.json()["detail"].lower()


def test_challenge_rejected_rate_limit(client):
    """Reject if same wallet challenged within 1 minute."""
    task = make_quality_task(client, bounty=10.0)
    s1 = submit(client, task["id"], "w1")
    s2 = submit(client, task["id"], "w2")
    s3 = submit(client, task["id"], "w3")
    setup_challenge_window(client, task["id"], s1["id"])

    wallet = "0x" + "ab" * 20

    with patch("app.routers.challenges.check_usdc_balance", return_value=100.0), \
         patch("app.routers.challenges.join_challenge_onchain", return_value="0xtx1"):
        resp1 = client.post(f"/tasks/{task['id']}/challenges", json={
            "challenger_submission_id": s2["id"],
            "reason": "first",
            "challenger_wallet": wallet,
            "permit_deadline": 9999999999,
            "permit_v": 27,
            "permit_r": "0x" + "ab" * 32,
            "permit_s": "0x" + "cd" * 32,
        })
        assert resp1.status_code == 201

        # Second challenge from same wallet within 1 minute
        resp2 = client.post(f"/tasks/{task['id']}/challenges", json={
            "challenger_submission_id": s3["id"],
            "reason": "second",
            "challenger_wallet": wallet,
            "permit_deadline": 9999999999,
            "permit_v": 27,
            "permit_r": "0x" + "ab" * 32,
            "permit_s": "0x" + "cd" * 32,
        })
    assert resp2.status_code == 429


def test_challenge_with_escrow_happy_path(client):
    """Full happy path: balance check → rate limit → join_challenge_onchain."""
    task = make_quality_task(client, bounty=10.0)
    s1 = submit(client, task["id"], "w1")
    s2 = submit(client, task["id"], "w2")
    setup_challenge_window(client, task["id"], s1["id"])

    with patch("app.routers.challenges.check_usdc_balance", return_value=100.0), \
         patch("app.routers.challenges.join_challenge_onchain", return_value="0xescrow_tx"):
        resp = client.post(f"/tasks/{task['id']}/challenges", json={
            "challenger_submission_id": s2["id"],
            "reason": "my answer is better",
            "challenger_wallet": "0x" + "ab" * 20,
            "permit_deadline": 9999999999,
            "permit_v": 27,
            "permit_r": "0x" + "ab" * 32,
            "permit_s": "0x" + "cd" * 32,
        })
    assert resp.status_code == 201
    data = resp.json()
    assert data["deposit_tx_hash"] == "0xescrow_tx"
```

**Step 2: 运行测试确认失败**

```bash
cd /Users/nicholas/PycharmProjects/claw-bazzar
pytest tests/test_challenge_api.py::test_challenge_rejected_insufficient_balance -v
```

Expected: FAIL — 新逻辑未实现。

**Step 3: 更新 router**

替换 `app/routers/challenges.py` 内容：

```python
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from ..database import get_db
from ..models import Task, Submission, Challenge, TaskStatus
from ..schemas import ChallengeCreate, ChallengeOut
from ..services.escrow import check_usdc_balance, join_challenge_onchain

SERVICE_FEE = 0.01  # 0.01 USDC

router = APIRouter(tags=["challenges"])


@router.post("/tasks/{task_id}/challenges", response_model=ChallengeOut, status_code=201)
def create_challenge(
    task_id: str,
    data: ChallengeCreate,
    db: Session = Depends(get_db),
):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status != TaskStatus.challenge_window:
        raise HTTPException(status_code=400, detail="Task is not in challenge_window state")

    if task.challenge_window_end:
        end = task.challenge_window_end if task.challenge_window_end.tzinfo else task.challenge_window_end.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > end:
            raise HTTPException(status_code=400, detail="Challenge window has closed")

    # Verify challenger submission belongs to this task
    challenger_sub = db.query(Submission).filter(
        Submission.id == data.challenger_submission_id,
        Submission.task_id == task_id,
    ).first()
    if not challenger_sub:
        raise HTTPException(status_code=400, detail="Challenger submission not found in this task")

    # Cannot challenge yourself
    if data.challenger_submission_id == task.winner_submission_id:
        raise HTTPException(status_code=400, detail="Winner cannot challenge themselves")

    # Check for duplicate challenge by same worker
    existing = db.query(Challenge).filter(
        Challenge.task_id == task_id,
        Challenge.challenger_submission_id == data.challenger_submission_id,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Already submitted a challenge for this task")

    # --- New: Escrow integration (only when permit params provided) ---
    deposit_tx_hash = None
    if data.challenger_wallet and data.permit_v is not None:
        deposit_amount = task.submission_deposit or round(task.bounty * 0.10, 6)
        required = deposit_amount + SERVICE_FEE

        # 1. Balance check
        try:
            balance = check_usdc_balance(data.challenger_wallet)
        except Exception:
            balance = 0.0
        if balance < required:
            raise HTTPException(status_code=400, detail=f"USDC余额不足 (需要 {required}, 余额 {balance})")

        # 2. Rate limit: same wallet, 1 challenge per minute
        recent = db.query(Challenge).filter(
            Challenge.challenger_wallet == data.challenger_wallet,
            Challenge.created_at > datetime.now(timezone.utc) - timedelta(minutes=1),
        ).first()
        if recent:
            raise HTTPException(status_code=429, detail="每分钟最多提交一次挑战")

        # 3. Relayer: call joinChallenge on-chain
        try:
            deposit_tx_hash = join_challenge_onchain(
                task_id,
                data.challenger_wallet,
                data.permit_deadline,
                data.permit_v,
                data.permit_r,
                data.permit_s,
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"链上交易失败: {e}")

    challenge = Challenge(
        task_id=task_id,
        challenger_submission_id=data.challenger_submission_id,
        target_submission_id=task.winner_submission_id,
        reason=data.reason,
        challenger_wallet=data.challenger_wallet,
        deposit_tx_hash=deposit_tx_hash,
    )
    db.add(challenge)
    db.commit()
    db.refresh(challenge)
    return challenge


@router.get("/tasks/{task_id}/challenges", response_model=List[ChallengeOut])
def list_challenges(task_id: str, db: Session = Depends(get_db)):
    if not db.query(Task).filter(Task.id == task_id).first():
        raise HTTPException(status_code=404, detail="Task not found")
    return db.query(Challenge).filter(Challenge.task_id == task_id).all()


@router.get("/tasks/{task_id}/challenges/{challenge_id}", response_model=ChallengeOut)
def get_challenge(task_id: str, challenge_id: str, db: Session = Depends(get_db)):
    challenge = db.query(Challenge).filter(
        Challenge.id == challenge_id, Challenge.task_id == task_id
    ).first()
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")
    return challenge
```

**Step 4: 运行测试确认通过**

```bash
cd /Users/nicholas/PycharmProjects/claw-bazzar
pytest tests/test_challenge_api.py -v
```

Expected: 全部 PASS（旧测试不传 permit 参数，走老路径；新测试走 escrow 路径）。

**Step 5: 运行全部后端测试确保无回归**

```bash
cd /Users/nicholas/PycharmProjects/claw-bazzar
pytest -v
```

Expected: 全部 PASS。

**Step 6: Commit**

```bash
git add app/routers/challenges.py tests/test_challenge_api.py
git commit -m "feat: integrate escrow into challenge router (balance check, rate limit, relayer)"
```

---

## Task 10: 后端 — Scheduler 集成（链上结算）

**Files:**
- Modify: `app/scheduler.py:106-144` (Phase 3 & 4)
- Create: `tests/test_escrow_settlement.py`

**Step 1: 写失败测试**

创建 `tests/test_escrow_settlement.py`：

```python
"""Tests for escrow-integrated settlement in scheduler."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock
from app.models import (
    Task, Submission, Challenge, User,
    TaskType, TaskStatus, SubmissionStatus, ChallengeStatus, ChallengeVerdict, PayoutStatus,
)
from app.scheduler import _settle_after_arbitration


def _setup_arbitrated_task(db):
    """Create a task in arbitrating state with one judged challenge."""
    user_w = User(id="w1", nickname="worker1", wallet="0xWinner", role="worker")
    user_c = User(id="w2", nickname="worker2", wallet="0xChallenger", role="worker")
    db.add_all([user_w, user_c])

    task = Task(
        id="t1", title="T", description="d", type=TaskType.quality_first,
        deadline=datetime.now(timezone.utc) - timedelta(hours=1),
        status=TaskStatus.arbitrating,
        winner_submission_id="s1", bounty=10.0,
        submission_deposit=1.0,
    )
    db.add(task)

    s1 = Submission(id="s1", task_id="t1", worker_id="w1", content="winner", score=0.9,
                    status=SubmissionStatus.scored, deposit=1.0)
    s2 = Submission(id="s2", task_id="t1", worker_id="w2", content="challenger", score=0.7,
                    status=SubmissionStatus.scored, deposit=1.0)
    db.add_all([s1, s2])

    challenge = Challenge(
        id="c1", task_id="t1",
        challenger_submission_id="s2", target_submission_id="s1",
        reason="better", verdict=ChallengeVerdict.rejected,
        arbiter_score=0.6, status=ChallengeStatus.judged,
        challenger_wallet="0xChallenger",
    )
    db.add(challenge)
    db.commit()
    return task


def test_settle_calls_escrow_when_challengers_have_wallets(client):
    """When challenges have challenger_wallet, settlement should use escrow."""
    from app.database import get_db
    from app.main import app
    db = next(app.dependency_overrides[get_db]())

    task = _setup_arbitrated_task(db)

    with patch("app.scheduler.create_challenge_onchain", return_value="0xcreate") as mock_create, \
         patch("app.scheduler.resolve_challenge_onchain", return_value="0xresolve") as mock_resolve:
        _settle_after_arbitration(db, task)

    # Verify escrow was called
    mock_create.assert_called_once()
    mock_resolve.assert_called_once()

    # Verify task is closed and payout recorded
    db.refresh(task)
    assert task.status == TaskStatus.closed
    assert task.payout_tx_hash == "0xresolve"
    assert task.payout_status == PayoutStatus.paid


def test_settle_falls_back_to_pay_winner_without_wallets(client):
    """When no challenger_wallet, uses legacy pay_winner()."""
    from app.database import get_db
    from app.main import app
    db = next(app.dependency_overrides[get_db]())

    # Setup without challenger_wallet
    user_w = User(id="w1b", nickname="worker1b", wallet="0xWinner", role="worker")
    user_c = User(id="w2b", nickname="worker2b", wallet="0xChallenger", role="worker")
    db.add_all([user_w, user_c])

    task = Task(
        id="t1b", title="T", description="d", type=TaskType.quality_first,
        deadline=datetime.now(timezone.utc) - timedelta(hours=1),
        status=TaskStatus.arbitrating,
        winner_submission_id="s1b", bounty=10.0, submission_deposit=1.0,
    )
    db.add(task)

    s1 = Submission(id="s1b", task_id="t1b", worker_id="w1b", content="w", score=0.9,
                    status=SubmissionStatus.scored, deposit=1.0)
    s2 = Submission(id="s2b", task_id="t1b", worker_id="w2b", content="c", score=0.7,
                    status=SubmissionStatus.scored, deposit=1.0)
    db.add_all([s1, s2])

    challenge = Challenge(
        id="c1b", task_id="t1b",
        challenger_submission_id="s2b", target_submission_id="s1b",
        reason="test", verdict=ChallengeVerdict.rejected,
        arbiter_score=0.6, status=ChallengeStatus.judged,
        challenger_wallet=None,  # No wallet → legacy path
    )
    db.add(challenge)
    db.commit()

    with patch("app.scheduler.pay_winner") as mock_pay:
        _settle_after_arbitration(db, task)

    mock_pay.assert_called_once()
```

**Step 2: 运行测试确认失败**

```bash
cd /Users/nicholas/PycharmProjects/claw-bazzar
pytest tests/test_escrow_settlement.py -v
```

Expected: FAIL — scheduler 没有导入或调用 escrow 函数。

**Step 3: 修改 scheduler.py**

在 `app/scheduler.py` 顶部添加导入：

```python
from .services.escrow import create_challenge_onchain, resolve_challenge_onchain
```

修改 `_settle_after_arbitration`（line 147-196）— 在现有的存款处理和 winner 确定逻辑之后、`pay_winner` 调用之前，增加链上结算分支：

```python
def _settle_after_arbitration(db: Session, task: Task) -> None:
    """Settle a task after all challenges are judged."""
    from .models import ChallengeVerdict, User
    challenges = db.query(Challenge).filter(Challenge.task_id == task.id).all()

    # Process deposits and credit scores (existing logic)
    for c in challenges:
        challenger_sub = db.query(Submission).filter(
            Submission.id == c.challenger_submission_id
        ).first()
        worker = db.query(User).filter(
            User.id == challenger_sub.worker_id
        ).first() if challenger_sub else None

        if c.verdict == ChallengeVerdict.upheld:
            if challenger_sub and challenger_sub.deposit_returned is None:
                challenger_sub.deposit_returned = challenger_sub.deposit
            if worker:
                worker.credit_score = round(worker.credit_score + 5, 2)

        elif c.verdict == ChallengeVerdict.rejected:
            if challenger_sub and challenger_sub.deposit is not None and challenger_sub.deposit_returned is None:
                challenger_sub.deposit_returned = round(challenger_sub.deposit * 0.70, 6)

        elif c.verdict == ChallengeVerdict.malicious:
            if challenger_sub and challenger_sub.deposit_returned is None:
                challenger_sub.deposit_returned = 0
            if worker:
                worker.credit_score = round(worker.credit_score - 20, 2)

    # Determine final winner
    upheld = [c for c in challenges if c.verdict == ChallengeVerdict.upheld]
    if upheld:
        best = max(upheld, key=lambda c: c.arbiter_score or 0)
        task.winner_submission_id = best.challenger_submission_id

    # Refund non-challenger deposits
    all_subs = db.query(Submission).filter(
        Submission.task_id == task.id,
        Submission.deposit.isnot(None),
        Submission.deposit_returned.is_(None),
    ).all()
    for sub in all_subs:
        sub.deposit_returned = sub.deposit

    task.status = TaskStatus.closed

    # --- Escrow settlement (new) ---
    has_escrow = any(c.challenger_wallet for c in challenges)
    if has_escrow:
        try:
            winner_sub = db.query(Submission).filter(
                Submission.id == task.winner_submission_id
            ).first()
            winner_user = db.query(User).filter(
                User.id == winner_sub.worker_id
            ).first() if winner_sub else None

            if winner_user:
                payout_amount = round(task.bounty * 0.80, 6)
                deposit_amount = task.submission_deposit or round(task.bounty * 0.10, 6)

                # 1. Lock bounty into escrow (first challenger triggers this)
                create_challenge_onchain(
                    task.id, winner_user.wallet, payout_amount, deposit_amount
                )

                # 2. Build verdict array
                verdicts = []
                for c in challenges:
                    if c.challenger_wallet:
                        result_map = {
                            ChallengeVerdict.upheld: 0,
                            ChallengeVerdict.rejected: 1,
                            ChallengeVerdict.malicious: 2,
                        }
                        verdicts.append({
                            "challenger": c.challenger_wallet,
                            "result": result_map.get(c.verdict, 1),
                        })

                # 3. Determine final winner wallet
                final_winner_wallet = winner_user.wallet

                # 4. Resolve on-chain
                tx_hash = resolve_challenge_onchain(
                    task.id, final_winner_wallet, verdicts
                )
                task.payout_status = PayoutStatus.paid
                task.payout_tx_hash = tx_hash
                task.payout_amount = payout_amount

        except Exception as e:
            task.payout_status = PayoutStatus.failed
            print(f"[scheduler] escrow settlement failed for {task.id}: {e}", flush=True)

        db.commit()
    else:
        # Legacy path: no escrow, direct pay_winner
        db.commit()
        pay_winner(db, task.id)
```

**Step 4: 运行测试确认通过**

```bash
cd /Users/nicholas/PycharmProjects/claw-bazzar
pytest tests/test_escrow_settlement.py -v
```

Expected: 2 tests PASS。

**Step 5: 运行全部后端测试**

```bash
cd /Users/nicholas/PycharmProjects/claw-bazzar
pytest -v
```

Expected: 全部 PASS。

**Step 6: Commit**

```bash
git add app/scheduler.py tests/test_escrow_settlement.py
git commit -m "feat: integrate escrow settlement into scheduler arbitration flow"
```

---

## Task 11: 前端 — Permit 签名工具函数

**Files:**
- Create: `frontend/lib/permit.ts`
- Create: `frontend/lib/permit.test.ts`

**Step 1: 写失败测试**

创建 `frontend/lib/permit.test.ts`：

```typescript
import { describe, it, expect } from 'vitest'
import { signChallengePermit } from './permit'

describe('signChallengePermit', () => {
  it('returns valid permit signature fields', async () => {
    // Use a known test private key
    const testKey = '0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80'
    const result = await signChallengePermit({
      privateKey: testKey,
      spender: '0x1234567890abcdef1234567890abcdef12345678',
      amount: 1.01, // 1 USDC deposit + 0.01 service fee
    })

    expect(result).toHaveProperty('v')
    expect(result).toHaveProperty('r')
    expect(result).toHaveProperty('s')
    expect(result).toHaveProperty('deadline')
    expect(typeof result.v).toBe('number')
    expect(result.r).toMatch(/^0x[0-9a-f]{64}$/)
    expect(result.s).toMatch(/^0x[0-9a-f]{64}$/)
    expect(result.deadline).toBeGreaterThan(Math.floor(Date.now() / 1000))
  })
})
```

**Step 2: 运行测试确认失败**

```bash
cd /Users/nicholas/PycharmProjects/claw-bazzar/frontend
npx vitest lib/permit.test.ts --run
```

Expected: FAIL — `./permit` 不存在。

**Step 3: 实现 permit.ts**

创建 `frontend/lib/permit.ts`：

```typescript
import { createPublicClient, createWalletClient, http, parseUnits, type Hex } from 'viem'
import { baseSepolia } from 'viem/chains'
import { privateKeyToAccount } from 'viem/accounts'

const USDC_ADDRESS = '0x036CbD53842c5426634e7929541eC2318f3dCF7e' as const

export interface PermitResult {
  v: number
  r: string
  s: string
  deadline: number
  nonce: bigint
}

export async function signChallengePermit(params: {
  privateKey: Hex
  spender: string   // ChallengeEscrow contract address
  amount: number    // USDC amount (deposit + service fee)
}): Promise<PermitResult> {
  const account = privateKeyToAccount(params.privateKey)

  const publicClient = createPublicClient({
    chain: baseSepolia,
    transport: http(),
  })

  const walletClient = createWalletClient({
    account,
    chain: baseSepolia,
    transport: http(),
  })

  // Get current nonce from USDC contract
  let nonce: bigint
  try {
    nonce = await publicClient.readContract({
      address: USDC_ADDRESS,
      abi: [{ name: 'nonces', type: 'function', stateMutability: 'view', inputs: [{ name: 'owner', type: 'address' }], outputs: [{ type: 'uint256' }] }],
      functionName: 'nonces',
      args: [account.address],
    }) as bigint
  } catch {
    nonce = 0n
  }

  const deadline = Math.floor(Date.now() / 1000) + 3600 // 1 hour from now
  const value = parseUnits(params.amount.toString(), 6) // USDC 6 decimals

  const signature = await walletClient.signTypedData({
    domain: {
      name: 'USDC',
      version: '2',
      chainId: 84532,
      verifyingContract: USDC_ADDRESS,
    },
    types: {
      Permit: [
        { name: 'owner', type: 'address' },
        { name: 'spender', type: 'address' },
        { name: 'value', type: 'uint256' },
        { name: 'nonce', type: 'uint256' },
        { name: 'deadline', type: 'uint256' },
      ],
    },
    primaryType: 'Permit',
    message: {
      owner: account.address,
      spender: params.spender as `0x${string}`,
      value,
      nonce,
      deadline: BigInt(deadline),
    },
  })

  // Parse signature into v, r, s
  const r = `0x${signature.slice(2, 66)}`
  const s = `0x${signature.slice(66, 130)}`
  const v = parseInt(signature.slice(130, 132), 16)

  return { v, r, s, deadline, nonce }
}
```

**Step 4: 运行测试确认通过**

```bash
cd /Users/nicholas/PycharmProjects/claw-bazzar/frontend
npx vitest lib/permit.test.ts --run
```

Expected: PASS。

**Step 5: Commit**

```bash
git add frontend/lib/permit.ts frontend/lib/permit.test.ts
git commit -m "feat(frontend): add EIP-2612 permit signing for challenge deposits"
```

---

## Task 12: 前端 — API 层更新

**Files:**
- Modify: `frontend/lib/api.ts` (createChallenge 函数)

**Step 1: 阅读现有 api.ts 的 createChallenge**

参考 `frontend/lib/api.ts` 中的 `createChallenge` 函数，添加新字段。

**Step 2: 更新 createChallenge API 函数**

在 `frontend/lib/api.ts` 中修改 `createChallenge` 函数，增加可选的 escrow 字段：

```typescript
export async function createChallenge(
  taskId: string,
  data: {
    challenger_submission_id: string
    reason: string
    challenger_wallet?: string
    permit_deadline?: number
    permit_v?: number
    permit_r?: string
    permit_s?: string
  }
): Promise<Challenge> {
  const res = await fetch(`/api/tasks/${taskId}/challenges`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}
```

同时更新 `Challenge` 类型，添加新字段：

```typescript
export interface Challenge {
  id: string
  task_id: string
  challenger_submission_id: string
  target_submission_id: string
  reason: string
  verdict: ChallengeVerdict | null
  arbiter_feedback: string | null
  arbiter_score: number | null
  status: ChallengeStatus
  challenger_wallet: string | null    // new
  deposit_tx_hash: string | null      // new
  created_at: string
}
```

**Step 3: Commit**

```bash
git add frontend/lib/api.ts
git commit -m "feat(frontend): update challenge API types with escrow fields"
```

---

## Task 13: 前端 — DevPanel 集成挑战签名

**Files:**
- Modify: `frontend/components/DevPanel.tsx` (challenge form section)
- Modify: `frontend/components/ChallengePanel.tsx` (challenge create form)

**Step 1: 更新 DevPanel 挑战表单**

在 DevPanel 的挑战提交部分，添加 permit 签名步骤：

1. 从活跃 worker 的私钥计算钱包地址
2. 调用 `signChallengePermit()` 签名
3. 把签名参数传给 `createChallenge()` API

```typescript
import { signChallengePermit } from '../lib/permit'

// Inside challenge submit handler:
const ESCROW_ADDRESS = process.env.NEXT_PUBLIC_ESCROW_CONTRACT_ADDRESS || ''
const workerKey = getActiveWorkerKey() // 当前选择的 worker 私钥

if (ESCROW_ADDRESS && workerKey) {
  const depositAmount = task.submission_deposit || task.bounty * 0.1
  const totalAmount = depositAmount + 0.01 // + service fee

  const permit = await signChallengePermit({
    privateKey: workerKey as `0x${string}`,
    spender: ESCROW_ADDRESS,
    amount: totalAmount,
  })

  await createChallenge(taskId, {
    challenger_submission_id: submissionId,
    reason,
    challenger_wallet: getDevWalletAddress(workerKey as `0x${string}`),
    permit_deadline: permit.deadline,
    permit_v: permit.v,
    permit_r: permit.r,
    permit_s: permit.s,
  })
} else {
  // Fallback: no escrow (legacy)
  await createChallenge(taskId, {
    challenger_submission_id: submissionId,
    reason,
  })
}
```

**Step 2: 更新 ChallengePanel**

在 ChallengePanel.tsx 的 ChallengeCreateForm 中显示 `deposit_tx_hash`（如果存在）。在 ChallengeCard 中展示链上交易链接。

**Step 3: 运行前端测试**

```bash
cd /Users/nicholas/PycharmProjects/claw-bazzar/frontend
npm test
```

Expected: 全部 PASS。

**Step 4: 运行前端 lint**

```bash
cd /Users/nicholas/PycharmProjects/claw-bazzar/frontend
npm run lint
```

Expected: 无错误。

**Step 5: Commit**

```bash
git add frontend/components/DevPanel.tsx frontend/components/ChallengePanel.tsx
git commit -m "feat(frontend): integrate permit signing into challenge UI"
```

---

## Task 14: 环境变量 + 文档更新

**Files:**
- Modify: `.env` (add ESCROW_CONTRACT_ADDRESS)
- Modify: `frontend/.env.local` (add NEXT_PUBLIC_ESCROW_CONTRACT_ADDRESS)
- Modify: `CLAUDE.md` (update architecture docs)

**Step 1: 添加环境变量**

在 `.env` 追加：
```
ESCROW_CONTRACT_ADDRESS=
```

在 `frontend/.env.local` 追加：
```
NEXT_PUBLIC_ESCROW_CONTRACT_ADDRESS=
```

**Step 2: 更新 CLAUDE.md**

在 CLAUDE.md 的 Key environment variables 表格中添加 `ESCROW_CONTRACT_ADDRESS` 行。

在 "Two settlement paths" 部分增加关于 escrow 的描述。

**Step 3: Commit**

```bash
git add .env frontend/.env.local CLAUDE.md
git commit -m "docs: add escrow environment variables and update architecture docs"
```

---

## Task 15: 全量回归测试

**Step 1: 运行全部后端测试**

```bash
cd /Users/nicholas/PycharmProjects/claw-bazzar
pytest -v
```

Expected: 全部 PASS。

**Step 2: 运行全部前端测试**

```bash
cd /Users/nicholas/PycharmProjects/claw-bazzar/frontend
npm test
```

Expected: 全部 PASS。

**Step 3: 运行合约测试**

```bash
cd /Users/nicholas/PycharmProjects/claw-bazzar/contracts
forge test -vv
```

Expected: 全部 PASS。

**Step 4: 启动 dev server 手动验证**

```bash
cd /Users/nicholas/PycharmProjects/claw-bazzar
uvicorn app.main:app --reload --port 8000 &
cd frontend && npm run dev &
```

手动在 DevPanel 测试：
1. 发布 quality_first 任务
2. 提交两个 submission
3. 等待 challenge_window
4. 提交带 permit 签名的 challenge
5. 验证挑战创建成功

**Step 5: 确认无回归后做最终 commit（如有遗漏修复）**

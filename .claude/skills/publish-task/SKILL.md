---
name: publish-task
description: 在 Claw Bazzar 平台发布任务。注册 Publisher 用户（如需），构造任务参数，通过 x402 协议支付赏金，验证任务创建成功。
---

# 发布任务技能

以 Publisher 身份在 Claw Bazzar 平台发布一个带赏金的任务。

## 前置条件

- 后端服务运行在 `http://localhost:8000`
- 钱包有足够 USDC（Base Sepolia）

## 工作流程

### 步骤一：确认或注册 Publisher 用户

检查是否已有用户身份。如果没有，注册一个：

```bash
# 查询已有用户
curl -s 'http://localhost:8000/users?nickname=<你的昵称>'

# 注册新用户（如需）
curl -s -X POST http://localhost:8000/users \
  -H 'Content-Type: application/json' \
  -d '{"nickname": "<唯一昵称>", "wallet": "<以太坊钱包地址>", "role": "publisher"}'
```

**保存返回的 `id` 字段**，后续步骤需要用它作为 `publisher_id`。

### 步骤二：确定任务参数

根据用户需求确定以下参数：

| 参数 | 说明 | 决策点 |
|------|------|--------|
| `type` | 结算模式 | 简单标准答案→`fastest_first`；需要竞争比较→`quality_first` |
| `bounty` | 赏金金额 | 最低 0.1 USDC |
| `deadline` | 截止时间 | fastest_first 建议 ≥15 分钟；quality_first 建议 ≥1 小时 |
| `threshold` | 通过分数 | 仅 fastest_first 必填，推荐 0.6-0.8 |
| `max_revisions` | 最大修改次数 | 仅 quality_first，推荐 2-3 |
| `challenge_duration` | 挑战窗口（秒）| 仅 quality_first，默认 7200（2小时）|

### 步骤三：编写 acceptance_criteria

**这是最重要的步骤**。Oracle 基于此生成评分维度、执行门检、指导评分。

编写原则：
- 每条标准必须**可客观验证**
- 包含**量化指标**（数量、格式、覆盖范围）
- **结构明确**（指定格式、包含哪些部分）
- 至少 1 条，建议 3-5 条

好的写法示例：
```
["函数必须接受 list[int] 参数并返回排序后的新列表",
 "代码覆盖率必须超过 80%",
 "报告必须使用 Markdown 格式，包含标题、摘要、详情三节"]
```

避免的写法：
- "代码要写得好" ← 太模糊
- "结果令人满意" ← 无法客观判断

### 步骤四：发布任务

发布需通过 x402 协议签名支付赏金。流程：

1. 先不带 X-PAYMENT header 发送请求，获取 402 支付要求
2. 根据返回的 payment requirements 构造 EIP-712 签名
3. 将签名 base64 编码后放入 X-PAYMENT header 重新发送

```bash
# 第一步：获取支付要求（HTTP 402）
curl -s -X POST http://localhost:8000/tasks \
  -H 'Content-Type: application/json' \
  -d '{"title":"...","description":"...","type":"fastest_first","threshold":0.6,"deadline":"...","publisher_id":"...","bounty":5.0,"acceptance_criteria":["..."]}'

# 返回 402 响应包含: scheme, network, asset, amount, payTo
# 用这些信息构造 EIP-712 TransferWithAuthorization 签名

# 第二步：带签名重新发送
curl -s -X POST http://localhost:8000/tasks \
  -H 'Content-Type: application/json' \
  -H 'X-PAYMENT: <base64编码的支付签名>' \
  -d '{...同上...}'
```

x402 签名结构（base64 编码前的 JSON）：
```json
{
  "x402Version": 2,
  "resource": {
    "url": "task-creation",
    "description": "Task creation payment",
    "mimeType": "application/json"
  },
  "accepted": {
    "scheme": "exact",
    "network": "eip155:84532",
    "asset": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
    "amount": "<bounty×1e6 的字符串>",
    "payTo": "<平台钱包地址>",
    "maxTimeoutSeconds": 30,
    "extra": {"assetTransferMethod": "eip3009", "name": "USDC", "version": "2"}
  },
  "payload": {
    "signature": "<EIP-712签名>",
    "authorization": {
      "from": "<你的钱包>", "to": "<平台钱包>",
      "value": "<amount>", "validAfter": "0",
      "validBefore": "<当前时间+3600>", "nonce": "<随机32字节hex>"
    }
  }
}
```

**EIP-712 域（签名时使用）：**
```json
{
  "name": "USDC",
  "version": "2",
  "chainId": 84532,
  "verifyingContract": "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
}
```

> ⚠️ **域名必须是 `"USDC"`，不是 `"USD Coin"`**。写错会得到 `invalid_exact_evm_payload_signature`。

### 步骤五：验证发布结果

检查响应：

```
✅ HTTP 201 — 发布成功
  - id: 任务UUID（保存，后续用于查看和管理）
  - status: "open"
  - scoring_dimensions: 应包含 3 个固定维度（实质性、可信度、完整性）+ 1-3 个动态维度
  - payment_tx_hash: 链上交易哈希（付费任务）

❌ HTTP 400 — 参数错误，检查:
  - acceptance_criteria 是否为非空列表
  - bounty 是否 ≥ 0.1
  - fastest_first 是否提供了 threshold
  - deadline 是否为有效 ISO8601 UTC 时间

❌ HTTP 402 — 支付问题，检查 X-PAYMENT header
```

### 步骤六：确认评分维度

查看任务详情确认维度生成正确：

```bash
curl -s http://localhost:8000/tasks/<task_id> | python3 -m json.tool
```

关注 `scoring_dimensions` 字段：
- 应有 **实质性**（Substantiveness）— 内容深度
- 应有 **可信度**（Credibility）— 真实性和可靠性
- 应有 **完整性**（Completeness）— 验收标准覆盖
- 可能有 1-3 个基于 acceptance_criteria 生成的**动态维度**

## fastest_first vs quality_first 选择指南

| 场景 | 推荐模式 | 理由 |
|------|---------|------|
| 有明确正确答案 | fastest_first | 第一个达标即胜出，高效 |
| 编程题、翻译任务 | fastest_first | 标准客观，不需要横向比较 |
| 创意写作、设计方案 | quality_first | 需要多方竞争，择优 |
| 安全审计、深度分析 | quality_first | 需要充分时间和比较 |
| 高赏金重要任务 | quality_first | 挑战机制保障公平 |

## 常见问题

| 问题 | 解决 |
|------|------|
| 维度生成失败 | 检查 `ORACLE_LLM_PROVIDER` 和 API Key 配置 |
| `invalid_exact_evm_payload_signature` | EIP-712 域名写错（必须是 `"USDC"` 不是 `"USD Coin"`），或 payload 缺少 `resource` 字段 |
| 402 签名被拒（其他原因） | 确认钱包 USDC 余额、nonce 唯一、validBefore 未过期 |
| 请求超时（settlement 阶段）| 正常现象：verify 通过后 settle 需调用链上，httpx 客户端超时需设为 ≥120s |
| deadline 格式错误 | 必须是 ISO8601 UTC 格式，以 Z 结尾 |
| acceptance_criteria 拒绝 | 必须是非空的字符串列表（list[str]）|

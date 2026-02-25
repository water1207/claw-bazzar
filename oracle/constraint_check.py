"""Constraint check — task relevance + authenticity."""
from llm_client import call_llm_json

SHARED_CONSTRAINTS = """### 约束1: 任务契合度

检查要点:
- 提交的核心内容是否与任务描述的诉求对应
- 是否只满足了字面条件但偏离了任务的真实意图
- 是否只回答了问题的一小部分而忽略核心诉求
- 是否存在"格式正确但内容无关"的情况

判断标准:
- pass: 提交明确在回应任务诉求，即使角度或方式不同
- fail: 提交答非所问、严重偏题、或仅涉及任务边缘内容

### 约束2: 真实性

检查要点:
- 数据是否具体到可验证的程度
- 是否标注了数据来源或获取方式
- 不同数据点之间是否自相矛盾
- 是否存在过于精确但无来源的数据（编造特征）
- 格式正确但内容明显虚假的字段
- 大量数据高度雷同或模板化生成的迹象

判断标准:
- pass: 数据整体可信，即使部分数据无法验证但无明显编造痕迹
- fail: 存在明显编造、伪造、或大面积不可信内容"""

FF_SYSTEM = "你是 Agent Market 的快速验证 Oracle。判断提交是否存在恶意或低质量问题，返回严格JSON。"

FF_PROMPT = """## 你的任务
判断该提交是否存在恶意或低质量问题。这不是质量评分，只是合格性检查。

## 输入

### 任务描述
{task_description}

### 验收标准
{acceptance_criteria}

### 提交内容
{submission_payload}

## 检查项
{constraints}

## 判断尺度
- 偏向宽松: 只拦截明显的恶意/垃圾提交
- 质量平庸但诚实的提交应该 pass

## 输出格式 (严格JSON)

{{
  "task_relevance": {{ "passed": true/false, "reason": "..." }},
  "authenticity": {{ "passed": true/false, "reason": "..." }},
  "overall_passed": true/false,
  "rejection_reason": null
}}"""

QF_SYSTEM = "你是 Agent Market 的质量评分 Oracle，当前执行底层约束检查，返回严格JSON。"

QF_PROMPT = """## 你的任务
检查该提交是否存在任务契合度或真实性问题。你的判断将作为后续维度评分的约束条件。

## 输入

### 任务标题
{task_title}

### 任务描述
{task_description}

### 验收标准
{acceptance_criteria}

### 待检查提交
{submission_label}: {submission_payload}

## 检查项
{constraints}

## 触发后果
- 任务契合度 fail → 所有维度得分上限降至 30
- 真实性 fail → 相关维度得分上限降至 40
- 两者都 fail → 取更严格的上限（30）

## 判断尺度
- 不区分"好"和"更好"，只拦截明显有问题的提交
- 有疑虑但无确切证据时倾向 pass

## 输出格式 (严格JSON)

{{
  "submission_label": "{submission_label}",
  "task_relevance": {{
    "passed": true/false,
    "analysis": "详细分析...",
    "score_cap": null
  }},
  "authenticity": {{
    "passed": true/false,
    "analysis": "详细分析...",
    "flagged_issues": [],
    "score_cap": null
  }},
  "effective_cap": null
}}"""


def run(input_data: dict) -> dict:
    task_type = input_data.get("task_type", "fastest_first")

    if task_type == "fastest_first":
        prompt = FF_PROMPT.format(
            task_description=input_data.get("task_description", ""),
            acceptance_criteria=input_data.get("acceptance_criteria", ""),
            submission_payload=input_data.get("submission_payload", ""),
            constraints=SHARED_CONSTRAINTS,
        )
        result, _usage = call_llm_json(prompt, system=FF_SYSTEM)
        return result
    else:
        label = input_data.get("submission_label", "Submission_A")
        prompt = QF_PROMPT.format(
            task_title=input_data.get("task_title", ""),
            task_description=input_data.get("task_description", ""),
            acceptance_criteria=input_data.get("acceptance_criteria", ""),
            submission_payload=input_data.get("submission_payload", ""),
            submission_label=label,
            constraints=SHARED_CONSTRAINTS,
        )
        result, _usage = call_llm_json(prompt, system=QF_SYSTEM)
        return result

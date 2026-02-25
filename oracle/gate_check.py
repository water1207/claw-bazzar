"""Gate Check — verify submission meets acceptance criteria."""
from llm_client import call_llm_json

SYSTEM_PROMPT = "你是 Agent Market 的验收检查器。逐条检查提交是否满足验收标准，返回严格JSON。"

PROMPT_TEMPLATE = """## 你的任务
逐条检查提交是否满足发布者设定的验收标准。这是 pass/fail 判断，不涉及质量评分。

## 输入

### 任务描述
{task_description}

### 验收标准
{acceptance_criteria}

### 提交内容
{submission_payload}

## 规则

1. 对每一条验收标准独立判断 pass 或 fail
2. 判断时优先使用可量化的方式:
   - "不少于50条" → 直接计数
   - "每条必须包含邮箱" → 逐条检查字段存在性
3. 对模糊标准使用合理推断:
   - "要有数据支撑" → 检查是否存在量化数据、来源引用
   - "给出可操作建议" → 检查是否有具体执行步骤
4. 任何一条 fail = 整体 fail
5. 对每条判断给出 evidence
6. 对 fail 的条目给出 revision_hint

## 判断尺度
- 偏向宽松: 只要提交明显在尝试满足标准，即使有小瑕疵也 pass
- 边界情况倾向 pass，质量差异留给后续评分阶段区分

## 输出格式 (严格JSON)

{{
  "overall_passed": true/false,
  "criteria_checks": [
    {{
      "criteria": "原文验收标准",
      "passed": true/false,
      "evidence": "判断依据",
      "revision_hint": "（仅fail时）修订建议"
    }}
  ],
  "summary": "一句话总结"
}}"""


def run(input_data: dict) -> dict:
    prompt = PROMPT_TEMPLATE.format(
        task_description=input_data.get("task_description", ""),
        acceptance_criteria=input_data.get("acceptance_criteria", ""),
        submission_payload=input_data.get("submission_payload", ""),
    )
    result, _usage = call_llm_json(prompt, system=SYSTEM_PROMPT)
    return result

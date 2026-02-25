"""Dimension generation — called once when a task is created."""
from llm_client import call_llm_json

SYSTEM_PROMPT = "你是 Agent Market 的评分维度生成器。根据任务描述生成评分维度，返回严格JSON。"

PROMPT_TEMPLATE = """## 你的任务
根据任务描述和验收标准，生成评分维度。

## 输入

### 任务标题
{task_title}

### 任务描述
{task_description}

### 验收标准
{acceptance_criteria}

## 规则

1. 固定维度（必须包含）:
   - **实质性**: 评估提交是否提供了真正有价值的内容，而非形式完整但实质空洞的堆砌。
   - **完整性**: 评估提交是否覆盖了任务描述中提及的所有方面和需求点，无重大遗漏。

2. 动态维度（根据任务推断，1-3个）:
   - 必须直接来源于任务描述中的显式或隐式需求
   - 维度之间不能有高度重叠
   - 每个维度必须有明确的评判标准描述

3. 权重分配:
   - 所有维度权重总和 = 1
   - 权重反映任务描述中各方面的重要程度
   - 验收标准中反复强调的方面应获得更高权重

4. 总维度数量: 3-5个（含2个固定维度）

## 输出格式 (严格JSON)

{{
  "dimensions": [
    {{
      "id": "substantiveness",
      "name": "实质性",
      "type": "fixed",
      "description": "...(根据具体任务定制描述)",
      "weight": 0.xx,
      "scoring_guidance": "...(什么样的提交得高分，什么样得低分)"
    }},
    {{
      "id": "completeness",
      "name": "完整性",
      "type": "fixed",
      "description": "...",
      "weight": 0.xx,
      "scoring_guidance": "..."
    }},
    {{
      "id": "dynamic_dim_1",
      "name": "...",
      "type": "dynamic",
      "description": "...",
      "weight": 0.xx,
      "scoring_guidance": "..."
    }}
  ],
  "rationale": "解释维度选择和权重分配的理由"
}}"""


def run(input_data: dict) -> dict:
    prompt = PROMPT_TEMPLATE.format(
        task_title=input_data.get("task_title", ""),
        task_description=input_data.get("task_description", ""),
        acceptance_criteria=input_data.get("acceptance_criteria", ""),
    )
    return call_llm_json(prompt, system=SYSTEM_PROMPT)

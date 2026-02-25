"""Individual scoring — score a single submission on all dimensions + provide revision suggestions."""
from llm_client import call_llm_json

SYSTEM_PROMPT = "你是 Agent Market 的质量评分 Oracle。对单个提交在各维度独立打分并给出修订建议，返回严格JSON。"

PROMPT_TEMPLATE = """## 你的任务
对单个提交在每个评分维度上独立打分（0-100），并给出修订建议帮助提交者改进。

## 任务信息

### 标题
{task_title}

### 描述
{task_description}

## 评分维度

{dimensions_text}

## 提交内容
{submission_payload}

## 评分流程
1. 对每个维度独立评分（0-100）
2. 给出每个维度的简要反馈
3. 综合所有维度给出2-3条修订建议

## 打分标准
- 90-100: 显著超出预期
- 70-89: 良好完成，有亮点
- 50-69: 基本满足但平庸
- 30-49: 勉强相关但质量差
- 0-29: 几乎无价值

## 输出格式 (严格JSON)

{{
  "dimension_scores": {{
    "dim_id": {{ "score": 0-100, "feedback": "简要反馈" }}
  }},
  "revision_suggestions": ["建议1", "建议2"]
}}"""


def _format_dimensions(dimensions: list) -> str:
    lines = []
    for dim in dimensions:
        lines.append(f"### {dim['name']} (id: {dim['id']})")
        lines.append(f"描述: {dim['description']}")
        lines.append(f"评分指引: {dim['scoring_guidance']}")
        lines.append("")
    return "\n".join(lines)


def run(input_data: dict) -> dict:
    dimensions = input_data.get("dimensions", [])
    prompt = PROMPT_TEMPLATE.format(
        task_title=input_data.get("task_title", ""),
        task_description=input_data.get("task_description", ""),
        dimensions_text=_format_dimensions(dimensions),
        submission_payload=input_data.get("submission_payload", ""),
    )
    return call_llm_json(prompt, system=SYSTEM_PROMPT)

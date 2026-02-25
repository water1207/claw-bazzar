"""Dimension scoring — horizontal comparison of submissions on a single dimension."""
from llm_client import call_llm_json

SYSTEM_PROMPT = "你是 Agent Market 的质量评分 Oracle，当前对单一维度进行横向评分，返回严格JSON。"

PROMPT_TEMPLATE = """## 你的任务
在指定维度下，对所有提交进行横向比较并打分。只关注当前维度。

## 任务信息

### 标题
{task_title}

### 描述
{task_description}

## 当前评分维度

### 维度名称
{dim_name}

### 维度描述
{dim_description}

### 评分指引
{dim_scoring_guidance}

## 底层约束结果（来自 Step 1）

以下提交存在约束上限，该维度得分不得超过 cap 值:
{constraint_caps_text}

## 待评提交（已匿名化）

{submissions_text}

## 评分流程

### 1. 明确评判焦点
结合任务描述和维度定义，阐述该维度的评判重点。

### 2. 逐提交分析
对每个提交分析在该维度上的表现，具体引用提交中的内容作为 evidence。

### 3. 横向比较
将所有提交在该维度上的表现放在一起对比，说明排序理由。

### 4. 打分
0-100 分。如果该提交有 score_cap，最终得分不得超过 cap 值。

## 打分标准
- 90-100: 显著超出预期
- 70-89: 良好完成，有亮点
- 50-69: 基本满足但平庸
- 30-49: 勉强相关但质量差
- 0-29: 几乎无价值

## 输出格式 (严格JSON)

{{
  "dimension_id": "{dim_id}",
  "dimension_name": "{dim_name}",
  "evaluation_focus": "本次评判的具体焦点",
  "comparative_analysis": "横向比较说明",
  "scores": [
    {{
      "submission": "Submission_A",
      "raw_score": 85,
      "cap_applied": false,
      "final_score": 85,
      "evidence": "核心评分依据"
    }}
  ]
}}"""


def _format_caps(caps: dict) -> str:
    lines = []
    for label, cap in caps.items():
        if cap is not None:
            lines.append(f"- {label}: score_cap = {cap}")
        else:
            lines.append(f"- {label}: 无约束")
    return "\n".join(lines) if lines else "无约束"


def _format_submissions(submissions: list) -> str:
    lines = []
    for sub in submissions:
        lines.append(f"### {sub['label']}")
        lines.append(sub.get("payload", ""))
        lines.append("")
    return "\n".join(lines)


def run(input_data: dict) -> dict:
    dim = input_data.get("dimension", {})
    prompt = PROMPT_TEMPLATE.format(
        task_title=input_data.get("task_title", ""),
        task_description=input_data.get("task_description", ""),
        dim_id=dim.get("id", ""),
        dim_name=dim.get("name", ""),
        dim_description=dim.get("description", ""),
        dim_scoring_guidance=dim.get("scoring_guidance", ""),
        constraint_caps_text=_format_caps(input_data.get("constraint_caps", {})),
        submissions_text=_format_submissions(input_data.get("submissions", [])),
    )
    result, _usage = call_llm_json(prompt, system=SYSTEM_PROMPT)
    return result

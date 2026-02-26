"""Tests for oracle.py mode routing and V2 oracle modules."""
import json
import subprocess
import sys
from unittest.mock import patch

# Add oracle/ to path for direct module imports
sys.path.insert(0, "oracle")

MOCK_USAGE = {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}


# --- Legacy behavior tests (subprocess) ---

def test_oracle_legacy_feedback_mode():
    """Existing feedback mode should still work."""
    payload = json.dumps({"mode": "feedback"})
    result = subprocess.run(
        [sys.executable, "oracle/oracle.py"],
        input=payload, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert "suggestions" in output
    assert len(output["suggestions"]) == 3


def test_oracle_legacy_score_mode():
    """Existing score mode should still work."""
    payload = json.dumps({"mode": "score"})
    result = subprocess.run(
        [sys.executable, "oracle/oracle.py"],
        input=payload, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert "score" in output
    assert 0.5 <= output["score"] <= 1.0


def test_oracle_unknown_mode_falls_back_to_legacy():
    """Unknown modes should fall back to legacy score behavior."""
    payload = json.dumps({"mode": "nonexistent"})
    result = subprocess.run(
        [sys.executable, "oracle/oracle.py"],
        input=payload, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert "score" in output


# --- V2 module direct tests ---

MOCK_DIMENSIONS = {
    "dimensions": [
        {"id": "substantiveness", "name": "实质性", "type": "fixed",
         "description": "评估提交是否有实质内容", "weight": 0.25,
         "scoring_guidance": "高分: 有独到见解; 低分: 空洞堆砌"},
        {"id": "credibility", "name": "可信度", "type": "fixed",
         "description": "评估数据可信度", "weight": 0.25,
         "scoring_guidance": "高分: 数据可追溯; 低分: 数据编造"},
        {"id": "completeness", "name": "完整性", "type": "fixed",
         "description": "评估覆盖度", "weight": 0.25,
         "scoring_guidance": "高分: 覆盖全面; 低分: 遗漏重要方面"},
        {"id": "data_precision", "name": "数据精度", "type": "dynamic",
         "description": "数据准确性", "weight": 0.25,
         "scoring_guidance": "高分: 数据可验证; 低分: 数据模糊"},
    ],
    "rationale": "根据任务需求生成"
}


def test_dimension_gen_mode():
    """dimension_gen module should call LLM and return dimensions."""
    import dimension_gen
    input_data = {
        "mode": "dimension_gen",
        "task_title": "市场调研",
        "task_description": "调研竞品",
        "acceptance_criteria": "至少覆盖10个产品",
    }
    with patch.object(dimension_gen, "call_llm_json", return_value=(MOCK_DIMENSIONS, MOCK_USAGE)):
        output = dimension_gen.run(input_data)
    assert "dimensions" in output
    assert len(output["dimensions"]) == 4
    assert output["dimensions"][0]["id"] == "substantiveness"
    assert output["dimensions"][1]["id"] == "credibility"
    assert output["dimensions"][2]["id"] == "completeness"


def test_dimension_gen_prompt_includes_credibility():
    """dimension_gen prompt should include credibility as a fixed dimension."""
    import dimension_gen
    input_data = {
        "mode": "dimension_gen",
        "task_title": "市场调研",
        "task_description": "调研竞品",
        "acceptance_criteria": "至少覆盖10个产品",
    }
    captured_prompt = None

    def fake_call_llm_json(prompt, system=None):
        nonlocal captured_prompt
        captured_prompt = prompt
        return (MOCK_DIMENSIONS, MOCK_USAGE)

    with patch.object(dimension_gen, "call_llm_json", side_effect=fake_call_llm_json):
        output = dimension_gen.run(input_data)

    # Verify prompt contains credibility references
    assert "可信度" in captured_prompt
    assert "credibility" in captured_prompt

    # Verify output has 3 fixed dimensions with correct ids
    fixed_dims = [d for d in output["dimensions"] if d["type"] == "fixed"]
    assert len(fixed_dims) == 3
    fixed_ids = [d["id"] for d in fixed_dims]
    assert fixed_ids == ["substantiveness", "credibility", "completeness"]


MOCK_GATE_PASS = {
    "overall_passed": True,
    "criteria_checks": [
        {"criteria": "至少覆盖10个产品", "passed": True, "evidence": "共计12个产品"}
    ],
    "summary": "已通过验收"
}

MOCK_GATE_FAIL = {
    "overall_passed": False,
    "criteria_checks": [
        {"criteria": "至少覆盖10个产品", "passed": False,
         "evidence": "仅8个", "revision_hint": "需补充至少2个产品"}
    ],
    "summary": "未通过验收"
}


def test_gate_check_pass():
    import gate_check
    input_data = {
        "mode": "gate_check",
        "task_description": "调研竞品",
        "acceptance_criteria": "至少覆盖10个产品",
        "submission_payload": "共12个产品的调研报告...",
    }
    with patch.object(gate_check, "call_llm_json", return_value=(MOCK_GATE_PASS, MOCK_USAGE)):
        output = gate_check.run(input_data)
    assert output["overall_passed"] is True


def test_gate_check_fail():
    import gate_check
    input_data = {
        "mode": "gate_check",
        "task_description": "调研竞品",
        "acceptance_criteria": "至少覆盖10个产品",
        "submission_payload": "仅8个产品...",
    }
    with patch.object(gate_check, "call_llm_json", return_value=(MOCK_GATE_FAIL, MOCK_USAGE)):
        output = gate_check.run(input_data)
    assert output["overall_passed"] is False
    assert output["criteria_checks"][0]["revision_hint"] is not None


MOCK_CONSTRAINT_FF_PASS = {
    "task_relevance": {"passed": True, "reason": "提交切题"},
    "authenticity": {"passed": True, "reason": "数据可信"},
    "overall_passed": True,
    "rejection_reason": None,
}

MOCK_CONSTRAINT_QF = {
    "submission_label": "Submission_A",
    "task_relevance": {"passed": True, "analysis": "切题", "score_cap": None},
    "authenticity": {"passed": False, "analysis": "数据疑似编造",
                     "flagged_issues": ["来源不可验证"], "score_cap": 40},
    "effective_cap": 40,
}


def test_constraint_check_fastest_first():
    import constraint_check
    input_data = {
        "mode": "constraint_check",
        "task_type": "fastest_first",
        "task_title": "Test", "task_description": "Desc",
        "acceptance_criteria": "AC",
        "submission_payload": "content",
    }
    with patch.object(constraint_check, "call_llm_json", return_value=(MOCK_CONSTRAINT_FF_PASS, MOCK_USAGE)):
        output = constraint_check.run(input_data)
    assert output["overall_passed"] is True


def test_constraint_check_quality_first():
    import constraint_check
    input_data = {
        "mode": "constraint_check",
        "task_type": "quality_first",
        "task_title": "Test", "task_description": "Desc",
        "acceptance_criteria": "AC",
        "submission_payload": "content",
        "submission_label": "Submission_A",
    }
    with patch.object(constraint_check, "call_llm_json", return_value=(MOCK_CONSTRAINT_QF, MOCK_USAGE)):
        output = constraint_check.run(input_data)
    assert output["effective_cap"] == 40


MOCK_INDIVIDUAL_SCORE = {
    "dimension_scores": {
        "substantiveness": {"band": "B", "score": 72, "evidence": "内容充实", "feedback": "内容充实但缺少深度分析"},
        "completeness": {"band": "C", "score": 65, "evidence": "覆盖了大部分", "feedback": "覆盖了大部分需求"},
        "data_precision": {"band": "B", "score": 80, "evidence": "数据精确", "feedback": "数据精确"},
    },
    "overall_band": "B",
    "revision_suggestions": [
        {"problem": "竞品对比不足", "suggestion": "建议增加竞品对比分析", "severity": "high"},
        {"problem": "数据来源缺失", "suggestion": "部分数据缺少来源标注", "severity": "medium"},
    ]
}


def test_score_individual():
    import score_individual
    input_data = {
        "mode": "score_individual",
        "task_title": "市场调研",
        "task_description": "调研竞品",
        "dimensions": [
            {"id": "substantiveness", "name": "实质性", "description": "内容质量",
             "weight": 0.3, "scoring_guidance": "guide1"},
            {"id": "completeness", "name": "完整性", "description": "覆盖度",
             "weight": 0.3, "scoring_guidance": "guide2"},
            {"id": "data_precision", "name": "数据精度", "description": "准确性",
             "weight": 0.4, "scoring_guidance": "guide3"},
        ],
        "submission_payload": "调研报告内容...",
    }
    with patch.object(score_individual, "call_llm_json", return_value=(MOCK_INDIVIDUAL_SCORE, MOCK_USAGE)):
        output = score_individual.run(input_data)
    assert "dimension_scores" in output
    assert "revision_suggestions" in output
    assert output["dimension_scores"]["substantiveness"]["score"] == 72
    assert output["dimension_scores"]["substantiveness"]["band"] == "B"
    assert "overall_band" in output
    assert len(output["revision_suggestions"]) == 2


MOCK_DIM_SCORE = {
    "dimension_id": "substantiveness",
    "dimension_name": "实质性",
    "evaluation_focus": "内容深度和独到性",
    "comparative_analysis": "A优于B和C",
    "scores": [
        {"submission": "Submission_A", "raw_score": 85, "cap_applied": False,
         "final_score": 85, "evidence": "深度分析到位"},
        {"submission": "Submission_B", "raw_score": 72, "cap_applied": True,
         "final_score": 40, "evidence": "有价值但真实性存疑"},
        {"submission": "Submission_C", "raw_score": 60, "cap_applied": False,
         "final_score": 60, "evidence": "基本满足"},
    ]
}


def test_dimension_score():
    import dimension_score
    input_data = {
        "mode": "dimension_score",
        "task_title": "市场调研",
        "task_description": "调研竞品",
        "dimension": {
            "id": "substantiveness", "name": "实质性",
            "description": "内容质量", "scoring_guidance": "guide",
        },
        "constraint_caps": {
            "Submission_A": None, "Submission_B": 40, "Submission_C": None,
        },
        "submissions": [
            {"label": "Submission_A", "payload": "content A"},
            {"label": "Submission_B", "payload": "content B"},
            {"label": "Submission_C", "payload": "content C"},
        ],
    }
    with patch.object(dimension_score, "call_llm_json", return_value=(MOCK_DIM_SCORE, MOCK_USAGE)):
        output = dimension_score.run(input_data)
    assert output["dimension_id"] == "substantiveness"
    assert len(output["scores"]) == 3
    assert output["scores"][1]["cap_applied"] is True
    assert output["scores"][1]["final_score"] == 40

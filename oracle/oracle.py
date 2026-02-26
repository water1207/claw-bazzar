#!/usr/bin/env python3
"""Oracle V2 — mode router. Dispatches to sub-modules or falls back to V1 stub."""
import json
import random
import sys

FEEDBACK_SUGGESTIONS = [
    "建议加强代码注释，提高可读性",
    "考虑增加边界条件的处理逻辑",
    "可以优化算法时间复杂度",
    "建议补充单元测试覆盖",
    "接口设计可以更简洁明了",
    "错误处理逻辑需要完善",
    "变量命名建议更具描述性",
    "可以抽取公共逻辑为独立函数",
    "建议增加输入参数校验",
    "文档注释缺失，建议补全",
]

V2_MODES = {}

def _register_v2_modules():
    """Lazy-import V2 modules. Only loaded when needed."""
    global V2_MODES
    if V2_MODES:
        return
    try:
        import os
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from dimension_gen import run as dimension_gen_run
        from gate_check import run as gate_check_run
        from score_individual import run as score_individual_run
        from dimension_score import run as dimension_score_run
        V2_MODES = {
            "dimension_gen": dimension_gen_run,
            "gate_check": gate_check_run,
            "score_individual": score_individual_run,
            "dimension_score": dimension_score_run,
        }
    except ImportError:
        pass  # V2 modules not yet available, fall back to legacy


def _legacy_handler(payload: dict) -> dict:
    """V1 stub behavior: feedback or score mode."""
    mode = payload.get("mode", "score")
    if mode == "feedback":
        suggestions = random.sample(FEEDBACK_SUGGESTIONS, 3)
        return {"suggestions": suggestions}
    else:
        score = round(random.uniform(0.5, 1.0), 2)
        return {"score": score, "feedback": f"Stub oracle: random score {score}"}


def main():
    payload = json.loads(sys.stdin.read())
    mode = payload.get("mode", "score")

    _register_v2_modules()

    if mode in V2_MODES:
        # Reset and track token usage for V2 LLM calls
        from llm_client import reset_accumulated_usage, get_accumulated_usage
        reset_accumulated_usage()
        result = V2_MODES[mode](payload)
        result["_token_usage"] = get_accumulated_usage()
    else:
        result = _legacy_handler(payload)

    print(json.dumps(result))


if __name__ == "__main__":
    main()

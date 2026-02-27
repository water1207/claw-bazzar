"""Prompt injection guard — rule-based detection, zero LLM calls."""
import re

# 各模式需要检测的字段
FIELDS_BY_MODE = {
    "gate_check": ["submission_payload"],
    "score_individual": ["submission_payload"],
    "dimension_gen": ["acceptance_criteria"],
    "dimension_score": ["submission_payloads"],  # 列表，特殊处理
}

# 注入检测正则（中英文）
_PATTERNS: list[tuple[str, str]] = [
    # 指令覆盖
    (r"(?i)(ignore|forget|disregard)\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions?|rules?|context|prompts?)",
     "instruction_override_en"),
    (r"忽略(之前|以上|上面|前面|所有)的?(所有)?(指令|规则|提示|要求|内容)",
     "instruction_override_zh"),
    # 角色注入
    (r"(?i)(you\s+are\s+now|act\s+as|pretend\s+to\s+be|roleplay\s+as)\b",
     "role_injection_en"),
    (r"(你现在是|你是一个新的|假装你是|你来扮演|扮演你是|roleplay)",
     "role_injection_zh"),
    # 系统提示操控
    (r"(?i)(system\s*prompt|system\s*instruction|hidden\s*instruction|override\s*instruction)",
     "system_prompt_manipulation"),
    (r"(系统提示词?|隐藏指令|覆盖指令|取消(之前的?)?指令)",
     "system_prompt_manipulation_zh"),
    # 输出劫持
    (r"(?i)(always\s+output|must\s+output|output\s+only|you\s+must\s+respond\s+with)",
     "output_hijack_en"),
    (r"(你必须输出|强制返回|你只能输出|你必须回复)",
     "output_hijack_zh"),
    # 分隔符伪造（三条或以上 --- 后接类指令内容）
    (r"(?m)^-{3,}\s*\n[\s\S]{0,200}?(指令|instruction|override|ignore|忽略|系统)",
     "separator_injection"),
]

_COMPILED = [(re.compile(pat), name) for pat, name in _PATTERNS]


def check(text: str, field: str) -> dict:
    """Check a single text field for injection patterns.

    Returns:
        {"detected": bool, "reason": str, "field": str}
    """
    if not text:
        return {"detected": False, "reason": "", "field": field}

    for pattern, name in _COMPILED:
        m = pattern.search(text)
        if m:
            return {
                "detected": True,
                "reason": f"injection pattern '{name}' matched: '{m.group(0)[:80]}'",
                "field": field,
            }

    return {"detected": False, "reason": "", "field": field}


def check_payload(payload: dict, mode: str) -> dict:
    """Check all user-controlled fields in an oracle payload for a given mode.

    Returns first detected result, or {"detected": False, ...} if clean.
    """
    fields = FIELDS_BY_MODE.get(mode, [])

    for field in fields:
        if field == "submission_payloads":
            # dimension_score: submissions is a list of dicts with "payload" key
            for sub in payload.get("submissions", []):
                sub_text = sub.get("payload", "")
                result = check(sub_text, "submission_payload")
                if result["detected"]:
                    return result
        else:
            text = payload.get(field, "")
            result = check(text, field)
            if result["detected"]:
                return result

    return {"detected": False, "reason": "", "field": ""}

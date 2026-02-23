#!/usr/bin/env python3
"""Oracle stub — V1. Supports feedback and score modes."""
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


def main():
    payload = json.loads(sys.stdin.read())
    mode = payload.get("mode", "score")

    if mode == "feedback":
        suggestions = random.sample(FEEDBACK_SUGGESTIONS, 3)
        print(json.dumps({"suggestions": suggestions}))
    else:
        score = round(random.uniform(0.5, 1.0), 2)
        print(json.dumps({
            "score": score,
            "feedback": f"Stub oracle: random score {score}",
        }))


if __name__ == "__main__":
    main()

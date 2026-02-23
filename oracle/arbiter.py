#!/usr/bin/env python3
"""Arbiter stub — V1. Rejects all challenges."""
import json
import sys


def main():
    payload = json.loads(sys.stdin.read())
    challenges = payload.get("challenges", [])
    verdicts = []
    for c in challenges:
        verdicts.append({
            "challenge_id": c["id"],
            "verdict": "rejected",
            "score": 0,
            "feedback": "Stub arbiter: challenge rejected",
        })
    print(json.dumps({"verdicts": verdicts}))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Oracle stub — V1. Auto-approves all submissions with score 0.9."""
import json
import sys


def main():
    payload = json.loads(sys.stdin.read())
    # Stub: always return 0.9
    # Replace this logic in future versions with real evaluation
    print(json.dumps({
        "score": 0.9,
        "feedback": "Stub oracle: auto-approved with score 0.9",
    }))


if __name__ == "__main__":
    main()

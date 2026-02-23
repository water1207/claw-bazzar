#!/usr/bin/env python3
"""Oracle stub — V1. Returns a random score between 0.5 and 1.0."""
import json
import random
import sys


def main():
    payload = json.loads(sys.stdin.read())
    score = round(random.uniform(0.5, 1.0), 2)
    print(json.dumps({
        "score": score,
        "feedback": f"Stub oracle: random score {score}",
    }))


if __name__ == "__main__":
    main()

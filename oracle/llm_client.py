"""LLM API client wrapper. Default: Anthropic Claude. Configurable via env vars."""
import json
import os


def call_llm(prompt: str, system: str = None) -> str:
    """Call LLM API and return raw text response.

    Env vars:
        ORACLE_LLM_PROVIDER: "anthropic" (default)
        ORACLE_LLM_MODEL: model name (default "claude-sonnet-4-20250514")
        ANTHROPIC_API_KEY: API key for Anthropic
    """
    provider = os.environ.get("ORACLE_LLM_PROVIDER", "anthropic")
    model = os.environ.get("ORACLE_LLM_MODEL", "claude-sonnet-4-20250514")

    if provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=model,
            max_tokens=4096,
            system=system or "",
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text
    else:
        raise ValueError(f"Unsupported provider: {provider}")


def call_llm_json(prompt: str, system: str = None) -> dict:
    """Call LLM and parse response as JSON. Strips markdown code fences if present."""
    raw = call_llm(prompt, system)
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]  # remove opening fence
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return json.loads(text)

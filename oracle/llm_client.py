"""LLM API client wrapper. Supports Anthropic and OpenAI-compatible APIs (e.g. SiliconFlow)."""
import json
import os

# Module-level usage accumulator (reset per oracle invocation)
_accumulated_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def reset_accumulated_usage():
    """Reset the accumulated token usage counters."""
    global _accumulated_usage
    _accumulated_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def get_accumulated_usage() -> dict:
    """Return a copy of the accumulated token usage."""
    return dict(_accumulated_usage)


def _clean_surrogates(s: str) -> str:
    """Replace lone surrogate characters (e.g. \\udca0) that are invalid in UTF-8."""
    return s.encode("utf-8", errors="replace").decode("utf-8")


def call_llm(prompt: str, system: str = None) -> tuple[str, dict]:
    """Call LLM API and return (text, usage_dict).

    Env vars:
        ORACLE_LLM_PROVIDER: "anthropic" or "openai" (default "openai")
        ORACLE_LLM_MODEL: model name
        ORACLE_LLM_BASE_URL: base URL for OpenAI-compatible APIs (e.g. SiliconFlow)
        ANTHROPIC_API_KEY: API key for Anthropic provider
        OPENAI_API_KEY: API key for OpenAI-compatible provider
    """
    prompt = _clean_surrogates(prompt)
    if system:
        system = _clean_surrogates(system)
    global _accumulated_usage
    provider = os.environ.get("ORACLE_LLM_PROVIDER", "openai")
    model = os.environ.get("ORACLE_LLM_MODEL", "")
    base_url = os.environ.get("ORACLE_LLM_BASE_URL", "")

    if provider == "openai":
        import openai
        kwargs = {}
        if base_url:
            kwargs["base_url"] = base_url
        client = openai.OpenAI(**kwargs)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = client.chat.completions.create(
            model=model,
            max_tokens=4096,
            messages=messages,
        )
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        if resp.usage:
            usage["prompt_tokens"] = resp.usage.prompt_tokens or 0
            usage["completion_tokens"] = resp.usage.completion_tokens or 0
            usage["total_tokens"] = resp.usage.total_tokens or 0
        _accumulated_usage["prompt_tokens"] += usage["prompt_tokens"]
        _accumulated_usage["completion_tokens"] += usage["completion_tokens"]
        _accumulated_usage["total_tokens"] += usage["total_tokens"]
        return resp.choices[0].message.content, usage
    elif provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=model or "claude-sonnet-4-20250514",
            max_tokens=4096,
            system=system or "",
            messages=[{"role": "user", "content": prompt}],
        )
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        if resp.usage:
            usage["prompt_tokens"] = resp.usage.input_tokens or 0
            usage["completion_tokens"] = resp.usage.output_tokens or 0
            usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
        _accumulated_usage["prompt_tokens"] += usage["prompt_tokens"]
        _accumulated_usage["completion_tokens"] += usage["completion_tokens"]
        _accumulated_usage["total_tokens"] += usage["total_tokens"]
        return resp.content[0].text, usage
    else:
        raise ValueError(f"Unsupported provider: {provider}")


def call_llm_json(prompt: str, system: str = None) -> tuple[dict, dict]:
    """Call LLM and parse response as JSON. Returns (parsed_dict, usage_dict).
    Strips markdown code fences if present."""
    raw, usage = call_llm(prompt, system)
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]  # remove opening fence
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return json.loads(text), usage

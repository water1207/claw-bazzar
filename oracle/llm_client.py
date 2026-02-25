"""LLM API client wrapper. Supports Anthropic and OpenAI-compatible APIs (e.g. SiliconFlow)."""
import json
import os


def call_llm(prompt: str, system: str = None) -> str:
    """Call LLM API and return raw text response.

    Env vars:
        ORACLE_LLM_PROVIDER: "anthropic" or "openai" (default "openai")
        ORACLE_LLM_MODEL: model name
        ORACLE_LLM_BASE_URL: base URL for OpenAI-compatible APIs (e.g. SiliconFlow)
        ANTHROPIC_API_KEY: API key for Anthropic provider
        OPENAI_API_KEY: API key for OpenAI-compatible provider
    """
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
        return resp.choices[0].message.content
    elif provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=model or "claude-sonnet-4-20250514",
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

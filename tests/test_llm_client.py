"""Tests for LLM client wrapper."""
import json
import pytest
from unittest.mock import patch, MagicMock


def test_call_llm_anthropic():
    """call_llm should use anthropic SDK and return (text, usage) tuple."""
    import sys
    sys.path.insert(0, "oracle")
    from llm_client import call_llm, reset_accumulated_usage
    sys.path.pop(0)

    mock_usage = MagicMock()
    mock_usage.input_tokens = 100
    mock_usage.output_tokens = 50

    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text='{"result": "test"}')]
    mock_resp.usage = mock_usage

    reset_accumulated_usage()
    with patch.dict("os.environ", {"ORACLE_LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "test-key"}):
        with patch("anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = mock_resp
            text, usage = call_llm("test prompt", system="test system")

    assert text == '{"result": "test"}'
    assert usage["prompt_tokens"] == 100
    assert usage["completion_tokens"] == 50
    assert usage["total_tokens"] == 150
    MockClient.return_value.messages.create.assert_called_once()
    call_args = MockClient.return_value.messages.create.call_args
    assert call_args.kwargs["messages"] == [{"role": "user", "content": "test prompt"}]
    assert call_args.kwargs["system"] == "test system"


def test_call_llm_openai_compatible():
    """call_llm should use openai SDK with custom base_url and return (text, usage)."""
    import sys
    sys.path.insert(0, "oracle")
    from llm_client import call_llm, reset_accumulated_usage
    sys.path.pop(0)

    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 200
    mock_usage.completion_tokens = 80
    mock_usage.total_tokens = 280

    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content='{"result": "ok"}'))]
    mock_resp.usage = mock_usage

    env = {
        "ORACLE_LLM_PROVIDER": "openai",
        "ORACLE_LLM_BASE_URL": "https://api.siliconflow.cn/v1",
        "ORACLE_LLM_MODEL": "Qwen/Qwen2.5-72B-Instruct",
        "OPENAI_API_KEY": "test-key",
    }
    reset_accumulated_usage()
    with patch.dict("os.environ", env):
        with patch("openai.OpenAI") as MockClient:
            MockClient.return_value.chat.completions.create.return_value = mock_resp
            text, usage = call_llm("test prompt", system="test system")

    assert text == '{"result": "ok"}'
    assert usage["prompt_tokens"] == 200
    assert usage["completion_tokens"] == 80
    assert usage["total_tokens"] == 280
    MockClient.assert_called_once_with(base_url="https://api.siliconflow.cn/v1")
    call_args = MockClient.return_value.chat.completions.create.call_args
    assert call_args.kwargs["messages"] == [
        {"role": "system", "content": "test system"},
        {"role": "user", "content": "test prompt"},
    ]


def test_call_llm_unsupported_provider():
    import sys
    sys.path.insert(0, "oracle")
    from llm_client import call_llm
    sys.path.pop(0)

    with patch.dict("os.environ", {"ORACLE_LLM_PROVIDER": "unknown"}):
        with pytest.raises(ValueError, match="Unsupported provider"):
            call_llm("test")


def test_accumulated_usage():
    """Token usage should accumulate across multiple calls."""
    import sys
    sys.path.insert(0, "oracle")
    from llm_client import call_llm, reset_accumulated_usage, get_accumulated_usage
    sys.path.pop(0)

    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 100
    mock_usage.completion_tokens = 50
    mock_usage.total_tokens = 150

    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content="hello"))]
    mock_resp.usage = mock_usage

    reset_accumulated_usage()
    env = {"ORACLE_LLM_PROVIDER": "openai", "ORACLE_LLM_MODEL": "test", "OPENAI_API_KEY": "k"}
    with patch.dict("os.environ", env):
        with patch("openai.OpenAI") as MockClient:
            MockClient.return_value.chat.completions.create.return_value = mock_resp
            call_llm("p1")
            call_llm("p2")

    acc = get_accumulated_usage()
    assert acc["prompt_tokens"] == 200
    assert acc["completion_tokens"] == 100
    assert acc["total_tokens"] == 300

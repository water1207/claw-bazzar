"""Tests for LLM client wrapper."""
import json
import pytest
from unittest.mock import patch, MagicMock


def test_call_llm_anthropic():
    """call_llm should use anthropic SDK and return text response."""
    import sys
    sys.path.insert(0, "oracle")
    from llm_client import call_llm
    sys.path.pop(0)

    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text='{"result": "test"}')]

    with patch.dict("os.environ", {"ORACLE_LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "test-key"}):
        with patch("anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = mock_resp
            result = call_llm("test prompt", system="test system")

    assert result == '{"result": "test"}'
    MockClient.return_value.messages.create.assert_called_once()
    call_args = MockClient.return_value.messages.create.call_args
    assert call_args.kwargs["messages"] == [{"role": "user", "content": "test prompt"}]
    assert call_args.kwargs["system"] == "test system"


def test_call_llm_unsupported_provider():
    import sys
    sys.path.insert(0, "oracle")
    from llm_client import call_llm
    sys.path.pop(0)

    with patch.dict("os.environ", {"ORACLE_LLM_PROVIDER": "unknown"}):
        with pytest.raises(ValueError, match="Unsupported provider"):
            call_llm("test")

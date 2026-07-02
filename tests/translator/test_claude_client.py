from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from databricks_to_pbi.translator.claude_client import AnthropicClaudeClient


def _fake_response(text: str) -> MagicMock:
    msg = MagicMock()
    block = MagicMock()
    block.text = text
    msg.content = [block]
    return msg


def test_translate_calls_anthropic_with_expected_shape() -> None:
    sdk = MagicMock()
    sdk.messages.create.return_value = _fake_response("SUM('Sales'[amount])")
    client = AnthropicClaudeClient(sdk=sdk, model="claude-opus-4-7")

    dax = client.translate(
        sql="SUM(amount)",
        table_context="Sales",
        columns_by_table={"Sales": ["amount", "status"]},
        measure_name="Total",
    )
    assert dax == "SUM('Sales'[amount])"

    _args, kwargs = sdk.messages.create.call_args
    assert kwargs["model"] == "claude-opus-4-7"
    prompt = "".join(m["content"] for m in kwargs["messages"])
    assert "SUM(amount)" in prompt
    assert "Sales" in prompt
    assert "amount" in prompt


def test_translate_strips_codeblock_fences() -> None:
    sdk = MagicMock()
    sdk.messages.create.return_value = _fake_response("```dax\nSUM('Sales'[amount])\n```")
    client = AnthropicClaudeClient(sdk=sdk, model="claude-opus-4-7")
    dax = client.translate(
        sql="SUM(amount)",
        table_context="Sales",
        columns_by_table={"Sales": ["amount"]},
        measure_name="Total",
    )
    assert dax == "SUM('Sales'[amount])"


def test_translate_preserves_manual_marker() -> None:
    sdk = MagicMock()
    sdk.messages.create.return_value = _fake_response("// MANUAL: window function not supported")
    client = AnthropicClaudeClient(sdk=sdk, model="claude-opus-4-7")
    dax = client.translate(
        sql="LAG(amount, 1) OVER ()", table_context="Sales",
        columns_by_table={"Sales": ["amount"]}, measure_name="X",
    )
    assert dax.startswith("// MANUAL:")


def test_load_from_env_returns_none_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from databricks_to_pbi.translator.claude_client import load_from_env
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert load_from_env() is None


def test_load_from_env_returns_client_when_key_present(monkeypatch: pytest.MonkeyPatch) -> None:
    from databricks_to_pbi.translator.claude_client import load_from_env
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch("databricks_to_pbi.translator.claude_client.anthropic.Anthropic") as A:
        A.return_value = MagicMock()
        c = load_from_env()
    assert c is not None

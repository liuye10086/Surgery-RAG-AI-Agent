from types import SimpleNamespace

from app.services.standard_llm_adapter import DeepSeekStandardCandidateAdapter, normalize_candidate_output


def test_normalize_candidate_output_extracts_json_and_preserves_raw_output():
    raw = '```json\n{"indicator_name":"ALT","rule_type":"numeric_range","unit":"U/L","lower":7,"upper":40}\n```'
    result = normalize_candidate_output(raw)
    assert result["indicator_name"] == "ALT"
    assert result["numeric"]["lower"] == 7
    assert result["_raw_output"] == raw


def test_adapter_uses_injected_client_without_network_call():
    calls = []

    class FakeLLM:
        def invoke(self, messages):
            calls.append(messages)
            return SimpleNamespace(content='{"indicator_name":"ALT","rule_type":"numeric_range","unit":"U/L","lower":7,"upper":40}')

    adapter = DeepSeekStandardCandidateAdapter(llm=FakeLLM())
    result = adapter("ALT normal range", {"section_title": "肝功能"})

    assert result["indicator_name"] == "ALT"
    assert result["_model_name"] == "deepseek-chat"
    assert calls and "ALT normal range" in str(calls[-1])


def test_adapter_returns_none_for_malformed_output():
    class FakeLLM:
        def invoke(self, messages):
            return SimpleNamespace(content="not-json")

    assert DeepSeekStandardCandidateAdapter(llm=FakeLLM())("片段", {}) is None

# Tests for the Groq client wrapper: model selection and the reasoning_effort switch for gpt-oss models.
from types import SimpleNamespace
from unittest import mock
from django.test import SimpleTestCase, override_settings
from agents import llm_client
def _completion(text='{"ok": true}', finish_reason="stop"):
    # Minimal stand-in for a Groq chat completion.
    choice = SimpleNamespace(finish_reason=finish_reason, message=SimpleNamespace(content=text))
    return SimpleNamespace(choices=[choice], model_dump=lambda **kw: {"choices": []})
class GroqCallTests(SimpleTestCase):
    # What actually gets sent to Groq.
    def _call(self, **kwargs):
        # Calls call_llm with a mocked SDK and returns (response, kwargs sent to create()).
        with mock.patch.object(llm_client.groq, "Groq") as sdk:
            sdk.return_value.chat.completions.create.return_value = _completion(**kwargs)
            response = llm_client.call_llm("groq", [{"role": "user", "content": "hi"}], api_key="k", max_output_tokens=500)
        return response, sdk.return_value.chat.completions.create.call_args.kwargs
    @override_settings(GROQ_MODEL="openai/gpt-oss-120b", GROQ_REASONING_EFFORT="low")
    def test_gpt_oss_gets_low_reasoning_effort(self):
        # Reasoning is capped so it doesn't consume the answer's token budget.
        response, sent = self._call()
        self.assertEqual(sent["model"], "openai/gpt-oss-120b")
        self.assertEqual(sent["reasoning_effort"], "low")
        self.assertEqual(sent["max_tokens"], 500)
        self.assertEqual(response.model, "openai/gpt-oss-120b")
    @override_settings(GROQ_MODEL="qwen/qwen3.8-27b", GROQ_REASONING_EFFORT="low")
    def test_other_models_do_not_get_reasoning_effort(self):
        # Sending reasoning_effort to a model that doesn't support it would be a 400.
        _, sent = self._call()
        self.assertNotIn("reasoning_effort", sent)
    @override_settings(GROQ_MODEL="openai/gpt-oss-120b", GROQ_REASONING_EFFORT="")
    def test_effort_can_be_disabled(self):
        # An empty setting leaves the provider default.
        _, sent = self._call()
        self.assertNotIn("reasoning_effort", sent)
    @override_settings(GROQ_MODEL="openai/gpt-oss-120b")
    def test_truncated_answer_is_an_explicit_error(self):
        # Running out of tokens mid-answer surfaces as a clear LLMError, not a JSON parse failure later.
        with self.assertRaisesMessage(llm_client.LLMError, "finish_reason=length"):
            self._call(finish_reason="length")

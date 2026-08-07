"""Smoke test for both LLM providers -- run after filling in .env:

    python manage.py test_llm

Confirms GOOGLE_API_KEY and GROQ_API_KEY are valid and llm_client.py can
reach both providers, per Build Order step 3.
"""
from django.core.management.base import BaseCommand

from agents.llm_client import LLMError, call_llm


class Command(BaseCommand):
    help = "Send a trivial prompt to Gemini and Groq to confirm both API keys work."

    def handle(self, *args, **options):
        messages = [
            {"role": "system", "content": "Reply with exactly one short sentence."},
            {"role": "user", "content": "Say hello and name yourself."},
        ]
        for provider in ("gemini", "groq"):
            self.stdout.write(f"--- {provider} ---")
            try:
                result = call_llm(provider, messages)
                self.stdout.write(self.style.SUCCESS(f"OK ({result.model}): {result.text.strip()}"))
            except LLMError as exc:
                self.stdout.write(self.style.ERROR(f"FAILED: {exc}"))

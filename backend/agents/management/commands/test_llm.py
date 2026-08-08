"""Smoke test for all four Groq keys -- run after filling in .env:

    python manage.py test_llm

Confirms each of GROQ_API_KEY_PLANNER, GROQ_API_KEY_CODER_A,
GROQ_API_KEY_CODER_B, and GROQ_API_KEY_REVIEWER is individually valid and
llm_client.py can reach Groq with each one, per Build Order step 3. Tested
one key at a time (not just "does Groq work") since a typo'd or exhausted
key on just one of the two Coder slots would otherwise go unnoticed until a
real pipeline run hit it -- the Coder's key rotation would quietly fail over
to its sibling and hide the problem.
"""
from django.conf import settings
from django.core.management.base import BaseCommand

from agents.llm_client import LLMError, call_llm

# (settings attr, provider, role label)
_KEYS = [
    ("GROQ_API_KEY_PLANNER", "groq", "Planner"),
    ("GROQ_API_KEY_CODER_A", "groq", "Coder (key A)"),
    ("GROQ_API_KEY_CODER_B", "groq", "Coder (key B)"),
    ("GROQ_API_KEY_REVIEWER", "groq", "Reviewer"),
]


class Command(BaseCommand):
    help = "Send a trivial prompt through each of the four per-role Groq keys to confirm they all work."

    def handle(self, *args, **options):
        messages = [
            {"role": "system", "content": "Reply with exactly one short sentence."},
            {"role": "user", "content": "Say hello and name yourself."},
        ]
        for setting_name, provider, role in _KEYS:
            api_key = getattr(settings, setting_name)
            self.stdout.write(f"--- {role}: {setting_name} ({provider}) ---")
            if not api_key:
                self.stdout.write(self.style.WARNING(f"SKIPPED: {setting_name} is not set in .env"))
                continue
            try:
                result = call_llm(provider, messages, api_key=api_key)
                self.stdout.write(self.style.SUCCESS(f"OK ({result.model}): {result.text.strip()}"))
            except LLMError as exc:
                self.stdout.write(self.style.ERROR(f"FAILED: {exc}"))

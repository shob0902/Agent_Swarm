# Management command that checks each per-role Groq API key can actually reach the model.
from django.conf import settings
from django.core.management.base import BaseCommand
from agents.llm_client import LLMError, call_llm
_KEYS = [
    ("GROQ_API_KEY_PLANNER", "groq", "Planner"),
    ("GROQ_API_KEY_CODER_A", "groq", "Coder (key A)"),
    ("GROQ_API_KEY_CODER_B", "groq", "Coder (key B)"),
    ("GROQ_API_KEY_REVIEWER", "groq", "Reviewer"),
]
class Command(BaseCommand):
    # Wires the check up as `python manage.py test_llm`.
    help = "Send a trivial prompt through each of the four per-role Groq keys to confirm they all work."
    def handle(self, *args, **options):
        # Sends a one-line prompt with every configured key and prints whether each one worked.
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

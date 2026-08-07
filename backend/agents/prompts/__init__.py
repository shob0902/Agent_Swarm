"""Loader for the versioned prompt templates in this package.

Templates are plain .txt files with Python str.format placeholders, kept
out of the service code so they can be reviewed/edited/versioned like any
other artifact (Section 8: "separate, versioned prompt templates, not
inline f-strings scattered in code").
"""
from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent


def load_prompt(name: str, **kwargs) -> str:
    """Read prompts/<name>.txt and .format(**kwargs) it."""
    path = _PROMPTS_DIR / f"{name}.txt"
    template = path.read_text(encoding="utf-8")
    return template.format(**kwargs)

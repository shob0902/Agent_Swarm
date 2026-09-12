# Loads the versioned prompt templates that live alongside this file as .txt files.
from pathlib import Path
_PROMPTS_DIR = Path(__file__).resolve().parent
def load_prompt(name: str, **kwargs) -> str:
    # Reads prompts/<name>.txt and fills its placeholders with the given keyword arguments.
    path = _PROMPTS_DIR / f"{name}.txt"
    template = path.read_text(encoding="utf-8")
    return template.format(**kwargs)

"""Loads prompt templates from ``prompts/<agent>.md``.

Each file has a ``=== SYSTEM ===`` section and a ``=== USER ===`` section.
Placeholders use ``${name}`` syntax (``string.Template``) so that code samples
and JSON braces inside prompts need no escaping.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from string import Template

PROMPTS_DIR = Path(__file__).resolve().parent
_SYSTEM_MARKER = "=== SYSTEM ==="
_USER_MARKER = "=== USER ==="


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    system: str
    user_template: str

    def render(self, **values: object) -> tuple[str, str]:
        user = Template(self.user_template).safe_substitute({k: str(v) for k, v in values.items()})
        return self.system, user


@lru_cache(maxsize=None)
def load_prompt(name: str) -> PromptTemplate:
    text = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
    if _SYSTEM_MARKER not in text or _USER_MARKER not in text:
        raise ValueError(f"Prompt '{name}' must contain '{_SYSTEM_MARKER}' and '{_USER_MARKER}' sections")
    _, rest = text.split(_SYSTEM_MARKER, 1)
    system, user = rest.split(_USER_MARKER, 1)
    return PromptTemplate(name=name, system=system.strip(), user_template=user.strip())

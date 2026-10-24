"""Static configuration for the POC: limits, providers and demo target sites."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"

load_dotenv(PROJECT_ROOT / ".env")

# Self-repair loop: 1 original run + up to MAX_HEAL_ATTEMPTS healed runs.
MAX_HEAL_ATTEMPTS = 2

# Each gate may send work back for regeneration this many times; the next
# rejection ends the run.
MAX_REJECTIONS_PER_GATE = 2

SUPPORTED_PROVIDERS = ("gemini", "openai", "anthropic", "ollama")
DEFAULT_LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").strip().lower() or "gemini"
DEFAULT_LLM_MODEL = os.getenv("LLM_MODEL", "gemini-3.8-flash").strip() or "gemini-3.8-flash"


def execution_timeout_seconds() -> int:
    try:
        return max(30, int(os.getenv("EXECUTION_TIMEOUT_SECONDS", "300")))
    except ValueError:
        return 300


@dataclass(frozen=True)
class TargetSite:
    """A site the generated tests run against.

    Credentials are referenced by *environment variable name* only; values are
    resolved at execution time and exposed to tests as TARGET_USERNAME /
    TARGET_PASSWORD so they never appear in prompts or generated code.
    """

    key: str
    name: str
    url: str
    description: str = ""
    username_env: str | None = None
    password_env: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["has_credentials"] = bool(self.username_env or self.password_env)
        return data


SITES: dict[str, TargetSite] = {
    "saucedemo": TargetSite(
        key="saucedemo",
        name="Swag Labs (SauceDemo)",
        url="https://www.saucedemo.com",
        description="E-commerce demo: login, inventory, cart and checkout.",
        username_env="SAUCEDEMO_USERNAME",
        password_env="SAUCEDEMO_PASSWORD",
    ),
    "the_internet": TargetSite(
        key="the_internet",
        name="The Internet (Herokuapp)",
        url="https://the-internet.herokuapp.com",
        description="Collection of classic UI challenges: forms, auth, dropdowns, dynamic content.",
    ),
    "demoqa": TargetSite(
        key="demoqa",
        name="DemoQA",
        url="https://demoqa.com",
        description="Forms, widgets, interactions and a book store app.",
    ),
}


def custom_site(url: str) -> TargetSite:
    return TargetSite(
        key="custom",
        name="Custom URL",
        url=url.strip().rstrip("/"),
        description="User supplied target application.",
        username_env="CUSTOM_SITE_USERNAME",
        password_env="CUSTOM_SITE_PASSWORD",
    )

"""Provider-agnostic LLM wrapper.

Agents only depend on the small :class:`LLMClient` protocol. The concrete
provider (Gemini by default) is chosen through ``LLM_PROVIDER`` / ``LLM_MODEL``
env vars or the Streamlit sidebar, which passes them through the LangGraph run
config (``configurable.llm_provider`` / ``configurable.llm_model``).
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from typing import Any, Protocol, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ValidationError

from config import DEFAULT_LLM_MODEL, DEFAULT_LLM_PROVIDER, SUPPORTED_PROVIDERS

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """Raised when the LLM cannot be created or returns unusable output."""


class LLMClient(Protocol):
    def generate_structured(self, schema: type[T], system: str, user: str) -> T: ...

    def generate_text(self, system: str, user: str) -> str: ...


def _message_text(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and part.get("type") == "text":
                parts.append(part.get("text", ""))
        return "".join(parts)
    return str(content)


def _extract_json(text: str) -> str:
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    start = min((i for i in (text.find("{"), text.find("[")) if i != -1), default=-1)
    return text[start:].strip() if start != -1 else text.strip()


class LangChainLLMClient:
    """Adapter around any LangChain chat model."""

    def __init__(self, chat_model: Any, label: str):
        self._model = chat_model
        self.label = label

    def generate_structured(self, schema: type[T], system: str, user: str) -> T:
        messages = [SystemMessage(content=system), HumanMessage(content=user)]
        structured_error: Exception | None = None
        try:
            result = self._model.with_structured_output(schema).invoke(messages)
            if isinstance(result, schema):
                return result
            if isinstance(result, dict):
                return schema.model_validate(result)
        except Exception as exc:  # provider-specific failures; fall back to plain JSON
            structured_error = exc

        # Fallback: ask for raw JSON and validate it ourselves.
        json_instruction = (
            "\n\nRespond with ONLY a JSON object that validates against this JSON schema:\n"
            + json.dumps(schema.model_json_schema())
        )
        raw = self.generate_text(system + json_instruction, user)
        try:
            return schema.model_validate_json(_extract_json(raw))
        except ValidationError as exc:
            raise LLMError(
                f"{self.label} returned output that does not match {schema.__name__}: {exc}"
                + (f" (structured output error: {structured_error})" if structured_error else "")
            ) from exc

    def generate_text(self, system: str, user: str) -> str:
        response = self._model.invoke([SystemMessage(content=system), HumanMessage(content=user)])
        text = _message_text(response)
        if not text.strip():
            raise LLMError(f"{self.label} returned an empty response")
        return text


def _temperature() -> float | None:
    raw = os.getenv("LLM_TEMPERATURE", "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _build_chat_model(provider: str, model: str) -> Any:
    temperature = _temperature()
    kwargs: dict[str, Any] = {"model": model}
    if temperature is not None:
        kwargs["temperature"] = temperature

    try:
        if provider == "gemini":
            from langchain_google_genai import ChatGoogleGenerativeAI

            api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
            if not api_key:
                raise LLMError("GOOGLE_API_KEY is not set. Add it to your .env file.")
            return ChatGoogleGenerativeAI(google_api_key=api_key, max_retries=2, **kwargs)
        if provider == "openai":
            from langchain_openai import ChatOpenAI

            return ChatOpenAI(max_retries=2, **kwargs)
        if provider == "anthropic":
            from langchain_anthropic import ChatAnthropic

            return ChatAnthropic(max_retries=2, max_tokens=16000, **kwargs)
        if provider == "ollama":
            from langchain_ollama import ChatOllama

            return ChatOllama(base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"), **kwargs)
    except ImportError as exc:
        raise LLMError(
            f"Provider '{provider}' needs an extra package ({exc.name}). "
            "Uncomment it in requirements.txt and run `uv pip install -r requirements.txt`."
        ) from exc
    raise LLMError(f"Unsupported LLM provider '{provider}'. Supported: {', '.join(SUPPORTED_PROVIDERS)}")


@lru_cache(maxsize=8)
def create_llm_client(provider: str | None = None, model: str | None = None) -> LLMClient:
    provider = (provider or DEFAULT_LLM_PROVIDER).strip().lower()
    model = (model or DEFAULT_LLM_MODEL).strip()
    return LangChainLLMClient(_build_chat_model(provider, model), label=f"{provider}:{model}")


def llm_client_from_config(config: dict | None) -> LLMClient:
    """Resolve the LLM client for a LangGraph run config."""
    configurable = (config or {}).get("configurable", {})
    return create_llm_client(configurable.get("llm_provider"), configurable.get("llm_model"))

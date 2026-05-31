import logging
import os

import click
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)

_PROVIDER_API_KEYS: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google_genai": "GOOGLE_API_KEY",
}

_DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-4o",
    "google_genai": "gemini-2.5-flash-lite",
}


def create_llm(provider: str | None = None, model: str | None = None) -> BaseChatModel:
    provider = provider or os.environ.get("LLM_PROVIDER", "anthropic")
    model = model or os.environ.get("LLM_MODEL") or _DEFAULT_MODELS.get(provider, "")

    required_key = _PROVIDER_API_KEYS.get(provider)
    if required_key and not os.environ.get(required_key):
        raise click.ClickException(
            f"Provider '{provider}' requires the {required_key} environment variable.\n"
            f"Set it in your shell or copy .env.example to .env and fill it in."
        )

    llm = init_chat_model(f"{provider}:{model}", max_retries=3, temperature=0)
    logger.info("LLM initialized", extra={"provider": provider, "model": model})
    return llm

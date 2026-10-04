"""Small model boundary used by the bounded agent loop."""
import json
from collections.abc import Sequence
from typing import Any, Protocol

from langchain_core.messages import BaseMessage

from app.config import settings


class ModelClient(Protocol):
    async def decide(self, messages: Sequence[BaseMessage]) -> Any:
        """Return one raw model decision without performing tool actions."""


class ModelConfigurationError(RuntimeError):
    pass


class GeminiModelClient:
    def __init__(self, model_name: str, max_retries: int | None = None):
        if not settings.gemini_api_key:
            raise ModelConfigurationError('Gemini API key is not configured.')
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError as error:
            raise ModelConfigurationError('Gemini model support is not installed.') from error
        model_options = {
            'model': model_name,
            'google_api_key': settings.gemini_api_key,
            'max_output_tokens': settings.max_output_tokens,
        }
        if max_retries is not None:
            model_options['max_retries'] = max_retries
        self._model = ChatGoogleGenerativeAI(
            **model_options,
        )
        self.last_usage: dict[str, int] = {}
        self.total_usage: dict[str, int] = {}

    async def decide(self, messages: Sequence[BaseMessage]) -> Any:
        response = await self._model.ainvoke(list(messages))
        self.last_usage = _usage_from_response(response)
        for key, value in self.last_usage.items():
            self.total_usage[key] = self.total_usage.get(key, 0) + value
        content = response.content
        return _parse_json_content(content) if isinstance(content, str) else content


class ScriptedModel:
    """Deterministic model double for unit tests."""

    def __init__(self, responses: Sequence[Any]):
        self.responses = list(responses)
        self.calls: list[list[BaseMessage]] = []

    async def decide(self, messages: Sequence[BaseMessage]) -> Any:
        self.calls.append(list(messages))
        if not self.responses:
            raise ModelConfigurationError('Scripted model has no response remaining.')
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def create_model_client(model_name: str, max_retries: int | None = None) -> ModelClient:
    provider = settings.model_provider.casefold()
    if provider in {'gemini', 'google', 'google-gemini'}:
        return GeminiModelClient(model_name or settings.model_name or 'gemini-2.0-flash', max_retries=max_retries)
    raise ModelConfigurationError(f'Model provider is not configured: {settings.model_provider}.')


def _parse_json_content(content: str) -> Any:
    cleaned = content.strip()
    if cleaned.startswith('```'):
        lines = cleaned.splitlines()[1:]
        if lines and lines[-1].strip() == '```':
            lines = lines[:-1]
        cleaned = '\n'.join(lines).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return content


def _usage_from_response(response: Any) -> dict[str, int]:
    """Return provider-reported token counts without estimating missing values."""
    usage = getattr(response, 'usage_metadata', None)
    if not isinstance(usage, dict):
        metadata = getattr(response, 'response_metadata', None)
        usage = metadata.get('usage_metadata') if isinstance(metadata, dict) else None
    if not isinstance(usage, dict):
        return {}

    aliases = {
        'input_tokens': ('input_tokens', 'prompt_token_count', 'prompt_tokens'),
        'output_tokens': ('output_tokens', 'candidates_token_count', 'completion_tokens'),
        'total_tokens': ('total_tokens', 'total_token_count'),
    }
    result: dict[str, int] = {}
    for target, names in aliases.items():
        value = next((usage.get(name) for name in names if usage.get(name) is not None), None)
        if isinstance(value, int) and value >= 0:
            result[target] = value
    if 'total_tokens' not in result and {'input_tokens', 'output_tokens'} <= result.keys():
        result['total_tokens'] = result['input_tokens'] + result['output_tokens']
    return result
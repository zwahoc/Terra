"""Direct provider REST adapters with ephemeral reasoning state and a common interface."""

import base64
import copy
import json
import time
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from filelock import FileLock

from backend.app.schemas.analysis import UsageRecord
from backend.app.services.analysis_settings import PRICING_VERSION
from backend.app.services.ingestion_errors import IngestionError
from backend.app.services.provider_files import MultipartImage, ProviderFiles


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


class ProviderError(IngestionError):
    pass


class RefuseRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ProviderError("PROVIDER_REDIRECT_REFUSED", "The provider redirected a credentialed request.", 502)


class ProviderTransport:
    """Fixed official origins only. Never log headers, bodies or raw error responses."""
    def request(self, method, url, headers, payload=None, timeout=180):
        if not url.startswith(("https://generativelanguage.googleapis.com/", "https://api.deepseek.com/")):
            raise ProviderError("PROVIDER_URL_REFUSED", "Only configured official provider endpoints are allowed.", 502)
        multipart = isinstance(payload, MultipartImage)
        data = payload if multipart else encode(payload).encode() if payload is not None else None
        extra = {'Content-Type': payload.content_type, 'Content-Length': str(payload.length)} if multipart else {'Content-Type': 'application/json'}
        request = Request(url, data, headers={**headers, **extra}, method=method)
        try:
            with build_opener(ProxyHandler({}), RefuseRedirect()).open(request, timeout=timeout) as response:
                result = json.load(response)
            if not isinstance(result, dict) or result.get("error"):
                raise ValueError
            return result
        except HTTPError as exc:
            status = exc.code
            try:
                payload = json.loads(exc.read(65536))
            except (ValueError, OSError):
                payload = {}
            retry_header = exc.headers.get("Retry-After") if exc.headers else None
            exc.close()
            code = {401: "PROVIDER_CREDENTIALS_REJECTED", 403: "PROVIDER_ACCESS_DENIED", 404: "PROVIDER_MODEL_UNAVAILABLE", 429: "PROVIDER_RATE_LIMIT", 503: "PROVIDER_UNAVAILABLE"}.get(status, "PROVIDER_HTTP_ERROR")
            error = ProviderError(code, f"Provider returned HTTP {status}. No automatic retry was sent.", 502)
            error.details = provider_error_details(payload, status, retry_header)
            if status == 429:
                delay = error.details.get("retry_after_seconds")
                error.message = f"The provider rate-limited this model. {f'Wait at least {delay} seconds before retrying. ' if delay else ''}One document can require several model/tool requests; no automatic retry was sent."
            raise error from None
        except (URLError, TimeoutError, OSError):
            raise ProviderError("PROVIDER_TRANSPORT_ERROR", "Provider call failed or timed out; billing may be uncertain. Retry explicitly.", 502) from None
        except (ValueError, TypeError):
            raise ProviderError("PROVIDER_RESPONSE_INVALID", "Provider returned an invalid or oversized response.", 502) from None


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass(frozen=True)
class ProviderTurn:
    calls: list[ToolCall]
    text: str
    usage: UsageRecord


def provider_error_details(payload, status, retry_header=None):
    """Whitelist quota metadata only. Raw response text may echo request contents."""
    details = {"http_status": status}
    if retry_header and str(retry_header).isdigit():
        details["retry_after_seconds"] = int(retry_header)
    error = payload.get("error", {}) if isinstance(payload, dict) else {}
    if not isinstance(error, dict):
        return details
    quotas = []
    entries = error.get("details") or []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        if "RetryInfo" in entry.get("@type", ""):
            delay = entry.get("retryDelay", "")
            try:
                if isinstance(delay, str) and delay.endswith("s"):
                    details["retry_after_seconds"] = round(float(delay[:-1]) + 0.5)
            except ValueError:
                pass
        for violation in entry.get("violations", []):
            if not isinstance(violation, dict):
                continue
            quotas.append({key: violation[key] for key in ("quotaMetric", "quotaId", "quotaValue")
                           if isinstance(violation.get(key), str)})
    if quotas:
        details["quota_violations"] = quotas
    return details


class RequestPacer:
    """Space Gemini generation calls per exact model across local processes."""
    def __init__(self, root: Path):
        self.root = root / "request-pacing"

    def wait(self, slot, interval):
        if interval <= 0:
            return
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self.root / f"{slot}.json"
        with FileLock(str(self.root / f"{slot}.lock"), timeout=30):
            try:
                previous = float(json.loads(path.read_text(encoding="utf-8"))["scheduled_at"])
            except FileNotFoundError:
                previous = 0
            except (KeyError, ValueError, TypeError):
                raise ProviderError("PROVIDER_PACING_INVALID", "Local request pacing state is invalid. Inspect it before retrying.", 503) from None
            scheduled = max(time.time(), previous + interval)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.root, delete=False) as handle:
                    temporary = Path(handle.name)
                    json.dump({"scheduled_at": scheduled}, handle)
                os.replace(temporary, path)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        time.sleep(max(0, scheduled - time.time()))


class ModelSession(Protocol):
    def step(self, tool_results: list[dict] | None = None) -> ProviderTurn: ...


class ProviderAdapter:
    def __init__(self, spec, settings, ledger, transport=None):
        self.spec, self.settings, self.ledger = spec, settings, ledger
        self.transport = transport or ProviderTransport()
        self.files = None

    def image_file(self, path):
        if self.files is None:
            self.files = ProviderFiles(self)
        return self.files.reference(path)

    def close(self):
        return self.files.close() if self.files else {'pending_cleanup': 0}

    def require_enabled(self):
        if not self.settings.enabled:
            raise ProviderError("MODELS_DISABLED", "Set TERRA_LLM_ENABLED=true locally to enable outbound model requests.", 503)
        if not self.spec.key.get_secret_value():
            raise ProviderError("PROVIDER_KEY_MISSING", "Set the provider API key in the local .env file.", 503)

    @property
    def headers(self):
        key = self.spec.key.get_secret_value()
        return {"x-goog-api-key": key} if self.spec.provider == "gemini" else {"Authorization": f"Bearer {key}"}

    def check_availability(self):
        self.require_enabled()
        if self.spec.provider == "gemini":
            result = self.transport.request("GET", f"https://generativelanguage.googleapis.com/v1beta/models/{self.spec.model_id}", self.headers)
            available = result.get("name") == f"models/{self.spec.model_id}" and "generateContent" in result.get("supportedGenerationMethods", [])
        else:
            result = self.transport.request("GET", "https://api.deepseek.com/models", self.headers)
            available = any(row.get("id") == self.spec.model_id for row in result.get("data", []))
        if not available:
            raise ProviderError("PROVIDER_MODEL_UNAVAILABLE", "The configured account did not expose the exact requested model.", 502)
        return {"slot": self.spec.slot, "model_id": self.spec.model_id, "available": True,
                "generation_tested": False, "free_tier_verified": False}

    def session(self, system, instruction, attachments, tools, output_schema):
        self.require_enabled()
        session_type = GeminiSession if self.spec.provider == "gemini" else DeepSeekSession
        return session_type(self, system, instruction, attachments, tools, output_schema)

    def generate(self, url, payload, input_bound):
        if input_bound > 1_048_576:
            raise ProviderError("MODEL_INPUT_TOO_LARGE", "The prepared input exceeds this model's context bound; no content was truncated.")
        if self.spec.provider == "gemini":
            RequestPacer(self.ledger.root).wait(self.spec.slot, self.settings.gemini_min_interval_seconds)
        output_bound = payload.get('max_tokens', self.settings.max_output_tokens)
        reservation = self.ledger.reserve(self.spec, input_bound, output_bound)
        started = time.monotonic()
        raw = self.transport.request("POST", url, self.headers, payload, self.settings.timeout_seconds)
        try:
            if self.spec.provider == "gemini":
                usage = raw["usageMetadata"]
                input_tokens = usage["promptTokenCount"]
                thinking = usage.get("thoughtsTokenCount", 0)
                output_tokens = usage.get("candidatesTokenCount", 0) + thinking
                cached = usage.get("cachedContentTokenCount", 0)
            else:
                usage = raw["usage"]
                input_tokens, output_tokens = usage["prompt_tokens"], usage["completion_tokens"]
                thinking = usage.get("completion_tokens_details", {}).get("reasoning_tokens", 0)
                cached = usage.get("prompt_cache_hit_tokens", 0)
            if any(type(value) is not int or value < 0 for value in (input_tokens, output_tokens, thinking, cached)):
                raise ValueError
            cost = self.ledger.settle(reservation, self.spec, input_tokens, output_tokens)
            record = UsageRecord(input_tokens=input_tokens, output_tokens=output_tokens,
                thinking_tokens=thinking, cached_input_tokens=cached, estimated_cost_myr=cost,
                billing_mode=self.spec.billing_mode,
                latency_ms=int((time.monotonic() - started) * 1000), pricing_version=PRICING_VERSION)
        except (KeyError, TypeError, ValueError):
            raise ProviderError("PROVIDER_USAGE_INVALID", "Provider usage was missing or invalid; the full budget reservation remains held.", 502) from None
        return raw, record


class GeminiSession:
    def __init__(self, adapter, system, instruction, attachments, tools, output_schema):
        self.adapter, self.schema = adapter, output_schema
        parts = [{"text": instruction}]
        for item in attachments:
            if item.get('source_label'):
                parts.append({'text':item['source_label']})
            parts.append({"inlineData": {"mimeType": item["media_type"], "data": base64.b64encode(item["data"]).decode("ascii")}})
        self.history = [{"role": "user", "parts": parts}]
        self.system, self.tools = system, tools

    def step(self, tool_results=None):
        if tool_results:
            parts = []
            for result in tool_results:
                response = {"name": result["name"], "response": result["result"]}
                if result.get("id"):
                    response["id"] = result["id"]
                parts.append({"functionResponse": response})
            self.history.append({"role": "user", "parts": parts})
        spec, settings = self.adapter.spec, self.adapter.settings
        payload = {"systemInstruction": {"parts": [{"text": self.system}]}, "contents": self.history,
                   "generationConfig": {"maxOutputTokens": settings.max_output_tokens,
                       "responseFormat": {"text": {"mimeType": "APPLICATION_JSON"}},
                       "thinkingConfig": {"thinkingLevel": "LOW", "includeThoughts": False}}}
        if self.tools:
            payload["tools"] = [{"functionDeclarations": [{"name": tool["name"], "description": tool["description"],
                "parametersJsonSchema": tool["parameters"]} for tool in self.tools]}]
            # Constrain JSON syntax here, then enforce the full dynamic contract in
            # Terra. Large numbered-array bounds were rejected by the live endpoint;
            # optional-field schema decoding also produced first-row-only candidates.
            # The schema is still supplied in the prompt, including source coverage.
        elif self.schema.get('title') != 'FileDraft':
            payload["generationConfig"]["responseFormat"]["text"]["schema"] = self.schema
        count_request = {"generateContentRequest": {**payload, "model": f"models/{spec.model_id}"}}
        count = self.adapter.transport.request("POST", f"https://generativelanguage.googleapis.com/v1beta/models/{spec.model_id}:countTokens", self.adapter.headers, count_request)
        tokens = count.get("totalTokens")
        if type(tokens) is not int or tokens < 0:
            raise ProviderError("TOKEN_COUNT_INVALID", "Cannot budget this Gemini request without a valid token count.", 502)
        raw, usage = self.adapter.generate(f"https://generativelanguage.googleapis.com/v1beta/models/{spec.model_id}:generateContent", payload, tokens + 1024)
        try:
            candidate = raw["candidates"][0]
            if candidate.get("finishReason") != "STOP":
                error = ProviderError("MODEL_OUTPUT_LIMIT" if candidate.get("finishReason") == "MAX_TOKENS" else "MODEL_OUTPUT_INCOMPLETE",
                    "Gemini reached the output-token limit before completing the document. The extraction remains incomplete; no rows were published." if candidate.get("finishReason") == "MAX_TOKENS" else "Gemini stopped without a complete candidate; no draft was accepted.", 502)
                error.usage = usage
                error.details = {"finish_reason": candidate.get("finishReason", "UNKNOWN"), "output_token_limit": settings.max_output_tokens}
                error.final_output = "".join(part.get("text", "") for part in candidate.get("content", {}).get("parts", []) if not part.get("thought"))
                raise error
            message = candidate["content"]
            # Preserve opaque signatures and original part boundaries for the next call.
            self.history.append(copy.deepcopy(message))
            calls = [ToolCall(part["functionCall"].get("id", ""), part["functionCall"]["name"], part["functionCall"].get("args", {})) for part in message["parts"] if "functionCall" in part]
            text = "".join(part.get("text", "") for part in message["parts"] if not part.get("thought"))
            return ProviderTurn(calls, text, usage)
        except (KeyError, IndexError, TypeError, ValueError):
            # Billing is already settled even when the candidate is truncated/refused.
            error = ProviderError("MODEL_OUTPUT_INCOMPLETE", "Gemini did not return a complete usable candidate; no partial draft was accepted.", 502)
            error.usage = usage
            raise error from None


class DeepSeekSession:
    def __init__(self, adapter, system, instruction, attachments, tools, output_schema):
        self.adapter, self.schema, self.tools = adapter, output_schema, tools
        content = [{"type": "text", "text": instruction}]
        self.file_blocks = []
        for item in attachments:
            if not item["media_type"].startswith("image/"):
                raise ProviderError("PROVIDER_INPUT_UNSUPPORTED", "DeepSeek accepts prepared text/images, not a raw PDF attachment. PDFs must pass through Terra's page preparer.")
            if item.get("page_number") is not None:
                content.append({"type": "text", "text": item.get('source_label', f"Original PDF page {item['page_number']} of {item['page_count']}.") + ' Match the following view to this same numbered source page.'})
            elif item.get('source_label'):
                content.append({'type':'text', 'text':item['source_label']})
            if 'region' in item:
                content.append({'type': 'text', 'text': 'Page view: ' + item['region'] + '. Same source page, not extra material evidence.'})
            if 'path' in item:
                block = {'type': 'file', 'file_id': self.adapter.image_file(item['path'])}
                self.file_blocks.append((block, item['path']))
                content.append(block)
            else:
                encoded = base64.b64encode(item["data"]).decode("ascii")
                content.append({"type": "image_url", "image_url": {"url": f"data:{item['media_type']};base64,{encoded}"}})
        self.messages = [{"role": "system", "content": system}, {"role": "user", "content": content}]
        self.has_images = bool(attachments)

    def step(self, tool_results=None):
        for block, path in self.file_blocks:
            block['file_id'] = self.adapter.image_file(path)
        for result in tool_results or []:
            self.messages.append({"role": "tool", "tool_call_id": result["id"], "content": encode(result["result"])})
        payload = {"model": self.adapter.spec.model_id, "messages": self.messages,
                   "max_tokens": self.adapter.settings.deepseek_max_output_tokens,
                   "thinking": {"type": "enabled"}, "reasoning_effort": "high"}
        if self.tools:
            payload["tools"] = [{"type": "function", "function": tool} for tool in self.tools]
        else:
            payload["response_format"] = {"type": "json_object"}
        # Include base64, prompt, tools and replayed reasoning in the actual body limit.
        if len(encode(payload).encode("utf-8")) > 48 * 1024 * 1024:
            raise ProviderError("PROVIDER_REQUEST_TOO_LARGE", "The complete prepared request exceeds DeepSeek's 48 MiB inline limit. No content was truncated or sent; use a smaller document.")
        # Text uses a deliberately loose UTF-8 byte bound plus framing allowance.
        # Images reserve the full published context capacity rather than guessing visual tokens.
        bound = len(encode(payload).encode('utf-8')) + 8192
        if self.file_blocks:
            bound += len(self.file_blocks) * 1024
            if bound + self.adapter.settings.deepseek_max_output_tokens > 1_048_576:
                raise ProviderError('MODEL_INPUT_TOO_LARGE', 'This conversation needs smaller connected page groups; no context was discarded.')
        elif self.has_images:
            bound = 1_048_576  # Legacy inline diagnostics retain conservative accounting.
        raw, usage = self.adapter.generate("https://api.deepseek.com/chat/completions", payload, bound)
        try:
            choice = raw["choices"][0]
            if choice.get("finish_reason") not in ("stop", "tool_calls"):
                reason = choice.get("finish_reason", "UNKNOWN")
                error = ProviderError("MODEL_OUTPUT_LIMIT" if reason == "length" else "MODEL_OUTPUT_INCOMPLETE",
                    "DeepSeek reached the output-token limit before completing the document. The extraction remains incomplete; no rows were published." if reason == "length" else "DeepSeek stopped without a complete candidate; no draft was accepted.", 502)
                error.usage = usage
                error.details = {"finish_reason": reason, "output_token_limit": self.adapter.settings.deepseek_max_output_tokens}
                error.final_output = choice.get("message", {}).get("content") or ""
                raise error
            message = choice["message"]
            # Provider requires reasoning_content replay during tools. Keep it only in this session.
            self.messages.append(copy.deepcopy(message))
            calls = [ToolCall(call["id"], call["function"]["name"], json.loads(call["function"]["arguments"])) for call in message.get("tool_calls") or []]
            return ProviderTurn(calls, message.get("content") or "", usage)
        except (KeyError, IndexError, TypeError, ValueError):
            error = ProviderError("MODEL_OUTPUT_INCOMPLETE", "DeepSeek did not return a complete usable candidate; no partial draft was accepted.", 502)
            error.usage = usage
            raise error from None

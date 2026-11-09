"""OpenAI-compatible AI client with secrets, retries and rate limiting."""

from __future__ import annotations

import json
import random
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Optional

from ..common.config import Settings, get_settings
from ..common.errors import UpstreamError
from ..common.logging_utils import get_logger
from ..common.models import Applicant
from .prompts import build_messages
from .schema import AIResponseError, parse_json_object, validate_ai_result

logger = get_logger("sbg.ai")


class _RateLimiter:
    """Process-local token bucket. AWS Lambda concurrency limits provide the
    global ceiling; this smooths bursts inside one container."""

    def __init__(self, rate_per_second: float = 2.0, burst: int = 4):
        self.rate = max(0.1, rate_per_second)
        self.burst = max(1, burst)
        self.tokens = float(self.burst)
        self.updated = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self.updated
            self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
            self.updated = now
            if self.tokens >= 1:
                self.tokens -= 1
                return
            wait = (1 - self.tokens) / self.rate
        time.sleep(wait)


_SECRET_CACHE: dict[str, tuple[float, str]] = {}


class KeyPool:
    """Manages a pool of AI API keys with automatic round-robin, failover and quota exhaustion handling.
    
    Supports 1 to N keys (e.g. 6-7 Google AI Studio Gemini API keys). When one key hits rate limits
    or quota exhaustion, it immediately fails over to the next available key.
    """

    def __init__(self, keys: list[str]):
        self.keys = [k.strip() for k in keys if k and k.strip()]
        self._index = 0
        self._lock = threading.Lock()
        self._exhausted_until: dict[str, float] = {}

    @property
    def has_keys(self) -> bool:
        return bool(self.keys)

    @property
    def count(self) -> int:
        return len(self.keys)

    def current_key(self) -> str:
        with self._lock:
            if not self.keys:
                return ""
            now = time.time()
            for i in range(len(self.keys)):
                candidate = self.keys[(self._index + i) % len(self.keys)]
                if self._exhausted_until.get(candidate, 0) < now:
                    self._index = (self._index + i) % len(self.keys)
                    return candidate
            return self.keys[self._index % len(self.keys)]

    def rotate(self, reason: str = "") -> str:
        with self._lock:
            if not self.keys:
                return ""
            old_key = self.keys[self._index % len(self.keys)]
            # Place old key on a 60-second cooldown so other keys are tried first
            self._exhausted_until[old_key] = time.time() + 60.0
            self._index = (self._index + 1) % len(self.keys)
            new_key = self.keys[self._index % len(self.keys)]
            masked_old = old_key[:6] + "..." + old_key[-4:] if len(old_key) > 10 else "***"
            masked_new = new_key[:6] + "..." + new_key[-4:] if len(new_key) > 10 else "***"
            logger.warning(
                "Rotating AI API key due to %s. Switched from %s to %s (key %d of %d)",
                reason or "quota exhaustion",
                masked_old,
                masked_new,
                (self._index % len(self.keys)) + 1,
                len(self.keys),
            )
            return new_key


def _split_keys(raw: str) -> list[str]:
    import re
    if not raw:
        return []
    parts = re.split(r"[\r\n,;]+", raw)
    return [p.strip() for p in parts if p.strip()]


def load_api_keys(settings: Settings, explicit: str = "") -> list[str]:
    keys: list[str] = []
    if explicit:
        keys.extend(_split_keys(explicit))
    if settings.ai_api_keys:
        keys.extend(_split_keys(settings.ai_api_keys))
    if settings.ai_api_key:
        keys.extend(_split_keys(settings.ai_api_key))

    if not keys and settings.ai_secret_arn:
        cached = _SECRET_CACHE.get(settings.ai_secret_arn)
        if cached and time.time() - cached[0] < 900:
            keys.extend(_split_keys(cached[1]))
        else:
            try:
                import boto3
                client = boto3.client("secretsmanager", region_name=settings.region)
                response = client.get_secret_value(SecretId=settings.ai_secret_arn)
                raw = response.get("SecretString") or ""
                try:
                    parsed = json.loads(raw)
                    val = str(parsed.get("api_keys") or parsed.get("api_key") or parsed.get("key") or "")
                except json.JSONDecodeError:
                    val = raw.strip()
                if val:
                    _SECRET_CACHE[settings.ai_secret_arn] = (time.time(), val)
                    keys.extend(_split_keys(val))
            except Exception as exc:
                logger.error("Unable to load AI API keys from Secrets Manager: %s", type(exc).__name__)

    # Deduplicate preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for k in keys:
        if k not in seen:
            seen.add(k)
            deduped.append(k)
    return deduped


def load_api_key(settings: Settings, explicit: str = "") -> str:
    keys = load_api_keys(settings, explicit)
    return keys[0] if keys else ""


def _default_transport(url: str, headers: dict[str, str], payload: dict[str, Any], timeout: float) -> tuple[int, str]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec - https configured URL
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


@dataclass
class ChatResult:
    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    attempts: int = 1
    finish_reason: str = ""


class AIClient:
    def __init__(
        self,
        settings: Optional[Settings] = None,
        config: Optional[dict[str, Any]] = None,
        *,
        api_key: str = "",
        transport: Optional[Callable[[str, dict[str, str], dict[str, Any], float], tuple[int, str]]] = None,
    ):
        self.settings = settings or get_settings()
        self.config = config or {}
        
        # Load all available keys into failover pool
        keys = load_api_keys(self.settings, api_key)
        self.key_pool = KeyPool(keys)
        self.api_key = self.key_pool.current_key()

        # Base URL and model with auto-detection for Google Gemini
        raw_base = str(self.config.get("base_url") or self.settings.ai_base_url).rstrip("/")
        raw_model = str(self.config.get("model") or self.settings.ai_model)
        provider = str(self.config.get("provider") or self.settings.ai_provider).lower()

        is_gemini = (
            provider == "gemini"
            or any(k.startswith("AIzaSy") for k in self.key_pool.keys)
            or "generativelanguage.googleapis.com" in raw_base
        )

        if is_gemini and ("deepseek" in raw_base or not raw_base):
            self.base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
        else:
            self.base_url = raw_base

        if is_gemini and ("deepseek" in raw_model or not raw_model):
            self.model = "gemini-1.5-flash"
        else:
            self.model = raw_model

        self.timeout = float(self.config.get("timeout_seconds") or self.settings.ai_timeout_seconds)
        self.max_retries = int(self.config.get("max_retries") or self.settings.ai_max_retries)
        self.temperature = float(
            self.config.get("temperature") if self.config.get("temperature") is not None else self.settings.ai_temperature
        )
        self.transport = transport or _default_transport
        self.limiter = _RateLimiter(
            rate_per_second=float(self.config.get("rate_per_second", 2.0)),
            burst=int(self.config.get("burst", 4)),
        )

    @property
    def enabled(self) -> bool:
        return self.key_pool.has_keys and bool(self.config.get("enabled", True))

    def chat(self, messages: list[dict[str, str]], *, response_format: bool = True) -> ChatResult:
        if not self.key_pool.has_keys:
            raise UpstreamError("AI provider is not configured (missing API keys)")

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": int(self.config.get("max_output_tokens", 4096)),
        }
        if response_format:
            payload["response_format"] = {"type": "json_object"}

        url = f"{self.base_url}/chat/completions"

        last_error: Optional[Exception] = None
        started = time.monotonic()
        total_attempts = max(self.max_retries, self.key_pool.count * 2)

        for attempt in range(1, total_attempts + 1):
            active_key = self.key_pool.current_key()
            headers = {
                "Authorization": f"Bearer {active_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            self.limiter.acquire()
            try:
                status, body = self.transport(url, headers, payload, self.timeout)
            except Exception as exc:  # noqa: BLE001 - network errors are retryable
                last_error = exc
                logger.warning("AI request attempt %s failed: %s", attempt, type(exc).__name__)
                self._backoff(attempt)
                continue

            # Check for quota exhaustion / rate limit across providers (Gemini, DeepSeek, OpenAI)
            is_exhausted = (
                status in (429, 403)
                or (status == 400 and ("RESOURCE_EXHAUSTED" in body or "quota" in body.lower()))
            )

            if is_exhausted and self.key_pool.count > 1:
                last_error = UpstreamError(f"AI provider key exhausted/rate-limited (HTTP {status})")
                self.key_pool.rotate(f"HTTP {status} / quota exhausted on attempt {attempt}")
                # Immediately retry with the next key in pool
                continue

            if status in (429, 500, 502, 503, 504):
                last_error = UpstreamError(f"AI provider returned HTTP {status}")
                logger.warning("AI provider transient failure HTTP %s (attempt %s)", status, attempt)
                self._backoff(attempt, retry_after=body if status == 429 else "")
                continue

            if status >= 400:
                # If key failed with 401 or 403 and there are more keys, rotate
                if status in (401, 403) and self.key_pool.count > 1:
                    self.key_pool.rotate(f"HTTP {status} auth rejection")
                    continue
                raise UpstreamError(f"AI provider rejected the request (HTTP {status})")

            try:
                parsed = json.loads(body)
                choice = parsed["choices"][0]
                content = choice["message"]["content"]
                usage = parsed.get("usage") or {}
                return ChatResult(
                    content=content,
                    model=str(parsed.get("model") or self.model),
                    prompt_tokens=int(usage.get("prompt_tokens", 0)),
                    completion_tokens=int(usage.get("completion_tokens", 0)),
                    latency_ms=int((time.monotonic() - started) * 1000),
                    attempts=attempt,
                    finish_reason=str(choice.get("finish_reason") or ""),
                )
            except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
                last_error = UpstreamError("AI provider returned an unexpected response envelope")
                logger.warning("Malformed AI response envelope on attempt %s", attempt)
                self._backoff(attempt)
                continue

        raise UpstreamError("AI provider request failed after retries") from last_error

    def _backoff(self, attempt: int, retry_after: str = "") -> None:
        delay = min(30.0, (2 ** (attempt - 1)) * 0.8 + random.uniform(0, 0.4))
        if retry_after:
            try:
                delay = max(delay, min(30.0, float(retry_after)))
            except ValueError:
                pass
        time.sleep(delay)

    def evaluate(
        self,
        applicant: Applicant,
        resume_text: str,
        rubric: dict[str, Any],
        roles_config: dict[str, Any],
        *,
        max_input_chars: int = 60000,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        from ..scoring.engine import normalise_role_ids

        messages = build_messages(applicant, resume_text, rubric, roles_config, max_input_chars=max_input_chars)
        expected_roles = normalise_role_ids(applicant.roles, roles_config)
        errors: list[str] = []
        last_result: Optional[ChatResult] = None

        for attempt in range(1, self.max_retries + 1):
            result = self.chat(messages)
            last_result = result
            try:
                raw = parse_json_object(result.content)
                validated = validate_ai_result(raw, rubric, expected_roles)
                metadata = {
                    "provider": self.config.get("provider", self.settings.ai_provider),
                    "model": result.model,
                    "prompt_tokens": result.prompt_tokens,
                    "completion_tokens": result.completion_tokens,
                    "latency_ms": result.latency_ms,
                    "attempts": result.attempts,
                    "finish_reason": result.finish_reason,
                    "structured_output": True,
                }
                return validated, metadata
            except AIResponseError as exc:
                errors = exc.errors
                logger.warning("AI response validation failed (attempt %s): %s", attempt, errors[:3])
                if attempt >= self.max_retries:
                    break
                messages = messages[:2] + [
                    messages[2] if len(messages) > 2 else {"role": "user", "content": "Return the JSON again."},
                    {"role": "assistant", "content": result.content[:8000]},
                    {
                        "role": "user",
                        "content": "Your response failed validation. Fix these issues and return only valid JSON:\n- "
                        + "\n- ".join(errors[:12]),
                    },
                ]

        raise AIResponseError(
            "AI response could not be validated after retries",
            errors or ["unknown validation failure"],
        )


class MockAIClient(AIClient):
    """Deterministic local evaluator. Never used in production.

    Produces a schema-valid, evidence-backed assessment from application
    answers so the full pipeline can be tested without an external API.
    """

    def __init__(self) -> None:
        super().__init__(api_key="local-mock", config={"enabled": True, "model": "mock-deepseek-flash"})
        self.api_key = "local-mock"

    def chat(self, messages: list[dict[str, str]], *, response_format: bool = True) -> ChatResult:
        raise NotImplementedError("MockAIClient.evaluate is used directly")

    def evaluate(
        self,
        applicant: Applicant,
        resume_text: str,
        rubric: dict[str, Any],
        roles_config: dict[str, Any],
        *,
        max_input_chars: int = 60000,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        from ..scoring.engine import normalise_role_ids

        roles = normalise_role_ids(applicant.roles, roles_config)
        evidence_text = " ".join(
            str(applicant.responses.get(k, "")) for k in ("experience", "projects", "leadership", "motivation")
        )
        evidence_quote = (resume_text or evidence_text or "Application provided limited detail.")[:220].strip()
        base = 0.55 + min(0.3, len(evidence_text) / 6000)
        criteria = []
        for criterion in rubric.get("criteria", []):
            cid = criterion["id"]
            boost = 0.08 if cid in ("relevant_skills", "projects_experience") and "project" in evidence_text.lower() else 0.0
            criteria.append(
                {
                    "id": cid,
                    "score_fraction": round(min(0.92, base + boost), 3),
                    "evidence": [evidence_quote or "No specific evidence found."],
                    "reasoning": "Deterministic local mock based on available application detail.",
                }
            )
        result = {
            "candidate_summary": f"Local mock evaluation for {applicant.applicant_id}. Not a real AI assessment.",
            "technical_skills": ["Mock skill"],
            "nontechnical_skills": ["Mock collaboration"],
            "projects": [],
            "experience": [],
            "certifications": [],
            "leadership_evidence": [],
            "communication_evidence": [evidence_quote],
            "criteria": criteria,
            "role_knowledge": {
                role: {"score_fraction": round(base, 3), "evidence": [evidence_quote], "reasoning": "Local mock."}
                for role in roles
            },
            "role_fit": {role: {"fit": "moderate", "rationale": "Local mock."} for role in roles},
            "strengths": ["Application contains evaluable detail"],
            "weaknesses": ["Mock evaluator does not assess quality"],
            "missing_information": [],
            "inconsistencies": [],
            "uncertain_findings": ["Local mock output - configure a real AI provider"],
            "interview_questions": [
                {"role": roles[0], "question": "Walk us through one project you are proud of.", "why": "Mock question"}
            ],
            "confidence": "low",
        }
        validated = validate_ai_result(result, rubric, roles)
        return validated, {"provider": "mock", "model": "mock-deepseek-flash", "structured_output": True, "mock": True}


def get_ai_client(settings: Optional[Settings] = None, config: Optional[dict[str, Any]] = None) -> AIClient:
    settings = settings or get_settings()
    config = config or {}
    provider = str(config.get("provider") or settings.ai_provider).lower()
    if provider == "mock":
        logger.warning("AI provider is set to mock; evaluations are NOT real assessments")
        return MockAIClient()
    return AIClient(settings, config)

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


def load_api_key(settings: Settings, explicit: str = "") -> str:
    if explicit:
        return explicit
    if settings.ai_api_key:
        return settings.ai_api_key
    if not settings.ai_secret_arn:
        return ""
    cached = _SECRET_CACHE.get(settings.ai_secret_arn)
    if cached and time.time() - cached[0] < 900:
        return cached[1]
    try:
        import boto3

        client = boto3.client("secretsmanager", region_name=settings.region)
        response = client.get_secret_value(SecretId=settings.ai_secret_arn)
        raw = response.get("SecretString") or ""
        try:
            parsed = json.loads(raw)
            key = str(parsed.get("api_key") or parsed.get("apiKey") or parsed.get("key") or "")
        except json.JSONDecodeError:
            key = raw.strip()
        if key:
            _SECRET_CACHE[settings.ai_secret_arn] = (time.time(), key)
        return key
    except Exception as exc:  # noqa: BLE001
        logger.error("Unable to load AI API key from Secrets Manager: %s", type(exc).__name__)
        return ""


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
        self.base_url = str(self.config.get("base_url") or self.settings.ai_base_url).rstrip("/")
        self.model = str(self.config.get("model") or self.settings.ai_model)
        self.timeout = float(self.config.get("timeout_seconds") or self.settings.ai_timeout_seconds)
        self.max_retries = int(self.config.get("max_retries") or self.settings.ai_max_retries)
        self.temperature = float(self.config.get("temperature") if self.config.get("temperature") is not None else self.settings.ai_temperature)
        self.api_key = load_api_key(self.settings, api_key)
        self.transport = transport or _default_transport
        self.limiter = _RateLimiter(
            rate_per_second=float(self.config.get("rate_per_second", 2.0)),
            burst=int(self.config.get("burst", 4)),
        )

    @property
    def enabled(self) -> bool:
        return bool(self.api_key) and bool(self.config.get("enabled", True))

    def chat(self, messages: list[dict[str, str]], *, response_format: bool = True) -> ChatResult:
        if not self.api_key:
            raise UpstreamError("AI provider is not configured (missing API key)")

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": int(self.config.get("max_output_tokens", 4096)),
        }
        if response_format:
            payload["response_format"] = {"type": "json_object"}

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        last_error: Optional[Exception] = None
        started = time.monotonic()
        for attempt in range(1, self.max_retries + 1):
            self.limiter.acquire()
            try:
                status, body = self.transport(url, headers, payload, self.timeout)
            except Exception as exc:  # noqa: BLE001 - network errors are retryable
                last_error = exc
                logger.warning("AI request attempt %s failed: %s", attempt, type(exc).__name__)
                self._backoff(attempt)
                continue

            if status in (429, 500, 502, 503, 504):
                last_error = UpstreamError(f"AI provider returned HTTP {status}")
                logger.warning("AI provider transient failure HTTP %s (attempt %s)", status, attempt)
                self._backoff(attempt, retry_after=body if status == 429 else "")
                continue

            if status >= 400:
                # Do not leak provider error bodies that may contain request data.
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

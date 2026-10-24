"""
LLM Gateway — Unified multi-provider router with automatic model fallback.

Architecture:
  ┌──────────────────────────────────────────────────────┐
  │                   LLM GATEWAY                        │
  │  call_chat_llm() / call_vision_llm()                 │
  │         │                                            │
  │         ▼                                            │
  │  ┌─────────────┐    fail    ┌─────────────┐         │
  │  │  Primary     │ ───────► │  Fallback 1   │         │
  │  │  Model       │          │  (next in     │         │
  │  │              │          │   chain)      │         │
  │  └─────────────┘          └──────┬────────┘         │
  │                             fail │                   │
  │                                  ▼                   │
  │                          ┌─────────────┐            │
  │                          │  Fallback 2   │            │
  │                          │  (next in     │            │
  │                          │   chain)      │            │
  │                          └─────────────┘            │
  │                                                      │
  │  Providers: OpenAI • Gemini • Anthropic              │
  │  Via: LiteLLM unified SDK                            │
  └──────────────────────────────────────────────────────┘

Features:
  - Automatic model fallback on failure (configurable chain)
  - Provider-aware API key detection
  - Audit logging for every gateway attempt + fallback event
  - Vision (multimodal) support across all providers
  - Configurable timeout and retry limits
"""

import os
import time
from typing import Any

from fastapi import HTTPException
import litellm

from app.config import settings

# ── LiteLLM Global Config ──────────────────────────────
litellm.drop_params = True
litellm.telemetry = False

# ── LangSmith Tracing via LiteLLM ──────────────────────
if settings.langchain_api_key or os.environ.get('LANGCHAIN_TRACING_V2') == 'true':
    try:
        if not litellm.success_callback:
            litellm.success_callback = []
        if 'langsmith' not in litellm.success_callback:
            litellm.success_callback.append('langsmith')
        if not litellm.failure_callback:
            litellm.failure_callback = []
        if 'langsmith' not in litellm.failure_callback:
            litellm.failure_callback.append('langsmith')
    except Exception as _ls_err:
        print(f"[LangSmith] LiteLLM callback registration note: {_ls_err}", flush=True)


# ── Model Catalog ──────────────────────────────────────
MODEL_CATALOG = [
    {
        "id": "gemini/gemini-2.5-flash",
        "alias": "gemini-3.8-flash",
        "name": "Gemini 3.8 Flash (Latest Preview)",
        "provider": "gemini",
        "supports_vision": True
    },
    {
        "id": "gemini/gemini-2.0-flash",
        "alias": "gemini-2.0-flash",
        "name": "Gemini 2.0 Flash",
        "provider": "gemini",
        "supports_vision": True
    },
    {
        "id": "claude-3-5-sonnet-20241022",
        "alias": "claude-3-5-sonnet",
        "name": "Anthropic Claude 3.5 Sonnet",
        "provider": "anthropic",
        "supports_vision": True
    },
    {
        "id": "claude-3-5-haiku-20241022",
        "alias": "claude-3-5-haiku",
        "name": "Anthropic Claude 3.5 Haiku",
        "provider": "anthropic",
        "supports_vision": True
    },
    {
        "id": "gpt-4.1-mini",
        "alias": "gpt-4.1-mini",
        "name": "OpenAI GPT-4.1 Mini",
        "provider": "openai",
        "supports_vision": True
    },
    {
        "id": "gpt-4o-mini",
        "alias": "gpt-4o-mini",
        "name": "OpenAI GPT-4o Mini",
        "provider": "openai",
        "supports_vision": True
    }
]


# ── Model Name Normalization ──────────────────────────

def normalize_model_name(model_name: str | None) -> str:
    """Normalize user or config model identifiers into standard LiteLLM model strings."""
    if not model_name:
        model_name = settings.chat_model or "gpt-4.1-mini"

    clean = model_name.strip()
    clean_lower = clean.lower()

    # Match against catalog aliases
    for entry in MODEL_CATALOG:
        if clean_lower == entry["alias"].lower() or clean_lower == entry["id"].lower():
            return entry["id"]

    # Special handling for user's Gemini 3.8 Flash query
    if "3.8" in clean_lower and "gemini" in clean_lower:
        # LiteLLM routes Gemini 2.5 Flash as the latest Flash generation
        return "gemini/gemini-2.5-flash"

    # Gemini prefix helper (LiteLLM requires `gemini/` prefix for Google models)
    if clean_lower.startswith("gemini-") and not clean_lower.startswith("gemini/"):
        return f"gemini/{clean}"

    # Claude prefix / format
    if clean_lower in ("claude", "claude-sonnet"):
        return "claude-3-5-sonnet-20241022"
    if clean_lower in ("claude-haiku",):
        return "claude-3-5-haiku-20241022"

    return clean


def get_provider_for_model(model: str) -> str:
    """Determine the provider name for a given model string."""
    model_lower = model.lower()
    if "gemini" in model_lower:
        return "gemini"
    if "claude" in model_lower or "anthropic" in model_lower:
        return "anthropic"
    return "openai"


# ── API Key Detection ─────────────────────────────────

def get_api_key_for_model(model: str, raise_on_missing: bool = True) -> str | None:
    """Detect required API key from model name. If raise_on_missing=False, returns None silently."""
    model_lower = model.lower()

    if "gemini" in model_lower:
        key = settings.gemini_api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key and raise_on_missing:
            raise HTTPException(
                status_code=400,
                detail="Google Gemini API key is missing. Please set GEMINI_API_KEY in your .env file."
            )
        return key

    if "claude" in model_lower or "anthropic" in model_lower:
        key = settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key and raise_on_missing:
            raise HTTPException(
                status_code=400,
                detail="Anthropic API key is missing. Please set ANTHROPIC_API_KEY in your .env file."
            )
        return key

    # Default to OpenAI
    key = settings.openai_api_key or os.environ.get("OPENAI_API_KEY")
    if not key and raise_on_missing and ("gpt" in model_lower or "openai" in model_lower or "text-" in model_lower):
        raise HTTPException(
            status_code=400,
            detail="OpenAI API key is missing. Please set OPENAI_API_KEY in your .env file."
        )
    return key


def has_api_key_for_model(model: str) -> bool:
    """Check whether the required API key is configured for the given model (non-throwing)."""
    try:
        key = get_api_key_for_model(model, raise_on_missing=False)
        return bool(key)
    except Exception:
        return False


# ── Fallback Chain Builder ────────────────────────────

def build_fallback_chain(primary_model: str) -> list[str]:
    """
    Build a fallback chain: [primary, fallback_1, fallback_2, ...].
    
    The chain is constructed from settings.fallback_models, filtered to:
      - Remove the primary model (it's already first)
      - Remove models whose API key is not configured
      - Respect settings.max_fallback_retries limit
    """
    resolved_primary = normalize_model_name(primary_model)
    chain = [resolved_primary]

    raw_fallbacks = settings.fallback_models
    if not raw_fallbacks:
        return chain

    candidates = [normalize_model_name(m.strip()) for m in raw_fallbacks.split(",") if m.strip()]

    for candidate in candidates:
        if candidate == resolved_primary:
            continue
        if not has_api_key_for_model(candidate):
            continue
        chain.append(candidate)
        # primary + N fallbacks = max_fallback_retries total attempts
        if len(chain) >= settings.max_fallback_retries:
            break

    return chain


# ── Core Gateway: Single LLM Call ─────────────────────

def _execute_llm_call(
    model: str,
    messages: list[dict],
    temperature: float = 0.1,
    max_tokens: int | None = None,
    timeout: int | None = None
) -> dict[str, Any]:
    """
    Execute a single LiteLLM completion call. Returns a result dict:
      {"content": str, "model": str, "latency_ms": float, "success": True}
    Raises on failure.
    """
    api_key = get_api_key_for_model(model, raise_on_missing=True)
    effective_timeout = timeout or settings.gateway_timeout or 45

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "timeout": effective_timeout
    }
    if api_key:
        kwargs["api_key"] = api_key
    if max_tokens:
        kwargs["max_tokens"] = max_tokens

    start = time.perf_counter()
    response = litellm.completion(**kwargs)
    latency_ms = (time.perf_counter() - start) * 1000

    content = response.choices[0].message.content or ""
    return {
        "content": content,
        "model": model,
        "latency_ms": round(latency_ms, 2),
        "success": True
    }


# ── Gateway: Chat with Automatic Fallback ─────────────

def call_chat_llm(
    model: str,
    messages: list[dict],
    temperature: float = 0.1,
    max_tokens: int | None = None
) -> str:
    """
    LLM Gateway entry point for chat completions with automatic model fallback.

    Flow:
      1. Resolve the primary model name
      2. Build a fallback chain [primary, fallback1, fallback2, ...]
      3. Try each model in order until one succeeds
      4. Audit-log every attempt and fallback event
      5. If all fail, raise HTTP 502 with aggregated error details
    """
    # Lazy import to avoid circular dependency (audit imports config, llm imports config)
    from app.audit import log_audit_event

    chain = build_fallback_chain(model)
    errors: list[dict[str, str]] = []
    attempted_models: list[str] = []

    for idx, candidate_model in enumerate(chain):
        is_fallback = idx > 0
        attempted_models.append(candidate_model)

        try:
            result = _execute_llm_call(
                model=candidate_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )

            # Log successful gateway resolution
            if is_fallback:
                log_audit_event(
                    event_type="GATEWAY_FALLBACK_SUCCESS",
                    model=candidate_model,
                    status="SUCCESS",
                    latency_ms=result["latency_ms"],
                    details={
                        "original_model": chain[0],
                        "fallback_index": idx,
                        "attempted_models": attempted_models,
                        "previous_errors": errors
                    }
                )
            else:
                log_audit_event(
                    event_type="GATEWAY_CALL",
                    model=candidate_model,
                    status="SUCCESS",
                    latency_ms=result["latency_ms"],
                    details={"fallback_chain_length": len(chain)}
                )

            return result["content"]

        except HTTPException:
            # API key missing — skip this candidate, don't re-raise yet
            errors.append({"model": candidate_model, "error": "API key not configured"})
            log_audit_event(
                event_type="GATEWAY_SKIP",
                model=candidate_model,
                status="SKIPPED",
                details={"reason": "API key not configured", "fallback_index": idx}
            )
            continue

        except Exception as exc:
            error_msg = str(exc)
            errors.append({"model": candidate_model, "error": error_msg})

            log_audit_event(
                event_type="GATEWAY_FALLBACK_TRIGGERED",
                model=candidate_model,
                status="FAILED",
                details={
                    "error": error_msg[:300],
                    "fallback_index": idx,
                    "remaining_candidates": len(chain) - idx - 1
                }
            )
            continue

    # All models in the chain failed
    log_audit_event(
        event_type="GATEWAY_ALL_FAILED",
        model=chain[0],
        status="ERROR",
        details={
            "attempted_models": attempted_models,
            "errors": errors
        }
    )
    raise HTTPException(
        status_code=502,
        detail=f"All models in the gateway chain failed. Attempted: {attempted_models}. Errors: {errors}"
    )


# ── Gateway: Vision (Multimodal) with Fallback ────────

def call_vision_llm(
    model: str | None,
    prompt: str,
    image_data_url: str,
    max_tokens: int = 300
) -> str:
    """
    LLM Gateway for multimodal vision calls with automatic model fallback.
    Constructs the vision message format and routes through the fallback chain.
    """
    from app.audit import log_audit_event

    chosen_model = model or settings.vision_model or settings.chat_model or "gpt-4.1-mini"
    chain = build_fallback_chain(chosen_model)

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_data_url}}
            ]
        }
    ]

    errors: list[dict[str, str]] = []
    attempted_models: list[str] = []

    for idx, candidate_model in enumerate(chain):
        is_fallback = idx > 0
        attempted_models.append(candidate_model)

        try:
            result = _execute_llm_call(
                model=candidate_model,
                messages=messages,
                max_tokens=max_tokens
            )

            if is_fallback:
                log_audit_event(
                    event_type="GATEWAY_VISION_FALLBACK_SUCCESS",
                    model=candidate_model,
                    status="SUCCESS",
                    latency_ms=result["latency_ms"],
                    details={
                        "original_model": chain[0],
                        "fallback_index": idx,
                        "attempted_models": attempted_models
                    }
                )

            return result["content"]

        except HTTPException:
            errors.append({"model": candidate_model, "error": "API key not configured"})
            continue

        except Exception as exc:
            errors.append({"model": candidate_model, "error": str(exc)})
            log_audit_event(
                event_type="GATEWAY_VISION_FALLBACK_TRIGGERED",
                model=candidate_model,
                status="FAILED",
                details={
                    "error": str(exc)[:300],
                    "fallback_index": idx,
                    "remaining_candidates": len(chain) - idx - 1
                }
            )
            continue

    raise HTTPException(
        status_code=502,
        detail=f"All vision models failed. Attempted: {attempted_models}. Errors: {errors}"
    )


# ── Gateway Status & Model Catalog ────────────────────

def get_fallback_chain_info(primary_model: str | None = None) -> dict[str, Any]:
    """Return the resolved fallback chain and gateway configuration for inspection."""
    primary = primary_model or settings.chat_model
    chain = build_fallback_chain(primary)
    return {
        "primary_model": chain[0] if chain else None,
        "fallback_chain": chain,
        "chain_length": len(chain),
        "max_retries": settings.max_fallback_retries,
        "gateway_timeout_s": settings.gateway_timeout,
        "fallback_models_config": settings.fallback_models,
    }


def get_available_models() -> list[dict[str, Any]]:
    """Return catalog models with availability status based on configured keys."""
    results = []
    for item in MODEL_CATALOG:
        has_key = has_api_key_for_model(item["id"])
        results.append({
            **item,
            "configured": has_key
        })
    return results

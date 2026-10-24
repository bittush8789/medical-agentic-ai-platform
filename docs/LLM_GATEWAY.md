# MedGuide AI — LLM Gateway & Fallback Architecture 🌐

The **LLM Gateway** (`app/llm.py`) is an enterprise-grade multi-provider abstraction layer designed to eliminate vendor lock-in, provide automatic failover during outages, and optimize cost and latency across foundation models.

---

## 1. Why an LLM Gateway?

In production medical AI applications, relying on a single AI vendor introduces severe operational vulnerabilities:
- **Rate Limiting (HTTP 429):** Sudden traffic spikes can exceed quota limits.
- **Provider Outages (HTTP 500 / 503):** Infrastructure downtimes can take down critical services.
- **Cost vs. Latency Tradeoffs:** Simple conversational turns do not require frontier-tier reasoning, while complex clinical differential inquiries benefit from higher reasoning depth.

The MedGuide AI LLM Gateway provides:
1. **Unified API:** A single function call (`call_chat_llm` and `call_vision_llm`) supports Google Gemini, Anthropic Claude, OpenAI GPT, Groq, and local Ollama models.
2. **Automatic Multi-Provider Fallback:** If the user's selected model fails or hits a rate limit, the gateway transparently tries the next configured fallback model in milliseconds.
3. **Provider-Aware Dynamic Detection:** The gateway inspects active API keys in `.env` and automatically disables unavailable providers.

---

## 2. Gateway Architecture

```
                                call_chat_llm(model="gemini/gemini-2.5-flash")
                                                      │
                                                      ▼
                            ┌──────────────────────────────────────────────────┐
                            │      Attempt Primary Model: Gemini 2.5 Flash     │
                            └─────────────────────────┬────────────────────────┘
                                                      │
                                          ┌───────────┴───────────┐
                                          │                       │
                                      (Success)             (Error / 429)
                                          ▼                       ▼
                                   ┌─────────────┐     ┌──────────────────────────────────┐
                                   │ Return Text │     │ Audit: GATEWAY_FALLBACK          │
                                   └─────────────┘     │ Attempt: Claude 3.5 Sonnet       │
                                                       └────────────────┬─────────────────┘
                                                                        │
                                                            ┌───────────┴───────────┐
                                                            │                       │
                                                        (Success)             (Error / 429)
                                                            ▼                       ▼
                                                     ┌─────────────┐     ┌──────────────────────┐
                                                     │ Return Text │     │ Attempt: GPT-4.1-Mini│
                                                     └─────────────┘     └──────────┬───────────┘
                                                                                    │
                                                                        ┌───────────┴───────────┐
                                                                        │                       │
                                                                    (Success)             (Error)
                                                                        ▼                       ▼
                                                                 ┌─────────────┐         ┌──────────────┐
                                                                 │ Return Text │         │ 502 Bad      │
                                                                 └─────────────┘         │ Gateway      │
                                                                                         └──────────────┘
```

---

## 3. Supported Model Families

MedGuide AI uses **LiteLLM** to standardize request formats and token usage across all major frontier providers:

| Provider | Model Identifier | Default Tier | Strengths |
| :--- | :--- | :--- | :--- |
| **Google Gemini** | `gemini/gemini-2.5-flash`<br>`gemini/gemini-2.0-flash` | Primary Default | High speed, cost efficiency, massive context window |
| **Anthropic** | `claude-3-5-sonnet-20241022`<br>`claude-3-5-haiku-20241022` | Fallback #1 | Superior reasoning, nuanced medical comprehension |
| **OpenAI** | `gpt-4.1-mini`<br>`gpt-4o`<br>`gpt-4o-mini` | Fallback #2 | High reliability, ubiquitous availability |

---

## 4. Configuring Fallback Chains

The fallback sequence is fully customizable via the `.env` configuration file:

```ini
# Primary model requested by default
CHAT_MODEL=gemini/gemini-2.5-flash

# Comma-separated list of fallback models
FALLBACK_MODELS=claude-3-5-sonnet-20241022,gpt-4.1-mini,gemini/gemini-2.0-flash

# Maximum retry attempts per model before triggering fallback
MAX_RETRIES=2

# Request timeout in seconds
REQUEST_TIMEOUT_SECONDS=30
```

### Dynamic Chain Resolution
If the user selects `claude-3-5-sonnet-20241022` in the UI, the gateway automatically excludes Claude from the fallback list and creates a chain prioritizing Gemini and GPT:
```
Primary: claude-3-5-sonnet-20241022
Fallback #1: gemini/gemini-2.5-flash
Fallback #2: gpt-4.1-mini
```

---

## 5. Multimodal Vision Gateway

MedGuide AI supports visual inspection of dermatological photos, lab reports, or imaging through `call_vision_llm`:

```python
from app.llm import call_vision_llm

observation = call_vision_llm(
    model="gemini/gemini-2.5-flash",
    prompt="Describe visible dermatological features objectively without diagnosing.",
    image_data_url="data:image/jpeg;base64,..."
)
```

### Multimodal Fallback Behavior
If the primary vision model encounters a rate limit or failure:
1. Retries with Anthropic Claude 3.5 Sonnet (using native image block formats).
2. Retries with OpenAI GPT-4o / GPT-4.1 Mini (using high-resolution image URL payloads).
3. Maintains safety constraints: Vision prompts strictly instruct the LLM never to assert a definitive medical diagnosis from an image.

---

## 6. Gateway Inspection & Telemetry

### Inspecting Fallback Chains via API:
```bash
curl -X GET "http://127.0.0.1:8000/api/gateway?model=gemini/gemini-2.5-flash"
```
```json
{
  "status": "ok",
  "gateway": {
    "primary_model": "gemini/gemini-2.5-flash",
    "fallback_chain": [
      "claude-3-5-sonnet-20241022",
      "gpt-4.1-mini"
    ],
    "total_fallbacks": 2,
    "max_retries": 2,
    "timeout_seconds": 30
  }
}
```

### LangSmith & Audit Integration
Every gateway call automatically pushes metadata into:
- **Audit Logs (`logs/audit.log`):** Records primary model attempts, failover reasons, latency in milliseconds, and token consumption.
- **LangSmith Tracing:** LiteLLM callbacks (`litellm.success_callback = ['langsmith']`) push complete input/output spans to your LangSmith project dashboard.

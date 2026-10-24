# MedGuide AI — API Reference 📡

Complete specification for the MedGuide AI REST API, request/response models, streaming behavior, and authorization standards.

---

## 1. General Standards

- **Base URL:** `http://127.0.0.1:8000` (or your production domain)
- **Content Type:** `application/json` (unless uploading multipart files for audio/vision)
- **Authentication:** Controlled by `API_TOKEN` in `.env`.
  - When set, include the header: `Authorization: Bearer <YOUR_API_TOKEN>`
  - If `API_TOKEN` is blank in `.env`, authentication is bypassed for local development.
- **Session Identification:** Include the `X-Conversation-ID: <uuid>` header in chat requests to maintain continuous multi-turn session state and episodic memory.

---

## 2. API Endpoints Overview

| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/health` | Comprehensive system health, provider readiness, and active modules | No |
| `POST`| `/api/chat` | Main clinical chat endpoint with RAG, guardrails, and memory | If configured |
| `GET` | `/api/gateway` | Inspect LLM Gateway model fallback chain | No |
| `GET` | `/api/guardrails` | Inspect status of Presidio and NeMo guardrails | No |
| `GET` | `/api/audit-logs` | Retrieve structured audit logs with filtering | If configured |
| `GET` | `/api/governance/status` | Inspect governance toolkit metrics, budgets, and circuit breaker | No |
| `POST`| `/api/governance/killswitch` | Emergency kill-switch to freeze all agent tool invocations | If configured |
| `GET` | `/api/memory` | Retrieve long-term patient memories extracted by LangMem | If configured |
| `POST`| `/api/memory` | Explicitly save a clinical fact into patient profile | If configured |
| `DELETE`| `/api/memory/{memory_id}` | Remove a specific long-term memory entry | If configured |
| `GET` | `/api/redis/status` | Inspect Redis connection status and cache metrics | No |
| `GET` | `/api/eval/status` | Inspect DeepEval and Ragas configuration and benchmark cases | No |
| `GET` | `/api/eval/latest` | Retrieve latest clinical evaluation report | No |
| `POST`| `/api/eval/run` | Execute on-demand clinical benchmark evaluation run | If configured |
| `GET` | `/api/langsmith` | Check LangSmith tracing and observability status | No |
| `POST`| `/api/transcribe` | Transcribe voice recording using OpenAI Whisper | If configured |
| `POST`| `/api/speak` | Synthesize speech audio from text using OpenAI TTS-1 | If configured |

---

## 3. Detailed Endpoint Specifications

### 3.1. System Health (`GET /api/health`)

Returns comprehensive diagnostic telemetry regarding AI providers, safety layers, Redis cache, and active settings.

```bash
curl -X GET http://127.0.0.1:8000/api/health
```

#### Response Example (`200 OK`):
```json
{
  "status": "ok",
  "providers": {
    "openai": true,
    "gemini": true,
    "anthropic": true,
    "pinecone": true,
    "tavily": true
  },
  "audit_logging": true,
  "default_model": "gemini/gemini-2.5-flash",
  "gateway": {
    "primary_model": "gemini/gemini-2.5-flash",
    "fallback_chain": ["claude-3-5-sonnet-20241022", "gpt-4.1-mini"],
    "total_fallbacks": 2
  },
  "guardrails": {
    "presidio_active": true,
    "nemo_active": true,
    "phi_redaction_entities": ["PERSON", "PHONE_NUMBER", "EMAIL_ADDRESS", "MEDICAL_RECORD_NUMBER", "US_SSN", "CREDIT_CARD"]
  },
  "redis": {
    "connected": true,
    "mode": "redis_server",
    "host": "localhost",
    "port": 6379,
    "cached_responses_count": 42
  },
  "governance": {
    "kill_switch_active": false,
    "registered_tools": 4,
    "rate_limiting_enabled": true
  },
  "memory": {
    "enabled": true,
    "sqlite_db_ready": true,
    "total_memories": 12
  },
  "models": [
    {"id": "gemini/gemini-2.5-flash", "name": "Google Gemini 2.5 Flash", "provider": "gemini"},
    {"id": "claude-3-5-sonnet-20241022", "name": "Anthropic Claude 3.5 Sonnet", "provider": "anthropic"},
    {"id": "gpt-4.1-mini", "name": "OpenAI GPT-4.1 Mini", "provider": "openai"}
  ]
}
```

---

### 3.2. Clinical Chat (`POST /api/chat`)

Processes a clinical inquiry through input guardrails, LangMem patient memory, LangGraph RAG reasoning, and output guardrails.

#### Headers:
- `Content-Type: application/json`
- `Authorization: Bearer <API_TOKEN>` (optional if not set)
- `X-Conversation-ID: 550e8400-e29b-41d4-a716-446655440000` (optional)

#### Request Body (`ChatRequest`):
```json
{
  "message": "My name is Bittu Sharma and my MRN is 987654. What are common early warning signs of asthma?",
  "history": [
    {"role": "user", "content": "Hello doctor"},
    {"role": "assistant", "content": "Hello. I am an educational medical assistant. How can I assist you today?"}
  ],
  "image_data": null,
  "model": "gemini/gemini-2.5-flash"
}
```

| Parameter | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `message` | `string` | **Yes** | Patient query text (1–4000 characters). |
| `history` | `list` | No | Up to 10 prior chat message objects `{"role": "...", "content": "..."}`. |
| `image_data`| `string` | No | Optional base64 data URL (`data:image/jpeg;base64,...`) max 5MB. |
| `model` | `string` | No | Target LLM model. Defaults to `settings.chat_model`. |

#### Response Example (`200 OK`):
```json
{
  "answer": "Common early warning signs of asthma include frequent coughing (especially at night or with exercise), mild wheezing or whistling sounds when breathing, feeling easily fatigued during physical activity, and a sensation of slight chest tightness.\n\n⚠️ **Educational Medical Disclaimer:** This information is for educational purposes only and is not a formal medical diagnosis. Please consult a qualified healthcare provider for personal clinical advice.",
  "sources": [
    {
      "type": "pdf",
      "page": 128,
      "score": 0.812
    },
    {
      "type": "web",
      "url": "https://www.cdc.gov/asthma/signs.html",
      "title": "Asthma Signs and Symptoms — CDC"
    }
  ],
  "tools": ["pinecone", "tavily", "presidio-pii", "nemo-guardrails"],
  "conversation_id": "550e8400-e29b-41d4-a716-446655440000",
  "model_used": "gemini/gemini-2.5-flash",
  "cached": false,
  "guardrails": {
    "intervened": false,
    "pii_redacted": true,
    "pii_entities": ["PERSON", "MEDICAL_RECORD_NUMBER"],
    "active_rails": ["presidio_pii", "nemo_emergency", "nemo_jailbreak", "nemo_off_topic", "disclaimer_enforcer"]
  },
  "patient_memory_used": false
}
```

---

### 3.3. Emergency Triage Interception (`POST /api/chat`)

When a patient query includes red-flag emergency symptoms (chest pain, stroke, suicidal intent), NeMo Guardrails intercepts immediately without invoking external LLMs:

#### Request Body:
```json
{
  "message": "I have severe crushing chest pain radiating to my left arm and jaw and I can barely breathe"
}
```

#### Response Example (`200 OK` with zero latency):
```json
{
  "answer": "🚨 **MEDICAL EMERGENCY DETECTED**\n\nYour symptoms indicate a potentially life-threatening medical emergency.\n\n- **Immediately call emergency services:** Dial **911** (US/Canada), **112** (Europe/India), or your local emergency line immediately.\n- **Do NOT drive yourself** to the hospital.\n- Stop all physical exertion and sit or lie in a comfortable position.\n- If available, notify someone nearby right now.",
  "sources": [],
  "tools": ["nemo-guardrails"],
  "conversation_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "model_used": "nemo-guardrails",
  "guardrails": {
    "intervened": true,
    "rail_triggered": "nemo_emergency_triage",
    "reason": "Emergency triage red flag: chest pain, difficulty breathing",
    "pii_redacted": false,
    "pii_entities": []
  }
}
```

---

### 3.4. LLM Gateway Status (`GET /api/gateway`)

Inspect active model routing and fallback chains.

```bash
curl -X GET "http://127.0.0.1:8000/api/gateway?model=gemini/gemini-2.5-flash"
```

#### Response:
```json
{
  "status": "ok",
  "gateway": {
    "primary_model": "gemini/gemini-2.5-flash",
    "fallback_chain": ["claude-3-5-sonnet-20241022", "gpt-4.1-mini"],
    "max_retries": 2,
    "timeout_seconds": 30
  },
  "models": [ ... ]
}
```

---

### 3.5. Audit Logs (`GET /api/audit-logs`)

Retrieve recent structured compliance events.

```bash
curl -X GET "http://127.0.0.1:8000/api/audit-logs?limit=10&event_type=CHAT_COMPLETED" \
     -H "Authorization: Bearer <API_TOKEN>"
```

#### Response:
```json
{
  "status": "ok",
  "count": 1,
  "logs": [
    {
      "timestamp": "2026-10-24T10:45:12.345Z",
      "event_type": "CHAT_COMPLETED",
      "conversation_id": "550e8400-e29b-41d4-a716-446655440000",
      "model": "gemini/gemini-2.5-flash",
      "status": "SUCCESS",
      "latency_ms": 1284.5,
      "tools_invoked": ["pinecone", "presidio-pii", "nemo-guardrails"],
      "client_ip": "127.0.0.1",
      "details": {
        "route_taken": "answer",
        "kb_citations": 3,
        "pii_redacted": true
      }
    }
  ]
}
```

---

### 3.6. Agent Governance & Kill Switch (`POST /api/governance/killswitch`)

Enables administrators to instantly freeze all tool execution across the entire cluster in case of an anomaly or security alert.

```bash
curl -X POST http://127.0.0.1:8000/api/governance/killswitch \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer <API_TOKEN>" \
     -d '{"active": true, "reason": "Scheduled maintenance"}'
```

#### Response:
```json
{
  "status": "ok",
  "kill_switch_active": true,
  "message": "Agent tool execution FROZEN."
}
```

---

### 3.7. LangMem Patient Memory Management

#### Retrieve Patient Memories (`GET /api/memory`):
```bash
curl -X GET "http://127.0.0.1:8000/api/memory?user_id=patient_101" \
     -H "Authorization: Bearer <API_TOKEN>"
```
```json
{
  "status": "ok",
  "user_id": "patient_101",
  "count": 2,
  "memories": [
    {
      "id": "mem_01",
      "category": "allergy",
      "content": "Severe allergic reaction (anaphylaxis) to Amoxicillin and Penicillin derivatives",
      "confidence": 1.0,
      "created_at": 1729765200.0
    },
    {
      "id": "mem_02",
      "category": "chronic_condition",
      "content": "Type 2 Diabetes Mellitus diagnosed in 2021",
      "confidence": 0.95,
      "created_at": 1729765215.0
    }
  ]
}
```

#### Create Memory (`POST /api/memory`):
```bash
curl -X POST http://127.0.0.1:8000/api/memory \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer <API_TOKEN>" \
     -d '{
       "user_id": "patient_101",
       "category": "medication",
       "content": "Currently taking Metformin 500mg twice daily with meals",
       "confidence": 1.0
     }'
```

---

### 3.8. Clinical Evaluation (`POST /api/eval/run`)

Triggers DeepEval and RAGAS benchmarks against golden clinical datasets.

```bash
curl -X POST "http://127.0.0.1:8000/api/eval/run?framework=both&samples=3" \
     -H "Authorization: Bearer <API_TOKEN>"
```

#### Response:
```json
{
  "status": "ok",
  "report": {
    "timestamp": "2026-10-24T10:48:00Z",
    "model_evaluated": "gemini/gemini-2.5-flash",
    "total_samples": 3,
    "total_duration_sec": 8.4,
    "results": {
      "deepeval": {
        "status": "completed",
        "faithfulness": {"score": 0.96, "passed": 3, "failed": 0},
        "answer_relevancy": {"score": 0.92, "passed": 3, "failed": 0},
        "hallucination": {"score": 0.04, "passed": 3, "failed": 0},
        "clinical_safety": {"score": 1.00, "passed": 3, "failed": 0}
      },
      "ragas": {
        "status": "completed",
        "faithfulness": 0.95,
        "answer_relevance": 0.91,
        "context_precision": 0.88
      }
    }
  }
}
```

---

### 3.9. Speech & Voice Endpoints

#### Audio Transcription (`POST /api/transcribe`):
```bash
curl -X POST http://127.0.0.1:8000/api/transcribe \
     -F "file=@voice_recording.webm"
```
```json
{
  "text": "What is the recommended treatment protocol for severe acute bronchitis?"
}
```

#### Audio Synthesis (`POST /api/speak`):
```bash
curl -X POST http://127.0.0.1:8000/api/speak \
     -H "Content-Type: application/json" \
     -d '{"text": "Early warning signs of asthma include coughing, wheezing, and shortness of breath."}' \
     --output speech.mp3
```
Returns an `audio/mpeg` stream.

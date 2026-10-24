# MedGuide AI — Governance, Memory & Redis Architecture 🧠⚡

This document details the three core operational subsystems that give MedGuide AI enterprise reliability, continuous clinical personalization, and ultra-low latency:
1. **Agent Governance Toolkit (`app/governance.py`)**
2. **LangMem Long-Term Patient Memory (`app/memory.py`)**
3. **Redis Caching & Graceful Fallback (`app/redis_client.py`)**

---

## 1. Agent Governance Toolkit

Autonomous AI agents equipped with tools can cause severe operational issues if left unconstrained (e.g., infinite tool execution loops, excessive API spend, data leaks, and unmonitored actions). MedGuide AI implements an **Agent Governance Toolkit** that enforces strict operational boundaries.

```
                           Agent Intends to Execute Tool
                                         │
                                         ▼
                     ┌───────────────────────────────────────┐
                     │       authorize_tool_execution()      │
                     └───────────────────┬───────────────────┘
                                         │
         ┌───────────────────────────────┼───────────────────────────────┐
         ▼                               ▼                               ▼
┌──────────────────┐           ┌──────────────────┐           ┌──────────────────┐
│  1. Kill Switch  │           │  2. RBAC Policy  │           │ 3. Tool Budgets  │
│  Is system tool  │           │  Does caller     │           │ Exceeded max     │
│  execution halted│           │  have permission?│           │ calls per turn?  │
└────────┬─────────┘           └────────┬─────────┘           └────────┬─────────┘
         │                               │                               │
         └───────────────────────────────┼───────────────────────────────┘
                                         │ (All Passed)
                                         ▼
                     ┌───────────────────────────────────────┐
                     │ 4. Tool Circuit Breaker Status        │
                     │ Has tool failed >= 3 times in a row?  │
                     └───────────────────┬───────────────────┘
                                         │ (Closed / Healthy)
                                         ▼
                     ┌───────────────────────────────────────┐
                     │ 5. I/O Inspection & PII Sanitization  │
                     │ Scrub patient identifiers from query  │
                     └───────────────────┬───────────────────┘
                                         │
                                         ▼
                     ┌───────────────────────────────────────┐
                     │         EXECUTE TOOL SAFELY           │
                     └───────────────────┬───────────────────┘
                                         │
                                         ▼
                     ┌───────────────────────────────────────┐
                     │    record_tool_execution_outcome()   │
                     │  Log success / trip circuit on error  │
                     └───────────────────────────────────────┘
```

### 1.1. Tool Registry & Permissions Matrix

Each agent tool is explicitly declared with operational constraints:

| Tool Identifier | Description | Allowed Roles | Max Calls/Turn | PII Sanitization | External |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `pinecone_kb` | Semantic medical encyclopedia retrieval | `user`, `clinician`, `admin` | 3 | False | False |
| `tavily_web` | Live web search for clinical guidelines | `user`, `clinician`, `admin` | 2 | **True** (Enforced) | **True** |
| `vision_inspection` | Dermatological image analysis | `user`, `clinician`, `admin` | 1 | False | **True** |
| `langmem_memory` | Patient long-term memory updates | `user`, `clinician`, `admin` | 5 | False | False |

### 1.2. Circuit Breakers

If an external service (such as Tavily or an external vector DB) experiences a temporary outage, repeated calls will rapidly drain thread pools and create high latencies.
- The governance engine tracks consecutive tool execution failures.
- If a tool fails **3 consecutive times**, the circuit trips **OPEN**.
- Subsequent tool invocations are rejected immediately without network requests for a 60-second cooldown period.

### 1.3. Global Emergency Kill Switch

Administrators can freeze all agent tool invocations instantly across all active threads:
```bash
# Freeze all agent tools
curl -X POST http://127.0.0.1:8000/api/governance/killswitch \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer <API_TOKEN>" \
     -d '{"active": true, "reason": "Security audit in progress"}'
```

---

## 2. LangMem: Long-Term Patient Semantic Memory

Healthcare interactions require contextual memory of patient history across multiple sessions (e.g., recalling that a patient is allergic to Penicillin or has Type 2 Diabetes). MedGuide AI uses **LangMem** (`app/memory.py`) paired with two-tier storage.

```
       Turn 1: "I have asthma and I am severely allergic to Sulfa antibiotics."
                                 │
                                 ▼
                     ┌────────────────────────┐
                     │  LangMem Fact Extractor│
                     └───────────┬────────────┘
                                 │
                 ┌───────────────┴───────────────┐
                 ▼                               ▼
       [ Allergy Fact ]                 [ Chronic Condition ]
       "Allergic to Sulfa"              "Diagnosed with Asthma"
                 │                               │
                 └───────────────┬───────────────┘
                                 ▼
                     ┌────────────────────────┐
                     │   Two-Tier Memory Store│
                     │   1. Redis (High-Speed)│
                     │   2. SQLite (Durable)  │
                     └───────────┬────────────┘
                                 │
                                 ▼
       Turn 2 (Days Later): "Can I take Bactrim for an infection?"
                                 │
                                 ▼
       System Prompt Injects:
       "Patient Profile: Allergic to Sulfa drugs; Diagnosed with Asthma"
                                 │
                                 ▼
       Agent Warns:
       "Bactrim contains sulfamethoxazole (a sulfa drug), which you are allergic to!"
```

### 2.1. Supported Memory Categories

1. **`allergy`:** Drug, environmental, or food allergies (e.g., Penicillin, Peanuts, Latex).
2. **`chronic_condition`:** Long-term illnesses (e.g., Hypertension, Type 2 Diabetes, Asthma).
3. **`medication`:** Ongoing prescriptions and supplements (e.g., Metformin 500mg, Lisinopril).
4. **`preference`:** User communication or lifestyle preferences.

### 2.2. Two-Tier Storage Architecture

- **High-Speed Cache (Redis):** Fast retrieval using key `medguide:memory:{user_id}` with automated JSON serialization.
- **Durable Persistence (SQLite):** Backed by table `patient_long_term_memory` in `medical_memory.db` ensuring facts survive container restarts.

---

## 3. Redis Performance Acceleration & Caching

Medical queries often exhibit repetitive patterns (e.g., common questions about asthma triggers, fever management, or diabetes guidelines). MedGuide AI employs **Redis** (`app/redis_client.py`) to reduce response latency from **~2,500ms down to ~5ms**.

```
                Incoming Chat Message (e.g., "What causes asthma?")
                                        │
                                        ▼
                     ┌─────────────────────────────────────┐
                     │       Compute Cache Hash Key        │
                     │   SHA256(message.lower() + model)   │
                     └──────────────────┬──────────────────┘
                                        │
                         ┌──────────────┴──────────────┐
                         ▼                             ▼
                 [ Cache Hit: 5ms ]           [ Cache Miss: 2.5s ]
                         │                             │
              Return instant cached response   Execute LangGraph Agent
                         │                             │
                         │                     Store in Redis (TTL: 1h)
                         ▼                             ▼
                    Patient Receives Safe, Sourced Medical Guidance
```

### 3.1. Zero-Crash In-Memory Fallback Cache

If Redis is not installed, unreachable, or in the process of restarting, the application **never crashes**. The system automatically and transparently falls back to `InMemoryFallbackCache`, an internal thread-safe token bucket and LRU cache with automatic TTL expiry.

### 3.2. Distributed Rate Limiting

The Redis layer enforces sliding-window rate limiting per client IP:
- Configurable via `RATE_LIMIT_RPM=60` in `.env`.
- Blocks abusive automated scraping while ensuring fair resource availability for legitimate users.
- Violations are logged to the audit log as `GOVERNANCE_RATE_LIMIT`.

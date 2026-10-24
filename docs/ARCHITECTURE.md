# MedGuide AI — System Architecture 🏛️

This document details the architectural principles, data flow, state machine mechanics, and component interactions that power **MedGuide AI**.

---

## 1. Architectural Philosophy

MedGuide AI is engineered around four core tenets:
1. **Safety First (Defense-in-Depth):** Every user prompt passes through multiple independent safety checks before reaching an LLM, and every generated response is validated for disclaimers and prescription prohibition before reaching the user.
2. **Resilience & High Availability:** No single provider failure can bring down the application. The **LLM Gateway** automatically fails over across Google Gemini, Anthropic Claude, and OpenAI GPT. Redis caching provides graceful in-memory fallbacks when external cache servers are offline.
3. **Strict Educational Scoping:** The agent is constitutionally prevented from asserting medical diagnoses, prescribing medications or dosages, or acting as a licensed medical practitioner.
4. **Deep Observability & HIPAA Readiness:** All interactions, tool executions, latency benchmarks, and safety interventions are captured in a rotating JSON Lines audit trail, paired with LangSmith distributed execution tracing and DeepEval clinical benchmarking.

---

## 2. End-to-End Request-Response Flow

```mermaid
sequenceDiagram
    autonumber
    actor Patient as User / Web Client
    participant API as FastAPI Gateway
    participant Redis as Redis Cache
    participant Gov as Agent Governance
    participant Guard as Presidio & NeMo Rails
    participant Mem as LangMem (Memory)
    participant Agent as LangGraph ReAct
    participant KB as Pinecone / Tavily
    participant Gateway as LLM Gateway
    participant Audit as Audit Logger

    Patient->>API: POST /api/chat (query, history, optional image)
    API->>Gov: Check Rate Limit (e.g. 60 RPM)
    alt Rate Limit Exceeded
        Gov-->>API: 429 Too Many Requests
        API-->>Patient: 429 Blocked by Governance Policy
    end

    API->>Redis: Check Cached Chat Response
    alt Cache Hit (< 5ms)
        Redis-->>API: Return cached response
        API->>Audit: Log CHAT_CACHE_HIT
        API-->>Patient: Return Instant Response (cached: true)
    end

    API->>Guard: apply_input_guardrails(message)
    Note over Guard: Presidio redacts PII/PHI (Names, MRN, SSN, etc.)<br/>NeMo checks Emergency Triage & Jailbreaks
    alt NeMo Input Rail Triggered (Emergency / Jailbreak / Off-Topic)
        Guard-->>API: Block with deterministic safe response
        API->>Audit: Log TRIAGE_ALERT / GUARDRAIL_BLOCK
        API-->>Patient: Return Immediate Safe Guidance
    end

    API->>Mem: Retrieve Long-Term Patient Context (Allergies, Conditions)
    Mem-->>API: Formatted clinical profile

    API->>Agent: graph.invoke(state, config)
    
    Agent->>Gov: authorize_tool_execution("pinecone_kb")
    alt Tool Authorized
        Agent->>KB: Semantic Vector Search
        KB-->>Agent: Relevant chunks ([PDF p.X])
    end

    alt KB Score < 0.62 OR Question asks for current guidelines
        Agent->>Gov: authorize_tool_execution("tavily_web")
        alt Tool Authorized
            Agent->>KB: Tavily Clinical Search (PII Scrubbed)
            KB-->>Agent: Live guidelines & medical sources
        end
    end

    Agent->>Gateway: call_chat_llm(model, prompt + context)
    alt Primary Model Fails (e.g., Gemini 429/500)
        Gateway->>Gateway: Automatic Fallback to Claude 3.5 / GPT-4.1
    end
    Gateway-->>Agent: Raw response text

    Agent-->>API: Final unvalidated state

    API->>Guard: apply_output_guardrails(raw_answer)
    Note over Guard: Blocks drug dosages & enforces clinical disclaimers
    Guard-->>API: Validated safe answer

    API->>Redis: Store response in cache (TTL: 1 hour)
    API->>Mem: LangMem extract new facts (Allergies, Medications)
    API->>Audit: Log CHAT_COMPLETED (latency, tokens, tools, IP)
    API-->>Patient: Safe, sourced response + citations
```

---

## 3. LangGraph ReAct State Machine

The core clinical reasoning engine is implemented using **LangGraph** (`app/agent.py`), structuring the decision-making process into an explicit Directed Acyclic Graph (DAG):

```mermaid
stateDiagram-v2
    [*] --> Retrieve : User question + optional image
    Retrieve --> Route : Pinecone KB results
    
    Route --> WebSearch : KB missing, score < 0.62, or query needs latest guidelines
    Route --> Answer : KB score >= 0.62 and sufficient evidence
    
    WebSearch --> Answer : Combined KB + Tavily web citations
    Answer --> [*] : Draft response generated
```

### State Definition (`TypedDict`)
```python
class State(TypedDict):
    question: str               # Sanitized patient query (PII masked)
    history: list               # Prior conversation turns (limited to last 10)
    image_description: str      # Vision LLM objective observations (if image attached)
    kb: list                    # Pinecone vector retrieval results with cosine scores
    web: list                   # Tavily clinical search results
    answer: str                 # LLM synthesized educational response
    route: str                  # Routing decision ('answer' vs 'web')
    model: str                  # Requested LLM (Gemini, Claude, GPT)
    patient_context: str        # Long-term memories injected from LangMem
```

### Dynamic Routing Logic
- **`retrieve` Node**: Executes Pinecone vector lookup with cosine similarity thresholding.
- **`route` Node**: Evaluates evidence quality. If top chunk score $< 0.62$, or the prompt includes temporal keywords (`"latest"`, `"current"`, `"2026"`, `"guidelines"`, `"new treatment"`), execution routes to `web_search`. Otherwise, routes directly to `answer`.
- **`web_search` Node**: Invokes Tavily search with clinical query sanitization and PII stripping.
- **`answer` Node**: Formulates a prompt combining the system constitution, patient long-term history, PDF excerpts, and web citations for final synthesis.

---

## 4. Multi-Layered Safety & Guardrails Architecture

The system implements a zero-trust safety boundary around the core LLM:

```
                  ┌───────────────────────────────────────────────┐
                  │                 USER QUERY                    │
                  └───────────────────────┬───────────────────────┘
                                          │
                        [ INPUT GUARDRAILS LAYER ]
                                          │
               ┌──────────────────────────┴──────────────────────────┐
               ▼                                                     ▼
    ┌──────────────────────┐                              ┌──────────────────────┐
    │  Microsoft Presidio  │                              │   NVIDIA NeMo Rails  │
    │  - PII Masking       │                              │  - Emergency Triage  │
    │  - PHI Protection    │                              │  - Jailbreak Guard   │
    │  - Redacts [PERSON]  │                              │  - Off-Topic Defense │
    └──────────┬───────────┘                              └──────────┬───────────┘
               │                                                     │
               └──────────────────────────┬──────────────────────────┘
                                          ▼
                         [ AGENT REASONING & TOOLS ]
                                          │
                        [ OUTPUT GUARDRAILS LAYER ]
                                          │
               ┌──────────────────────────┴──────────────────────────┐
               ▼                                                     ▼
    ┌──────────────────────┐                              ┌──────────────────────┐
    │ Prescription Blocker │                              │ Disclaimer Enforcer  │
    │ - Detects dosages    │                              │ - Injects mandatory  │
    │ - Replaces with safe │                              │   educational notice │
    │   clinical advice    │                              │   if model forgot it │
    └──────────┬───────────┘                              └──────────┬───────────┘
               │                                                     │
               └──────────────────────────┬──────────────────────────┘
                                          ▼
                  ┌───────────────────────────────────────────────┐
                  │                 SAFE RESPONSE                 │
                  └───────────────────────────────────────────────┘
```

1. **Microsoft Presidio Layer:**
   - Detects patient names, phone numbers, email addresses, Medical Record Numbers (MRN), Social Security Numbers (SSN), and credit card numbers.
   - Masks sensitive tokens (e.g. `bittu sharma` $\rightarrow$ `<PERSON>`, `9876543210` $\rightarrow$ `<PHONE_NUMBER>`).
   - Ensures no patient PII reaches third-party API providers or audit logs.

2. **NVIDIA NeMo Guardrails Layer:**
   - **Emergency Triage Rail:** Detects life-threatening symptoms (chest pain, stroke, severe respiratory distress, suicidal thoughts) and triggers immediate emergency intervention with numbers (911 / 112) without invoking LLMs.
   - **Jailbreak / Injection Rail:** Neutralizes adversarial prompt attacks (DAN, roleplay exploits, instruction override).
   - **Off-Topic Rail:** Gently deflects non-medical queries (coding, politics, entertainment) back to healthcare education.
   - **Prescription & Dosage Blocker:** Intercepts unverified medication dosage recommendations and substitutes with standard consultation advice.
   - **Disclaimer Enforcer:** Appends mandatory educational disclaimers to ensure compliance.

---

## 5. Unified LLM Gateway & Fallback Architecture

MedGuide AI communicates with LLM providers through an intelligent abstraction layer (`app/llm.py`) built on LiteLLM:

```
                           call_chat_llm(model="gemini/gemini-2.5-flash")
                                              │
                                              ▼
                             ┌─────────────────────────────────┐
                             │    Step 1: Check Primary Model  │
                             │       gemini/gemini-2.5-flash   │
                             └────────────────┬────────────────┘
                                              │
                                     (success)│ (error / 429 / 500)
                                     ┌────────┴────────┐
                                     ▼                 ▼
                               ┌───────────┐     ┌─────────────────────────────────┐
                               │  Return   │     │    Step 2: Fallback Model #1    │
                               │  Answer   │     │       claude-3-5-sonnet         │
                               └───────────┘     └────────────────┬────────────────┘
                                                                  │
                                                         (success)│ (error)
                                                         ┌────────┴────────┐
                                                         ▼                 ▼
                                                   ┌───────────┐     ┌─────────────────────────────────┐
                                                   │  Return   │     │    Step 3: Fallback Model #2    │
                                                   │  Answer   │     │       gpt-4.1-mini              │
                                                   └───────────┘     └────────────────┬────────────────┘
                                                                                      │
                                                                             (success)│ (all failed)
                                                                             ┌────────┴────────┐
                                                                             ▼                 ▼
                                                                       ┌───────────┐     ┌───────────┐
                                                                       │  Return   │     │ 502 Bad   │
                                                                       │  Answer   │     │ Gateway   │
                                                                       └───────────┘     └───────────┘
```

- **Zero-Downtime Resilience:** Automatically retries across different providers with exponential backoff.
- **Provider-Aware Key Checking:** Dynamically constructs available model lists based on active API keys in `.env`.
- **Latency & Gateway Auditing:** Each attempt, latency delta, and failover event is logged with full transparency.

---

## 6. Long-Term Patient Memory Architecture (LangMem)

MedGuide AI maintains continuous, cross-session clinical context using **LangMem** (`app/memory.py`):

```
       Conversation Turn (Question + Answer)
                        │
                        ▼
       ┌─────────────────────────────────┐
       │   LangMem Fact Extractor        │
       │   - Allergy detection           │
       │   - Chronic conditions          │
       │   - Medication list             │
       └────────────────┬────────────────┘
                        │
                        ▼
       ┌─────────────────────────────────┐
       │   Two-Tier Storage Engine       │
       │                                 │
       │   1. High-Speed Cache (Redis)   │
       │      medguide:memory:{user_id}  │
       │                                 │
       │   2. Persistent Store (SQLite)  │
       │      patient_long_term_memory   │
       └────────────────┬────────────────┘
                        │
                        ▼
       Inject into next turn's System Prompt:
       "Patient Profile: Allergic to Penicillin; Diagnosed with Type 2 Diabetes"
```

---

## 7. High-Performance Caching & Resilience (Redis)

```
                       Inbound Request
                              │
                              ▼
               ┌───────────────────────────────┐
               │    Redis Connection Active?   │
               └──────────────┬────────────────┘
                              │
                    ┌─────────┴─────────┐
                    │                   │
                 (Yes)                 (No)
                    ▼                   ▼
        ┌───────────────────────┐   ┌───────────────────────┐
        │   Redis 7 Container   │   │  Thread-Safe In-Mem   │
        │   - Response Cache    │   │  TTL Fallback Cache   │
        │   - Rate Limiting     │   │  (Zero crash guarantee│
        │   - LangMem Storage   │   │   on connection drop) │
        └───────────────────────┘   └───────────────────────┘
```

---

## 8. Clinical Evaluation & Benchmarking (DeepEval & Ragas)

MedGuide AI features an offline and runtime clinical evaluation harness (`app/evaluation.py` and `eval.py`):

```
              Golden Clinical Dataset (10 Benchmark Cases)
                                │
                                ▼
              ┌─────────────────────────────────┐
              │     MedGuide Agent Execution    │
              └────────────────┬────────────────┘
                               │
            ┌──────────────────┴──────────────────┐
            ▼                                     ▼
┌───────────────────────────────┐     ┌───────────────────────────────┐
│        DeepEval Suite         │     │          RAGAS Suite          │
│ - Faithfulness Metric         │     │ - Faithfulness Metric         │
│ - Answer Relevancy Metric     │     │ - Answer Relevance Metric     │
│ - Hallucination Metric        │     │ - Context Precision Metric    │
│ - Clinical Safety G-Eval      │     └───────────────────────────────┘
└───────────────┬───────────────┘                     │
                └──────────────────┬──────────────────┘
                                   ▼
                    Comprehensive Evaluation Report
                    logs/evaluation_report.json
```

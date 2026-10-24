# MedGuide AI — Documentation Hub 📚

Welcome to the comprehensive technical documentation for **MedGuide AI**, an enterprise-grade, multi-model medical agentic chatbot featuring an autonomous **LangGraph ReAct Agent**, **Unified LLM Gateway with Fallback**, **Dual Guardrails (Microsoft Presidio & NVIDIA NeMo)**, **Agent Governance Toolkit**, **Long-Term Patient Memory (LangMem)**, **Redis Performance Acceleration**, and **DeepEval / Ragas Clinical Benchmarks**.

---

## 🧭 Documentation Navigation

| Document | Description |
| :--- | :--- |
| [**1. System Architecture**](ARCHITECTURE.md) | End-to-end system design, LangGraph state machine, data flow diagrams, and component interactions. |
| [**2. Full API Reference**](API_REFERENCE.md) | Exhaustive REST & streaming API documentation, request/response schemas, curl examples, and status codes. |
| [**3. Guardrails & Safety**](GUARDRAILS_AND_SAFETY.md) | In-depth breakdown of Microsoft Presidio (PII/PHI) and NVIDIA NeMo Guardrails (Emergency triage, jailbreak, dosage blocks). |
| [**4. LLM Gateway & Fallback**](LLM_GATEWAY.md) | Multi-provider router, zero-downtime model fallback chains, dynamic model switching, and LiteLLM integration. |
| [**5. Governance, Memory & Redis**](GOVERNANCE_MEMORY_REDIS.md) | Agent Governance Toolkit (RBAC, circuit breaker, kill-switch), LangMem long-term memory, and Redis caching. |
| [**6. Evaluation & Benchmarks**](EVALUATION_AND_BENCHMARKS.md) | DeepEval & RAGAS clinical evaluation suite, RAG Triad metrics, offline CLI runner (`eval.py`), and LangSmith tracing. |
| [**7. Deployment & Docker**](DEPLOYMENT_AND_DOCKER.md) | Multi-stage Docker build, Docker Compose stack (FastAPI + Redis + Redis Commander), and production checklist. |
| [**8. Ingestion & Knowledge Base**](INGESTION_AND_KNOWLEDGE_BASE.md) | PDF extraction with PyMuPDF, semantic chunking, SHA-256 deduplication, and Pinecone vector store indexing. |
| [**9. Enterprise AI Security**](AI_SECURITY.md) | Comprehensive OWASP Top 10 for LLMs, Anti-Poisoning Gate, Indirect Injections, and Exfiltration Defenses. |
| [**10. 1M Users Ubuntu DevOps Deployment**](UBUNTU_PRODUCTION_DEPLOYMENT.md) | End-to-end Ubuntu step-by-step setup for Terraform, AWS EKS, Helm 3, RDS PostgreSQL, and CI/CD. |

---

## 🏛️ High-Level System Architecture

```
                                  [ Patient / Client ]
                                           │
                                    (HTTPS / JSON)
                                           ▼
                 ┌──────────────────────────────────────────────────┐
                 │             FastAPI Gateway Server               │
                 │   - Bearer Authentication                        │
                 │   - Rate Limiting (Agent Governance / Redis)     │
                 │   - Sub-millisecond Response Cache (Redis)       │
                 └─────────────────────────┬────────────────────────┘
                                           │
                      ┌────────────────────┴────────────────────┐
                      ▼                                         ▼
         ┌─────────────────────────┐               ┌─────────────────────────┐
         │  Microsoft Presidio     │               │  NVIDIA NeMo Guardrails │
         │  - PII / PHI Redaction  │               │  - Emergency Triage     │
         │  - Zero-download Engine │               │  - Jailbreak Defense    │
         │  - Names/MRN/Phones/SSN │               │  - Off-Topic Deflection │
         └────────────┬────────────┘               └────────────┬────────────┘
                      │                                         │
                      └────────────────────┬────────────────────┘
                                           ▼
                 ┌──────────────────────────────────────────────────┐
                 │       LangMem Long-Term Patient Memory           │
                 │   - Recalls allergies, conditions, medications   │
                 │   - Redis High-Speed Layer + SQLite Persistence  │
                 └─────────────────────────┬────────────────────────┘
                                           │
                                           ▼
                 ┌──────────────────────────────────────────────────┐
                 │          LangGraph ReAct Medical Agent           │
                 │                                                  │
                 │   ┌─────────────┐            ┌───────────────┐   │
                 │   │  retrieve   │ ─────────► │     route     │   │
                 │   └──────┬──────┘            └───────┬───────┘   │
                 │          │ (Pinecone RAG)            │           │
                 │          ▼                           ▼           │
                 │   ┌─────────────┐            ┌───────────────┐   │
                 │   │ web_search  │ ◄──────────│  score < 0.62 │   │
                 │   └──────┬──────┘ (Tavily)   └───────┬───────┘   │
                 │          │                           │           │
                 │          └─────────────┬─────────────┘           │
                 │                        ▼                         │
                 │                 ┌─────────────┐                  │
                 │                 │   answer    │                  │
                 │                 └─────────────┘                  │
                 └─────────────────────────┬────────────────────────┘
                                           │
                                           ▼
                 ┌──────────────────────────────────────────────────┐
                 │       LLM Gateway & Automatic Fallback           │
                 │   Primary Model  ──(fail)──► Fallback Chain      │
                 │   Gemini 3.8/2.5 ──► Claude 3.5 ──► GPT-4.1      │
                 └─────────────────────────┬────────────────────────┘
                                           │
                                           ▼
                 ┌──────────────────────────────────────────────────┐
                 │          Output Safety & Compliance              │
                 │   - Prescription & Dosage Blocker                │
                 │   - Mandatory Medical Disclaimer Enforcer        │
                 │   - Structured HIPAA-compliant Audit Logger      │
                 │   - DeepEval / RAGAS & LangSmith Observability   │
                 └──────────────────────────────────────────────────┘
```

---

## ⚡ Quick Technology Matrix

| Subsystem | Primary Technologies | File Location |
| :--- | :--- | :--- |
| **Web Server & API** | FastAPI, Pydantic v2, Uvicorn, Vanilla JS | [`app/main.py`](file:///d:/New%20folder/Medical-Agentic-Chatbot/app/main.py) |
| **Agent Orchestration** | LangGraph, LangChain Core | [`app/agent.py`](file:///d:/New%20folder/Medical-Agentic-Chatbot/app/agent.py) |
| **LLM Gateway** | LiteLLM, Google Gemini, Anthropic Claude, OpenAI GPT | [`app/llm.py`](file:///d:/New%20folder/Medical-Agentic-Chatbot/app/llm.py) |
| **PII & Behavioral Safety**| Microsoft Presidio, NVIDIA NeMo Guardrails concepts | [`app/guardrails.py`](file:///d:/New%20folder/Medical-Agentic-Chatbot/app/guardrails.py) |
| **Agent Governance** | RBAC, Loop prevention budgets, Circuit breaker, Kill-switch | [`app/governance.py`](file:///d:/New%20folder/Medical-Agentic-Chatbot/app/governance.py) |
| **Long-Term Memory** | LangMem, SQLite (`medical_memory.db`), Redis | [`app/memory.py`](file:///d:/New%20folder/Medical-Agentic-Chatbot/app/memory.py) |
| **Caching & Acceleration** | Redis 7, In-memory TTL fallback cache | [`app/redis_client.py`](file:///d:/New%20folder/Medical-Agentic-Chatbot/app/redis_client.py) |
| **Evaluation & Benchmarks**| DeepEval, RAGAS, Custom G-Eval, Golden Clinical Dataset | [`app/evaluation.py`](file:///d:/New%20folder/Medical-Agentic-Chatbot/app/evaluation.py), [`eval.py`](file:///d:/New%20folder/Medical-Agentic-Chatbot/eval.py) |
| **Observability & Tracing**| LangSmith (LangChain Tracing v2), Rotating JSONL Audit Log | [`app/audit.py`](file:///d:/New%20folder/Medical-Agentic-Chatbot/app/audit.py) |
| **Vector RAG & Storage** | Pinecone Serverless Vector Store, PyMuPDF, OpenAI / Gemini Embeddings | [`app/knowledge.py`](file:///d:/New%20folder/Medical-Agentic-Chatbot/app/knowledge.py), [`ingest.py`](file:///d:/New%20folder/Medical-Agentic-Chatbot/ingest.py) |
| **Containerization** | Docker (Python 3.13-slim), Docker Compose | [`Dockerfile`](file:///d:/New%20folder/Medical-Agentic-Chatbot/Dockerfile), [`docker-compose.yml`](file:///d:/New%20folder/Medical-Agentic-Chatbot/docker-compose.yml) |

---

## 🚀 Getting Started in 3 Steps

1. **Configure Environment:**
   ```bash
   cp .env.example .env
   # Add your GEMINI_API_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY, and PINECONE_API_KEY
   ```
2. **Ingest Medical Knowledge Base:**
   ```bash
   python ingest.py --pdf data/medical_book.pdf
   ```
3. **Launch Server:**
   ```bash
   # Run directly with Python:
   uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

   # Or run with Docker Compose (includes Redis):
   docker compose up --build -d
   ```
   Open **http://127.0.0.1:8000** to interact with the medical agent.

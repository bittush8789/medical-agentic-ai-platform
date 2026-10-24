# 🩺 MedGuide AI — Multi-Model Medical Agent

[![Python 3.11+](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/Docker-Compose%20Ready-2496ED.svg?logo=docker&logoColor=white)](https://www.docker.com/)
[![Redis](https://img.shields.io/badge/Redis-7%20Cache-DC382D.svg?logo=redis&logoColor=white)](https://redis.io/)
[![LangGraph](https://img.shields.io/badge/LangGraph-Agentic%20Workflow-orange.svg)](https://langchain-ai.github.io/langgraph/)
[![License](https://img.shields.io/badge/License-Apache%202.0-green.svg)](LICENSE)

An enterprise-ready, educational medical agent featuring an **Autonomous LangGraph ReAct Agent**, **Unified LLM Gateway with Automatic Model Fallback**, **Dual Safety Guardrails (Microsoft Presidio & NVIDIA NeMo)**, **Agent Governance Toolkit**, **Long-Term Patient Memory (LangMem)**, and **Sub-Millisecond Redis Caching**.

---

## ✨ Key Features

- **🌐 Unified LLM Gateway & Fallback:** Seamlessly switch between **Google Gemini (2.5 / 2.0 Flash)**, **Anthropic Claude (3.5 Sonnet / Haiku)**, and **OpenAI (GPT-4.1 / GPT-4o)** via LiteLLM. Automatically triggers fallback models in milliseconds if an API fails or rate-limits.
- **🛡️ Dual Safety Perimeter:**
  - **Microsoft Presidio:** Real-time de-identification of PII/PHI (Names, Phone Numbers, MRN, SSN, Credit Cards).
  - **NVIDIA NeMo Guardrails:** Instant emergency triage interception (chest pain, stroke FAST, severe dyspnea), jailbreak defense, prescription & dosage blocking, and clinical disclaimer enforcement.
- **🧠 Agent Governance Toolkit:** Tool access control (RBAC), loop prevention budgets (max tool calls per turn), automated circuit breakers, and an emergency administrative kill-switch.
- **📝 Persistent Patient Memory (LangMem):** Cross-conversation extraction and recall of clinical facts (drug allergies, chronic conditions, current medications) backed by Redis and SQLite.
- **⚡ Redis Performance Acceleration:** Sub-millisecond response caching (reducing repetitive queries from ~2.5s to ~5ms) and sliding-window rate limiting with zero-crash in-memory fallback.
- **📊 Clinical Evaluation (DeepEval & RAGAS):** Comprehensive RAG Triad benchmarking (Faithfulness, Answer Relevancy, Hallucination, and Clinical Safety G-Eval) with an offline CLI runner (`eval.py`).
- **🔍 Hybrid Vector RAG:** Semantic vector retrieval using **Pinecone Serverless** paired with live fallback to **Tavily Search** for current clinical guidelines.
- **👁️ Multimodal & Voice Ready:** Dermatological image feature inspection (vision models) plus voice transcription (Whisper) and text-to-speech (TTS-1).

---

## 🚀 Quick Start

### Option A: Local Python Environment

```bash
# 1. Clone repository and install dependencies
pip install -r requirements.txt

# 2. Configure environment variables
copy .env.example .env
# Edit .env and supply your GEMINI_API_KEY, OPENAI_API_KEY, and PINECONE_API_KEY

# 3. Ingest reference medical knowledge base (run once)
python ingest.py --pdf data/medical_book.pdf

# 4. Start the FastAPI server
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
Open **http://127.0.0.1:8000** in your browser.

---

### Option B: Docker Compose (Recommended)

Run the full stack (**FastAPI App + Redis 7 + Redis Commander Admin**) with a single command:

```bash
# 1. Configure secrets
copy .env.example .env

# 2. Launch container stack
docker compose up --build -d

# 3. (Optional) Launch with Redis Commander UI on port 8081
docker compose --profile debug up --build -d
```

| Service | Endpoint | Description |
| :--- | :--- | :--- |
| **Web UI & Chatbot** | `http://localhost:8000` | Full interactive medical chat interface |
| **Swagger API Docs** | `http://localhost:8000/docs` | Interactive OpenAPI documentation |
| **System Health** | `http://localhost:8000/api/health` | Diagnostic status of all providers & services |
| **Redis Commander** | `http://localhost:8081` | Web admin UI to inspect cached responses & memory |

---

## 🏛️ System Architecture

```
                                  [ Patient / User ]
                                           │
                                    (HTTPS / JSON)
                                           ▼
                 ┌──────────────────────────────────────────────────┐
                 │             FastAPI Gateway Server               │
                 │   - Bearer Authentication                        │
                 │   - Sliding-Window Rate Limiting (Redis)         │
                 │   - Sub-millisecond Response Cache (5ms)         │
                 └─────────────────────────┬────────────────────────┘
                                           │
                      ┌────────────────────┴────────────────────┐
                      ▼                                         ▼
         ┌─────────────────────────┐               ┌─────────────────────────┐
         │  Microsoft Presidio     │               │  NVIDIA NeMo Guardrails │
         │  - PII / PHI Redaction  │               │  - Emergency Triage     │
         │  - Names/MRN/Phones/SSN │               │  - Jailbreak Protection │
         └────────────┬────────────┘               └────────────┬────────────┘
                      │                                         │
                      └────────────────────┬────────────────────┘
                                           ▼
                 ┌──────────────────────────────────────────────────┐
                 │       LangMem Long-Term Patient Memory           │
                 │   - Allergies, chronic conditions, medications   │
                 └─────────────────────────┬────────────────────────┘
                                           │
                                           ▼
                 ┌──────────────────────────────────────────────────┐
                 │          LangGraph ReAct Medical Agent           │
                 │   Retrieve (Pinecone) ──► Route ──► Tavily Web   │
                 │   [Governed by Circuit Breaker & Tool Budgets]   │
                 └─────────────────────────┬────────────────────────┘
                                           │
                                           ▼
                 ┌──────────────────────────────────────────────────┐
                 │       LLM Gateway & Automatic Fallback           │
                 │   Primary (Gemini) ──► Claude 3.5 ──► GPT-4.1    │
                 └─────────────────────────┬────────────────────────┘
                                           │
                                           ▼
                 ┌──────────────────────────────────────────────────┐
                 │          Output Safety & Compliance              │
                 │   - Prescription & Dosage Blocker                │
                 │   - Mandatory Clinical Disclaimer Enforcer       │
                 │   - Structured HIPAA JSONL Audit Logger          │
                 │   - DeepEval / Ragas & LangSmith Tracing         │
                 └──────────────────────────────────────────────────┘
```

---

## 📚 Documentation Hub

Detailed technical guides and operational documentation are available in the [`docs/`](docs/README.md) directory:

| Guide | Description |
| :--- | :--- |
| [**📖 Documentation Hub**](docs/README.md) | Central navigation hub and quick links for all technical guides |
| [**🏛️ System Architecture**](docs/ARCHITECTURE.md) | In-depth LangGraph state machine, data flows, and Mermaid diagrams |
| [**📡 API Reference**](docs/API_REFERENCE.md) | Comprehensive REST API specification, JSON schemas, and `curl` examples |
| [**🛡️ Guardrails & Safety**](docs/GUARDRAILS_AND_SAFETY.md) | Microsoft Presidio PII masks, NeMo emergency triage, and HIPAA compliance |
| [**🌐 LLM Gateway & Fallback**](docs/LLM_GATEWAY.md) | Multi-provider routing, zero-downtime failover, and model chain configuration |
| [**🧠 Governance, Memory & Redis**](docs/GOVERNANCE_MEMORY_REDIS.md) | Agent Governance Toolkit (RBAC, kill-switch), LangMem, and Redis caching |
| [**📊 Evaluation & Benchmarks**](docs/EVALUATION_AND_BENCHMARKS.md) | DeepEval & Ragas evaluation suite, 10 Golden Cases, and LangSmith tracing |
| [**🐳 Deployment & Docker**](docs/DEPLOYMENT_AND_DOCKER.md) | Production Dockerfile, Compose orchestration, and security checklist |
| [**🛡️ Enterprise AI Security**](docs/AI_SECURITY.md) | OWASP Top 10 for LLMs, Anti-Poisoning Gate, Indirect Injections, and Exfiltration |
| [**🚀 1M Users DevOps Runbook**](docs/UBUNTU_PRODUCTION_DEPLOYMENT.md) | Step-by-step Ubuntu setup for Terraform, AWS EKS, Helm 3, RDS, and CI/CD |

---

## 📡 Core API Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/health` | Comprehensive health check and active provider status |
| `POST` | `/api/chat` | Main clinical chat endpoint (RAG + Guardrails + Memory + AI Security) |
| `GET` | `/api/security/status` | Live Enterprise AI Security status and OWASP Top 10 matrix |
| `GET` | `/api/gateway` | Inspect current LLM Gateway fallback sequence |
| `GET` | `/api/guardrails` | Live status of Presidio PII and NeMo guardrails |
| `GET` | `/api/governance/status`| Live governance metrics, tool budgets, and circuit breaker |
| `POST` | `/api/governance/killswitch`| Freeze/resume all agent tool invocations |
| `GET` | `/api/memory` | Retrieve long-term patient profile facts (LangMem) |
| `GET` | `/api/redis/status` | Inspect Redis connection status and cache metrics |
| `POST` | `/api/eval/run` | Trigger on-demand DeepEval and Ragas evaluation run |
| `GET` | `/api/audit-logs` | Retrieve structured audit events with filtering |
| `POST` | `/api/transcribe` | Audio speech-to-text transcription via Whisper |
| `POST` | `/api/speak` | Text-to-speech audio synthesis via TTS-1 |

---

## 🧪 Clinical Benchmarking CLI (`eval.py`)

Run automated clinical benchmark evaluations against the golden test suite:

```bash
# Run evaluation across both DeepEval and RAGAS:
python eval.py

# Benchmark a specific foundation model:
python eval.py --model gemini/gemini-2.5-flash
python eval.py --model claude-3-5-sonnet-20241022

# Display latest evaluation scorecard:
python eval.py --latest
```

---

## 📁 Repository Structure

```
Medical-Agentic-Chatbot/
├── app/
│   ├── agent.py            # LangGraph ReAct Agent (Retrieve -> Route -> Answer)
│   ├── audit.py            # HIPAA-compliant JSONL & SQLite audit logger
│   ├── config.py           # Pydantic environment configuration
│   ├── evaluation.py       # DeepEval & Ragas benchmark engine
│   ├── governance.py       # Agent Governance Toolkit (RBAC, budgets, kill-switch)
│   ├── guardrails.py       # Presidio PII masking & NeMo Guardrails
│   ├── knowledge.py        # Pinecone vector retrieval & embeddings
│   ├── llm.py              # LLM Gateway with automatic multi-provider fallback
│   ├── main.py             # FastAPI REST server & streaming endpoints
│   ├── memory.py           # LangMem long-term patient clinical memory
│   ├── redis_client.py     # Redis caching layer with in-memory fallback
│   └── security.py         # Enterprise AI Security Engine (OWASP Top 10 for LLMs)
├── data/
│   └── medical_book.pdf    # Clinical reference encyclopedia PDF
├── docs/                   # Comprehensive technical documentation hub
│   ├── README.md           # Documentation index
│   ├── ARCHITECTURE.md     # System design & Mermaid diagrams
│   ├── API_REFERENCE.md    # Full REST API specifications
│   ├── AI_SECURITY.md      # Enterprise AI Security & OWASP mitigations
│   ├── GUARDRAILS_AND_SAFETY.md
│   ├── LLM_GATEWAY.md
│   ├── GOVERNANCE_MEMORY_REDIS.md
│   ├── EVALUATION_AND_BENCHMARKS.md
│   ├── DEPLOYMENT_AND_DOCKER.md
│   └── INGESTION_AND_KNOWLEDGE_BASE.md
├── static/                 # Frontend CSS and JavaScript
├── templates/              # Chatbot web interface (HTML)
├── Dockerfile              # Multi-stage production container build
├── docker-compose.yml      # Orchestration (FastAPI + Redis 7 + Admin UI)
├── eval.py                 # CLI benchmark runner
├── ingest.py               # PDF knowledge base indexing script
└── requirements.txt        # Python dependencies
```

---

## ⚠️ Clinical Disclaimer & Educational Notice

> **IMPORTANT:** MedGuide AI is designed strictly for **educational, triage demonstration, and research purposes**. It is **not** a certified medical diagnostic device and does **not** provide formal medical diagnoses, prescription drug dosages, or clinical treatment plans.
>
> In the event of a medical emergency, acute chest pain, stroke symptoms, severe breathing difficulty, or suicidal ideation, immediately call your local emergency services (**911** in the US/Canada, **112** in Europe/India) or proceed to the nearest emergency department.

---

## 📄 License

This project is licensed under the Apache License 2.0. See the [LICENSE](LICENSE) file for details.

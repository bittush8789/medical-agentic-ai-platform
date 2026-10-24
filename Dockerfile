# ==============================================================================
# MedGuide AI — Production Docker Image
# Multi-stage build for Medical Agentic Chatbot
# ==============================================================================

# ---------------------------------------------------------------------------
# Stage 1: Builder — Install dependencies in isolated layer
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS builder

WORKDIR /build

# System dependencies for Presidio (spaCy NLP models), PyMuPDF, and compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies (cached unless requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Download spaCy English model required by Presidio NER
RUN pip install --no-cache-dir --prefix=/install spacy \
    && /install/bin/python -m spacy download en_core_web_lg 2>/dev/null || \
       python -m spacy download en_core_web_lg


# ---------------------------------------------------------------------------
# Stage 2: Runtime — Lean production image
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS runtime

# Labels for container metadata
LABEL maintainer="MedGuide AI Team"
LABEL description="Medical Agentic Chatbot — LangGraph + LiteLLM Gateway + Pinecone RAG + Redis + Agent Governance"
LABEL version="1.0.0"

# Security: Run as non-root user
RUN groupadd -r medguide && useradd -r -g medguide -m -s /bin/bash medguide

# Runtime system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local
COPY --from=builder /usr/local/lib/python3.13/site-packages/en_core_web_lg /usr/local/lib/python3.13/site-packages/en_core_web_lg 2>/dev/null || true

# Copy application source code
COPY app/ ./app/
COPY static/ ./static/
COPY templates/ ./templates/
COPY data/ ./data/
COPY ingest.py .
COPY eval.py .
COPY requirements.txt .

# Create necessary directories with correct ownership
RUN mkdir -p /app/logs /app/data \
    && chown -R medguide:medguide /app

# Environment defaults (override via docker-compose or .env file)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONIOENCODING=utf-8 \
    # Redis: Points to docker-compose Redis service by default
    REDIS_URL=redis://redis:6379/0 \
    ENABLE_REDIS_CACHE=true \
    # Agent Governance
    ENABLE_AGENT_GOVERNANCE=true \
    MAX_TOOL_CALLS_PER_TURN=6 \
    RATE_LIMIT_RPM=60 \
    # LangMem
    ENABLE_LANGMEM=true \
    # Audit Logging
    ENABLE_AUDIT_LOGGING=true \
    # Guardrails
    ENABLE_GUARDRAILS=true \
    ENABLE_PRESIDIO_PII=true \
    ENABLE_NEMO_GUARDRAILS=true \
    # LangSmith (disabled by default in container)
    LANGCHAIN_TRACING_V2=false \
    # Server
    HOST=0.0.0.0 \
    PORT=8000

# Expose FastAPI port
EXPOSE 8000

# Health check — hits /api/health every 30s
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# Switch to non-root user
USER medguide

# Start uvicorn server
CMD ["python", "-m", "uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--timeout-keep-alive", "120", \
     "--log-level", "info"]

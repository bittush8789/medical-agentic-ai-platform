# MedGuide AI — Deployment & Docker Architecture 🐳

This guide outlines containerization and production deployment procedures for **MedGuide AI**, including Docker multi-stage builds, Docker Compose orchestration, Redis integration, and production hardening.

---

## 1. Containerization Architecture

MedGuide AI is packaged as a lightweight, secure, and production-ready container image:

```
┌─────────────────────────────────────────────────────────────┐
│                  DOCKER COMPOSE STACK                       │
│                                                             │
│   ┌─────────────────┐       ┌──────────────────────────┐   │
│   │   Redis 7        │◄──────│   MedGuide FastAPI App   │   │
│   │   (Alpine)       │       │   (Python 3.13-slim)     │   │
│   │   Port: 6379     │       │   Port: 8000             │   │
│   │   256MB LRU      │       │   Non-root user (appuser)│   │
│   │   AOF Persist    │       │   Health-checked         │   │
│   └─────────────────┘       └──────────────────────────┘   │
│            ▲                                                │
│   ┌────────┴────────┐   (debug profile only)               │
│   │ Redis Commander  │                                      │
│   │ Port: 8081       │                                      │
│   └─────────────────┘                                      │
└─────────────────────────────────────────────────────────────┘
```

### 1.1. Security & Hardening Highlights
- **Multi-Stage Build:** Dependencies are compiled in a temporary builder stage and only the clean wheels and runtime libraries are copied into the final image, minimizing image size and attack surface.
- **Non-Root Execution:** The application executes under a dedicated non-root user (`appuser` with UID `10001`), preventing privilege escalation.
- **Active Health Checks:** Both the FastAPI app (`curl -f http://localhost:8000/api/health`) and the Redis container (`redis-cli ping`) report container health status to Docker.
- **Exclusion of Secrets:** `.dockerignore` strictly excludes `.env`, `.git`, temporary scratch files, and virtual environments from the build context.

---

## 2. Quick Start with Docker Compose

### Step 1: Prepare Environment
Ensure your `.env` file exists and has the necessary API keys:
```bash
cp .env.example .env
# Edit .env and supply GEMINI_API_KEY, PINECONE_API_KEY, etc.
```

### Step 2: Build & Start Stack
```bash
# Start all core services in detached mode:
docker compose up --build -d
```

### Step 3: Verify Services
```bash
# Check container status
docker compose ps

# View real-time logs
docker compose logs -f app
```

Once running, access:
- **Application Web UI:** `http://localhost:8000`
- **Interactive Swagger Docs:** `http://localhost:8000/docs`
- **Health Endpoint:** `http://localhost:8000/api/health`

### Optional: Start with Redis Commander UI
For inspecting cached chat responses and memory keys in real-time:
```bash
docker compose --profile debug up --build -d
```
Open **http://localhost:8081** to view the Redis web interface.

---

## 3. Production Deployment Checklist

Before exposing MedGuide AI to public traffic:

### 3.1. Reverse Proxy & TLS/SSL
Always place a reverse proxy (e.g., **Nginx**, **Caddy**, or **Cloudflare**) in front of the container:
```nginx
server {
    listen 443 ssl http2;
    server_name ai.yourclinic.org;

    ssl_certificate /etc/letsencrypt/live/ai.yourclinic.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/ai.yourclinic.org/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket & Streaming support
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

### 3.2. Data Persistence
Ensure Docker volume mounts are mapped to persistent block storage:
- `logs:/app/logs`: Stores HIPAA audit trails (`audit.log`).
- `data:/app/data`: Stores PDF medical encyclopedias.
- `medical_memory.db`: Persists LangMem SQLite patient memory records.

### 3.3. Worker Concurrency
For high concurrency in production environments, configure Uvicorn with multiple workers:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4 --proxy-headers
```

### 3.4. API Token Authentication
Enable bearer token authentication by setting:
```ini
API_TOKEN=your-randomly-generated-64-char-token
```
Clients must then pass `Authorization: Bearer <API_TOKEN>` for protected routes.

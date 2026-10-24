# MedGuide AI — Local Kubernetes Development Guide (Kind / Minikube) 💻☸️

This guide provides step-by-step instructions for testing and running the complete **MedGuide AI** production Kubernetes stack locally on **Ubuntu / macOS / Windows (WSL2)** without incurring any AWS cloud costs.

---

## 📑 Table of Contents

1. [Local Architecture Overview](#1-local-architecture-overview)
2. [Prerequisites & Tooling Installation](#2-prerequisites--tooling-installation)
3. [Phase 1: Spin Up Local Kubernetes Cluster (Kind)](#3-phase-1-spin-up-local-kubernetes-cluster-kind)
4. [Phase 2: Deploy Local Infrastructure (Postgres & Redis via Helm)](#4-phase-2-deploy-local-infrastructure-postgres--redis-via-helm)
5. [Phase 3: Deploy MedGuide AI via Helm](#5-phase-3-deploy-medguide-ai-via-helm)
6. [Phase 4: Ingress & Local Domain Resolution](#6-phase-4-ingress--local-domain-resolution)
7. [Phase 5: Test Autoscaling (HPA) Locally](#7-phase-5-test-autoscaling-hpa-locally)
8. [Phase 6: Cluster Teardown](#8-phase-6-cluster-teardown)

---

## 1. Local Architecture Overview

```
 [ Local Browser / curl ] ──► localhost:80 / localhost:443
                                       │
                                       ▼
                   ┌───────────────────────────────────────┐
                   │    Kind Ingress NGINX Controller      │
                   └───────────────────┬───────────────────┘
                                       │ (Routing via medguide.local)
                                       ▼
                   ┌───────────────────────────────────────┐
                   │   medguide-ai-service (ClusterIP)     │
                   └───────────────────┬───────────────────┘
                                       │
         ┌─────────────────────────────┼─────────────────────────────┐
         ▼                             ▼                             ▼
 ┌───────────────┐             ┌───────────────┐             ┌───────────────┐
 │ Pod 1 (FastAPI)│            │ Pod 2 (FastAPI)│            │ Pod 3 (FastAPI)│ (HPA: 2-10 pods)
 └───────┬───────┘             └───────┬───────┘             └───────┬───────┘
         │                             │                             │
         └─────────────────────────────┼─────────────────────────────┘
                                       │
                    ┌──────────────────┴──────────────────┐
                    ▼                                     ▼
        ┌───────────────────────┐             ┌───────────────────────┐
        │  Bitnami PostgreSQL   │             │     Bitnami Redis     │
        │   (Port 5432 - PVC)   │             │   (Port 6379 - PVC)   │
        └───────────────────────┘             └───────────────────────┘
```

---

## 2. Prerequisites & Tooling Installation

Ensure you have the following installed on your local machine:

### A. Docker Engine
```bash
# Verify Docker is running
docker --version
docker ps
```

### B. kubectl (Kubernetes CLI)
```bash
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
kubectl version --client
```

### C. Kind (Kubernetes-in-Docker)
```bash
# Install Kind binary (Linux amd64)
curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.23.0/kind-linux-amd64
chmod +x ./kind
sudo mv ./kind /usr/local/bin/kind
kind --version
```

### D. Helm 3
```bash
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
helm version
```

---

## 3. Phase 1: Spin Up Local Kubernetes Cluster (Kind)

Create a Kind configuration file that maps ports `80` and `443` to the host machine for NGINX Ingress:

### Step 1: Create `kind-config.yaml`
```yaml
cat <<EOF > kind-config.yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
name: medguide-local
nodes:
- role: control-plane
  kubeadmConfigPatches:
  - |
    kind: InitConfiguration
    nodeRegistration:
      kubeletExtraArgs:
        node-labels: "ingress-ready=true"
  extraPortMappings:
  - containerPort: 80
    hostPort: 80
    protocol: TCP
  - containerPort: 443
    hostPort: 443
    protocol: TCP
- role: worker
- role: worker
EOF
```

### Step 2: Create Cluster
```bash
kind create cluster --config kind-config.yaml

# Verify nodes
kubectl get nodes -o wide
```

### Step 3: Install NGINX Ingress Controller for Kind
```bash
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml

# Wait for ingress controller pod to be Ready
kubectl wait --namespace ingress-nginx \
  --for=condition=ready pod \
  --selector=app.kubernetes.io/component=controller \
  --timeout=120s
```

### Step 4: Install Metrics Server (for HPA testing)
```bash
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml

# Patch metrics-server to allow insecure TLS in local dev
kubectl patch deployment metrics-server -n kube-system --type 'json' -p '[{"op": "add", "path": "/spec/template/spec/containers/0/args/-", "value": "--kubelet-insecure-tls"}]'

# Verify metrics-server
kubectl top nodes
```

---

## 4. Phase 2: Deploy Local Infrastructure (Postgres & Redis via Helm)

### Step 1: Create Namespaces
```bash
kubectl create namespace medguide-data
kubectl create namespace medguide-prod
```

### Step 2: Deploy Redis via Bitnami Helm Chart
```bash
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo update

helm install local-redis bitnami/redis \
  --namespace medguide-data \
  --set auth.enabled=false \
  --set architecture=standalone \
  --set master.persistence.size=2Gi

# Local Redis endpoint:
# redis://local-redis-master.medguide-data.svc.cluster.local:6379/0
```

### Step 3: Deploy PostgreSQL via Bitnami Helm Chart
```bash
helm install local-postgres bitnami/postgresql \
  --namespace medguide-data \
  --set auth.username=medguide_admin \
  --set auth.password=LocalDevPassword123! \
  --set auth.database=medguide_clinical \
  --set primary.persistence.size=5Gi

# Local Postgres endpoint:
# postgresql://medguide_admin:LocalDevPassword123!@local-postgres.medguide-data.svc.cluster.local:5432/medguide_clinical
```

---

## 5. Phase 3: Deploy MedGuide AI via Helm

### Step 1: Build & Load Docker Image into Kind
Bypasses the need for pushing to a remote registry:

```bash
# Build local docker image
docker build -t medguide-ai:local .

# Load directly into Kind nodes
kind load docker-image medguide-ai:local --name medguide-local
```

### Step 2: Create Local Secrets
```bash
kubectl create secret generic medguide-secrets \
  --namespace medguide-prod \
  --from-literal=DATABASE_URL="postgresql://medguide_admin:LocalDevPassword123!@local-postgres.medguide-data.svc.cluster.local:5432/medguide_clinical" \
  --from-literal=REDIS_URL="redis://local-redis-master.medguide-data.svc.cluster.local:6379/0" \
  --from-literal=GEMINI_API_KEY="${GEMINI_API_KEY}" \
  --from-literal=ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY}" \
  --from-literal=OPENAI_API_KEY="${OPENAI_API_KEY}" \
  --from-literal=PINECONE_API_KEY="${PINECONE_API_KEY}" \
  --from-literal=TAVILY_API_KEY="${TAVILY_API_KEY}" \
  --from-literal=API_BEARER_TOKEN="local-dev-secret-token"
```

### Step 3: Install Helm Chart with Local Overrides
```bash
helm install medguide ./helm/medguide \
  --namespace medguide-prod \
  --set image.repository=medguide-ai \
  --set image.tag=local \
  --set image.pullPolicy=Never \
  --set replicaCount=2 \
  --set ingress.enabled=true \
  --set ingress.className=nginx \
  --set ingress.hosts[0].host=medguide.local \
  --set ingress.hosts[0].paths[0].path=/ \
  --set ingress.hosts[0].paths[0].pathType=Prefix
```

### Step 4: Verify Deployment Status
```bash
kubectl get pods -n medguide-prod -w
```

---

## 6. Phase 4: Ingress & Local Domain Resolution

### Step 1: Map `medguide.local` to `127.0.0.1`

Add the following entry to your hosts file:
* **Linux / macOS:** `/etc/hosts`
* **Windows:** `C:\Windows\System32\drivers\etc\hosts`

```
127.0.0.1   medguide.local
```

### Step 2: Test Endpoints via `curl`

```bash
# 1. Health check
curl -X GET http://medguide.local/api/health

# 2. AI Security Status
curl -X GET http://medguide.local/api/security/status

# 3. Test Chat Query
curl -X POST http://medguide.local/api/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer local-dev-secret-token" \
  -d '{"message": "What are the common symptoms of asthma?", "user_id": "local_dev_user"}'
```

---

## 7. Phase 5: Test Autoscaling (HPA) Locally

### Step 1: Inspect Initial HPA Status
```bash
kubectl get hpa -n medguide-prod
```

### Step 2: Generate Load with ApacheBench or Hey
```bash
# Send 10,000 requests with 50 concurrent connections
kubectl run load-generator \
  --rm -i --tty \
  --image=busybox:latest \
  --restart=Never -- \
  /bin/sh -c "while true; do wget -q -O- http://medguide-service.medguide-prod.svc.cluster.local:8000/api/health; done"
```

### Step 3: Observe HPA Scaling Up
In a separate terminal:
```bash
kubectl get hpa -n medguide-prod -w
```
You will observe pods scaling from `2` up to `5+` as CPU utilization breaches the target threshold.

---

## 8. Phase 6: Cluster Teardown

To cleanly wipe all local cluster resources:

```bash
kind delete cluster --name medguide-local
```

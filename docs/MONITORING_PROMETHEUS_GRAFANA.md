# MedGuide AI — Monitoring, Observability & Alerting Runbook 📊🚨
## Enterprise Prometheus, Grafana, & Alertmanager Deployment for Agentic AI

This runbook details how to deploy and configure an enterprise observability stack to monitor **MedGuide AI** across Kubernetes. It covers AI-specific metrics (token throughput, LLM gateway latency, model fallback rates, guardrail interceptions), infrastructure health, and production Alertmanager rules.

---

## 📑 Table of Contents

1. [Observability Architecture](#1-observability-architecture)
2. [AI Platform Metric Definitions](#2-ai-platform-metric-definitions)
3. [Deploying Prometheus & Grafana via Helm](#3-deploying-prometheus--grafana-via-helm)
4. [Kubernetes `ServiceMonitor` Configuration](#4-kubernetes-servicemonitor-configuration)
5. [Alertmanager Rules (`PrometheusRule`)](#5-alertmanager-rules-prometheusrule)
6. [Production Grafana Dashboards](#6-production-grafana-dashboards)
7. [Log Aggregation via Loki / CloudWatch](#7-log-aggregation-via-loki--cloudwatch)

---

## 1. Observability Architecture

```
                    ┌─────────────────────────────────────────────────────┐
                    │               Kubernetes Cluster                    │
                    │                                                     │
                    │   ┌──────────────────┐      ┌──────────────────┐   │
                    │   │ MedGuide Pod 1   │      │ MedGuide Pod 2   │   │
                    │   │  :8000/metrics   │      │  :8000/metrics   │   │
                    │   └────────┬─────────┘      └────────┬─────────┘   │
                    │            │                         │             │
                    │            └────────────┬────────────┘             │
                    │                         │ (Scrape /metrics 15s)    │
                    │                         ▼                          │
                    │             ┌───────────────────────┐              │
                    │             │ Prometheus Server TSDB│              │
                    │             └───────────┬───────────┘              │
                    │                         │                          │
                    └─────────────────────────┼──────────────────────────┘
                                              │
                      ┌───────────────────────┴───────────────────────┐
                      ▼                                               ▼
          ┌───────────────────────┐                       ┌───────────────────────┐
          │   Grafana Dashboard   │                       │     Alertmanager      │
          │   (SLO/SLI Panels)    │                       │  (Slack / PagerDuty)  │
          └───────────────────────┘                       └───────────────────────┘
```

---

## 2. AI Platform Metric Definitions

In addition to standard HTTP telemetry (`http_requests_total`, `http_request_duration_seconds`), MedGuide AI exposes dedicated Prometheus gauges, counters, and histograms:

| Metric Name | Type | Labels | Description |
| :--- | :--- | :--- | :--- |
| `llm_gateway_requests_total` | Counter | `provider`, `model`, `status` | Total LLM invocations across Gemini, Claude, and GPT-4 |
| `llm_gateway_latency_seconds` | Histogram | `provider`, `model` | End-to-end token generation & inference latency (p50, p95, p99) |
| `llm_gateway_fallbacks_total` | Counter | `from_model`, `to_model`, `reason` | Count of automatic failovers triggered due to timeouts or 429s |
| `presidio_phi_redactions_total` | Counter | `entity_type` | De-identified clinical entities (`PERSON`, `PHONE`, `MRN`, `SSN`) |
| `nemo_guardrail_blocks_total` | Counter | `rail`, `trigger_reason` | Emergency triage intercepts, jailbreaks, and dosage blocks |
| `security_injections_blocked_total` | Counter | `attack_type` | OWASP direct prompt overrides and indirect RAG injections neutralized |
| `redis_cache_hits_total` | Counter | `cache_type` | Queries resolved in <5ms without triggering downstream LLM |
| `redis_cache_misses_total` | Counter | `cache_type` | Queries requiring full LangGraph state machine execution |
| `langmem_facts_stored_total` | Counter | `category` | Verified clinical facts written to persistent memory |
| `db_connection_pool_active` | Gauge | `pool_name` | Current active PostgreSQL connections in PgBouncer pool |

---

## 3. Deploying Prometheus & Grafana via Helm

We utilize the battle-tested `kube-prometheus-stack` Helm chart:

### Step 1: Add Helm Repository
```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
```

### Step 2: Create `monitoring-values.yaml`
```yaml
cat <<EOF > monitoring-values.yaml
grafana:
  enabled: true
  adminPassword: "StrongGrafanaPassword2026!"
  ingress:
    enabled: true
    ingressClassName: alb
    annotations:
      alb.ingress.kubernetes.io/scheme: internet-facing
      alb.ingress.kubernetes.io/target-type: ip
    hosts:
      - grafana.yourdomain.com

prometheus:
  prometheusSpec:
    serviceMonitorSelectorNilUsesHelmValues: false
    retention: 30d
    storageSpec:
      volumeClaimTemplate:
        spec:
          storageClassName: gp3
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 50Gi

alertmanager:
  config:
    global:
      resolve_timeout: 5m
    route:
      group_by: ['alertname', 'namespace']
      group_wait: 30s
      group_interval: 5m
      repeat_interval: 4h
      receiver: 'slack-notifications'
    receivers:
    - name: 'slack-notifications'
      slack_configs:
      - channel: '#alerts-ai-platform'
        send_resolved: true
        api_url: 'https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK'
EOF
```

### Step 3: Install `kube-prometheus-stack`
```bash
kubectl create namespace monitoring

helm install prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --values monitoring-values.yaml
```

---

## 4. Kubernetes `ServiceMonitor` Configuration

To instruct Prometheus to automatically discover and scrape the MedGuide AI application pods every 15 seconds:

### `k8s/servicemonitor.yaml`
```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: medguide-servicemonitor
  namespace: medguide-prod
  labels:
    release: prometheus-stack
spec:
  selector:
    matchLabels:
      app: medguide-ai
  endpoints:
  - port: http
    path: /api/metrics
    interval: 15s
    scrapeTimeout: 10s
```

Apply to cluster:
```bash
kubectl apply -f k8s/servicemonitor.yaml
```

---

## 5. Alertmanager Rules (`PrometheusRule`)

These production rules alert engineers to clinical safety anomalies, cloud provider failures, or infrastructure exhaustion:

### `k8s/prometheus-rules.yaml`
```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: medguide-ai-alerts
  namespace: medguide-prod
  labels:
    release: prometheus-stack
spec:
  groups:
  - name: medguide-ai-clinical-and-llm-alerts
    rules:
    
    # 1. High LLM Fallback Rate Alert
    - alert: HighLLMFallbackRate
      expr: rate(llm_gateway_fallbacks_total[5m]) / rate(llm_gateway_requests_total[5m]) > 0.15
      for: 3m
      labels:
        severity: critical
        team: ai-platform
      annotations:
        summary: "Primary LLM provider failover exceeds 15%"
        description: "Google Gemini 2.5 is failing over to Anthropic Claude or OpenAI at {{ $value | humanizePercentage }} of requests. Inspect provider API quotas and latency."

    # 2. P99 Latency Breach Alert
    - alert: HighP99ChatLatency
      expr: histogram_quantile(0.99, sum(rate(llm_gateway_latency_seconds_bucket[5m])) by (le)) > 4.0
      for: 5m
      labels:
        severity: warning
        team: ai-platform
      annotations:
        summary: "P99 Chat Latency exceeds 4.0s"
        description: "End-to-end medical response latency for 99th percentile is {{ $value }}s."

    # 3. Cache Miss Spike
    - alert: LowRedisCacheHitRatio
      expr: sum(rate(redis_cache_hits_total[10m])) / (sum(rate(redis_cache_hits_total[10m])) + sum(rate(redis_cache_misses_total[10m]))) < 0.20
      for: 15m
      labels:
        severity: warning
        team: devops
      annotations:
        summary: "Redis Cache Hit Ratio dropped below 20%"
        description: "Cache hit ratio is currently {{ $value | humanizePercentage }}. Downstream LLM API costs may spike."

    # 4. Database Connection Pool Exhaustion
    - alert: DatabasePoolExhaustion
      expr: db_connection_pool_active > 90
      for: 2m
      labels:
        severity: critical
        team: devops
      annotations:
        summary: "RDS PostgreSQL connection pool > 90% capacity"
        description: "PgBouncer pool active connections reached {{ $value }}. Incoming queries risk queuing or dropping."

    # 5. Pod Restart Loop (CrashLoopBackOff)
    - alert: MedGuidePodCrashLooping
      expr: rate(kube_pod_container_status_restarts_total{container="medguide-ai"}[10m]) * 600 > 3
      for: 5m
      labels:
        severity: critical
        team: devops
      annotations:
        summary: "MedGuide AI pods are crashing repeatedly"
        description: "Pod is restarting frequently in namespace medguide-prod."
```

Apply rules:
```bash
kubectl apply -f k8s/prometheus-rules.yaml
```

---

## 6. Production Grafana Dashboards

The MedGuide AI platform dashboard is organized into four visual quadrants:

### Quadrant 1: Executive SLO / SLI Health
* **Availability SLI:** `(1 - (sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m])))) * 100` (Target: 99.95%)
* **Cache Efficiency:** Real-time gauge of Redis hit percentage.
* **Active Concurrent Streams:** Live Server-Sent Events (SSE) connections.

### Quadrant 2: LLM Gateway & Provider Telemetry
* **Throughput by Provider:** Stacked area chart showing QPS across Gemini, Claude, and OpenAI.
* **Latency Heatmap:** p50, p90, and p99 generation latency across models.
* **Fallback Matrix:** Sankey diagram showing source model -> failover trigger -> target model.

### Quadrant 3: Clinical Safety & AI Security
* **Presidio PHI Masking Rate:** Stacked bar chart showing names, phone numbers, and MRNs redacted per minute.
* **Emergency Triage Triggers:** Count of critical chest pain/stroke interventions.
* **OWASP Attack Neutralization:** Count of prompt injection / jailbreak attempts repelled.

### Quadrant 4: Infrastructure & Pod Telemetry
* **HPA Replica Count vs CPU Utilization:** Visual correlation between traffic spikes and pod scale-out.
* **Memory RSS per Worker:** Monitoring for Python memory leaks.
* **PostgreSQL PgBouncer Pool Depth:** Active vs idle database connections.

---

## 7. Log Aggregation via Loki / CloudWatch

All application containers stream JSON-formatted structured logs directly to stdout:

```json
{
  "timestamp": "2026-10-24T17:15:00.123Z",
  "level": "INFO",
  "trace_id": "9f8b4e2a-1c3d-4e5f-b7a9-0d1e2f3a4b5c",
  "endpoint": "/api/chat",
  "user_id": "patient_847291",
  "cache_hit": false,
  "presidio_phi_detected": true,
  "phi_entities": ["PERSON", "DATE_TIME"],
  "primary_model": "gemini/gemini-2.5-flash",
  "model_used": "gemini/gemini-2.5-flash",
  "latency_ms": 1142,
  "disclaimer_attached": true
}
```

These logs are captured by **FluentBit** daemonsets on EKS and forwarded to **Amazon CloudWatch Logs** with a 90-day HIPAA retention policy.

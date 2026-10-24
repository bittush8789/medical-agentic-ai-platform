# MedGuide AI — Disaster Recovery & Zero-Downtime Runbook 🛡️🔄
## Enterprise High Availability, Canary Deployments, & Incident Response Playbooks

This runbook establishes disaster recovery (DR) protocols, zero-downtime deployment patterns, and Sev-1/Sev-2 incident playbooks for **MedGuide AI** operating at 1,000,000 user scale.

---

## 📑 Table of Contents

1. [High Availability & DR Objectives (RPO / RTO)](#1-high-availability--dr-objectives-rpo--rto)
2. [Multi-Region Active-Passive Architecture](#2-multi-region-active-passive-architecture)
3. [AWS RDS PostgreSQL Backup & Point-In-Time Recovery (PITR)](#3-aws-rds-postgresql-backup--point-in-time-recovery-pitr)
4. [Zero-Downtime Deployment Strategies](#4-zero-downtime-deployment-strategies)
   - [A. Kubernetes Rolling Updates](#a-kubernetes-rolling-updates)
   - [B. Progressive Canary Deployments (Argo Rollouts)](#b-progressive-canary-deployments-argo-rollouts)
   - [C. Blue-Green Deployments (AWS ALB Target Groups)](#c-blue-green-deployments-aws-alb-target-groups)
5. [Sev-1 / Sev-2 Incident Response Playbooks](#5-sev-1--sev-2-incident-response-playbooks)
   - [Playbook 1: Total Foundation LLM Outage](#playbook-1-total-foundation-llm-outage)
   - [Playbook 2: Database Connection Pool Exhaustion](#playbook-2-database-connection-pool-exhaustion)
   - [Playbook 3: Redis ElastiCache Failure](#playbook-3-redis-elasticache-failure)
   - [Playbook 4: Active Prompt Injection Attack (Kill-Switch Activation)](#playbook-4-active-prompt-injection-attack-kill-switch-activation)

---

## 1. High Availability & DR Objectives (RPO / RTO)

| Metric | Target SLA | Strategy |
| :--- | :--- | :--- |
| **Availability** | **99.99%** | Multi-AZ EKS worker nodes, RDS Multi-AZ Standby, Redis Multi-AZ replication |
| **Recovery Point Objective (RPO)** | **< 5 minutes** | Continuous WAL archiving in RDS PostgreSQL; AWS S3 continuous audit backups |
| **Recovery Time Objective (RTO)** | **< 15 minutes** | Automated DNS failover via Route 53; pre-provisioned warm standby cluster |

---

## 2. Multi-Region Active-Passive Architecture

```
                                [ Amazon Route 53 ]
                          (Latency & Health Check Routing)
                                        │
                 ┌──────────────────────┴──────────────────────┐
                 │ (100% Traffic - Healthy)                    │ (Failover on 3x Unhealthy)
                 ▼                                             ▼
     [ Primary: us-east-1 ]                        [ Secondary DR: us-west-2 ]
  ┌──────────────────────────────┐              ┌──────────────────────────────┐
  │  AWS ALB Ingress             │              │  AWS ALB Ingress             │
  │  Amazon EKS (5-50 Pods)      │              │  Amazon EKS (Warm: 2 Pods)   │
  │  RDS Postgres (Multi-AZ)     │──Async Repl─►│  RDS Cross-Region Replica    │
  │  ElastiCache Redis Cluster   │              │  ElastiCache Redis Cluster   │
  └──────────────────────────────┘              └──────────────────────────────┘
```

### Route 53 Health Check Configuration
```bash
aws route53 create-health-check \
  --caller-reference "medguide-primary-$(date +%s)" \
  --health-check-config '{
    "IPAddress": "PRIMARY_ALB_IP",
    "Port": 443,
    "Type": "HTTPS",
    "ResourcePath": "/api/health",
    "FullyQualifiedDomainName": "api.medguide.com",
    "RequestInterval": 10,
    "FailureThreshold": 3
  }'
```

---

## 3. AWS RDS PostgreSQL Backup & Point-In-Time Recovery (PITR)

### Automated Backup Policy
* **Continuous WAL Archival:** Every 5 minutes to S3.
* **Automated Daily Snapshots:** Captured at 03:00 UTC with 35-day retention.
* **Storage Encryption:** AWS KMS (`aws/rds`).

### Step-by-Step Point-In-Time Recovery Procedure
If catastrophic data corruption occurs at `2026-10-24 14:32:00 UTC`:

```bash
# 1. Restore database to 14:30:00 UTC (2 minutes prior to corruption)
aws rds restore-db-instance-to-point-in-time \
  --source-db-instance-identifier medguide-prod-postgres \
  --target-db-instance-identifier medguide-prod-postgres-restored \
  --restore-time "2026-10-24T14:30:00.000Z" \
  --db-subnet-group-name medguide-prod-db-subnet-group \
  --vpc-security-group-ids "sg-xxxxxxx" \
  --auto-minor-version-upgrade

# 2. Wait for restored instance to become available
aws rds wait db-instance-available \
  --db-instance-identifier medguide-prod-postgres-restored

# 3. Retrieve restored database endpoint
RESTORED_ENDPOINT=$(aws rds describe-db-instances \
  --db-instance-identifier medguide-prod-postgres-restored \
  --query 'DBInstances[0].Endpoint.Address' \
  --output text)

# 4. Update Kubernetes Secret with new DB endpoint
kubectl set env deployment/medguide-ai-deployment \
  -n medguide-prod \
  DATABASE_URL="postgresql://medguide_admin:Password@${RESTORED_ENDPOINT}:5432/medguide_clinical"
```

---

## 4. Zero-Downtime Deployment Strategies

### A. Kubernetes Rolling Updates
Ensures new pods are verified healthy by readiness probes before old pods receive `SIGTERM`:

```yaml
# In k8s/deployment.yaml
spec:
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 25%         # Spin up 25% new pods first
      maxUnavailable: 0     # Never drop below 100% capacity
  template:
    spec:
      terminationGracePeriodSeconds: 60
      containers:
      - name: medguide-ai
        lifecycle:
          preStop:
            exec:
              command: ["/bin/sh", "-c", "sleep 15"] # Let active SSE streams finish
        readinessProbe:
          httpGet:
            path: /api/health
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 5
```

---

### B. Progressive Canary Deployments (Argo Rollouts)

Automates progressive traffic shifting (10% -> 25% -> 50% -> 100%) with automated rollbacks if error rates exceed 0.5%:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: medguide-rollout
  namespace: medguide-prod
spec:
  replicas: 10
  strategy:
    canary:
      analysis:
        templates:
        - template-name: success-rate-analysis
      steps:
      - setWeight: 10
      - pause: { duration: 5m }   # Monitor 10% traffic for 5 mins
      - setWeight: 25
      - pause: { duration: 10m }  # Monitor 25% traffic for 10 mins
      - setWeight: 50
      - pause: { duration: 10m }  # Monitor 50% traffic
      - setWeight: 100
```

---

### C. Blue-Green Deployments (AWS ALB Target Groups)

1. **Deploy Green Version:** Helm deploys the new release into parallel pods and registers them to `tg-medguide-green`.
2. **Execute Smoke Tests:** Automated integration and DeepEval tests run against internal green DNS.
3. **Shift Traffic:** Route 53 or ALB modifies listener rule weight:
   * Target Group Blue: `0%`
   * Target Group Green: `100%`
4. **Decommission Blue:** After 30 minutes with zero errors.

---

## 5. Sev-1 / Sev-2 Incident Response Playbooks

### Playbook 1: Total Foundation LLM Outage
* **Symptom:** Primary provider (e.g. Google Gemini) responds with 503 Service Unavailable or 429 Resource Exhausted.
* **Automated Action:** MedGuide's `LLMGateway` automatically shifts traffic to **Anthropic Claude 3.5 Sonnet**, and if Claude degrades, cascades to **OpenAI GPT-4o**.
* **Manual Override:**
  If an API key is suspended or needs manual rotation:
  ```bash
  # Rotate secret live in Kubernetes
  kubectl create secret generic medguide-secrets \
    --namespace medguide-prod \
    --from-literal=GEMINI_API_KEY="new_key" \
    --dry-run=client -o yaml | kubectl apply -f -

  # Force restart workers to reload environment
  kubectl rollout restart deployment/medguide-ai-deployment -n medguide-prod
  ```

---

### Playbook 2: Database Connection Pool Exhaustion
* **Symptom:** Prometheus fires `DatabasePoolExhaustion`, queries return `psycopg2.OperationalError: remaining connection slots are reserved`.
* **Resolution Steps:**
  1. Inspect active PostgreSQL queries:
     ```sql
     SELECT pid, age(clock_timestamp(), query_start), usename, query 
     FROM pg_stat_activity 
     WHERE state != 'idle' 
     ORDER BY query_start ASC LIMIT 10;
     ```
  2. Terminate rogue hanging queries:
     ```sql
     SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE age(clock_timestamp(), query_start) > interval '2 minutes';
     ```
  3. Scale up PgBouncer pool max connections or reboot RDS standby:
     ```bash
     aws rds reboot-db-instance --db-instance-identifier medguide-prod-postgres --force-failover
     ```

---

### Playbook 3: Redis ElastiCache Failure
* **Symptom:** Redis cluster nodes become unreachable due to network partition or AWS maintenance.
* **Automated Mitigation:** MedGuide AI's `redis_client.py` activates **Zero-Crash Graceful In-Memory Fallback**. The app logs a warning and stores rate-limits in local Python memory.
* **Manual Recovery:**
  ```bash
  # Check ElastiCache cluster status
  aws elasticache describe-replication-groups --replication-group-id medguide-prod-redis

  # Failover to secondary replica
  aws elasticache test-failover --replication-group-id medguide-prod-redis --node-group-id 0001
  ```

---

### Playbook 4: Active Prompt Injection Attack (Kill-Switch Activation)
* **Symptom:** Alertmanager triggers high rate of OWASP injection alerts or LLM exfiltration anomalies.
* **Immediate Mitigation:**
  Activate the MedGuide AI **Emergency Administrative Kill-Switch** to immediately freeze all agent tool executions (Pinecone retrieval and Tavily Web Search) while leaving basic emergency medical disclaimers active:
  ```bash
  # Send kill-switch POST request
  curl -X POST https://api.medguide.com/api/governance/killswitch \
    -H "Authorization: Bearer ADMIN_MASTER_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"active": true, "reason": "Suspected prompt injection flood under forensic review"}'

  # Verify kill-switch status
  curl -X GET https://api.medguide.com/api/governance/status
  ```





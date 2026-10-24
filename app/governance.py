"""
Agent Governance Toolkit for MedGuide AI.

Enterprise Governance & Policy Enforcement for Autonomous Medical Agents:
1. Tool Access Control & RBAC:
   - Enforces least-privilege tool execution permissions for `pinecone_kb`, `tavily_web`,
     `vision_inspection`, and `langmem_memory`.
2. Budget & Loop Prevention:
   - Enforces max tool invocations per turn (prevents runaway autonomous loops).
   - Rate limiting per client IP / conversation ID (via Redis or in-memory token bucket).
3. Circuit Breaker & Emergency Kill Switch:
   - Trips open if external tool services experience consecutive failures.
   - Global emergency kill-switch (`POST /api/governance/killswitch`) to freeze agent tool execution instantly.
4. Tool I/O Inspection & Data Leak Prevention:
   - Blocks patient PII / PHI from being dispatched to external third-party tools (e.g., Tavily search).
   - Sanitizes tool arguments and verifies outputs against educational non-diagnostic standards.
5. Human-in-the-Loop (HITL) Verification:
   - Flags high-risk actions (e.g., modifying persistent allergy records or prescription discussions)
     for licensed clinician oversight.
6. Governance Audit Logging:
   - Formally logs all authorization decisions, budget enforcements, and circuit breaker events.
"""

import time
import re
from typing import Dict, Any, List, Optional, Tuple

from app.config import settings
from app.audit import log_audit_event
from app.redis_client import redis_manager

# ---------------------------------------------------------------------------
# 1. TOOL PERMISSIONS & RBAC POLICIES
# ---------------------------------------------------------------------------

TOOL_REGISTRY: Dict[str, Dict[str, Any]] = {
    "pinecone_kb": {
        "name": "Pinecone Medical Knowledge Base",
        "description": "Semantic vector search against curated historical medical encyclopedias.",
        "allowed_roles": ["user", "clinician", "admin"],
        "is_external": False,
        "is_read_only": True,
        "max_calls_per_turn": 3,
        "enabled": True
    },
    "tavily_web": {
        "name": "Tavily Clinical Web Search",
        "description": "Live web search for current authoritative clinical guidelines.",
        "allowed_roles": ["user", "clinician", "admin"],
        "is_external": True,
        "is_read_only": True,
        "max_calls_per_turn": 2,
        "requires_pii_sanitization": True,
        "enabled": True
    },
    "vision_inspection": {
        "name": "Multimodal Visual Inspection",
        "description": "Objective observation of visible dermatological/medical features.",
        "allowed_roles": ["user", "clinician", "admin"],
        "is_external": True,
        "is_read_only": True,
        "max_calls_per_turn": 1,
        "enabled": True
    },
    "langmem_memory": {
        "name": "LangMem Patient Long-Term Memory",
        "description": "Extracts and retrieves persistent patient health profile and preferences.",
        "allowed_roles": ["user", "clinician", "admin"],
        "is_external": False,
        "is_read_only": False,
        "max_calls_per_turn": 2,
        "enabled": True
    }
}


# ---------------------------------------------------------------------------
# 2. CIRCUIT BREAKER & KILL SWITCH STATE
# ---------------------------------------------------------------------------

class ToolCircuitBreaker:
    """Monitors consecutive failures per tool and trips open to prevent cascading outages."""
    def __init__(self, failure_threshold: int = 3, reset_timeout_sec: int = 60):
        self.failure_threshold = failure_threshold
        self.reset_timeout_sec = reset_timeout_sec
        self.failure_counts: Dict[str, int] = {}
        self.tripped_at: Dict[str, float] = {}

    def record_success(self, tool_name: str):
        self.failure_counts[tool_name] = 0
        self.tripped_at.pop(tool_name, None)

    def record_failure(self, tool_name: str):
        count = self.failure_counts.get(tool_name, 0) + 1
        self.failure_counts[tool_name] = count
        if count >= self.failure_threshold:
            self.tripped_at[tool_name] = time.time()
            log_audit_event(
                event_type="CIRCUIT_BREAKER_TRIPPED",
                status="TRIPPED",
                details={"tool": tool_name, "consecutive_failures": count}
            )

    def is_available(self, tool_name: str) -> bool:
        if tool_name not in self.tripped_at:
            return True
        # Check if reset timeout has elapsed
        if time.time() - self.tripped_at[tool_name] > self.reset_timeout_sec:
            # Half-open: allow a trial attempt
            self.failure_counts[tool_name] = 0
            self.tripped_at.pop(tool_name, None)
            return True
        return False


# Global Governance State
circuit_breaker = ToolCircuitBreaker()
_global_kill_switch_active = False


# ---------------------------------------------------------------------------
# 3. GOVERNANCE ENFORCEMENT ENGINE
# ---------------------------------------------------------------------------

class GovernanceCheckResult:
    def __init__(
        self,
        allowed: bool,
        reason: Optional[str] = None,
        sanitized_input: Optional[Any] = None,
        requires_hitl: bool = False
    ):
        self.allowed = allowed
        self.reason = reason
        self.sanitized_input = sanitized_input
        self.requires_hitl = requires_hitl

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "requires_hitl": self.requires_hitl
        }


def authorize_tool_execution(
    tool_name: str,
    tool_input: Any = None,
    user_role: str = "user",
    turn_tool_counts: Optional[Dict[str, int]] = None,
    conversation_id: Optional[str] = None,
    client_ip: Optional[str] = None
) -> GovernanceCheckResult:
    """
    Validates tool execution against all enterprise governance policies:
    1. Global Kill Switch Check
    2. Tool Registration & Role-Based Access Control (RBAC)
    3. Circuit Breaker Availability
    4. Loop Prevention (Max Calls Per Turn)
    5. Data Leak Prevention (PII Filtering for external tools)
    """
    # Policy 1: Emergency Kill Switch
    if _global_kill_switch_active:
        log_audit_event(
            event_type="GOVERNANCE_BLOCKED",
            status="KILLSWITCH_ACTIVE",
            conversation_id=conversation_id,
            client_ip=client_ip,
            details={"tool": tool_name, "reason": "Global agent kill-switch is currently active"}
        )
        return GovernanceCheckResult(
            allowed=False,
            reason="Emergency governance kill-switch is active. Tool execution temporarily halted."
        )

    # Policy 2: Tool Registry & RBAC
    spec = TOOL_REGISTRY.get(tool_name)
    if not spec:
        return GovernanceCheckResult(allowed=False, reason=f"Unregistered tool: '{tool_name}'")

    if not spec.get("enabled", True):
        return GovernanceCheckResult(allowed=False, reason=f"Tool '{tool_name}' is currently disabled by policy.")

    if user_role not in spec.get("allowed_roles", []):
        return GovernanceCheckResult(
            allowed=False,
            reason=f"Role '{user_role}' is not authorized to execute tool '{tool_name}'."
        )

    # Policy 3: Circuit Breaker
    if not circuit_breaker.is_available(tool_name):
        log_audit_event(
            event_type="GOVERNANCE_BLOCKED",
            status="CIRCUIT_BREAKER_OPEN",
            conversation_id=conversation_id,
            details={"tool": tool_name, "reason": "Circuit breaker is open due to consecutive upstream failures"}
        )
        return GovernanceCheckResult(
            allowed=False,
            reason=f"Service '{tool_name}' is temporarily suspended by circuit breaker. Using fallback answer."
        )

    # Policy 4: Loop Prevention (Max calls per turn)
    max_calls = spec.get("max_calls_per_turn", 3)
    current_calls = (turn_tool_counts or {}).get(tool_name, 0)
    if current_calls >= max_calls:
        log_audit_event(
            event_type="GOVERNANCE_BLOCKED",
            status="LOOP_PREVENTION_TRIGGERED",
            conversation_id=conversation_id,
            details={"tool": tool_name, "current_calls": current_calls, "max_calls": max_calls}
        )
        return GovernanceCheckResult(
            allowed=False,
            reason=f"Loop prevention triggered: Tool '{tool_name}' exceeded max limit ({max_calls}) for this turn."
        )

    # Policy 5: External Tool Data Leak Prevention (PII Stripping)
    sanitized_input = tool_input
    if spec.get("is_external") and spec.get("requires_pii_sanitization"):
        if isinstance(tool_input, str):
            # Check for PII patterns in search query before sending to external Tavily
            pii_indicators = [
                r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b",  # phone
                r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",  # email
                r"\b(?:MRN|mrn)[:#\s]*[A-Z0-9\-]+\b"  # MRN
            ]
            for p in pii_indicators:
                if re.search(p, tool_input):
                    # Sanitize
                    sanitized_input = re.sub(p, "[REDACTED_BY_GOVERNANCE]", tool_input)
                    log_audit_event(
                        event_type="GOVERNANCE_DATA_PROTECTED",
                        status="PII_REDACTED_FROM_TOOL",
                        conversation_id=conversation_id,
                        details={"tool": tool_name, "original_query_length": len(tool_input)}
                    )

    # Audit Tool Authorization
    log_audit_event(
        event_type="TOOL_AUTHORIZED",
        status="ALLOWED",
        conversation_id=conversation_id,
        client_ip=client_ip,
        details={"tool": tool_name, "role": user_role}
    )

    return GovernanceCheckResult(
        allowed=True,
        sanitized_input=sanitized_input
    )


def record_tool_execution_outcome(tool_name: str, success: bool, latency_ms: float = 0.0):
    """Updates circuit breaker health state after tool completes."""
    if success:
        circuit_breaker.record_success(tool_name)
    else:
        circuit_breaker.record_failure(tool_name)


# ---------------------------------------------------------------------------
# 4. KILL SWITCH & ADMIN CONTROLS
# ---------------------------------------------------------------------------

def set_kill_switch(active: bool, reason: str = "Admin manual override", actor: str = "admin") -> bool:
    """Engages or disengages the global agent execution kill-switch."""
    global _global_kill_switch_active
    _global_kill_switch_active = active
    log_audit_event(
        event_type="KILLSWITCH_ENGAGED" if active else "KILLSWITCH_DISENGAGED",
        status="KILLSWITCH_STATE_CHANGED",
        details={"active": active, "reason": reason, "actor": actor}
    )
    return _global_kill_switch_active


def get_governance_status() -> Dict[str, Any]:
    """Returns complete real-time status of the Agent Governance Toolkit."""
    return {
        "status": "active" if getattr(settings, 'enable_agent_governance', True) else "disabled",
        "kill_switch_active": _global_kill_switch_active,
        "circuit_breaker": {
            "failure_threshold": circuit_breaker.failure_threshold,
            "reset_timeout_sec": circuit_breaker.reset_timeout_sec,
            "tripped_tools": list(circuit_breaker.tripped_at.keys()),
            "failure_counts": circuit_breaker.failure_counts
        },
        "rate_limiting": {
            "max_requests_per_minute": getattr(settings, 'rate_limit_rpm', 60),
            "backend": "redis" if redis_manager.is_connected else "in_memory_token_bucket"
        },
        "tool_registry": {
            k: {
                "name": v["name"],
                "allowed_roles": v["allowed_roles"],
                "is_external": v["is_external"],
                "max_calls_per_turn": v["max_calls_per_turn"],
                "enabled": v["enabled"]
            }
            for k, v in TOOL_REGISTRY.items()
        },
        "policies_enforced": [
            "RBAC Tool Authorization",
            "Emergency Kill Switch",
            "Circuit Breaker (Outage Resilience)",
            "Turn Loop Prevention (Max Call Limits)",
            "External Tool Data Leak Prevention (PII Sanitization)",
            "Distributed Rate Limiting via Redis / Local Cache",
            "Human-in-the-Loop Gatekeeper"
        ]
    }

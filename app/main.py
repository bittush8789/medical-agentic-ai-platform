import os
import base64
import io
import secrets
import time
from pathlib import Path
from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from openai import OpenAI
from uuid import uuid4
from app.config import settings
from app.agent import graph
from app.llm import call_vision_llm, get_available_models, normalize_model_name, get_fallback_chain_info
from app.audit import log_audit_event, detect_triage_alert, get_recent_audit_logs
from app.guardrails import apply_input_guardrails, apply_output_guardrails, get_guardrails_status
from app.evaluation import get_evaluation_status, get_latest_evaluation_report, run_benchmark_evaluation
from app.redis_client import redis_manager
from app.governance import get_governance_status, set_kill_switch
from app.memory import memory_manager
from app.security import (
    get_ai_security_status,
    check_direct_prompt_injection,
    sanitize_model_output_security
)

ROOT=Path(__file__).resolve().parent.parent
app=FastAPI(title='Medical Agent Educational API',version='1.0.0')
app.add_middleware(CORSMiddleware,allow_origins=settings.allowed_origins.split(','),allow_credentials=False,allow_methods=['GET','POST'],allow_headers=['Authorization','Content-Type'])
app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')


class ChatRequest(BaseModel):
    message: str = Field(min_length=1,max_length=4000)
    history: list[dict[str,str]] = Field(default_factory=list,max_length=10)
    image_data: str | None = None
    model: str | None = None

def auth(authorization: str | None, client_ip: str | None = None):
    if settings.api_token and not secrets.compare_digest(authorization or '',f'Bearer {settings.api_token}'):
        log_audit_event(
            event_type="AUTH_FAILURE",
            status="UNAUTHORIZED",
            client_ip=client_ip,
            details={"reason": "Invalid or missing API authorization token"}
        )
        raise HTTPException(status_code=401,detail='Invalid API token')


def inspect_image(data: str | None, model: str | None = None, conversation_id: str | None = None, client_ip: str | None = None) -> str:
    if not data:
        return ''
    start_time = time.perf_counter()
    try:
        header,payload=data.split(',',1)
        mime=header.split(';')[0].split(':')[1]
        raw=base64.b64decode(payload,validate=True)
        if mime not in ('image/jpeg','image/png','image/webp') or len(raw)>5_000_000:
            raise ValueError('Only JPEG/PNG/WebP under 5MB supported')
    except (ValueError,IndexError) as exc:
        log_audit_event(
            event_type="IMAGE_INSPECTION",
            conversation_id=conversation_id,
            status="FAILED",
            client_ip=client_ip,
            details={"error": str(exc)}
        )
        raise HTTPException(status_code=400,detail=f'Invalid image: {exc}')

    prompt = 'Describe only objectively visible medical-relevant features. Do not diagnose, estimate severity, or assert absence of illness. If image unclear, say so.'
    observation = call_vision_llm(model=model, prompt=prompt, image_data_url=data, max_tokens=300)
    latency_ms = (time.perf_counter() - start_time) * 1000

    log_audit_event(
        event_type="IMAGE_INSPECTION",
        conversation_id=conversation_id,
        model=model,
        status="SUCCESS",
        latency_ms=latency_ms,
        client_ip=client_ip,
        details={"bytes": len(raw), "mime": mime}
    )
    return observation


@app.get('/',response_class=HTMLResponse)
def home():
    return (ROOT/'templates'/'index.html').read_text(encoding='utf-8')

@app.get('/api/health')
def health():
    gateway_info = get_fallback_chain_info()
    return {
        'status': 'ok',
        'providers': {
            'openai': bool(settings.openai_api_key),
            'gemini': bool(settings.gemini_api_key),
            'anthropic': bool(settings.anthropic_api_key),
            'pinecone': bool(settings.pinecone_api_key),
            'tavily': bool(settings.tavily_api_key)
        },
        'audit_logging': settings.enable_audit_logging,
        'default_model': settings.chat_model,
        'gateway': gateway_info,
        'guardrails': get_guardrails_status(),
        'langsmith': {
            'enabled': bool(settings.langchain_api_key or os.environ.get('LANGCHAIN_TRACING_V2') == 'true'),
            'project': settings.langchain_project,
            'endpoint': settings.langchain_endpoint
        },
        'evaluation': get_evaluation_status(),
        'redis': redis_manager.get_status(),
        'governance': get_governance_status(),
        'memory': memory_manager.get_status(),
        'ai_security': get_ai_security_status(),
        'models': get_available_models()
    }


@app.get('/api/security/status')
def security_status_endpoint():
    """Inspect Enterprise AI Security Engine status, threat counters, and OWASP Top 10 matrix."""
    return {
        'status': 'ok',
        'security': get_ai_security_status()
    }


@app.get('/api/redis/status')
def redis_status_endpoint():
    """Inspect Redis connection, mode (server vs in-memory fallback), and caching stats."""
    return {
        'status': 'ok',
        'redis': redis_manager.get_status()
    }


@app.get('/api/governance/status')
def governance_status_endpoint():
    """Inspect Agent Governance Toolkit status, circuit breakers, rate limits, and RBAC policies."""
    return {
        'status': 'ok',
        'governance': get_governance_status()
    }


class KillSwitchRequest(BaseModel):
    active: bool
    reason: str = "Admin manual override"


@app.post('/api/governance/killswitch')
def governance_killswitch_endpoint(
    payload: KillSwitchRequest,
    authorization: str | None = Header(default=None),
    request: Request = None
):
    """Emergency kill-switch to freeze or unfreeze all agent tool executions."""
    client_ip = request.client.host if request and request.client else None
    auth(authorization, client_ip=client_ip)
    state = set_kill_switch(payload.active, reason=payload.reason, actor=client_ip or "admin")
    return {
        'status': 'ok',
        'kill_switch_active': state,
        'message': f"Agent tool execution {'FROZEN' if state else 'RESUMED'}."
    }


@app.get('/api/memory')
def get_memory_endpoint(
    user_id: str,
    category: str | None = None,
    authorization: str | None = Header(default=None),
    request: Request = None
):
    """Retrieve persistent patient long-term memories extracted by LangMem."""
    client_ip = request.client.host if request and request.client else None
    auth(authorization, client_ip=client_ip)
    memories = memory_manager.get_memories(user_id=user_id, category=category)
    return {
        'status': 'ok',
        'user_id': user_id,
        'count': len(memories),
        'memories': memories
    }


class MemoryCreateRequest(BaseModel):
    user_id: str
    category: str
    content: str
    confidence: float = 1.0


@app.post('/api/memory')
def create_memory_endpoint(
    payload: MemoryCreateRequest,
    authorization: str | None = Header(default=None),
    request: Request = None
):
    """Explicitly save a patient fact (allergy, condition, medication) into LangMem."""
    client_ip = request.client.host if request and request.client else None
    auth(authorization, client_ip=client_ip)
    rec = memory_manager.save_memory(
        user_id=payload.user_id,
        category=payload.category,
        content=payload.content,
        confidence=payload.confidence
    )
    return {'status': 'ok', 'record': rec}


@app.delete('/api/memory/{memory_id}')
def delete_memory_endpoint(
    memory_id: str,
    user_id: str,
    authorization: str | None = Header(default=None),
    request: Request = None
):
    """Delete a specific patient long-term memory record."""
    client_ip = request.client.host if request and request.client else None
    auth(authorization, client_ip=client_ip)
    deleted = memory_manager.delete_memory(user_id=user_id, memory_id=memory_id)
    return {'status': 'ok', 'deleted': deleted, 'memory_id': memory_id}



@app.get('/api/eval/status')
def eval_status_endpoint():
    """Inspect availability, active metrics, and benchmark cases for DeepEval and RAGAS."""
    return {
        'status': 'ok',
        'evaluation': get_evaluation_status()
    }


@app.get('/api/eval/latest')
def eval_latest_endpoint():
    """Retrieve the most recent clinical evaluation report generated by DeepEval / RAGAS."""
    report = get_latest_evaluation_report()
    if not report:
        return {'status': 'not_found', 'message': 'No evaluation run found yet. Run POST /api/eval/run first.'}
    return {'status': 'ok', 'report': report}


@app.post('/api/eval/run')
def eval_run_endpoint(
    framework: str = 'both',
    samples: int = 3,
    model: str | None = None,
    authorization: str | None = Header(default=None),
    request: Request = None
):
    """Trigger an on-demand clinical evaluation run with DeepEval and/or RAGAS."""
    client_ip = request.client.host if request and request.client else None
    auth(authorization, client_ip=client_ip)
    report = run_benchmark_evaluation(framework=framework, max_samples=samples, model=model)
    return {'status': 'ok', 'report': report}


@app.get('/api/langsmith')
def langsmith_endpoint():
    """Inspect LangSmith tracing status, project name, and endpoint configuration."""
    return {
        'status': 'ok',
        'langsmith': {
            'enabled': bool(settings.langchain_api_key or os.environ.get('LANGCHAIN_TRACING_V2') == 'true'),
            'project': settings.langchain_project,
            'endpoint': settings.langchain_endpoint,
            'has_api_key': bool(settings.langchain_api_key or os.environ.get('LANGCHAIN_API_KEY'))
        }
    }


@app.get('/api/guardrails')
def guardrails_endpoint():
    """Inspect active status of Microsoft Presidio (PII/PHI) and NVIDIA NeMo Guardrails."""
    return {
        'status': 'ok',
        'guardrails': get_guardrails_status()
    }


@app.get('/api/gateway')
def gateway_status(model: str | None = None):
    """Inspect the LLM Gateway fallback chain for a given model (or the default)."""
    info = get_fallback_chain_info(primary_model=model)
    models = get_available_models()
    return {
        'status': 'ok',
        'gateway': info,
        'models': models
    }


@app.get('/api/audit-logs')
def audit_logs_endpoint(
    limit: int = 50,
    event_type: str | None = None,
    authorization: str | None = Header(default=None),
    request: Request = None
):
    client_ip = request.client.host if request and request.client else None
    auth(authorization, client_ip=client_ip)
    logs = get_recent_audit_logs(limit=limit, event_type=event_type)
    return {'status': 'ok', 'count': len(logs), 'logs': logs}



@app.post('/api/chat')
def chat(
    payload: ChatRequest,
    request: Request,
    authorization: str | None = Header(default=None),
    conversation_id: str | None = Header(default=None, alias='X-Conversation-ID')
):
    client_ip = request.client.host if request and request.client else None
    auth(authorization, client_ip=client_ip)

    # SQLite persistent memory & LangSmith run tracing
    thread_id = conversation_id or str(uuid4())
    chosen_model = payload.model or settings.chat_model
    config = {
        "configurable": {"thread_id": thread_id},
        "metadata": {
            "conversation_id": thread_id,
            "model": normalize_model_name(chosen_model),
            "client_ip": client_ip or "anonymous",
            "has_image": bool(payload.image_data)
        },
        "tags": ["medical-agent", "educational", chosen_model.split("/")[-1]]
    }

    start_time = time.perf_counter()

    # Agent Governance: Distributed Rate Limiting & Abuse Prevention
    if getattr(settings, 'enable_agent_governance', True):
        rate_limit_rpm = getattr(settings, 'rate_limit_rpm', 60)
        allowed, _ = redis_manager.check_rate_limit(client_ip or "anonymous", rate_limit_rpm)
        if not allowed:
            log_audit_event(
                event_type="GOVERNANCE_RATE_LIMIT",
                conversation_id=thread_id,
                model=normalize_model_name(chosen_model),
                status="BLOCKED",
                client_ip=client_ip,
                details={"reason": "Rate limit exceeded", "limit_rpm": rate_limit_rpm}
            )
            raise HTTPException(429, f"Rate limit of {rate_limit_rpm} requests/min exceeded by Agent Governance policy. Please slow down.")

    # Redis Performance Acceleration: Sub-millisecond response cache
    if not payload.image_data and getattr(settings, 'enable_redis_cache', True):
        cached_res = redis_manager.get_cached_chat_response(payload.message, chosen_model)
        if cached_res:
            latency_ms = (time.perf_counter() - start_time) * 1000
            cached_res = dict(cached_res)
            cached_res['conversation_id'] = thread_id
            cached_res['cached'] = True
            log_audit_event(
                event_type="CHAT_CACHE_HIT",
                conversation_id=thread_id,
                model=normalize_model_name(chosen_model),
                status="SUCCESS",
                latency_ms=latency_ms,
                client_ip=client_ip,
                details={"message_length": len(payload.message)}
            )
    # AI Security: Direct Prompt Injection & System Prompt Exfiltration Check (OWASP LLM01, LLM07)
    if getattr(settings, 'enable_ai_security', True):
        is_threat, threat_reason = check_direct_prompt_injection(payload.message)
        if is_threat:
            latency_ms = (time.perf_counter() - start_time) * 1000
            log_audit_event(
                event_type="AI_SECURITY_BLOCK",
                conversation_id=thread_id,
                model="ai-security-engine",
                status="BLOCKED",
                latency_ms=latency_ms,
                client_ip=client_ip,
                details={"threat_reason": threat_reason, "query_preview": payload.message[:100]}
            )
            return {
                'answer': f"🛡️ **AI SECURITY ADVISORY: Inquiry Blocked**\n\nYour message was flagged and neutralized by the MedGuide Enterprise AI Security Engine.\n\n- **Violation:** {threat_reason}\n- **Standard:** OWASP Top 10 for LLMs (LLM01 / LLM07 Compliance)\n\nThis application is dedicated exclusively to responsible medical education and clinical triage demonstrations. System commands, instruction overrides, and credential probing are strictly prohibited.",
                'sources': [],
                'tools': ['ai-security-engine'],
                'conversation_id': thread_id,
                'model_used': 'ai-security-engine',
                'security': {
                    'blocked': True,
                    'reason': threat_reason,
                    'standard': 'OWASP LLM01/LLM07'
                }
            }

    # Step 1: Apply Dual Input Guardrails (Presidio PII + NeMo Behavioral Rails)
    guard_result = apply_input_guardrails(
        message=payload.message,
        conversation_id=thread_id,
        client_ip=client_ip
    )

    # If NeMo Input Rail blocked (Emergency Triage / Jailbreak / Off-Topic):
    # Intercepts immediately with zero external dependencies
    if guard_result["is_blocked"]:
        latency_ms = (time.perf_counter() - start_time) * 1000
        return {
            'answer': guard_result["safe_response"],
            'sources': [],
            'tools': ['nemo-guardrails'] + (['presidio-pii'] if guard_result['pii_entities'] else []),
            'conversation_id': thread_id,
            'model_used': 'nemo-guardrails',
            'guardrails': {
                'intervened': True,
                'rail_triggered': guard_result['rail_triggered'],
                'reason': guard_result['reason'],
                'pii_redacted': len(guard_result['pii_entities']) > 0,
                'pii_entities': [e['entity_type'] for e in guard_result['pii_entities']]
            }
        }

    # For clinical queries requiring RAG knowledge base search, require Pinecone key
    if not settings.pinecone_api_key:
        raise HTTPException(503, 'PINECONE_API_KEY is required in .env for knowledge base retrieval')

    history=[x for x in payload.history if x.get('role') in ('user','assistant') and isinstance(x.get('content'),str)][:10]

    # Use sanitized message for retrieval, reasoning, and LLM generation (PII-protected)
    sanitized_message = guard_result["sanitized_text"]

    # Emergency Triage Audit Check (Secondary check for audit trail)
    red_flags = detect_triage_alert(payload.message)
    if red_flags:
        log_audit_event(
            event_type="TRIAGE_ALERT",
            conversation_id=thread_id,
            model=normalize_model_name(chosen_model),
            status="ALERT",
            client_ip=client_ip,
            details={"red_flags_detected": red_flags, "query_preview": payload.message[:120]}
        )

    # LangMem: Retrieve Patient Long-Term Clinical Memory (allergies, chronic illnesses, medications)
    patient_context = ""
    if getattr(settings, 'enable_langmem', True):
        patient_context = memory_manager.format_memories_for_prompt(user_id=thread_id)

    try:
        observation = inspect_image(payload.image_data, model=chosen_model, conversation_id=thread_id, client_ip=client_ip)

        state = graph.invoke(
            {
                'question': sanitized_message,
                'history': history,
                'image_description': observation,
                'kb': [],
                'web': [],
                'answer': '',
                'route': '',
                'model': chosen_model,
                'patient_context': patient_context
            },
            config=config
        )

        # Step 2: Apply Output Guardrails (Prescription Blocker + Disclaimer Enforcement + PII Leak Prevention)
        raw_answer = state.get('answer', '')
        guarded_answer = apply_output_guardrails(
            answer=raw_answer,
            user_question=payload.message,
            conversation_id=thread_id,
            client_ip=client_ip
        )

        # AI Security: Insecure Output Handling & Markdown Exfiltration Defense (OWASP LLM02, LLM03)
        if getattr(settings, 'enable_exfiltration_defense', True):
            guarded_answer = sanitize_model_output_security(guarded_answer)

        latency_ms = (time.perf_counter() - start_time) * 1000
        tools = ['pinecone'] + (['tavily'] if state['route']=='web' and settings.tavily_api_key else []) + (['vision'] if observation else [])
        if guard_result['pii_entities']:
            tools.append('presidio-pii')
        tools.append('nemo-guardrails')

        # Record Successful Completion Audit
        log_audit_event(
            event_type="CHAT_COMPLETED",
            conversation_id=thread_id,
            model=normalize_model_name(chosen_model),
            status="SUCCESS",
            latency_ms=latency_ms,
            tools_invoked=tools,
            client_ip=client_ip,
            details={
                "route_taken": state.get('route', 'answer'),
                "kb_citations": len(state['kb']),
                "web_citations": len(state['web']),
                "message_length": len(payload.message),
                "answer_length": len(guarded_answer),
                "pii_redacted": len(guard_result['pii_entities']) > 0,
                "patient_memory_used": bool(patient_context)
            }
        )

        final_response = {
            'answer': guarded_answer,
            'sources': [{'type':'pdf','page':x['page'],'score':x['score']} for x in state['kb']]+[{'type':'web','url':x['url'],'title':x['title']} for x in state['web']],
            'tools': tools,
            'conversation_id': thread_id,
            'model_used': normalize_model_name(chosen_model),
            'cached': False,
            'guardrails': {
                'intervened': False,
                'pii_redacted': len(guard_result['pii_entities']) > 0,
                'pii_entities': [e['entity_type'] for e in guard_result['pii_entities']],
                'active_rails': ['presidio_pii', 'nemo_emergency', 'nemo_jailbreak', 'nemo_off_topic', 'disclaimer_enforcer']
            },
            'patient_memory_used': bool(patient_context)
        }

        # Cache in Redis / In-Memory cache for acceleration
        if not payload.image_data and getattr(settings, 'enable_redis_cache', True):
            redis_manager.cache_chat_response(payload.message, chosen_model, final_response)

        # Extract & Store Long-term Patient Facts via LangMem
        if getattr(settings, 'enable_langmem', True):
            try:
                memory_manager.extract_and_store_facts_from_turn(thread_id, payload.message, guarded_answer)
            except Exception as mem_err:
                print(f"[Memory Extraction Warning]: {mem_err}", flush=True)

        return final_response

    except HTTPException:
        raise
    except Exception as exc:
        latency_ms = (time.perf_counter() - start_time) * 1000
        log_audit_event(
            event_type="CHAT_FAILED",
            conversation_id=thread_id,
            model=normalize_model_name(chosen_model),
            status="ERROR",
            latency_ms=latency_ms,
            client_ip=client_ip,
            details={"error": str(exc)}
        )
        print('Chat error:',repr(exc),flush=True)
        raise HTTPException(502, f'AI service failed: {str(exc)}')


@app.post('/api/transcribe')
async def transcribe(file:UploadFile=File(...),authorization:str|None=Header(default=None),request:Request=None):
    client_ip = request.client.host if request and request.client else None
    auth(authorization, client_ip=client_ip)
    start_time = time.perf_counter()
    data=await file.read(10_000_001)
    if len(data)>10_000_000:
        raise HTTPException(413,'Audio exceeds 10 MB')
    audio=io.BytesIO(data); audio.name='voice.webm'
    try:
        result=OpenAI(api_key=settings.openai_api_key).audio.transcriptions.create(model='whisper-1',file=audio)
        latency_ms = (time.perf_counter() - start_time) * 1000
        log_audit_event(
            event_type="AUDIO_TRANSCRIBE",
            status="SUCCESS",
            latency_ms=latency_ms,
            client_ip=client_ip,
            details={"file_bytes": len(data), "transcribed_length": len(result.text)}
        )
        return {'text':result.text}
    except Exception as exc:
        latency_ms = (time.perf_counter() - start_time) * 1000
        log_audit_event(
            event_type="AUDIO_TRANSCRIBE",
            status="ERROR",
            latency_ms=latency_ms,
            client_ip=client_ip,
            details={"error": str(exc)}
        )
        raise HTTPException(502,'Speech transcription unavailable')

@app.post('/api/speak')
def speak(payload:dict,authorization:str|None=Header(default=None),request:Request=None):
    client_ip = request.client.host if request and request.client else None
    auth(authorization, client_ip=client_ip)
    start_time = time.perf_counter()
    text=str(payload.get('text',''))[:3000]
    if not text:
        raise HTTPException(400,'Missing text')
    try:
        speech=OpenAI(api_key=settings.openai_api_key).audio.speech.create(model='tts-1',voice='alloy',input=text)
        latency_ms = (time.perf_counter() - start_time) * 1000
        log_audit_event(
            event_type="AUDIO_SPEAK",
            status="SUCCESS",
            latency_ms=latency_ms,
            client_ip=client_ip,
            details={"chars": len(text)}
        )
        return Response(content=speech.content,media_type='audio/mpeg')
    except Exception as exc:
        latency_ms = (time.perf_counter() - start_time) * 1000
        log_audit_event(
            event_type="AUDIO_SPEAK",
            status="ERROR",
            latency_ms=latency_ms,
            client_ip=client_ip,
            details={"error": str(exc)}
        )
        raise HTTPException(502,'Speech synthesis unavailable')

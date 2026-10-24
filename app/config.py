import os 
import certifi 
from dotenv import load_dotenv

# Disable TensorFlow import in transformers to prevent Protobuf version collision
os.environ['USE_TF'] = '0'
os.environ['TRANSFORMERS_NO_TF'] = '1'

# --- AUTOMATIC SSL FIX FOR CONDA/PYTHON ENVIRONMENTS ---
ssl_cert = os.environ.get('SSL_CERT_FILE')
if ssl_cert and not os.path.exists(ssl_cert):
    os.environ['SSL_CERT_FILE'] = certifi.where()
elif not ssl_cert:
    os.environ['SSL_CERT_FILE'] = certifi.where()
# --------------------------------------------------------

load_dotenv()
from pydantic_settings import BaseSettings, SettingsConfigDict



class Settings(BaseSettings):
    openai_api_key: str = ''
    gemini_api_key: str = ''
    anthropic_api_key: str = ''
    pinecone_api_key: str = ''
    tavily_api_key: str = ''
    pinecone_index: str = 'medical-agent-demo'
    chat_model: str = 'gpt-4.1-mini'
    openai_chat_model: str = 'gpt-4.1-mini'
    openai_embed_model: str = 'text-embedding-3-small'
    vision_model: str = ''
    openai_vision_model: str = 'gpt-4.1-mini'
    api_token: str = ''
    allowed_origins: str = 'http://localhost:8000,http://127.0.0.1:8000'
    enable_audit_logging: bool = True
    # LLM Gateway: fallback chain (comma-separated model IDs tried in order on failure)
    fallback_models: str = 'gemini/gemini-2.5-flash,claude-3-5-sonnet-20241022,gpt-4.1-mini'
    max_fallback_retries: int = 3
    gateway_timeout: int = 45
    # Guardrails: Microsoft Presidio (PII) + NVIDIA NeMo Guardrails (Safety/Triage)
    enable_guardrails: bool = True
    enable_presidio_pii: bool = True
    enable_nemo_guardrails: bool = True
    # LangSmith Observability & Tracing
    langchain_tracing_v2: bool = True
    langchain_api_key: str = ''
    langchain_project: str = 'medical-agentic-chatbot'
    langchain_endpoint: str = 'https://api.smith.langchain.com'
    # Redis High-Speed Caching & Distributed Storage
    redis_url: str = 'redis://localhost:6379/0'
    enable_redis_cache: bool = True
    # Agent Governance Toolkit
    enable_agent_governance: bool = True
    max_tool_calls_per_turn: int = 5
    rate_limit_rpm: int = 60
    # LangMem Long-Term Patient Semantic Memory
    enable_langmem: bool = True
    # Enterprise AI Security Engine (OWASP Top 10 for LLMs)
    enable_ai_security: bool = True
    enable_indirect_injection_defense: bool = True
    enable_memory_poisoning_defense: bool = True
    enable_exfiltration_defense: bool = True
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')



settings = Settings()

# Sync keys into environment for LiteLLM and provider SDKs
if settings.openai_api_key and not os.environ.get('OPENAI_API_KEY'):
    os.environ['OPENAI_API_KEY'] = settings.openai_api_key
if settings.gemini_api_key:
    os.environ['GEMINI_API_KEY'] = settings.gemini_api_key
    os.environ['GOOGLE_API_KEY'] = settings.gemini_api_key
if settings.anthropic_api_key and not os.environ.get('ANTHROPIC_API_KEY'):
    os.environ['ANTHROPIC_API_KEY'] = settings.anthropic_api_key

# Sync LangSmith tracing variables into environment
if settings.langchain_api_key:
    os.environ['LANGCHAIN_TRACING_V2'] = 'true' if settings.langchain_tracing_v2 else 'false'
    os.environ['LANGCHAIN_API_KEY'] = settings.langchain_api_key
    os.environ['LANGCHAIN_PROJECT'] = settings.langchain_project or 'medical-agentic-chatbot'
    os.environ['LANGCHAIN_ENDPOINT'] = settings.langchain_endpoint or 'https://api.smith.langchain.com'
elif os.environ.get('LANGCHAIN_API_KEY'):
    # In case user supplied it directly via system env
    if settings.langchain_tracing_v2:
        os.environ['LANGCHAIN_TRACING_V2'] = 'true'
    if not os.environ.get('LANGCHAIN_PROJECT'):
        os.environ['LANGCHAIN_PROJECT'] = settings.langchain_project or 'medical-agentic-chatbot'
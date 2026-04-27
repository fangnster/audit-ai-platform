import os
import ssl
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from celery import Celery
from app.config import settings
from app.logging_config import configure_logging

configure_logging()


def _with_celery_rediss_ssl(url: str) -> str:
    """Celery/Kombu requires ssl_cert_reqs to be explicit for rediss URLs."""
    if not url.lower().startswith("rediss://"):
        return url

    parsed = urlsplit(url)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    if not any(key.lower() == "ssl_cert_reqs" for key, _ in query):
        query.append(("ssl_cert_reqs", "CERT_REQUIRED"))
    return urlunsplit((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        urlencode(query),
        parsed.fragment,
    ))


broker_url = _with_celery_rediss_ssl(settings.CELERY_BROKER_URL)
result_backend = _with_celery_rediss_ssl(settings.CELERY_RESULT_BACKEND)
os.environ["CELERY_BROKER_URL"] = broker_url
os.environ["CELERY_RESULT_BACKEND"] = result_backend

celery_config = {
    "task_serializer": "json",
    "result_serializer": "json",
    "accept_content": ["json"],
    "timezone": "Asia/Shanghai",
    "enable_utc": True,
    # Priority queues
    "task_queues": {
        "p0_fact_fix":   {"exchange": "p0", "routing_key": "p0"},
        "p1_lawyer_cmd": {"exchange": "p1", "routing_key": "p1"},
        "p2_parse":      {"exchange": "p2", "routing_key": "p2"},
        "p3_draft":      {"exchange": "p3", "routing_key": "p3"},
        "default":       {"exchange": "default", "routing_key": "default"},
    },
    "task_default_queue": "default",
    "task_routes": {
        "app.workers.agent_tasks.rewrite_section":   {"queue": "p1_lawyer_cmd"},
        "app.workers.agent_tasks.fix_fact":          {"queue": "p0_fact_fix"},
        "app.workers.document_tasks.parse_document": {"queue": "p2_parse"},
        "app.workers.agent_tasks.reparse_fact":      {"queue": "p2_parse"},
        "app.workers.agent_tasks.generate_drafts":   {"queue": "p3_draft"},
        "app.workers.agent_tasks.generate_rfi":      {"queue": "p3_draft"},
    },
    # Retry config
    "task_acks_late": True,
    "task_reject_on_worker_lost": True,
    "worker_prefetch_multiplier": 1,
}

if broker_url.lower().startswith("rediss://"):
    celery_config["broker_use_ssl"] = {"ssl_cert_reqs": ssl.CERT_REQUIRED}

if result_backend.lower().startswith("rediss://"):
    celery_config["redis_backend_use_ssl"] = {"ssl_cert_reqs": ssl.CERT_REQUIRED}

celery_app = Celery(
    "immigration_ai",
    broker=broker_url,
    backend=result_backend,
    include=[
        "app.workers.document_tasks",
        "app.workers.agent_tasks",
    ],
)

celery_app.conf.update(**celery_config)

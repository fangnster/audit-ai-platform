from celery import Celery
from app.config import settings
from app.logging_config import configure_logging

configure_logging()

celery_app = Celery(
    "immigration_ai",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.workers.document_tasks",
        "app.workers.agent_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=True,
    # Priority queues
    task_queues={
        "p0_fact_fix":   {"exchange": "p0", "routing_key": "p0"},
        "p1_lawyer_cmd": {"exchange": "p1", "routing_key": "p1"},
        "p2_parse":      {"exchange": "p2", "routing_key": "p2"},
        "p3_draft":      {"exchange": "p3", "routing_key": "p3"},
        "default":       {"exchange": "default", "routing_key": "default"},
    },
    task_default_queue="default",
    task_routes={
        "app.workers.agent_tasks.rewrite_section":   {"queue": "p1_lawyer_cmd"},
        "app.workers.agent_tasks.fix_fact":          {"queue": "p0_fact_fix"},
        "app.workers.document_tasks.parse_document": {"queue": "p2_parse"},
        "app.workers.agent_tasks.generate_drafts":   {"queue": "p3_draft"},
        "app.workers.agent_tasks.generate_rfi":      {"queue": "p3_draft"},
    },
    # Retry config
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
)

"""
In-memory metrics for API monitoring: response times, job failures, webhook failures.
Used by GET /health for production monitoring.
"""
import time
from collections import deque
from typing import Deque, Dict, Any
import threading

# Thread-safe simple metrics store (for single process; use Redis for multi-instance)
_lock = threading.Lock()
_request_times: Deque[float] = deque(maxlen=1000)  # last 1000 request durations
_job_failures: Dict[str, int] = {}   # job_id -> count
_webhook_failures: Dict[str, int] = {}  # webhook_type -> count
_start_time = time.time()


def record_request_time(duration_sec: float) -> None:
    with _lock:
        _request_times.append(duration_sec)


def record_job_failure(job_id: str) -> None:
    with _lock:
        _job_failures[job_id] = _job_failures.get(job_id, 0) + 1
    try:
        import sentry_sdk
        sentry_sdk.capture_message(f"Scheduled job failed: {job_id}", level="error")
    except Exception:
        pass


def record_webhook_failure(webhook_type: str) -> None:
    with _lock:
        _webhook_failures[webhook_type] = _webhook_failures.get(webhook_type, 0) + 1


def get_metrics() -> Dict[str, Any]:
    with _lock:
        times = list(_request_times)
        job_f = dict(_job_failures)
        web_f = dict(_webhook_failures)
    avg_response = sum(times) / len(times) if times else 0
    return {
        "uptime_seconds": time.time() - _start_time,
        "request_count_sampled": len(times),
        "avg_response_time_seconds": round(avg_response, 4),
        "job_failures": job_f,
        "webhook_failures": web_f,
    }

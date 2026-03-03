import os
import time
from pathlib import Path

HEARTBEAT_DIR = Path("/app/temp/health")
HEARTBEAT_INTERVAL_SECONDS = 30
HEARTBEAT_MAX_AGE_SECONDS = 120


def get_heartbeat_path(name: str) -> Path:
    safe_name = (name or "").strip().replace("/", "_").replace("\\", "_")
    if not safe_name:
        raise ValueError("Heartbeat name is required")
    return HEARTBEAT_DIR / f"{safe_name}.heartbeat"


def touch_heartbeat(name: str) -> None:
    path = get_heartbeat_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    os.utime(path, None)


def heartbeat_age_seconds(name: str) -> float | None:
    path = get_heartbeat_path(name)
    if not path.exists():
        return None
    return max(0.0, time.time() - path.stat().st_mtime)


def heartbeat_is_fresh(name: str, max_age_seconds: int = HEARTBEAT_MAX_AGE_SECONDS) -> bool:
    age = heartbeat_age_seconds(name)
    return age is not None and age <= max_age_seconds


def remove_heartbeat(name: str) -> None:
    path = get_heartbeat_path(name)
    try:
        path.unlink()
    except FileNotFoundError:
        pass

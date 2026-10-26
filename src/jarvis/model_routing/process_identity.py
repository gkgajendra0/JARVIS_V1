"""PID plus incarnation fencing shared by routing operations."""

from dataclasses import dataclass

import psutil


@dataclass(frozen=True, slots=True)
class RoutingProcessIdentity:
    pid: int
    started_at: float


def current_process_identity():
    p = psutil.Process()
    return RoutingProcessIdentity(p.pid, p.create_time())


def process_identity_alive(identity):
    try:
        p = psutil.Process(identity.pid)
        return (
            p.create_time() == identity.started_at
            and p.is_running()
            and p.status() != psutil.STATUS_ZOMBIE
        )
    except psutil.NoSuchProcess:
        return False
    except psutil.AccessDenied:
        return None

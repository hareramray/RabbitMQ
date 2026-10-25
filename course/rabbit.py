"""Shared connection setup and bounded polling for notebook demonstrations."""
from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

import pika
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=False)
DEFAULT_URL = "amqp://student:student-local-only@localhost:5672/learning"


def broker_url() -> str:
    return os.getenv("BROKER_URL", os.getenv("RABBITMQ_URL", DEFAULT_URL))


def connect(url: str | None = None) -> pika.BlockingConnection:
    """Open a connection owned by the calling thread. Caller must close it."""
    parameters = pika.URLParameters(url or broker_url())
    parameters.heartbeat = 60
    parameters.blocked_connection_timeout = 10
    parameters.socket_timeout = 5
    parameters.stack_timeout = 15
    parameters.connection_attempts = 2
    parameters.retry_delay = 1
    return pika.BlockingConnection(parameters)


def unique_name(label: str) -> str:
    """Use isolated lab resources; restart + Run All creates a fresh namespace."""
    return f"rmqcourse.{label}.{uuid.uuid4().hex[:12]}"


def wait_for_message(channel, queue: str, timeout: float = 5.0, auto_ack: bool = False):
    """Poll for one message with a deadline; QoS does not apply to basic_get.

    Returns (method, properties, body). With the default auto_ack=False,
    the caller must explicitly acknowledge/reject on this same channel.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        delivery = channel.basic_get(queue=queue, auto_ack=auto_ack)
        if delivery[0] is not None:
            return delivery
        time.sleep(0.05)
    raise TimeoutError(f"No message in {queue!r} within {timeout}s. Check producer, binding and consumer.")

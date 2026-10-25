"""Database transaction boundaries are deliberately visible for the lessons."""
import uuid
from django.db import connection, transaction
from django.utils import timezone
from .models import Order, Outbox, ProcessedEvent
from .messaging import publish_event


def event_for(order):
    return {"schema_version": 1, "event_id": str(order.event_id), "order_id": order.pk,
            "product": order.product, "quantity": order.quantity}


def process_event(event):
    if (not isinstance(event, dict) or type(event.get("schema_version")) is not int
            or event["schema_version"] != 1):
        raise ValueError("Expected an order.created.v1 JSON object")
    try:
        event_id = uuid.UUID(str(event["event_id"]))
        order_id = event["order_id"]
        if type(order_id) is not int or order_id <= 0:
            raise ValueError("order_id must be a positive integer")
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError("Invalid event_id or order_id") from exc
    with transaction.atomic():
        # Lock the business row as well as recording a unique event identifier.
        # This serializes two consumers processing events for the same order.
        try:
            order = Order.objects.select_for_update().get(pk=order_id)
        except Order.DoesNotExist as exc:
            raise ValueError("Event references an unknown order") from exc
        if event_id != order.event_id:
            raise ValueError("Event identifier does not match the order")
        _, created = ProcessedEvent.objects.get_or_create(event_id=event_id, defaults={"order": order})
        if created and order.status != "completed":
            order.status = "completed"
            order.fulfillments += 1
            order.save(update_fields=["status", "fulfillments"])
        return {"order_id": order.pk, "applied": created, "status": order.status,
                "fulfillments": order.fulfillments}


def dispatch_pending(limit=100):
    """Confirm before marking sent; a crash between these steps can duplicate."""
    sent = 0
    for _ in range(limit):
        with transaction.atomic():
            pending = Outbox.objects.filter(published_at__isnull=True).order_by("created_at")
            # SQLite is for single-dispatcher development only. Compose uses PostgreSQL.
            if connection.features.has_select_for_update_skip_locked:
                pending = pending.select_for_update(skip_locked=True)
            else:
                pending = pending.select_for_update()
            event = pending.first()
            if event is None:
                break
            publish_event(event.payload)
            event.published_at = timezone.now()
            event.save(update_fields=["published_at"])
            sent += 1
    return sent

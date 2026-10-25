import json
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from kombu.exceptions import OperationalError as BrokerError
from pika.exceptions import AMQPError
from .messaging import publish_event
from .models import Order, Outbox
from .services import event_for
from .tasks import fulfill_order


def serialize(order):
    return {"id": order.pk, "event_id": str(order.event_id), "product": order.product,
            "quantity": order.quantity, "mode": order.mode, "status": order.status,
            "fulfillments": order.fulfillments,
            "outbox_pending": order.outbox_events.filter(published_at__isnull=True).count()}


@require_GET
def health(request):
    # This tests HTTP + database reachability, not broker or worker readiness.
    Order.objects.exists()
    return JsonResponse({"status": "ok", "service": "rabbitmq-course"})


@require_GET
def order_detail(request, order_id):
    return JsonResponse(serialize(get_object_or_404(Order, pk=order_id)))


@csrf_exempt  # Local unauthenticated JSON teaching API; see django_demo/README.md.
@require_POST
def create_order(request):
    try:
        data = json.loads(request.body)
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object")
        product = data.get("product", "")
        quantity = data.get("quantity", 1)
        mode = data.get("mode", "outbox")
        if not isinstance(product, str) or not 1 <= len(product.strip()) <= 120:
            raise ValueError("product must contain 1 to 120 characters")
        if type(quantity) is not int or not 1 <= quantity <= 100:
            raise ValueError("quantity must be an integer from 1 to 100")
        if mode not in ("direct", "celery", "outbox"):
            raise ValueError("mode must be direct, celery or outbox")
    except (ValueError, TypeError, UnicodeError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    order = None
    try:
        with transaction.atomic():
            order = Order.objects.create(product=product.strip(), quantity=quantity, mode=mode)
            event = event_for(order)
            if mode == "outbox":
                Outbox.objects.create(id=order.event_id, order=order, payload=event)
            elif mode == "celery":
                # Workers can only see the order after this transaction commits.
                # This fixes the timing race; it does NOT make DB+broker atomic.
                transaction.on_commit(lambda: fulfill_order.delay(order.pk))
            else:
                transaction.on_commit(lambda: publish_event(event))
    except (AMQPError, BrokerError, OSError) as exc:
        # The callback failed after commit: return the persisted order identifier.
        return JsonResponse({"error": "Order saved, publication failed", "order_id": order.pk,
                             "exception": type(exc).__name__}, status=503)
    return JsonResponse(serialize(order), status=201)

from celery import shared_task
from django.db import OperationalError
from .models import Order
from .services import event_for, process_event


@shared_task(acks_late=True, autoretry_for=(OperationalError,), retry_backoff=True,
             retry_kwargs={"max_retries": 3})
def fulfill_order(order_id):
    order = Order.objects.get(pk=order_id)
    return process_event(event_for(order))


@shared_task
def add(x, y):
    return x + y


@shared_task
def multiply(x, y):
    return x * y


class TemporaryDemoError(Exception):
    pass


@shared_task(bind=True, autoretry_for=(TemporaryDemoError,),
             retry_kwargs={"max_retries": 3}, default_retry_delay=1)
def retry_then_add(self, x, y, fail_first=2):
    """Deterministic teaching failure, with a finite retry budget."""
    if self.request.retries < fail_first:
        raise TemporaryDemoError("Simulated temporary dependency failure")
    return {"value": x + y, "retries": self.request.retries}

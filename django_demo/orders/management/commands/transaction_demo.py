import json
from django.core.management.base import BaseCommand
from django.db import transaction
from orders.models import Order, Outbox
from orders.services import event_for


class Command(BaseCommand):
    help = "Prove rollback removes the order and outbox, and suppresses on_commit callbacks."

    def handle(self, *args, **options):
        callbacks = []
        rolled_back_order_id = None
        event_id = None
        try:
            with transaction.atomic():
                order = Order.objects.create(product="rollback-demo", quantity=1, mode="outbox")
                rolled_back_order_id = order.pk
                event_id = order.event_id
                Outbox.objects.create(id=event_id, order=order, payload=event_for(order))
                transaction.on_commit(lambda: callbacks.append("rolled-back callback"))
                raise RuntimeError("Intentional rollback")
        except RuntimeError:
            pass
        rollback_callbacks = list(callbacks)
        with transaction.atomic():
            transaction.on_commit(lambda: callbacks.append("committed callback"))
            inside_callbacks = list(callbacks)
        result = {
            "order_rolled_back": not Order.objects.filter(pk=rolled_back_order_id, event_id=event_id).exists(),
            "outbox_rolled_back": not Outbox.objects.filter(pk=event_id).exists(),
            "callbacks_after_rollback": rollback_callbacks,
            "callbacks_inside_commit_block": inside_callbacks,
            "callbacks_after_commit": callbacks,
        }
        self.stdout.write(json.dumps(result))

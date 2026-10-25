import io
import json
import uuid
from unittest.mock import patch
from django.core.management import call_command
from django.db import transaction
from django.test import TestCase
from pika.exceptions import AMQPConnectionError
from .models import Order, Outbox, ProcessedEvent
from .services import dispatch_pending, event_for, process_event


class OrderFlowTests(TestCase):
    def create_order(self):
        return Order.objects.create(product="Book", quantity=2, mode="outbox")

    def post(self, **overrides):
        payload = {"product": "Book", "quantity": 2, "mode": "outbox"}
        payload.update(overrides)
        return self.client.post("/api/orders/", data=json.dumps(payload), content_type="application/json")

    def test_outbox_request_stores_order_and_event_without_publishing(self):
        with patch("orders.views.publish_event") as publisher:
            response = self.post()
        self.assertEqual(response.status_code, 201)
        order = Order.objects.get()
        self.assertEqual(Outbox.objects.get().payload, event_for(order))
        self.assertEqual(response.json()["outbox_pending"], 1)
        publisher.assert_not_called()

    def test_invalid_requests_do_not_create_rows(self):
        for invalid in ({"quantity": True}, {"quantity": -1}, {"product": "  "}, {"mode": "unknown"}):
            self.assertEqual(self.post(**invalid).status_code, 400)
        self.assertFalse(Order.objects.exists())

    def test_order_and_outbox_are_rolled_back_together(self):
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                order = self.create_order()
                Outbox.objects.create(id=order.event_id, order=order, payload=event_for(order))
                raise RuntimeError("simulated crash before commit")
        self.assertFalse(Order.objects.exists())
        self.assertFalse(Outbox.objects.exists())

    def test_celery_publication_is_deferred_until_commit(self):
        with patch("orders.views.fulfill_order.delay") as publish:
            with self.captureOnCommitCallbacks(execute=True) as callbacks:
                response = self.post(mode="celery")
                publish.assert_not_called()
            self.assertEqual(len(callbacks), 1)
            publish.assert_called_once_with(response.json()["id"])

    def test_direct_publication_is_deferred_until_commit(self):
        with patch("orders.views.publish_event") as publish:
            with self.captureOnCommitCallbacks(execute=True):
                self.post(mode="direct")
                publish.assert_not_called()
            publish.assert_called_once()

    def test_dispatcher_keeps_event_pending_after_publish_failure(self):
        order = self.create_order()
        event = Outbox.objects.create(id=order.event_id, order=order, payload=event_for(order))
        with patch("orders.services.publish_event", side_effect=AMQPConnectionError):
            with self.assertRaises(AMQPConnectionError):
                dispatch_pending()
        event.refresh_from_db()
        self.assertIsNone(event.published_at)

    def test_dispatcher_marks_only_confirmed_rows(self):
        order = self.create_order()
        event = Outbox.objects.create(id=order.event_id, order=order, payload=event_for(order))
        with patch("orders.services.publish_event") as publish:
            self.assertEqual(dispatch_pending(), 1)
            self.assertEqual(dispatch_pending(), 0)
        event.refresh_from_db()
        self.assertIsNotNone(event.published_at)
        publish.assert_called_once_with(event.payload)

    def test_mark_failure_republishes_same_event_and_consumer_applies_once(self):
        order = self.create_order()
        event = Outbox.objects.create(id=order.event_id, order=order, payload=event_for(order))
        with patch("orders.services.publish_event") as publish:
            with patch.object(Outbox, "save", side_effect=RuntimeError("crash after broker confirmation")):
                with self.assertRaises(RuntimeError):
                    dispatch_pending()
            event.refresh_from_db()
            self.assertIsNone(event.published_at)
            self.assertEqual(dispatch_pending(), 1)
        self.assertEqual(publish.call_count, 2)
        deliveries = [call.args[0] for call in publish.call_args_list]
        self.assertEqual(deliveries[0]["event_id"], deliveries[1]["event_id"])
        self.assertTrue(process_event(deliveries[0])["applied"])
        self.assertFalse(process_event(deliveries[1])["applied"])
        order.refresh_from_db()
        self.assertEqual(order.fulfillments, 1)

    def test_redelivery_does_not_repeat_database_effect(self):
        order = self.create_order()
        first = process_event(event_for(order))
        second = process_event(event_for(order))
        order.refresh_from_db()
        self.assertTrue(first["applied"])
        self.assertFalse(second["applied"])
        self.assertEqual(order.fulfillments, 1)
        self.assertEqual(ProcessedEvent.objects.count(), 1)

    def test_processing_failure_rolls_back_dedup_record(self):
        order = self.create_order()
        with patch.object(Order, "save", side_effect=RuntimeError("database write failure")):
            with self.assertRaises(RuntimeError):
                process_event(event_for(order))
        self.assertFalse(ProcessedEvent.objects.exists())
        result = process_event(event_for(order))
        self.assertTrue(result["applied"])

    def test_invalid_event_cannot_fulfill_an_order(self):
        order = self.create_order()
        invalid = event_for(order)
        invalid["event_id"] = str(uuid.uuid4())
        with self.assertRaises(ValueError):
            process_event(invalid)
        self.assertFalse(ProcessedEvent.objects.exists())

    def test_schema_rejects_boolean_string_and_nonpositive_integer_ids(self):
        order = self.create_order()
        for overrides in ({"schema_version": True}, {"schema_version": "1"},
                          {"order_id": True}, {"order_id": str(order.pk)},
                          {"order_id": 0}, {"order_id": -1}, {"order_id": 1.5}):
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValueError):
                    process_event({**event_for(order), **overrides})
        self.assertFalse(ProcessedEvent.objects.exists())


from django.test import TransactionTestCase


class CommitBoundaryTests(TransactionTestCase):
    def test_failed_direct_publish_returns_saved_order_identifier(self):
        with patch("orders.views.publish_event", side_effect=AMQPConnectionError):
            response = self.client.post("/api/orders/", data=json.dumps({
                "product": "Book", "quantity": 1, "mode": "direct"
            }), content_type="application/json")
        self.assertEqual(response.status_code, 503)
        self.assertTrue(Order.objects.filter(pk=response.json()["order_id"]).exists())

    def test_transaction_demo_reports_real_callback_boundaries(self):
        output = io.StringIO()
        call_command("transaction_demo", stdout=output)
        result = json.loads(output.getvalue())
        self.assertTrue(result["order_rolled_back"])
        self.assertTrue(result["outbox_rolled_back"])
        self.assertEqual(result["callbacks_after_rollback"], [])
        self.assertEqual(result["callbacks_inside_commit_block"], [])
        self.assertEqual(result["callbacks_after_commit"], ["committed callback"])

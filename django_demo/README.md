# The Django order demonstration

Use notebooks 12–15 after the Python RabbitMQ lessons. Start the services from the repository root:

```powershell
docker compose up -d --build web worker
docker compose exec -T web python manage.py check
```

The web image contains this directory at `/app`. Rebuild `web` and `worker` after source changes. `/health/` checks HTTP and the database; it does not claim that a Celery worker is ready. The Compose environment uses PostgreSQL; a local command without `POSTGRES_HOST` uses SQLite for tests. Run the worker in the Linux container, including on Windows.

## Read the code in this order

1. `orders/models.py`: an order, durable publication intent, and a deduplication record.
2. `orders/views.py`: JSON validation, a transaction, and the three publication modes.
3. `orders/messaging.py`: explicit exchange/queue bindings, persistence, confirms, mandatory routing.
4. `orders/services.py`: atomic business effect + event deduplication and the outbox dispatcher.
5. `orders/tasks.py`: Celery task registration, idempotent processing, retry and Canvas examples.
6. `orders/management/commands/`: finite terminal demonstrations.

## HTTP API

`POST http://localhost:8000/api/orders/` accepts a JSON object:

```json
{"product":"Python book","quantity":2,"mode":"outbox"}
```

The response includes `id`, `event_id`, `status`, `fulfillments`, and `outbox_pending`. Use `GET /api/orders/<id>/` to inspect progress. POST creates a new order every time: this demo does **not** implement HTTP idempotency keys.

| Mode | What the request does | What completes the order |
|---|---|---|
| `direct` | Commit the order, then publish its event with Pika | `consume_events` command |
| `celery` | Commit the order, then enqueue `orders.tasks.fulfill_order` | The Celery worker |
| `outbox` | Commit both the order and its pending Outbox row | `dispatch_outbox`, then `consume_events` |

Direct and Celery mode use `on_commit`. If publishing fails after commit, the response is HTTP 503 and includes the saved `order_id`. Blindly retrying POST would create another order. If the process dies between commit and publishing, these modes can leave a pending order with no message; outbox mode preserves publication intent in the same database transaction.

## Finite commands

```powershell
docker compose exec -T web python manage.py dispatch_outbox --once --limit 100
docker compose exec -T web python manage.py consume_events --max-messages 100 --timeout 3
docker compose exec -T web python manage.py transaction_demo
docker compose exec -T web python manage.py test orders
```

`consume_events` is a bounded `basic_get` teaching consumer. The prefetch lesson uses push consumers elsewhere. It acknowledges after DB commit; malformed messages go to `rmqcourse.orders.dead`; an unexpected processing error requeues once and stops the command so it cannot busy-loop. Default dead-lettering does not guarantee lossless transfer if the destination is unavailable.

`dispatch_outbox` locks pending rows with PostgreSQL `select_for_update(skip_locked=True)`, publishes with confirms, and marks the row published in the same DB transaction. A failure before marking keeps the row pending. A crash after broker acceptance but before DB commit can cause a duplicate on the next dispatch. `ProcessedEvent` and the order change are committed atomically, so replay does not increase `fulfillments` twice. This covers a database effect only: an external payment or email would need its own idempotency mechanism. SQLite does not provide PostgreSQL row-lock behavior; use only one local SQLite dispatcher.

The dispatcher keeps a transaction open during its bounded broker call for clarity. Production designs need measured batch sizes, lock duration, retry scheduling, metrics, schema evolution, retention, and deliberate handling of poison events.

## Local teaching boundaries

This is an unauthenticated, localhost-only JSON API. Its POST is CSRF-exempt so Python notebooks can call it without browser sessions. These are explicit teaching choices, not deployable authentication settings. There are no emails, payments, or external business operations. Never expose these sample credentials and development settings publicly.

The result backend is `rpc://`; consume results from the same notebook client that submitted the tasks. Group and chain examples are supported; chords require a suitable different result backend. The worker uses `--pool=solo` for predictable demonstrations, so a group is a set of independent tasks but does not run in parallel in this single worker. Scale separate worker containers to observe concurrency.

## References

- [Django transactions](https://docs.djangoproject.com/en/5.2/topics/db/transactions/)
- [Django select_for_update](https://docs.djangoproject.com/en/5.2/ref/models/querysets/#select-for-update)
- [Celery with Django](https://docs.celeryq.dev/en/stable/django/first-steps-with-django.html)
- [Celery tasks](https://docs.celeryq.dev/en/stable/userguide/tasks.html)
- [Celery Canvas](https://docs.celeryq.dev/en/stable/userguide/canvas.html)
- [RabbitMQ confirms and acknowledgements](https://www.rabbitmq.com/docs/confirms)

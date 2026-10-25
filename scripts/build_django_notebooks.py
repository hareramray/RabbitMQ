"""Build the four Django lessons as clean, portable nbformat 4 notebooks."""
import json
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def md(text):
    return {"cell_type": "markdown", "metadata": {}, "source": textwrap.dedent(text).strip() + "\n"}


def code(text):
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
            "source": textwrap.dedent(text).strip() + "\n"}


def write(name, cells):
    for index, cell in enumerate(cells):
        cell["id"] = f"cell-{index:03d}"
    notebook = {"cells": cells, "metadata": {"kernelspec": {"display_name": "Python 3 (ipykernel)",
        "language": "python", "name": "python3"}, "language_info": {"name": "python", "version": "3.12"}},
        "nbformat": 4, "nbformat_minor": 5}
    (ROOT / "notebooks" / name).write_text(json.dumps(notebook, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


BOOTSTRAP = code('''
from pathlib import Path
import sys, os, json, time, subprocess
import requests
from dotenv import load_dotenv

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "course" / "rabbit.py").exists())
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")
API = os.getenv("DJANGO_BASE_URL", "http://localhost:8000").rstrip("/")

def get_order(order_id):
    response = requests.get(f"{API}/api/orders/{order_id}/", timeout=5)
    response.raise_for_status()
    return response.json()

def wait_completed(order_id, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        order = get_order(order_id)
        if order["status"] == "completed":
            return order
        time.sleep(0.2)
    raise TimeoutError(f"Order {order_id} is still pending. Inspect worker/consumer logs.")

def manage(*args, check=True, broker_override=None):
    command = ["docker", "compose", "exec", "-T"]
    if broker_override is not None:
        command += ["-e", f"BROKER_URL={broker_override}"]
    command += ["web", "python", "manage.py", *map(str, args)]
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=60)
    if check and completed.returncode:
        raise RuntimeError(completed.stderr or completed.stdout)
    return completed

response = requests.get(f"{API}/health/", timeout=5)
response.raise_for_status()
print(response.json())
''')

CLIENT = code('''
from celery import Celery
client = Celery("course_notebook",
                broker=os.getenv("BROKER_URL", "amqp://student:student-local-only@localhost:5672/learning"),
                backend="rpc://")
client.conf.update(
    task_serializer="json", result_serializer="json", accept_content=["json"],
    task_default_queue="celery", broker_connection_timeout=5,
    broker_transport_options={"confirm_publish": True},
    task_publish_retry_policy={"max_retries": 2, "interval_start": 0, "interval_step": 0.2, "interval_max": 0.5},
)
print("Celery notebook client ready; a worker must be running separately.")
''')

START = '''
Prerequisites: notebook 00; Docker Compose running RabbitMQ, PostgreSQL, web and worker.
From the repository root run `docker compose up -d --build web worker` and wait for startup.
Use a Python notebook kernel on the host. Celery workers run in Linux containers, including on Windows.
These notebooks call HTTP instead of importing Django ORM into Jupyter's running async event loop.
Cells finish or time out; run top to bottom. New orders are created each run.
'''

write("12_django_direct_publishing.ipynb", [
md("# 12 · Django publishes an order event\n\n**Level:** intermediate · **Time:** 40–55 minutes\n\n"
   "**You will:** trace an HTTP request to a queue, process an event in Django, replay a duplicate, "
   "and inspect the database effect.\n\n" + START),
md('''
## 1. Read the route through the system

`Notebook → HTTP POST → Django transaction → Pika publisher → RabbitMQ queue`

`Management-command consumer → database transaction → acknowledgement`

The publisher and consumer are separate pieces. A successful publish means the broker accepted the
event; it does not mean the order is completed. This lesson uses **direct** mode, which publishes
after the database commits. Lesson 14 closes the remaining publication gap with an outbox.
First check the HTTP service and define bounded helpers for later cells.
'''), BOOTSTRAP,
md('''
## 2. Inspect the actual application code

Read the `create_order` transaction and `publish_event`. Locate `on_commit`, `confirm_delivery`,
`mandatory=True`, the queue binding, and `delivery_mode=2`. They solve different problems.
The local JSON API intentionally has no authentication and is CSRF-exempt; it is bound to localhost.
'''),
code('''
print((ROOT / "django_demo" / "orders" / "views.py").read_text())
print((ROOT / "django_demo" / "orders" / "messaging.py").read_text())
'''),
md('''
## 3. Create an order

**Predict:** the response is HTTP 201 and the order remains `pending`. The separate event consumer
is not running yet. Django commits the row before publishing, so a consumer cannot beat the commit.
If this returns 503, the response includes the already-saved order identifier: inspect it instead of
blindly retrying POST and creating another order.
'''),
code('''
response = requests.post(f"{API}/api/orders/", json={
    "product": "Python messaging workbook", "quantity": 2, "mode": "direct"
}, timeout=30)
print(response.status_code, response.json())
response.raise_for_status()
order = response.json()
assert order["status"] == "pending"
assert order["fulfillments"] == 0
'''),
md('''
## 4. Observe the waiting event

Open RabbitMQ Management at http://localhost:15672, select virtual host `learning`, then the
`rmqcourse.orders.process` queue. You should see a ready message; dashboard statistics can lag.
Do not use the Management "Get messages" control with automatic acknowledgement, because that
would remove the message before our Django consumer sees it.

Now run the finite consumer. It drains at most 100 messages for at most three seconds. Existing
events from previous runs may also be processed. The output reports the individual database effects.
'''),
code('''
result = manage("consume_events", "--max-messages", 100, "--timeout", 3)
print(result.stdout)
completed = get_order(order["id"])
assert completed["status"] == "completed"
assert completed["fulfillments"] == 1
print(completed)
'''),
md('''
## 5. Replay exactly the same event

An acknowledgement can be lost after a database commit. The broker may then redeliver the message.
Simulate that duplicate explicitly by publishing the same event ID again. A unique event record and
the business update share one database transaction. This protects this database effect; it does not
make delivery exactly once or protect an unrelated external payment/email automatically.
'''),
code('''
import pika
from course.rabbit import connect
event = {"schema_version": 1, "event_id": order["event_id"], "order_id": order["id"],
         "product": order["product"], "quantity": order["quantity"]}
with connect() as connection:
    channel = connection.channel()
    channel.confirm_delivery()
    channel.basic_publish(exchange="rmqcourse.orders", routing_key="order.created",
                          body=json.dumps(event).encode(), mandatory=True,
                          properties=pika.BasicProperties(delivery_mode=2, content_type="application/json",
                                                          message_id=event["event_id"]))
print(manage("consume_events", "--max-messages", 100, "--timeout", 3).stdout)
assert get_order(order["id"])["fulfillments"] == 1
print("Duplicate delivered; database effect still occurred once.")
'''),
md('''
## 6. Exercise: add an audit subscriber

Create a separate temporary queue bound to `order.*`. Publish the same event again and prove that
both the processing queue and the audit queue receive a copy. Explain why a second consumer on
the **same** processing queue would share work instead of receiving another copy.

Try it before opening the solution cell. Its queue is deleted when the connection closes.
'''),
code('''
# Suggested solution: an independent binding creates a second destination.
from course.rabbit import wait_for_message
with connect() as connection:
    channel = connection.channel()
    audit = channel.queue_declare(queue="", exclusive=True).method.queue
    channel.queue_bind(queue=audit, exchange="rmqcourse.orders", routing_key="order.*")
    channel.confirm_delivery()
    channel.basic_publish(exchange="rmqcourse.orders", routing_key="order.created",
                          body=json.dumps(event).encode(), mandatory=True)
    method, properties, body = wait_for_message(channel, audit)
    assert json.loads(body)["event_id"] == event["event_id"]
    channel.basic_ack(method.delivery_tag)
    print("Audit subscriber received:", json.loads(body))
print(manage("consume_events", "--max-messages", 100, "--timeout", 3).stdout)
assert get_order(order["id"])["fulfillments"] == 1
'''),
md('''
## Checkpoint, cleanup, and troubleshooting

- Explain why publisher confirms cannot establish that `fulfillments` is one.
- Explain why `ProcessedEvent` and the order change must commit atomically.
- A pending order after a confirmed publish usually means the consumer has not run; inspect its output.
- `PRECONDITION_FAILED` can mean an older queue has different declaration arguments. Inspect it before
  changing or deleting it; all Django lessons share this topology.
- Leave the completed rows as demonstration evidence. Temporary audit resources were automatically
  removed. Do not delete the shared Django queue between these lessons. `docker compose down`
  stops the local services and keeps their named data volumes.

Read: [RabbitMQ confirms](https://www.rabbitmq.com/docs/confirms),
[Django transactions](https://docs.djangoproject.com/en/5.2/topics/db/transactions/).
Continue with **13 · Django and Celery**.
'''),
])

write("13_django_celery.ipynb", [
md("# 13 · Django background work with Celery\n\n**Level:** intermediate · **Time:** 40–50 minutes\n\n"
   "**You will:** submit a background task after commit, observe durable business state, "
   "prove task idempotency, and inspect a bounded retry.\n\n" + START),
md('''
## 1. Understand the extra layer

RabbitMQ transports messages. Celery provides task names, serialization, worker execution, retries,
and result handling. The Django request publishes a task message; the worker imports and executes
`orders.tasks.fulfill_order`. The same business processing function is used by the Pika consumer.
The worker needs this application's code: a function written only in a notebook is not installed
on that worker automatically. Check the HTTP service first.
'''), BOOTSTRAP,
md('''
## 2. Find registration and delivery settings

Locate the task decorator, `acks_late=True`, and the bounded database retry policy. Late ack is
useful only with idempotent work; it is not a promise that every failure is retried forever.
The worker's `--pool=solo` executes one task at a time for this lab. Production worker pools and
failure behavior need separate testing. Inspect both task code and settings.
'''),
code('''
print((ROOT / "django_demo" / "orders" / "tasks.py").read_text())
print((ROOT / "django_demo" / "config" / "celery.py").read_text())
'''),
md('''
## 3. Let a worker complete an HTTP-created order

**Predict:** POST returns without waiting for the task result. A fast worker may already have finished
by the first GET, so do not assert that every initial response is pending. Poll the persisted order
with a deadline. The application schedules the task inside `transaction.on_commit`.
'''),
code('''
response = requests.post(f"{API}/api/orders/", json={
    "product": "Celery practice kit", "quantity": 1, "mode": "celery"
}, timeout=30)
response.raise_for_status()
order = response.json()
print("HTTP accepted:", order)
completed = wait_completed(order["id"])
assert completed["fulfillments"] == 1
print("Worker completed:", completed)
'''),
md('''
## 4. Create a notebook Celery client

Use the host-side broker URL, not the container hostname `rabbitmq`. The `rpc://` backend returns
results through RabbitMQ to this submitting client. It is a demonstration result channel, while
the order table is our durable business record. Keep the same client and kernel for result reads.
'''), CLIENT,
md('''
## 5. Resubmit the same logical work

Submit an explicit named task for the already-completed order. The task ID will be new, but the
business event ID stays the same. **Predict:** the result says `applied=False` and the count stays one.
Every `get` has a timeout; this notebook never waits forever for a worker.
'''),
code('''
duplicate = client.send_task("orders.tasks.fulfill_order", args=[order["id"]])
duplicate_result = duplicate.get(timeout=30)
print(duplicate.id, duplicate_result)
assert duplicate_result["applied"] is False
assert get_order(order["id"])["fulfillments"] == 1
'''),
md('''
## 6. Observe a deterministic temporary failure

`retry_then_add` raises a teaching exception for the first two attempts and waits one second between
retries. It succeeds on the third execution. This task has no external side effect. Watch
`docker compose logs --tail 50 worker` in a terminal to see retries. Retry republishes work;
ordinary broker redelivery and Celery retry are distinct mechanisms.
'''),
code('''
retry_job = client.send_task("orders.tasks.retry_then_add", args=[7, 8], kwargs={"fail_first": 2})
answer = retry_job.get(timeout=30)
print(answer)
assert answer == {"value": 15, "retries": 2}
'''),
md('''
## 7. Exercise: exhaust the retry budget

Request ten simulated failures from a task configured for at most three retries. Predict the
terminal state. Then run the solution and inspect the failure without raising it into the kernel.
`max_retries=3` permits the initial attempt plus three retries.
'''),
code('''
failed = client.send_task("orders.tasks.retry_then_add", args=[1, 2], kwargs={"fail_first": 10})
failure = failed.get(timeout=30, propagate=False)
assert failed.state == "FAILURE"
print("Terminal state:", failed.state, "Reason:", str(failure))
'''),
md('''
## Checkpoint and cleanup

Why does a unique Celery task ID not deduplicate repeated requests for the same order? Why does
`on_commit` solve worker timing but leave a publication-failure gap? Lesson 14 addresses that gap.

If results time out, inspect worker startup, task names and queue `celery` before increasing timeouts.
An unknown task indicates mismatched worker code: rebuild the image. In this single-worker lab,
completed task results need not be retained after inspection. Close the notebook client.
'''),
code('''
client.close()
print("Client closed. Completed orders remain available through the HTTP API.")
'''),
md('''
References: [Celery with Django](https://docs.celeryq.dev/en/stable/django/first-steps-with-django.html),
[Celery task acknowledgements and retries](https://docs.celeryq.dev/en/stable/userguide/tasks.html).
Continue with **14 · Transactions and the outbox**.
'''),
])

write("14_transactions_and_outbox.ipynb", [
md("# 14 · Transactions, the outbox, and duplicate-safe processing\n\n**Level:** advanced · **Time:** 50–65 minutes\n\n"
   "**You will:** prove commit/rollback behavior, retain publication intent through a failed send, "
   "recover pending events, and explain the remaining duplicate window.\n\n" + START),
md('''
## 1. Locate the two commit boundaries

The database and RabbitMQ do not share our application's transaction. `on_commit` prevents a worker
from reading an uncommitted order, but the process could die after DB commit and before publishing.
An **outbox** stores the order and its intended event together. A dispatcher later publishes that
event and marks it sent. Repeating the dispatch is safe only when the consumer handles duplicates.
First check the local services and load the finite command helper.
'''), BOOTSTRAP,
md('''
## 2. Prove rollback and callback ordering

The command below runs actual Django database transactions. It intentionally rolls back one order
and outbox record, then observes callbacks inside and after a successful transaction. It does not
contact RabbitMQ. **Predict:** rolled-back callbacks never execute; the committed callback appears
only after the transaction exits.
'''),
code('''
result = json.loads(manage("transaction_demo").stdout.strip())
print(json.dumps(result, indent=2))
assert result["order_rolled_back"] and result["outbox_rolled_back"]
assert result["callbacks_after_rollback"] == []
assert result["callbacks_inside_commit_block"] == []
assert result["callbacks_after_commit"] == ["committed callback"]
'''),
md('''
## 3. Store publication intent

Create an outbox order. This HTTP path does not call the broker. **Predict:** `outbox_pending=1`
and the order remains pending until we explicitly dispatch and consume. The event identifier stays
stable across dispatch attempts and is used for consumer deduplication.
'''),
code('''
response = requests.post(f"{API}/api/orders/", json={
    "product": "Reliable messaging handbook", "quantity": 3, "mode": "outbox"
}, timeout=10)
response.raise_for_status()
order = response.json()
assert order["outbox_pending"] == 1 and order["status"] == "pending"
print(order)
'''),
md('''
## 4. Inject a publication failure without stopping shared services

Override the broker URL for **one dispatcher process** to the unused loopback port 1 inside its
container. Other services keep their valid broker configuration. The connection attempt fails;
the dispatcher's transaction must leave the outbox row pending. This is an intentional nonzero exit.
Only the exception tail is shown; inspect full output yourself if needed.
'''),
code('''
failure = manage("dispatch_outbox", "--once", "--limit", 100, check=False,
                 broker_override="amqp://student:student-local-only@127.0.0.1:1/learning")
assert failure.returncode != 0, "Expected the isolated connection failure"
print("Expected dispatcher failure:", failure.stderr.strip().splitlines()[-1])
after_failure = get_order(order["id"])
assert after_failure["outbox_pending"] == 1
assert after_failure["status"] == "pending"
print("Publication intent survived:", after_failure)
'''),
md('''
## 5. Recover using the normal broker URL

The dispatcher locks pending rows, publishes persistent messages with confirms and mandatory
routing, and records `published_at` only after confirmation. It runs separately from consumption.
**Predict:** after dispatch the outbox is clear, while the order is still pending; after consumption
the business state becomes completed. These assertions assume no separate event consumer is running.
'''),
code('''
print(manage("dispatch_outbox", "--once", "--limit", 100).stdout)
after_publish = get_order(order["id"])
assert after_publish["outbox_pending"] == 0
assert after_publish["status"] == "pending"
print("Published, not processed:", after_publish)
print(manage("consume_events", "--max-messages", 100, "--timeout", 3).stdout)
completed = get_order(order["id"])
assert completed["status"] == "completed" and completed["fulfillments"] == 1
print(completed)
'''),
md('''
## 6. Inspect the implementation and its limits

Read `dispatch_pending` and `process_event`. PostgreSQL row locks plus `skip_locked=True` let
dispatchers take different rows. SQLite fallback is for a single dispatcher and does not provide
the same locking semantics. This clear teaching implementation holds a DB transaction open during
the bounded broker call; production tuning must account for that lock duration.

There is still a crash window **after RabbitMQ accepts the event but before the DB marks it sent**.
The next dispatcher may publish it again. A second crash window is after the consumer commits its
database change but before acknowledgement. Both require duplicate-safe business processing.
'''),
code('''
print((ROOT / "django_demo" / "orders" / "services.py").read_text())
'''),
md('''
## 7. Exercise: reproduce the duplicate outcome

Simulate a send-success/mark-failed duplicate by republishing the saved event ID. The simulation
injects the resulting duplicate directly; it does not pretend to crash at an exact timing point.
Before running the solution, predict the consumer's `applied` flag and fulfillment count.
'''),
code('''
import pika
from course.rabbit import connect
event = {"schema_version": 1, "event_id": order["event_id"], "order_id": order["id"],
         "product": order["product"], "quantity": order["quantity"]}
with connect() as connection:
    channel = connection.channel()
    channel.confirm_delivery()
    channel.basic_publish(exchange="rmqcourse.orders", routing_key="order.created",
                          body=json.dumps(event).encode(), mandatory=True,
                          properties=pika.BasicProperties(delivery_mode=2, content_type="application/json",
                                                          message_id=event["event_id"]))
print(manage("consume_events", "--max-messages", 100, "--timeout", 3).stdout)
assert get_order(order["id"])["fulfillments"] == 1
print("Duplicate was harmless to this database side effect.")
'''),
md('''
## 8. Run focused failure-boundary tests

The Django test suite uses mocks for broker calls and verifies atomic rollback, deferred publishing,
failed dispatch retention, duplicate handling, and rollback of the deduplication record when the
business update fails. It does not claim to be a broker failover test. Django creates a separate
test database, leaving the demonstration orders intact.
'''),
code('''
tests = manage("test", "orders")
print(tests.stdout + tests.stderr)
assert tests.returncode == 0
'''),
md('''
## Checkpoint, cleanup, and troubleshooting

- Which row lets the system recover if the web process dies after commit? Which constraint prevents
  repeated event application? Which external side effects still need an idempotency key?
- If a batch had more than 100 pending events, run the finite dispatcher/consumer again to continue.
- A PostgreSQL lock is released when its transaction ends. Keep broker timeouts and batch sizes bounded.
- Retain completed orders and outbox records as evidence. A production retention policy must account
  for how long old events can be replayed before deleting deduplication history.

References: [Django on_commit](https://docs.djangoproject.com/en/5.2/topics/db/transactions/),
[row locking](https://docs.djangoproject.com/en/5.2/ref/models/querysets/#select-for-update),
[RabbitMQ confirms](https://www.rabbitmq.com/docs/confirms).
Continue with **15 · Celery workflows**.
'''),
])

write("15_celery_workflows.ipynb", [
md("# 15 · Celery groups, chains, and workflow reasoning\n\n**Level:** advanced · **Time:** 35–50 minutes\n\n"
   "**You will:** construct task signatures, fan out independent tasks, pass results through a chain, "
   "and trace failure propagation with bounded waits.\n\n" + START),
md('''
## 1. Prepare the services and client

Celery Canvas describes relationships between tasks. RabbitMQ carries the resulting task messages;
the broker does not itself execute the graph. A **group** is independent work, while a **chain**
passes one task's result into the next task. The provided solo worker processes a group sequentially;
more worker processes/containers would be needed to observe simultaneous execution.
'''), BOOTSTRAP,
md('''
Create the same host-side client used in the previous Celery lesson. Results belong to this client
session through `rpc://`; keep it alive until all submitted results have been collected.
'''), CLIENT,
md('''
## 2. Describe work before submitting it

A signature contains a task name, arguments and execution options. It does not publish until
`apply_async()` is called. Use task names registered in the worker's `orders/tasks.py`.
**Predict:** describing `add(2, 3)` does not immediately change any RabbitMQ queue.
'''),
code('''
from celery import group, chain
addition = client.signature("orders.tasks.add", args=(2, 3))
print("Task:", addition.task, "arguments:", addition.args)
result = addition.apply_async()
assert result.get(timeout=30) == 5
print("Completed:", result.id, "→ 5")
'''),
md('''
## 3. Fan out independent additions with a group

The results are returned in the input signature order even if completion order differs. Do not
infer concurrency from this result ordering. The notebook waits from outside a worker; calling
blocking `.get()` inside a task can exhaust worker capacity and is not the pattern taught here.
'''),
code('''
batch = group(client.signature("orders.tasks.add", args=(n, n)) for n in range(5)).apply_async()
answers = batch.get(timeout=30)
assert answers == [0, 2, 4, 6, 8]
print("Input-ordered results:", answers)
'''),
md('''
## 4. Build a dependent chain

In a chain the prior result is prepended to the next signature's arguments.
`add(2, 3)` produces 5; `multiply(10)` therefore receives `(5, 10)` and returns 50.
**Predict the argument list before running.** No task needs to wait for another task inside its code.
'''),
code('''
workflow = chain(
    client.signature("orders.tasks.add", args=(2, 3)),
    client.signature("orders.tasks.multiply", args=(10,)),
)
final_result = workflow.apply_async()
assert final_result.get(timeout=30) == 50
print("Final value: 50; final task ID:", final_result.id)
'''),
md('''
## 5. Exercise: deliberately ignore the prior result

Build a chain whose second task computes `4 × 6`, regardless of the first task's result.
Use an immutable signature (`immutable=True`, equivalent to `.si()` on an imported task).
Run your attempt, then compare it with the solution.
'''),
code('''
independent_second = chain(
    client.signature("orders.tasks.add", args=(100, 200)),
    client.signature("orders.tasks.multiply", args=(4, 6), immutable=True),
).apply_async()
assert independent_second.get(timeout=30) == 24
print("Immutable second signature returned 24.")
'''),
md('''
## 6. Observe a failed prerequisite

The first task exhausts its retry budget, so the following multiplication does not execute.
Use `propagate=False` to inspect the terminal failure. Watch worker logs to distinguish the retrying
task from a broker redelivery. Celery propagates the predecessor failure to the chain result.
'''),
code('''
broken = chain(
    client.signature("orders.tasks.retry_then_add", args=(1, 2), kwargs={"fail_first": 10}),
    client.signature("orders.tasks.multiply", args=(5,)),
).apply_async()
error = broken.get(timeout=30, propagate=False)
assert broken.state == "FAILURE"
print("Workflow state:", broken.state, "Reason:", str(error))
'''),
md('''
## 7. Design discussion: aggregation and scheduling

A **chord** runs a callback after a group finishes, but the RPC result backend used here does not
support chords. A group followed by a callback may be upgraded to a chord; do not assume that
composition works with this backend. Use a supported result backend before implementing that lab.

For periodic work, Celery beat schedules task publication and workers execute tasks. Run one
authoritative scheduler for a given schedule; multiple independent schedulers can duplicate jobs.
Scheduling is distinct from delaying a task or retrying a failure. No scheduler is started here.

**Challenge:** sketch an order workflow with independent inventory and invoice work and a final
aggregation. Identify its result-backend requirements, business idempotency keys, and what must
happen if one branch fails. Do not model long transactions by holding a database lock across tasks.
'''),
md('''
## Cleanup and verification

All submitted work has a terminal result and the client can close. Orders from the Django lessons
remain as evidence. A result timeout is an observation, not proof that a task failed: inspect the
worker and business state before resubmitting side-effecting work.
'''),
code('''
client.close()
print("All workflow demonstrations completed; client closed.")
'''),
md('''
References: [Celery Canvas](https://docs.celeryq.dev/en/stable/userguide/canvas.html),
[Celery periodic tasks](https://docs.celeryq.dev/en/stable/userguide/periodic-tasks.html).
Continue with **16 · Monitoring and performance**, then quorum queues and the capstone.
'''),
])

if __name__ == "__main__":
    print("Built Django notebooks 12–15")

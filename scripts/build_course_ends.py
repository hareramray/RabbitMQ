"""Build the setup and capstone notebooks without notebook-library dependencies."""
import json
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def md(source):
    return {"cell_type": "markdown", "metadata": {}, "source": textwrap.dedent(source).strip() + "\n"}


def code(source):
    return {"cell_type": "code", "metadata": {}, "source": textwrap.dedent(source).strip() + "\n",
            "execution_count": None, "outputs": []}


def write(name, cells):
    for index, cell in enumerate(cells):
        cell["id"] = f"cell-{index:03d}"
    notebook = {"cells": cells, "metadata": {
        "kernelspec": {"name": "python3", "display_name": "RabbitMQ course", "language": "python"},
        "language_info": {"name": "python", "version": "3.12"}}, "nbformat": 4, "nbformat_minor": 5}
    (ROOT / "notebooks").mkdir(exist_ok=True)
    (ROOT / "notebooks" / name).write_text(json.dumps(notebook, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


write("00_setup_and_mental_model.ipynb", [
md('''
# 00 · Set up your lab and understand the moving parts

**Level:** beginner · **Time:** 30–45 minutes, plus first-time downloads

**You will:** start RabbitMQ, select the right Python kernel, inspect the broker, and explain
producer, exchange, queue, consumer and acknowledgement. You need basic Python variables,
dictionaries and functions. No RabbitMQ knowledge is assumed.

This is a practical course: read, predict, run, observe, then change something. The numbered
notebooks progress to Django/Celery, outbox delivery and quorum failover. Run one notebook at
a time, from top to bottom. Use **Restart Kernel and Run All** when repeating a lesson.
'''),
md('''
## 1. Start the local services

Install Python 3.12 or 3.13 and Docker Desktop with Linux containers. Open a terminal in the
repository directory. On Windows PowerShell, run:

```powershell
python -m venv .venv
.\\.venv\\Scripts\\python.exe -m pip install -r requirements.lock
Copy-Item .env.example .env
docker compose up -d --wait rabbitmq
.\\.venv\\Scripts\\python.exe -m ipykernel install --sys-prefix --name python3 --display-name "RabbitMQ course"
.\\.venv\\Scripts\\python.exe -m jupyterlab
```

Reuse an existing `.venv` and `.env` instead of overwriting custom settings. On macOS/Linux use
`.venv/bin/python` and `cp .env.example .env`. Full instructions are in `README.md`.

Choose **RabbitMQ course** in Jupyter's kernel selector. The kernel is the Python process that
executes these cells; installing a package in a different Python does not install it here.

Before lessons 12–15 and 18, run `docker compose up -d --build --wait` and check
`docker compose logs --tail 30 worker` for `ready`. This also starts PostgreSQL, Django and
the Linux Celery worker. Standalone messaging lessons need only RabbitMQ.
'''),
md('''
## 2. Check which interpreter this notebook uses

**Predict:** the executable path contains `.venv`, and every package below has a version.
If any import/package is missing, select the course kernel before continuing.
'''),
code('''
from pathlib import Path
import sys
import importlib.metadata

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "course" / "rabbit.py").exists())
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
print("Python:", sys.version.split()[0])
print("Executable:", sys.executable)
print("Course directory:", ROOT)
assert (3, 12) <= sys.version_info[:2] <= (3, 13), "Use Python 3.12 or 3.13 for the supplied locks."
for package in ["pika", "Django", "celery", "aio-pika", "jupyterlab"]:
    print(package, importlib.metadata.version(package))
'''),
md('''
## 3. Identify the services

| Service | Address from your notebook | Purpose |
| --- | --- | --- |
| RabbitMQ AMQP | `localhost:5672` | Send and receive messages |
| RabbitMQ Management | `http://localhost:15672` | Inspect queues and metrics |
| Django (later lessons) | `http://localhost:8000` | Create and inspect orders |
| PostgreSQL | Internal Compose network | Store Django business data |

The container hostname `rabbitmq` is used by the Django and worker containers. Your host-side
notebook uses `localhost`. The virtual host `learning` is a logical namespace within RabbitMQ.
Local teaching credentials are `student` / `student-local-only`.

The next cell checks TCP ports; a reachable port alone does not prove AMQP authentication works.
Django can be unavailable here if you started only the broker.
'''),
code('''
import shutil
import socket

print("Docker CLI:", shutil.which("docker") or "Not found: install Docker Desktop and reopen your terminal")
for port, service in [(5672, "AMQP"), (15672, "Management"), (8000, "Django, needed later")]:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            print(f"{service}: reachable on {port}")
    except OSError:
        print(f"{service}: unavailable on {port}")
'''),
md('''
## 4. Learn the message path

```text
Producer ── publish(exchange, routing key, body) ──> Exchange
                                                      │ binding rule
                                                      ▼
                                                    Queue
                                                      │ delivery
                                                      ▼
                                                   Consumer
                                                      │ acknowledgement
                                                      └─────> RabbitMQ
```

- **Producer:** application sending work or events.
- **Exchange:** routes each publication to zero or more queues using bindings.
- **Queue:** holds messages for consumers; a queue is not a Python list in your program.
- **Consumer:** receives messages and performs application work.
- **Acknowledgement:** consumer tells RabbitMQ that a delivery has been handled.
- **Publisher confirm:** broker tells a publisher it accepted responsibility for a publication.

A confirm does not prove a consumer finished. RabbitMQ delivers message bodies as bytes; JSON is
an application serialization choice. Two consumers on one queue share deliveries; two queues
bound to an exchange can each get a copy. We will demonstrate both behaviors.
'''),
md('''
## 5. Build a message before sending anything

An event ID identifies the logical event even if it is delivered again. A schema version lets a
consumer distinguish payload formats. The timestamp describes when the event was created.
**Predict:** serializing then parsing this JSON preserves all the values.
'''),
code('''
import json
import uuid
from datetime import datetime, timezone

event = {
    "schema_version": 1,
    "event_id": str(uuid.uuid4()),
    "event_type": "order.created",
    "occurred_at": datetime.now(timezone.utc).isoformat(),
    "data": {"order_id": 101, "product": "Learning RabbitMQ", "quantity": 2},
}
wire_body = json.dumps(event).encode("utf-8")
assert isinstance(wire_body, bytes)
assert json.loads(wire_body) == event
print(json.dumps(event, indent=2))
print("Wire bytes:", len(wire_body))
'''),
md('''
## 6. Authenticate and declare a temporary queue

`course/rabbit.py` loads connection settings from `.env` and bounds connection waits. It does
not hide publishing or acknowledging; those Pika operations remain visible in the lessons.
This first check creates an **exclusive** queue with a broker-generated name. It is removed
when this connection closes. It publishes no message.

**Expected:** a queue name appears and its initial message count is zero. Connection refusal
means the service is not ready; access refusal means credentials or vhost permissions need checking.
'''),
code('''
from course.rabbit import connect

try:
    with connect() as connection:
        channel = connection.channel()
        declared = channel.queue_declare(queue="", exclusive=True)
        assert declared.method.message_count == 0
        print("Authenticated. Temporary queue:", declared.method.queue)
except Exception as error:
    raise RuntimeError(
        "RabbitMQ connection check failed. Start Docker Desktop, run "
        "'docker compose up -d --wait rabbitmq', and check .env credentials/vhost. "
        f"Underlying exception: {type(error).__name__}"
    ) from error
print("Connection closed; temporary queue removed.")
'''),
md('''
## 7. Inspect Management without exposing connection secrets

Open http://localhost:15672 and sign in. Select the `learning` virtual host. The HTTP API below
checks the same broker and reports its version. Management statistics are sampled and may lag.
Do not infer successful business processing from a dashboard count alone.
'''),
code('''
import os
import requests

management_url = os.getenv("RABBITMQ_MANAGEMENT_URL", "http://localhost:15672").rstrip("/")
session = requests.Session()
session.auth = (os.getenv("RABBITMQ_USER", "student"), os.getenv("RABBITMQ_PASSWORD", "student-local-only"))
try:
    response = session.get(f"{management_url}/api/overview", timeout=5)
    response.raise_for_status()
    overview = response.json()
    print("RabbitMQ version:", overview["rabbitmq_version"])
    response = session.get(f"{management_url}/api/vhosts", timeout=5)
    response.raise_for_status()
    print("Visible virtual hosts:", [item["name"] for item in response.json()])
finally:
    session.close()
'''),
md('''
## 8. Exercise: predict where work waits

For each scenario, make a prediction before reading the suggested answer.

1. A producer publishes to an existing queue while no consumer runs. Where is the work?
2. Two consumers listen to one queue. Does each get every message?
3. Two queues are bound to a fanout exchange. How many copies can one publication create?
4. A consumer changes the database, then crashes before acknowledging. Can the event arrive again?

<details><summary>Suggested answers</summary>

1. It can wait in the queue, subject to policies such as expiry and size limits.
2. Deliveries are distributed among consumers; redelivery can later reach another consumer.
3. One routed copy in each bound queue, so two here.
4. Yes. Use an idempotent business operation; acknowledging before the change would introduce a loss window.

</details>
'''),
md('''
## Troubleshooting and completion check

- If the environment check cannot find the repository, launch Jupyter from this repository or `notebooks/`.
- If `.env` changes after imports, restart the kernel; imported settings may still be cached.
- AMQP uses 5672, not the Management HTTP port 15672.
- Container defaults initialize users/vhosts on a fresh volume; changing them does not rewrite an existing volume.
- Keep Docker running while practicing. `docker compose stop` stops services and preserves data.

You are ready when authentication and Management checks pass and you can name each step of the
message path. Continue with **01 · Messaging basics**.

References: [RabbitMQ Python tutorials](https://www.rabbitmq.com/tutorials),
[acknowledgements and confirms](https://www.rabbitmq.com/docs/confirms),
[Management plugin](https://www.rabbitmq.com/docs/management).
'''),
])


write("18_capstone_order_pipeline.ipynb", [
md('''
# 18 · Capstone: a recoverable order-processing pipeline

**Level:** expert practice · **Time:** 60–90 minutes

**You will:** create orders and outbox intent atomically, fail a publisher, recover the backlog,
observe confirmed-but-unprocessed work, replay duplicates, and prove a single database effect.

Prerequisites: lessons 07–10 and 12–15. Run `docker compose up -d --build --wait` from the repository.
Keep any manually started `consume_events` process stopped so the observation points stay visible.
This notebook uses new order IDs on each run and leaves completed records for inspection.
'''),
md('''
## 1. Define success and the failure model

```text
HTTP request → [DB transaction: Order + Outbox]
                                      │ later, dispatcher
                                      ▼
                    confirmed publish → RabbitMQ orders queue
                                      │ delivery
                                      ▼
                       [DB transaction: dedupe + fulfill]
                                      │ after DB commit
                                      ▼
                                acknowledgement
```

Success means every order ends with `status=completed` and `fulfillments=1`, even when its event
is delivered more than once. We promise no exactly-once transport. The application side effect is
a database update; an external payment or email would require another idempotency design.

Every network request and subprocess below has a timeout. The injected failure affects one
dispatcher process, so the rest of your services remain available.
'''),
code('''
from pathlib import Path
import sys, os, json, time, subprocess
import requests
import pika
from dotenv import load_dotenv

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "course" / "rabbit.py").exists())
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")
from course.rabbit import connect
API = os.getenv("DJANGO_BASE_URL", "http://localhost:8000").rstrip("/")

def manage(*args, broker_override=None, check=True):
    command = ["docker", "compose", "exec", "-T"]
    if broker_override:
        command.extend(["-e", f"BROKER_URL={broker_override}"])
    command.extend(["web", "python", "manage.py", *map(str, args)])
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=90)
    if check and result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    return result

def get_order(order_id):
    response = requests.get(f"{API}/api/orders/{order_id}/", timeout=5)
    response.raise_for_status()
    return response.json()

response = requests.get(f"{API}/health/", timeout=5)
response.raise_for_status()
print(response.json())
'''),
md('''
## 2. Commit three orders without contacting RabbitMQ

The `outbox` HTTP route writes both the order and event in one database transaction. There is
no running background outbox dispatcher in this course; we invoke it explicitly.
**Predict:** all three orders have one unpublished event and zero fulfillments.
'''),
code('''
orders = []
for product, quantity in [("Python workbook", 1), ("Django workbook", 2), ("Messaging workbook", 3)]:
    response = requests.post(f"{API}/api/orders/", json={
        "product": product, "quantity": quantity, "mode": "outbox"
    }, timeout=10)
    response.raise_for_status()
    orders.append(response.json())
assert all(item["outbox_pending"] == 1 and item["fulfillments"] == 0 for item in orders)
print(json.dumps(orders, indent=2))
'''),
md('''
## 3. Record evidence at every boundary

The HTTP status of the business object is our evidence. Queue counts can help diagnose a problem,
but neither a confirm nor an empty queue alone proves that the correct database change committed.
This helper prints a compact snapshot and keeps it for comparison at the end.
'''),
code('''
observations = []

def snapshot(stage):
    current = [get_order(item["id"]) for item in orders]
    evidence = {"stage": stage, "pending_outbox": sum(item["outbox_pending"] for item in current),
                "completed_orders": sum(item["status"] == "completed" for item in current),
                "fulfillments": [item["fulfillments"] for item in current]}
    observations.append(evidence)
    print(evidence)
    return current

snapshot("Database committed")
'''),
md('''
## 4. Inject a connection failure

For one dispatcher invocation, use an unavailable local port inside the container. Its publish
fails before broker acceptance. **Predict:** none of these outbox rows is marked sent. This tests
one failure boundary; the later duplicate drill covers the outcome of an ambiguous successful send.
'''),
code('''
failure = manage("dispatch_outbox", "--once", "--limit", 100,
                 broker_override="amqp://student:student-local-only@127.0.0.1:1/learning", check=False)
assert failure.returncode != 0, "Expected the injected connection failure"
print("Expected failure:", (failure.stderr or failure.stdout).strip().splitlines()[-1])
pending = snapshot("Publisher unavailable")
assert all(item["outbox_pending"] == 1 and item["status"] == "pending" for item in pending)
'''),
md('''
## 5. Recover publication, then pause before processing

Use the normal broker configuration. The dispatcher publishes with confirms and `mandatory=True`
before marking a row sent. Open Management and inspect `rmqcourse.orders.process` now.
**Predict:** the outbox count becomes zero while order status remains pending.

The finite batch limit is 100. If you intentionally accumulated a larger backlog, dispatch additional
batches before asserting on these newer order IDs. No separate consumer should be running.
'''),
code('''
print(manage("dispatch_outbox", "--once", "--limit", 100).stdout)
published = snapshot("Broker accepted")
assert all(item["outbox_pending"] == 0 and item["status"] == "pending" for item in published)
'''),
md('''
## 6. Apply the business effect and acknowledge

The consumer validates each event, locks its order, records the event ID and updates the order in
one database transaction. It acknowledges only after that function succeeds.
**Predict:** all three orders become completed, each with exactly one fulfillment.
'''),
code('''
print(manage("consume_events", "--max-messages", 100, "--timeout", 5).stdout)
completed = snapshot("Consumer committed and acknowledged")
assert all(item["status"] == "completed" and item["fulfillments"] == 1 for item in completed)
'''),
md('''
## 7. Reproduce the duplicate-delivery outcome

A dispatcher can die after RabbitMQ accepts a message but before it marks the outbox row sent.
A consumer can die after the database commit but before acknowledging. Both can lead to the same
logical event arriving again. Inject that outcome explicitly by publishing each original event twice.
This is deterministic duplicate injection, not a claim that we timed an actual crash.

**Predict:** six duplicate deliveries produce zero additional fulfillments. The broker does not
deduplicate `message_id` for us; the application uses its unique `ProcessedEvent` record.
'''),
code('''
with connect() as connection:
    channel = connection.channel()
    channel.confirm_delivery()
    for order in orders:
        event = {"schema_version": 1, "event_id": order["event_id"], "order_id": order["id"],
                 "product": order["product"], "quantity": order["quantity"]}
        for _ in range(2):
            channel.basic_publish(exchange="rmqcourse.orders", routing_key="order.created",
                body=json.dumps(event).encode("utf-8"), mandatory=True,
                properties=pika.BasicProperties(content_type="application/json", delivery_mode=2,
                    message_id=event["event_id"], type="order.created.v1"))
print(manage("consume_events", "--max-messages", 100, "--timeout", 5).stdout)
after_replay = snapshot("Six duplicate deliveries processed")
assert all(item["fulfillments"] == 1 for item in after_replay)
'''),
md('''
## 8. Read the evidence as a timeline

Compare publication intent, broker acceptance and business completion. Explain why each transition
needs its own mechanism. These are observations from your run, not pre-filled sample results.
'''),
code('''
for item in observations:
    print(f"{item['stage']:<40} outbox={item['pending_outbox']} "
          f"completed={item['completed_orders']} effects={item['fulfillments']}")
assert observations[0]["pending_outbox"] == 3
assert observations[-1]["completed_orders"] == 3
assert observations[-1]["fulfillments"] == [1, 1, 1]
print("Capstone passed: recovered publication and duplicate-safe database effects.")
'''),
md('''
## 9. Exercise: reason about the unsolved boundaries

Before looking at the suggested answers, describe what happens in each case:

| Failure point | What must recover? |
| --- | --- |
| Process dies before the order/outbox transaction commits | ? |
| Order/outbox commit, dispatcher never runs | ? |
| Broker accepts, dispatcher loses connection before seeing the confirm | ? |
| Consumer database update fails | ? |
| Same HTTP POST is submitted twice by a user | ? |

<details><summary>Suggested answers</summary>

1. The uncommitted transaction rolls back; no order or event should remain.
2. Outbox rows remain pending. A supervised dispatcher and backlog-age alert are needed.
3. The publish outcome is ambiguous. Retry with the same event ID; deduplicate downstream.
4. The deduplication record and business effect must roll back together. Retry policy must be bounded.
5. This demo creates two different orders. Add a request idempotency key with a database uniqueness
   constraint if the product must treat repeated HTTP requests as one logical order.

</details>

**Extension:** add a separate audit subscriber using notebook 03/05's routing patterns. Give each
subscriber its own queue and deduplication scope. A global dedupe record shared across unrelated
subscribers could incorrectly suppress one subscriber's work.
'''),
md('''
## 10. Explain the design before calling it complete

Give a five-minute walkthrough of this pipeline. Point to the code for validation, atomic storage,
publish confirms, mandatory routing, row locking, duplicate detection and acknowledgement.
Then name its limits: local teaching credentials, unauthenticated API, finite manually invoked
dispatcher/consumer, no external side-effect guarantee, and a single broker unless you ran lab 17.

Use `PRODUCTION_PRACTICE.md` for the next exercises: TLS and permissions, backpressure,
dead-letter safety, observability, replication, backup and recovery.

**Cleanup:** all temporary connections are closed. Completed orders and outbox rows are retained
as evidence; the shared topology is not deleted. Use `docker compose stop` to pause the course.
Use the reset instructions in README only if you want to discard all course data.

References: [Django transactions](https://docs.djangoproject.com/en/5.2/topics/db/transactions/),
[RabbitMQ confirms](https://www.rabbitmq.com/docs/confirms),
[RabbitMQ reliability](https://www.rabbitmq.com/docs/reliability).
'''),
])

if __name__ == "__main__":
    print("Built setup and capstone notebooks")

"""Generate the intermediate/expert course notebooks using only the stdlib."""
from pathlib import Path
import json
import textwrap

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "notebooks"
OUT.mkdir(exist_ok=True)


def md(source):
    return {"cell_type": "markdown", "metadata": {}, "source": textwrap.dedent(source).strip() + "\n"}


def code(source):
    return {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [],
            "source": textwrap.dedent(source).strip() + "\n"}


BOOT = code('''
from pathlib import Path
import sys
ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "course" / "rabbit.py").is_file())
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from course.rabbit import connect, unique_name, wait_for_message, broker_url
import pika
print("Course root:", ROOT)
''')


def write(name, cells):
    for index, cell in enumerate(cells):
        cell["id"] = f"cell-{index:03d}"
    notebook = {"cells": cells, "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3.12"},
    }, "nbformat": 4, "nbformat_minor": 5}
    path = OUT / name
    path.write_text(json.dumps(notebook, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(path.name, len(cells), "cells")


write("07_durability_and_confirms.ipynb", [
md('''
# 07 · Durability, publisher confirms, and unroutable messages

**Level:** intermediate · **Time:** 35 minutes · **Before you start:** complete setup 00 and understand acknowledgements from 02.

By the end you can distinguish queue durability, message persistence, publisher confirms, mandatory routing, and consumer acknowledgements. You will deliberately publish an unroutable message and catch it.

| Mechanism | What it addresses |
|---|---|
| Durable queue | Queue definition survives a broker restart |
| Persistent message (`delivery_mode=2`) | Request storage of the message when routed to a suitable durable queue |
| Publisher confirm | Broker accepts responsibility for a publication; does not mean the consumer finished |
| `mandatory=True` | Report when a publication cannot route to any queue |
| Consumer acknowledgement | Consumer tells the broker it finished processing |

**Prediction:** does a durable queue alone make transient messages durable? No. A confirm alone also does not prove that any queue matched: add mandatory routing when that matters.

Run cells in order. Only the explicitly marked terminal restart is optional.
'''), BOOT,
md('''
## Step 1 — Declare durable storage and confirm a persistent publication

The default exchange routes by queue name. We give the queue a unique name so another lesson cannot consume its message. The `with` block closes the connection; closing a connection does not remove this durable, non-exclusive queue.
'''),
code('''
queue_name = unique_name("durable")
payload = b"invoice-1001: created"
with connect() as connection:
    channel = connection.channel()
    channel.queue_declare(queue=queue_name, durable=True)
    channel.confirm_delivery()
    channel.basic_publish(
        exchange="", routing_key=queue_name, body=payload,
        properties=pika.BasicProperties(delivery_mode=2, content_type="text/plain"),
        mandatory=True,
    )
print("Broker confirmed publication to", queue_name)
'''),
md('''
## Optional pause — Test a real broker restart

To demonstrate persistence, **pause before Step 2**, run `docker compose restart rabbitmq` in a terminal at the course root, and wait for `docker compose ps` to show RabbitMQ healthy. Keep the Docker volume; do not run `down -v`.

Without this manual step, the next assertion proves survival across a client disconnect only. A single broker and disk are still a single failure domain. Quorum replication is covered in 17.
'''),
md('''
## Step 2 — Reconnect, read, and acknowledge

Expected: the body is unchanged and its persistence property is `2`. Acknowledge only after checking the result.
'''),
code('''
with connect() as connection:
    channel = connection.channel()
    method, properties, body = wait_for_message(channel, queue_name)
    assert body == payload
    assert properties.delivery_mode == 2
    channel.basic_ack(method.delivery_tag)
print("Received and acknowledged:", body.decode())
'''),
md('''
## Step 3 — Fail visibly when no queue matches

We intentionally publish to a queue name that was never declared. In Pika's blocking confirm mode, an unroutable mandatory publication raises `UnroutableError`. Treat a connection failure during publishing differently: the outcome can be unknown, so a retry may duplicate the message.
'''),
code('''
with connect() as connection:
    channel = connection.channel()
    channel.confirm_delivery()
    try:
        channel.basic_publish(exchange="", routing_key=unique_name("missing"),
                              body=b"must not vanish silently", mandatory=True)
    except pika.exceptions.UnroutableError:
        print("Expected: RabbitMQ returned the unroutable message.")
    else:
        raise AssertionError("Expected an unroutable message error")
'''),
md('''
## Step 4 — Observe an incompatible declaration

An existing durable queue cannot be redeclared as non-durable. The broker closes the **channel**, so isolate the deliberate error on its own channel and connection. Expected AMQP reply code: `406 PRECONDITION_FAILED`.
'''),
code('''
with connect() as connection:
    channel = connection.channel()
    try:
        channel.queue_declare(queue=queue_name, durable=False)
    except pika.exceptions.ChannelClosedByBroker as error:
        assert error.reply_code == 406
        print("Expected declaration mismatch:", error.reply_code)
    else:
        raise AssertionError("Incompatible declaration unexpectedly succeeded")
'''),
md('''
## Exercise — Explain the two failure windows

1. The broker stores a message, but the connection dies before the publisher sees its confirm. Should the publisher retry?
2. The consumer commits a database change, then dies before acknowledging. What happens on redelivery?

**Suggested answer:** retry when delivery is required, keeping the same event ID, and make the consumer idempotent. Both windows can produce duplicates. Publisher confirms and acknowledgements do not provide end-to-end exactly-once execution. Notebook 09 makes the database side effect safe to repeat.

**Troubleshooting:** a `406` in normal code usually means mismatched queue/exchange arguments. Use a new lesson queue name or reconcile its definition. A confirm timeout is an uncertain outcome, not evidence that the broker discarded the message.
'''),
md("## Cleanup — Delete only this notebook's queue"),
code('''
with connect() as connection:
    connection.channel().queue_delete(queue=queue_name)
print("Deleted", queue_name)
'''),
md('''
## References and next step

- [RabbitMQ acknowledgements and confirms](https://www.rabbitmq.com/docs/4.2/confirms)
- [RabbitMQ queue durability](https://www.rabbitmq.com/docs/4.2/queues#durability)
- [Pika delivery confirmation example](https://pika.readthedocs.io/en/stable/examples/blocking_delivery_confirmations.html)

Next: give failed messages a bounded retry path in 08.
''')])


write("08_dead_letters_ttl_retries.ipynb", [
md('''
# 08 · Dead letters, TTL, and bounded delayed retries

**Level:** intermediate · **Time:** 40 minutes · **Prerequisites:** 00, 02, and 07.

Build a work queue, a 500 ms retry queue, and a parking queue. A flaky job succeeds on its third attempt; a poison job is parked after three attempts.

```text
work --confirmed republish + ack--> retry (TTL 500 ms)
  ^                                  |
  +-------- dead-letter on expiry ----+
  |
  +-- reject(requeue=False) ----------> parking
```

A DLX is an ordinary exchange used when a message is dead-lettered. This lesson uses the default exchange (`""`) with queue-name routing keys. TTL is an expiry mechanism, not a precise scheduling guarantee. Do not create a rapid `nack(requeue=True)` loop.
'''), BOOT,
md('''
## Step 1 — Declare the three queues

Each queue is durable. The retry queue has no consumer: its messages wait until expiry and are routed back to work. The work queue dead-letters final failures to parking. Here arguments keep the example self-contained; operational policies are easier to update in deployed systems.
'''),
code('''
import json
import time

work_queue = unique_name("retry.work")
retry_queue = unique_name("retry.delay")
parking_queue = unique_name("retry.parking")
with connect() as connection:
    channel = connection.channel()
    channel.queue_declare(queue=parking_queue, durable=True)
    channel.queue_declare(queue=work_queue, durable=True, arguments={
        "x-dead-letter-exchange": "", "x-dead-letter-routing-key": parking_queue,
    })
    channel.queue_declare(queue=retry_queue, durable=True, arguments={
        "x-message-ttl": 500,
        "x-dead-letter-exchange": "", "x-dead-letter-routing-key": work_queue,
    })
print("Topology ready:", work_queue, retry_queue, parking_queue, sep="\\n")
'''),
md('''
## Step 2 — Publish two jobs with stable IDs

An application-owned `attempt` header is explicit and independent of broker redelivery flags. Retrying must preserve the job's identity. `x-death` will later show broker-generated history for the current publication, not an application-wide retry counter.
'''),
code('''
with connect() as connection:
    channel = connection.channel()
    channel.confirm_delivery()
    for job_id in ("flaky", "poison"):
        channel.basic_publish(
            exchange="", routing_key=work_queue,
            body=json.dumps({"job_id": job_id}).encode(), mandatory=True,
            properties=pika.BasicProperties(
                delivery_mode=2, content_type="application/json",
                message_id=job_id, headers={"attempt": 1},
            ),
        )
print("Published flaky and poison")
'''),
md('''
## Step 3 — Process with a maximum of three attempts

Predict six deliveries: `flaky` three times and `poison` three times. A retry is confirmed **before** acknowledging the original. If publishing raises, the connection closes with the original unacknowledged. Each retry is a new application publication: copy application-owned headers only, and let RabbitMQ maintain its own death headers.

This is still not atomic: a crash between republishing and acknowledging can create duplicates. Use idempotency (09). Also, ordinary/classic-queue dead-lettering can lose a message if its destination is unavailable. For stronger transfer guarantees, configure a source quorum queue with `dead-letter-strategy=at-least-once`, `overflow=reject-publish`, and a DLX; capacity limits and duplicate handling still matter.
'''),
code('''
MAX_ATTEMPTS = 3
attempts = []
completed = []
parked = []
deadline = time.monotonic() + 15
with connect() as connection:
    channel = connection.channel()
    channel.confirm_delivery()
    while len(completed) + len(parked) < 2:
        if time.monotonic() >= deadline:
            raise TimeoutError("Retry workflow did not finish; inspect queue bindings and TTL")
        try:
            method, properties, body = wait_for_message(channel, work_queue, timeout=1)
        except TimeoutError:
            continue
        job = json.loads(body)
        attempt = int(properties.headers["attempt"])
        attempts.append((job["job_id"], attempt))
        succeeds = job["job_id"] == "flaky" and attempt >= 3
        if succeeds:
            completed.append(job["job_id"])
            channel.basic_ack(method.delivery_tag)
            print(job["job_id"], attempt, "SUCCESS")
        elif attempt < MAX_ATTEMPTS:
            # Preserve application state, not broker-owned x-death / x-first-death-* / x-last-death-*.
            headers = {"attempt": attempt + 1}
            channel.basic_publish(
                exchange="", routing_key=retry_queue, body=body, mandatory=True,
                properties=pika.BasicProperties(
                    delivery_mode=2, content_type="application/json",
                    message_id=properties.message_id, headers=headers,
                ),
            )
            channel.basic_ack(method.delivery_tag)
            print(job["job_id"], attempt, "RETRY LATER")
        else:
            channel.basic_reject(method.delivery_tag, requeue=False)
            parked.append(job["job_id"])
            print(job["job_id"], attempt, "PARKED")
assert completed == ["flaky"] and parked == ["poison"]
assert sorted(attempts) == sorted((job, attempt) for job in ("flaky", "poison") for attempt in (1, 2, 3))
'''),
md('''
## Step 4 — Inspect the poison message and its history

Expected: `attempt=3`, a `rejected` death for the work queue, and an `expired` death for the retry queue. Both broker events happen after the final application republish: the retry queue expires that publication, then the work consumer rejects it into parking.

RabbitMQ compresses repeated broker-generated deaths by queue and reason within a publication's broker history. **RabbitMQ 4 does not interpret client-supplied `x-death` as trusted prior history when an AMQP 0.9.1 application republishes.** Do not expect its count to accumulate across all three application attempts. Our republisher deliberately excludes broker-owned death headers; the application-owned `attempt` header enforces the retry budget. See the [RabbitMQ maintainers' explanation](https://github.com/rabbitmq/rabbitmq-server/discussions/15386).

Parking preserves evidence for repair and a controlled replay; endlessly replaying poison messages only repeats the failure.
'''),
code('''
with connect() as connection:
    channel = connection.channel()
    method, properties, body = wait_for_message(channel, parking_queue)
    history = properties.headers.get("x-death", [])
    assert json.loads(body)["job_id"] == "poison"
    assert properties.headers["attempt"] == 3
    assert any(entry["reason"] == "rejected" for entry in history)
    assert any(entry["reason"] == "expired" for entry in history)
    print("Parked body:", body.decode())
    print("Dead-letter history:", history)
    channel.basic_ack(method.delivery_tag)
'''),
md('''
## Exercise — Add backoff and classify failures

Design separate delay queues for 1 s, 5 s, and 30 s retries. Which failures should skip retries? What happens if the parking queue cannot accept a message?

**Suggested solution:** choose a delay queue by attempt number; keep one TTL per delay queue to make behavior easier to predict. Reject invalid schemas and impossible business operations directly to parking. Use a finite retry budget, idempotency, monitored parking queues, and an appropriate quorum dead-letter strategy where loss is unacceptable. Different per-message TTLs can wait behind other messages before they are dead-lettered; avoid treating a shared queue as an exact timer.

**Troubleshooting:** inspect the default-exchange routing key, which must exactly equal the destination queue name. A queue argument mismatch requires a new name or coordinated replacement. `x-death` absence before the first dead-letter event is normal.
'''),
md("## Cleanup"),
code('''
with connect() as connection:
    channel = connection.channel()
    for name in (work_queue, retry_queue, parking_queue):
        channel.queue_delete(queue=name)
print("Deleted this lesson's three queues")
'''),
md('''
## References

- [Dead-letter exchanges and safety](https://www.rabbitmq.com/docs/4.2/dlx)
- [TTL behavior](https://www.rabbitmq.com/docs/4.2/ttl)
- [Quorum dead-letter guarantees](https://www.rabbitmq.com/docs/4.2/quorum-queues#dead-lettering)
''')])


write("09_idempotent_consumers.ipynb", [
md('''
# 09 · Idempotent consumers and the commit-before-ack crash

**Level:** advanced · **Time:** 40 minutes · **Prerequisites:** 00, 02, and 07.

Apply a payment-like credit to a local SQLite account, then simulate a crash after committing but before acknowledging. A stable event ID and a database uniqueness constraint stop the repeated delivery from repeating the database side effect.

The deduplication record and the balance change must commit in **the same transaction**. Acknowledgement happens after that commit. This gives one applied database effect per retained event ID in this database; it does not make RabbitMQ or arbitrary external calls exactly-once.

The amounts below are integer demo units, not a financial system.
'''), BOOT,
md('''
## Step 1 — Create an isolated database

The temporary directory belongs only to this run. `processed_events.event_id` is a primary key, making duplicate detection a database operation rather than a race-prone read-then-write check.
'''),
code('''
import json
import sqlite3
import tempfile

temporary_directory = tempfile.TemporaryDirectory(prefix="rmqcourse-idempotency-")
database_path = Path(temporary_directory.name) / "consumer.sqlite3"
database = sqlite3.connect(database_path)
database.executescript("""
CREATE TABLE account (id INTEGER PRIMARY KEY, balance INTEGER NOT NULL);
INSERT INTO account VALUES (1, 0);
CREATE TABLE processed_events (event_id TEXT PRIMARY KEY);
""")
database.commit()

def apply_once(event, fail_before_commit=False):
    with database:
        inserted = database.execute(
            "INSERT OR IGNORE INTO processed_events(event_id) VALUES (?)", (event["event_id"],)
        ).rowcount
        if not inserted:
            return False
        database.execute("UPDATE account SET balance = balance + ? WHERE id=1", (event["amount"],))
        if fail_before_commit:
            raise RuntimeError("Simulated failure before database commit")
    return True

def balance():
    return database.execute("SELECT balance FROM account WHERE id=1").fetchone()[0]

assert balance() == 0
'''),
md('''
## Step 2 — Commit once, then close without acknowledging

Expected balance: 75. Closing the connection with an unacknowledged delivery simulates the delivery consequence of a worker crash. It is deliberate for this demonstration; real code acknowledges after the transaction succeeds.
'''),
code('''
queue_name = unique_name("idempotency")
first_event = {"event_id": unique_name("event"), "amount": 75}
with connect() as connection:
    channel = connection.channel()
    channel.queue_declare(queue=queue_name, durable=True)
    channel.confirm_delivery()
    channel.basic_publish(exchange="", routing_key=queue_name,
                          body=json.dumps(first_event).encode(), mandatory=True,
                          properties=pika.BasicProperties(delivery_mode=2, message_id=first_event["event_id"]))
    method, properties, body = wait_for_message(channel, queue_name)
    assert apply_once(json.loads(body)) is True
    print("Committed balance:", balance(), "— deliberately leaving the delivery unacknowledged")
assert balance() == 75
'''),
md('''
## Step 3 — Receive the duplicate, skip its effect, then acknowledge

Predict that `redelivered` is true, `apply_once` returns false, and the balance stays 75. The same event ID can also arrive in a newly published message whose redelivery flag is false; always deduplicate by application identity, not by that flag alone.
'''),
code('''
with connect() as connection:
    channel = connection.channel()
    method, properties, body = wait_for_message(channel, queue_name)
    assert method.redelivered
    applied = apply_once(json.loads(body))
    assert applied is False
    channel.basic_ack(method.delivery_tag)
    print("Redelivered:", method.redelivered, "Applied again:", applied, "Balance:", balance())
assert balance() == 75
'''),
md('''
## Step 4 — Prove rollback covers both writes

A second event fails before commit. Its balance update and event record must both roll back. We requeue exactly once for this controlled experiment, then process successfully. A deployed worker should use bounded delayed retries such as 08.
'''),
code('''
second_event = {"event_id": unique_name("event"), "amount": 25}
with connect() as connection:
    channel = connection.channel()
    channel.confirm_delivery()
    channel.basic_publish(exchange="", routing_key=queue_name,
                          body=json.dumps(second_event).encode(), mandatory=True,
                          properties=pika.BasicProperties(delivery_mode=2, message_id=second_event["event_id"]))
    method, properties, body = wait_for_message(channel, queue_name)
    try:
        apply_once(json.loads(body), fail_before_commit=True)
    except RuntimeError as error:
        print(error)
        channel.basic_nack(method.delivery_tag, requeue=True)
    else:
        raise AssertionError("Expected injected failure")
    assert balance() == 75
    assert database.execute("SELECT COUNT(*) FROM processed_events WHERE event_id=?", (second_event["event_id"],)).fetchone()[0] == 0
    method, properties, body = wait_for_message(channel, queue_name)
    assert apply_once(json.loads(body)) is True
    channel.basic_ack(method.delivery_tag)
assert balance() == 100
print("Final balance:", balance())
'''),
md('''
## Exercise — Where does this guarantee stop?

Try calling `apply_once(first_event)` three more times. Then explain why inserting the event ID into a database cannot atomically protect a separate HTTP payment request.

**Suggested solution:** all three calls return false and the balance remains 100. For an external service, use its idempotency-key API when available, or persist an outgoing intent and reconcile outcomes. Retain deduplication IDs for at least the maximum replay window. Reusing an ID for a different payload is an application error; deployed systems should detect that, for example by storing a payload hash.

**Troubleshooting:** acknowledgement before commit allows lost effects; recording the ID in a separate transaction can suppress unfinished work. A SQLite file is convenient for a one-process lab; the Django examples use a database transaction and a unique constraint with multiple processes in mind.
'''),
code('''
assert [apply_once(first_event) for _ in range(3)] == [False, False, False]
assert balance() == 100
print("Repeated delivery does not repeat the stored effect")
'''),
md("## Cleanup — Remove only this run's queue and temporary database"),
code('''
with connect() as connection:
    connection.channel().queue_delete(queue=queue_name)
database.close()
temporary_directory.cleanup()
print("Cleaned up")
'''),
md('''
## References

- [RabbitMQ reliability and redeliveries](https://www.rabbitmq.com/docs/4.2/reliability)
- [Python SQLite transaction control](https://docs.python.org/3/library/sqlite3.html#transaction-control)
''')])


write("10_prefetch_and_concurrency.ipynb", [
md('''
# 10 · Prefetch, push consumers, and competing workers

**Level:** advanced · **Time:** 35 minutes · **Prerequisites:** 00 and 02.

Observe how prefetch limits unacknowledged push deliveries, then run two real workers with different speeds. Each worker owns its connection and channel. Pika connections are not shared between threads.

**Prediction:** with eight queued messages and no acknowledgements, prefetch 1 permits one delivery; prefetch 4 permits four. `basic_get` is a polling API and does not demonstrate prefetch, so this notebook uses `basic_consume` callbacks.
'''), BOOT,
md('''
## Step 1 — Measure the unacknowledged delivery window

The callback deliberately records deliveries without acknowledging. We pump the connection for up to two seconds, then cancel and clean up. The messages are disposable numbers created by this experiment.
'''),
code('''
import time

def observe_window(prefetch):
    queue_name = unique_name(f"prefetch{prefetch}")
    delivered = []
    with connect() as connection:
        channel = connection.channel()
        channel.queue_declare(queue=queue_name)
        for number in range(8):
            channel.basic_publish(exchange="", routing_key=queue_name, body=str(number).encode())
        channel.basic_qos(prefetch_count=prefetch)
        tag = channel.basic_consume(
            queue=queue_name, auto_ack=False,
            on_message_callback=lambda ch, method, properties, body: delivered.append((method.delivery_tag, body)),
        )
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            connection.process_data_events(time_limit=0.1)
        count = len(delivered)
        assert count == prefetch, (prefetch, count)
        channel.basic_cancel(tag)
        for delivery_tag, body in delivered:
            channel.basic_ack(delivery_tag)
        channel.queue_delete(queue=queue_name)
    return {"prefetch": prefetch, "delivered_without_ack": count}

for value in (1, 4):
    print(observe_window(value))
'''),
md('''
## Step 2 — Start two workers before publishing

The next cell owns all worker threads and stops within a deadline. A ready signal ensures both consumers are registered before messages are published. The slow worker waits 80 ms per task; the fast worker waits 20 ms. Prefetch 1 prevents either from reserving many tasks at once.

Expected: every job completes once in this failure-free run. The faster worker often does more work, but exact distribution and timing depend on scheduling, so they are observations rather than correctness assertions. The brief sleeps model work; long blocking work requires careful heartbeat handling or a different execution design.
'''),
code('''
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
import threading

queue_name = unique_name("competing")
job_count = 12
completed = []
lock = threading.Lock()
finished = threading.Event()
ready = {"slow": threading.Event(), "fast": threading.Event()}
with connect() as connection:
    connection.channel().queue_declare(queue=queue_name)

def worker(worker_name, delay):
    with connect() as connection:
        channel = connection.channel()
        channel.basic_qos(prefetch_count=1)
        def handle(ch, method, properties, body):
            time.sleep(delay)
            ch.basic_ack(method.delivery_tag)
            with lock:
                completed.append((worker_name, int(body)))
                if len(completed) == job_count:
                    finished.set()
        tag = channel.basic_consume(queue=queue_name, on_message_callback=handle, auto_ack=False)
        ready[worker_name].set()
        deadline = time.monotonic() + 12
        while not finished.is_set() and time.monotonic() < deadline:
            connection.process_data_events(time_limit=0.1)
        channel.basic_cancel(tag)
        if not finished.is_set():
            raise TimeoutError(f"Worker {worker_name} reached its deadline")

try:
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker, "slow", 0.08), pool.submit(worker, "fast", 0.02)]
        if not all(signal.wait(timeout=5) for signal in ready.values()):
            finished.set()
            raise TimeoutError("Workers did not register in time")
        with connect() as connection:
            channel = connection.channel()
            channel.confirm_delivery()
            for number in range(job_count):
                channel.basic_publish(exchange="", routing_key=queue_name, body=str(number).encode(), mandatory=True)
        for future in futures:
            future.result(timeout=15)
    assert sorted(number for _, number in completed) == list(range(job_count))
    print("Completed jobs per worker:", dict(Counter(name for name, _ in completed)))
    print("Completion order:", completed)
finally:
    finished.set()
    with connect() as connection:
        connection.channel().queue_delete(queue=queue_name)
'''),
md('''
## Exercise — Tune and explain

Change the worker prefetch to 6, run Step 2 again, and compare assignment and completion order. Repeat three times. Then make both workers equally fast.

**Suggested interpretation:** larger prefetch can reduce waiting on network round trips, but lets a slow consumer reserve more work. Prefetch does not create worker parallelism. Competing workers also mean completion order can differ from publication order. Choose a value using measured latency, memory, task duration, and throughput; no universal value is best.

**Troubleshooting:** if a worker fails, inspect its future exception. Sharing one Pika connection across these threads is unsupported. `prefetch_count=0` removes the limit; do not use it as a generic performance fix. If interrupted, restart the kernel to stop abandoned threads and remove the named lesson queue in Management.

**Cleanup:** both experiments delete their own queues. No long-running worker remains after successful completion.

## References

- [RabbitMQ consumer prefetch](https://www.rabbitmq.com/docs/4.2/consumer-prefetch)
- [Pika FAQ on threads](https://pika.readthedocs.io/en/stable/faq.html)
''')])


write("11_asyncio_and_recovery.ipynb", [
md('''
# 11 · Async consumers and connection recovery

**Level:** advanced · **Time:** 35 minutes · **Prerequisites:** 00, 07, and 10; basic `async` / `await`.

Use `aio-pika` to overlap waiting work without sharing a Pika blocking connection across threads. Then optionally restart the local broker while a robust connection is active.

Jupyter already has an event loop: use top-level `await`, not `asyncio.run(...)` inside a notebook. A robust connection can restore declared topology and consumers after reconnecting; it does not make an interrupted publish atomic or remove duplicates.
'''), BOOT,
md('''
## Step 1 — Publish and process four jobs asynchronously

We bound connection setup and the whole demo. `message.process()` acknowledges when its block exits normally. Here every task succeeds; a real failure needs the retry/parking policy from 08. Waiting uses `asyncio.sleep` so other tasks can run. CPU-heavy work should use an appropriate process pool or worker system.
'''),
code('''
import asyncio
import aio_pika
import time

async def async_demo():
    connection = await aio_pika.connect_robust(broker_url(), timeout=5, reconnect_interval=1)
    async with connection:
        channel = await connection.channel(publisher_confirms=True)
        await channel.set_qos(prefetch_count=4)
        queue = await channel.declare_queue(unique_name("async"), exclusive=True, auto_delete=True)
        try:
            for number in range(4):
                await channel.default_exchange.publish(
                    aio_pika.Message(body=str(number).encode()), routing_key=queue.name, mandatory=True,
                )
            completed = []
            async def handle(message):
                async with message.process(requeue=False):
                    await asyncio.sleep(0.15)
                    completed.append(int(message.body))
            started = time.perf_counter()
            async with queue.iterator() as iterator:
                # Keep all acknowledgements in this event loop; no thread shares this channel.
                messages = [await asyncio.wait_for(iterator.__anext__(), timeout=5) for _ in range(4)]
                await asyncio.gather(*(handle(message) for message in messages))
            assert sorted(completed) == [0, 1, 2, 3]
            print("Completed:", completed, "elapsed:", round(time.perf_counter() - started, 3), "seconds")
        finally:
            # auto_delete may already remove the queue when its last consumer cancels.
            if not channel.is_closed:
                await channel.close()

await asyncio.wait_for(async_demo(), timeout=20)
'''),
md('''
## Step 2 — Optional live recovery experiment

The default flag is false, so **Run All** does not disrupt services or wait for a human. To demonstrate recovery:

1. Finish other lessons and keep a terminal ready at the course root.
2. Set `RUN_RECOVERY_LAB = True` and run the next cell.
3. When it prints the prompt, run `docker compose restart rabbitmq` in the terminal.
4. The cell allows 45 seconds for a reconnect, then verifies a persistent message remains available. If your machine starts slowly, increase that explicit timeout.

This deliberately affects the shared local lab broker. No restart command is executed by notebook code. The queue is durable so the pre-restart publication has a chance to survive with the preserved volume. Restoration depends on the broker becoming reachable again with compatible topology and permissions.
'''),
code('''
RUN_RECOVERY_LAB = False

async def recovery_demo():
    reconnected = asyncio.Event()
    connection = await aio_pika.connect_robust(broker_url(), timeout=5, reconnect_interval=1)
    async def record_reconnect(sender, **kwargs):
        reconnected.set()
    connection.reconnect_callbacks.add(record_reconnect)
    queue = None
    try:
        channel = await connection.channel(publisher_confirms=True)
        queue = await channel.declare_queue(unique_name("recovery"), durable=True)
        await channel.default_exchange.publish(
            aio_pika.Message(body=b"survive-restart", delivery_mode=aio_pika.DeliveryMode.PERSISTENT),
            routing_key=queue.name, mandatory=True,
        )
        print("Recovery queue:", queue.name, flush=True)
        print("Now run in the terminal: docker compose restart rabbitmq", flush=True)
        await asyncio.wait_for(reconnected.wait(), timeout=45)
        message = await queue.get(timeout=5, fail=True)
        async with message.process():
            assert message.body == b"survive-restart"
        print("Reconnected and received the pre-restart message")
    finally:
        try:
            if queue is not None and connection.connected.is_set():
                await asyncio.wait_for(queue.delete(if_unused=False, if_empty=False), timeout=5)
        finally:
            await connection.close()

if RUN_RECOVERY_LAB:
    await asyncio.wait_for(recovery_demo(), timeout=60)
else:
    print("Recovery drill skipped. Set RUN_RECOVERY_LAB=True to perform it manually.")
'''),
md('''
## Exercise — Reconnection is not replay

What should you do when the network drops during `publish()` and you do not know whether the broker confirmed it? What happens to work that was in progress during disconnection?

**Suggested answer:** retain a stable message ID, retry according to a bounded policy, and tolerate duplicates at the consumer. A robust client restores connectivity, not arbitrary application state. An unacknowledged delivery may return to another consumer; partially completed effects still require idempotency. Decide whether to cancel in-flight work on loss and how to reconcile uncertain outcomes.

**Troubleshooting:** `RuntimeError: asyncio.run() cannot be called...` means the notebook event loop is already running. A recovery timeout can mean the broker never stopped, never recovered, or the vhost/credentials changed. If cleanup cannot reach the broker, delete only the printed `rmqcourse.recovery...` queue after recovery.

**Cleanup:** the normal demo's exclusive queue is removed when the connection closes, even if the demo fails before registering a consumer; it also auto-deletes after its consumer cancels. The optional demo explicitly deletes its durable queue after recovery.

## References

- [aio-pika quick start](https://docs.aio-pika.com/quick-start.html)
- [aio-pika robust connection options](https://docs.aio-pika.com/url-parameters.html)
- [RabbitMQ reliability](https://www.rabbitmq.com/docs/4.2/reliability)
''')])


write("16_monitoring_and_performance.ipynb", [
md('''
# 16 · Monitoring, overload, and measurement

**Level:** advanced · **Time:** 45 minutes · **Prerequisites:** 00, 07, and 10.

Inspect the Management HTTP API, create a visible ready/unacknowledged state, reject excess publications with a queue limit, and measure a small publishing experiment.

The UI and management statistics are sampled and may lag. Correctness assertions below rely on message bodies and protocol responses, not exact dashboard counts. Results are a local teaching experiment, not a production capacity estimate.
'''), BOOT,
md('''
## Step 1 — Read the management API

The course's local account can inspect its vhost. Authentication is derived from the broker URL without printing the password. HTTP and AMQP are different endpoints: default local ports are 15672 and 5672 respectively.
'''),
code('''
import os
import requests
from urllib.parse import urlsplit, unquote, quote

parts = urlsplit(broker_url())
vhost = unquote(parts.path[1:]) or "/"
management_url = os.getenv("RABBITMQ_MANAGEMENT_URL", "http://localhost:15672").rstrip("/")
http = requests.Session()
http.auth = (unquote(parts.username or ""), unquote(parts.password or ""))

def api_get(path):
    response = http.get(management_url + "/api/" + path, timeout=5)
    response.raise_for_status()
    return response.json()

overview = api_get("overview")
print({key: overview.get(key) for key in ("rabbitmq_version", "cluster_name", "management_version")})
'''),
md('''
## Step 2 — Hold three deliveries unacknowledged

Open Management → Queues and Streams while this connection remains open. We publish ten messages and receive three without ack. The remaining seven stay ready. The API snapshot may take several seconds to reflect this state; the notebook prints values without asserting their timing.
'''),
code('''
queue_name = unique_name("monitor")
connection = connect()
channel = connection.channel()
channel.queue_declare(queue=queue_name)
channel.confirm_delivery()
for number in range(10):
    channel.basic_publish(exchange="", routing_key=queue_name, body=str(number).encode(), mandatory=True)
held = [wait_for_message(channel, queue_name) for _ in range(3)]
info = api_get(f"queues/{quote(vhost, safe='')}/{quote(queue_name, safe='')}")
print("Inspect this queue:", queue_name)
print({key: info.get(key, "not sampled yet") for key in ("messages", "messages_ready", "messages_unacknowledged", "consumers")})
print("This client is holding", len(held), "unacknowledged deliveries")
'''),
md('''
## Step 3 — Finish the messages and release the connection

If you leave a Pika blocking connection idle between cells for a long time, heartbeat servicing stops; reconnect and redelivery may be required. Run this cell promptly after inspecting the UI.
'''),
code('''
try:
    numbers = []
    for method, properties, body in held:
        numbers.append(int(body))
        channel.basic_ack(method.delivery_tag)
    for _ in range(7):
        method, properties, body = wait_for_message(channel, queue_name)
        numbers.append(int(body))
        channel.basic_ack(method.delivery_tag)
    assert sorted(numbers) == list(range(10))
    channel.queue_delete(queue=queue_name)
finally:
    if connection.is_open:
        connection.close()
print("All ten messages completed")
'''),
md('''
## Step 4 — Reject an excess publication instead of silently growing

This classic queue accepts at most three ready messages and uses `reject-publish` overflow. Publisher confirms let the producer observe the fourth publication's negative acknowledgement. A deployed publisher needs a bounded response to overload; endlessly retrying immediately adds load.
'''),
code('''
bounded_queue = unique_name("bounded")
with connect() as connection:
    channel = connection.channel()
    channel.queue_declare(queue=bounded_queue, arguments={"x-max-length": 3, "x-overflow": "reject-publish"})
    channel.confirm_delivery()
    try:
        for number in range(3):
            channel.basic_publish(exchange="", routing_key=bounded_queue, body=str(number).encode(), mandatory=True)
        try:
            channel.basic_publish(exchange="", routing_key=bounded_queue, body=b"excess", mandatory=True)
        except pika.exceptions.NackError:
            print("Expected: broker rejected the excess publication")
        else:
            raise AssertionError("Expected a negative acknowledgement")
    finally:
        channel.queue_delete(queue=bounded_queue)
'''),
md('''
## Step 5 — Measure exactly what your experiment measures

Compare unconfirmed transient publishing with waiting for a confirm on every message. Both use fresh non-durable queues and 50 tiny messages. The timer covers publishing only; receiving and cleanup are outside it. Unconfirmed time measures client writes, whereas confirmed time also waits for broker acceptance, so these have different guarantees.

For production capacity planning, vary payload size, persistence, queue type, network delay, publish concurrency, consumer work, and failure conditions. Use a dedicated benchmark environment. This is intentionally small enough for a laptop.
'''),
code('''
import time

def sample_publish(confirms, count=50):
    name = unique_name("measurement")
    with connect() as connection:
        channel = connection.channel()
        channel.queue_declare(queue=name)
        try:
            if confirms:
                channel.confirm_delivery()
            started = time.perf_counter()
            for number in range(count):
                channel.basic_publish(exchange="", routing_key=name, body=str(number).encode())
            elapsed = time.perf_counter() - started
            received = []
            for _ in range(count):
                method, properties, body = wait_for_message(channel, name)
                received.append(int(body))
                channel.basic_ack(method.delivery_tag)
            assert sorted(received) == list(range(count))
            return {"confirms": confirms, "count": count, "publish_seconds": round(elapsed, 4),
                    "publications_per_second": round(count / max(elapsed, 0.000001))}
        finally:
            channel.queue_delete(queue=name)

measurements = [sample_publish(confirms=value) for value in (False, True)]
for measurement in measurements:
    print(measurement)
'''),
md('''
## Exercise — Diagnose a slow system

For each observation, name the next measurement you would take:

| Observation | Suggested next check |
|---|---|
| Ready messages grow | Arrival rate versus completion rate; consumer count and downstream latency |
| Unacknowledged messages stay high | In-flight work, stuck handlers, prefetch, and acknowledgement path |
| Connections churn | Heartbeat servicing, connection reuse, retry/backoff, and broker logs |
| Publishers are blocked | Broker memory/disk alarms and flow control |
| Parking queues grow | Failure reason, retry budget, and controlled replay procedure |

Add end-to-end latency by putting a timestamp and event ID in the message and observing when the side effect commits. Do not infer it from publish duration alone.

## Deployment exercise — Security and recovery

The Compose credentials are for a local lab, with ports bound to loopback. For deployment, give each application a distinct user and vhost permissions, use TLS with certificate verification (`amqps://`), inject secrets securely, restrict management access, and practice restore and failover. Never disable certificate verification to make an example connect. Rotation must account for both publishers and consumers. Stream workloads and large replayable logs may call for RabbitMQ Streams; the AMQP queue examples here do not demonstrate that protocol.

**Troubleshooting:** HTTP 401 means authentication failed; 403 means permissions are insufficient; 404 often means a wrong vhost or escaped queue path. RabbitMQ URL path `/learning` names the `learning` vhost; `/` is encoded as `%2F` in API paths.
'''),
md("## Cleanup"),
code('''
http.close()
print("HTTP session closed; successful experiments have deleted their queues")
'''),
md('''
## References

- [Management HTTP API](https://www.rabbitmq.com/docs/4.2/http-api-reference)
- [Monitoring](https://www.rabbitmq.com/docs/4.2/monitoring)
- [Queue length limits](https://www.rabbitmq.com/docs/4.2/maxlength)
- [Resource alarms](https://www.rabbitmq.com/docs/4.2/alarms)
- [TLS](https://www.rabbitmq.com/docs/4.2/ssl)
''')])


write("17_quorum_queues_and_failover.ipynb", [
md('''
# 17 · Quorum queues and a real three-node failover drill

**Level:** expert · **Time:** 30 minutes single-node, 60 minutes with cluster · **Prerequisites:** 00 and 07; Docker Compose for the optional cluster.

First declare a quorum queue on the normal single-node broker. Then optionally form a separate three-node cluster, publish a confirmed persistent message, stop its leader, and retrieve it from a surviving node.

**A one-node quorum queue does not provide high availability.** A three-member quorum queue needs a majority (two members) available. Three containers on one laptop demonstrate a node failure, not protection against losing that laptop or its disk.

Cluster membership does not automatically replicate every queue: classic queues are not replicated. Quorum queue membership and confirmed publishing are what this lab examines.
'''), BOOT,
md('''
## Step 1 — Use a quorum queue on one broker

Quorum queues are durable and cannot be exclusive. Queue type is chosen when declaring the queue; changing an existing queue from classic to quorum requires migration. This small example requests one initial member because the base course broker is a single node.
'''),
code('''
queue_name = unique_name("quorum.single")
with connect() as connection:
    channel = connection.channel()
    channel.queue_declare(queue=queue_name, durable=True,
                          arguments={"x-queue-type": "quorum", "x-quorum-initial-group-size": 1})
    channel.confirm_delivery()
    try:
        channel.basic_publish(exchange="", routing_key=queue_name, body=b"quorum-demo", mandatory=True,
                              properties=pika.BasicProperties(delivery_mode=2))
        method, properties, body = wait_for_message(channel, queue_name)
        assert body == b"quorum-demo"
        channel.basic_ack(method.delivery_tag)
        print("Quorum queue worked on one node; this is not an HA test")
    finally:
        channel.queue_delete(queue=queue_name)
'''),
md('''
## Step 2 — Optional: start a separate three-node cluster

All following cluster cells are skipped unless you set the flag below. The supplied `compose.cluster.yaml` uses different ports and its own named volumes, so it can coexist with the normal course stack. Allow several GB of free memory.

Run these commands **in a terminal at the course root**, only for this new disposable cluster:

```powershell
docker compose -f compose.cluster.yaml up -d --wait
docker compose -f compose.cluster.yaml exec rmq2 rabbitmqctl join_cluster rabbit@rmq1
docker compose -f compose.cluster.yaml exec rmq3 rabbitmqctl join_cluster rabbit@rmq1
docker compose -f compose.cluster.yaml exec rmq1 rabbitmqctl cluster_status
```

Confirm all three running nodes: `rabbit@rmq1`, `rabbit@rmq2`, and `rabbit@rmq3`. RabbitMQ 4.2 with Khepri supports joining without the old stop/reset/start sequence. Joining replaces the joining node's standalone metadata; use these commands only on these fresh lab nodes, not on a populated unrelated broker. Do not rerun join commands on an already formed cluster.

| Node | AMQP port | Management port |
|---|---:|---:|
| rmq1 | 5673 | 15673 |
| rmq2 | 5674 | 15674 |
| rmq3 | 5675 | 15675 |

The cluster uses the local demo username `student`, password `student-local-only`, and vhost `learning`.
'''),
code('''
RUN_CLUSTER_LAB = False
print("Optional cluster lab enabled:", RUN_CLUSTER_LAB)
'''),
md('''
## Step 3 — Declare three replicas, verify membership, and publish

This code checks actual queue membership rather than assuming that three running containers imply replication. It prints the current leader and the exact terminal command to stop that one container. **Pause after this cell** and run the printed command before Step 4.
'''),
code('''
import requests
from urllib.parse import quote

cluster_ports = {"rabbit@rmq1": (5673, 15673), "rabbit@rmq2": (5674, 15674), "rabbit@rmq3": (5675, 15675)}

def cluster_connection(node):
    amqp_port, _ = cluster_ports[node]
    params = pika.URLParameters(f"amqp://student:student-local-only@localhost:{amqp_port}/learning")
    params.socket_timeout = 3
    params.stack_timeout = 5
    params.blocked_connection_timeout = 5
    params.heartbeat = 15
    params.connection_attempts = 1
    return pika.BlockingConnection(params)

def cluster_queue_info(node, name):
    _, port = cluster_ports[node]
    response = requests.get(f"http://localhost:{port}/api/queues/learning/{quote(name, safe='')}",
                            auth=("student", "student-local-only"), timeout=5)
    response.raise_for_status()
    return response.json()

if RUN_CLUSTER_LAB:
    cluster_queue = unique_name("quorum.cluster")
    with cluster_connection("rabbit@rmq1") as connection:
        channel = connection.channel()
        channel.queue_declare(queue=cluster_queue, durable=True,
                              arguments={"x-queue-type": "quorum", "x-quorum-initial-group-size": 3})
        channel.confirm_delivery()
        channel.basic_publish(exchange="", routing_key=cluster_queue, body=b"confirmed-before-leader-loss",
                              properties=pika.BasicProperties(delivery_mode=2), mandatory=True)
    info = cluster_queue_info("rabbit@rmq1", cluster_queue)
    members = info.get("members", [])
    assert len(members) == 3, f"Expected three queue members; got {members}. Form the cluster before declaration."
    original_leader = info.get("leader") or info.get("node")
    assert original_leader in cluster_ports, info
    print("Queue:", cluster_queue, "Members:", members, "Leader:", original_leader)
    print("PAUSE. Run in a terminal: docker compose -f compose.cluster.yaml stop", original_leader.split("@")[1])
else:
    print("Skipped: start the optional cluster and set RUN_CLUSTER_LAB=True to continue")
'''),
md('''
## Step 4 — Read from a survivor after the leader changes

Run only after stopping the printed leader. The HTTP check prevents accidentally claiming a failover demonstration when no leader was stopped. It waits up to 30 seconds for a new leader, reconnects through another node, and consumes the original confirmed message.

A publisher cannot safely assume a failed unconfirmed publication was lost; retrying such a publication still needs duplicate protection. This drill starts with a confirmed message to isolate leader failover.
'''),
code('''
import time

if RUN_CLUSTER_LAB:
    survivor = next(node for node in cluster_ports if node != original_leader)
    deadline = time.monotonic() + 30
    last_problem = "Original leader is still reported"
    while True:
        try:
            info = cluster_queue_info(survivor, cluster_queue)
            new_leader = info.get("leader") or info.get("node")
            if new_leader and new_leader != original_leader:
                break
        except requests.RequestException as error:
            # The management endpoint can be temporarily unavailable during election.
            last_problem = type(error).__name__
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Leader did not change ({last_problem}). Stop the original leader, then rerun this cell.")
        time.sleep(0.5)
    with cluster_connection(survivor) as connection:
        channel = connection.channel()
        method, properties, body = wait_for_message(channel, cluster_queue, timeout=10)
        assert body == b"confirmed-before-leader-loss"
        channel.basic_ack(method.delivery_tag)
    print("Original leader:", original_leader, "New leader:", new_leader)
    print("Received the confirmed message after leader failover")
    print("Restore now: docker compose -f compose.cluster.yaml start", original_leader.split("@")[1])
else:
    print("Failover drill skipped")
'''),
md('''
## Exercise — Lose a majority, then recover

After restoring all three members, create a fresh test message and stop two members. Predict whether the queue can safely accept confirmed writes. Set finite connection and blocked timeouts, then record the result and restore both nodes. Do not assert a particular client exception or timeout duration: election timing, alarms, and client behavior differ.

**Suggested answer:** one surviving member is not a majority, so it cannot provide quorum queue availability. Bring back at least one existing member with its data intact. Do not reset nodes or force recovery merely to make the experiment pass; those actions can change the data-safety assumptions.

RabbitMQ 4.2 quorum queues also have a default delivery limit of 20. Configure a dead-letter destination for poison messages and test the intended retry policy. Quorum queues are intended for longer-lived durable workloads, not high churn of temporary queues. This lesson creates only a small number and cleans them up.

**Troubleshooting:** a single member means the queue was created before the cluster formed; remove only that empty lab queue and create a new one after joining. An `ACCESS_REFUSED` error suggests credentials/vhost mismatch. Erlang cookie mismatch prevents nodes joining even when AMQP logins work. Restore the stopped leader before another lab.
'''),
md('''
## Cleanup

Restore the stopped node first using the printed command. The next cell removes only the test queue. To stop the optional cluster while preserving its data, run `docker compose -f compose.cluster.yaml down`. A future fresh restart with preserved volumes should not need `join_cluster` again. Use `down -v` only when you intentionally want to erase this optional cluster's lab data.
'''),
code('''
if RUN_CLUSTER_LAB and "cluster_queue" in globals():
    with cluster_connection(survivor if "survivor" in globals() else "rabbit@rmq1") as connection:
        connection.channel().queue_delete(queue=cluster_queue)
    print("Deleted", cluster_queue)
else:
    print("No optional cluster queue to clean up")
'''),
md('''
## References

- [RabbitMQ 4.2 quorum queues](https://www.rabbitmq.com/docs/4.2/quorum-queues)
- [RabbitMQ 4.2 clustering](https://www.rabbitmq.com/docs/4.2/clustering)
- [Khepri cluster formation](https://www.rabbitmq.com/docs/4.2/metadata-store/clustering)
''')])

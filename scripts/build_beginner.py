"""Build the six introductory notebooks. Run from any working directory."""
import json
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "notebooks"
OUT.mkdir(exist_ok=True)


def md(text):
    return {"cell_type": "markdown", "metadata": {}, "source": textwrap.dedent(text).strip() + "\n"}


def code(text):
    return {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [],
            "source": textwrap.dedent(text).strip() + "\n"}


BOOTSTRAP = """
from pathlib import Path
import sys
import json
import time
import pika

ROOT = next((p for p in [Path.cwd(), *Path.cwd().parents]
             if (p / "course" / "rabbit.py").is_file()), None)
assert ROOT is not None, "Open Jupyter from the RabbitMQ course folder."
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from course.rabbit import connect, unique_name, wait_for_message
"""


def write(name, cells):
    notebook = {"cells": cells, "metadata": {
        "kernelspec": {"display_name": "Python 3 (RabbitMQ course)", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3.12.0"}}, "nbformat": 4, "nbformat_minor": 5}
    for number, cell in enumerate(cells):
        cell["id"] = f"cell-{number:03d}"
    (OUT / name).write_text(json.dumps(notebook, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


write("01_messaging_basics.ipynb", [
md("""
# 01 · Send, inspect, and receive your first message

**Level:** beginner · **Time:** 25–35 minutes · **Prerequisite:** finish notebook 00 and start RabbitMQ.

By the end, you can explain a producer, broker, exchange, queue, consumer, channel, and acknowledgement;
send Python data as JSON; and prove that a queue holds a message while no consumer is running.

Run cells in order. All examples finish by themselves. A fresh run uses a unique queue, so two presenters
can run this lesson without taking each other's messages. Run the cleanup cell when finished.

## 1. Follow the message

```text
Python producer → exchange → queue → Python consumer → acknowledgement
```

The broker is the RabbitMQ server. A connection is a network conversation with it; channels are logical
conversations inside that connection. An exchange chooses queues using bindings. A queue stores deliveries
until consumers handle them. An acknowledgement tells the broker a delivery can be removed.

Here we use the built-in **default exchange**, whose name is the empty string. RabbitMQ automatically
binds every queue to this exchange with its queue name as the routing key. We will create our own
exchanges in notebook 03. The helper only reads connection settings; the messaging operations stay visible.
"""), code(BOOTSTRAP),
md("""
## 2. Declare a queue

Predict: does creating an empty queue create a message? `message_count` should be zero.
This first queue is deliberately non-durable; later lessons address restart survival. Closing a connection
does not delete this queue because it is neither exclusive nor auto-delete.
"""),
code("""
queue_name = unique_name("hello")
with connect() as connection:
    channel = connection.channel()
    result = channel.queue_declare(queue=queue_name, durable=False)
    print("Queue:", result.method.queue)
    print("Ready messages:", result.method.message_count)
    assert result.method.message_count == 0
"""),
md("""
## 3. Publish a JSON document, with no consumer running

Python dictionaries are not an AMQP wire format. Serialize to JSON and encode text as UTF-8 bytes.
`content_type` describes the payload; it does not perform serialization for you. The producer connection
will close at the end of this cell. Predict whether the message will still be available in the next cell.
"""),
code("""
order = {"order_id": 1001, "customer": "Asha", "items": ["book", "pen"]}
with connect() as connection:
    channel = connection.channel()
    channel.basic_publish(
        exchange="", routing_key=queue_name,
        body=json.dumps(order).encode("utf-8"),
        properties=pika.BasicProperties(content_type="application/json", content_encoding="utf-8"),
    )
    # This synchronous inspection also lets us observe the queued message.
    ready = channel.queue_declare(queue=queue_name, passive=True).method.message_count
    print("Ready messages after publish:", ready)
    assert ready == 1
"""),
md("""
Pause to demonstrate: open the RabbitMQ management UI at `http://localhost:15672`, choose the
`learning` virtual host, open **Queues and Streams**, and find the printed queue name. Observe one
ready message and zero consumers. Do not use the UI's Get messages action yet: it can consume messages.

## 4. Read, process, then acknowledge

`basic_get` fetches at most one message. We use it here so a cell always finishes. A push consumer using
`basic_consume` is the usual approach for a running service. The wait helper retries `basic_get` until
a deadline and returns the same method, properties, and bytes as Pika.

Predict: the bytes become the original dictionary; after acknowledging, the queue will be empty.
"""),
code("""
with connect() as connection:
    channel = connection.channel()
    method, properties, body = wait_for_message(channel, queue_name, timeout=5)
    received = json.loads(body.decode("utf-8"))
    print("Raw bytes:", body)
    print("Decoded order:", received)
    print("Content type:", properties.content_type)
    assert received == order
    # Ack on the same channel that delivered this message, after successful work.
    channel.basic_ack(delivery_tag=method.delivery_tag)
    method, properties, body = channel.basic_get(queue=queue_name, auto_ack=False)
    assert method is None
    print("The queue is now empty.")
"""),
md("""
## 5. Try it yourself

Send three orders with IDs 1002–1004. Receive each one, collect the IDs, and acknowledge it only after
decoding. Before running your solution, predict the number of messages remaining after reading two.
The solution below expects an empty queue and creates its own three messages.
"""),
code("""
# Suggested solution: change these payloads, then rerun this whole cell.
with connect() as connection:
    channel = connection.channel()
    for order_id in range(1002, 1005):
        channel.basic_publish(exchange="", routing_key=queue_name,
                              body=json.dumps({"order_id": order_id}).encode())
    seen = []
    for _ in range(2):
        method, _, body = wait_for_message(channel, queue_name)
        seen.append(json.loads(body)["order_id"])
        channel.basic_ack(method.delivery_tag)
    remaining = channel.queue_declare(queue=queue_name, passive=True).method.message_count
    assert remaining == 1
    method, _, body = wait_for_message(channel, queue_name)
    seen.append(json.loads(body)["order_id"])
    channel.basic_ack(method.delivery_tag)
    assert seen == [1002, 1003, 1004]
    print("Processed:", seen, "| Ready after the first two:", remaining)
"""),
md("""
## 6. Clean up and explain it back

Delete only this lesson's unique queue. Then explain why a message survived closing the producer
connection and why that does **not** prove it would survive a broker restart.
"""),
code("""
with connect() as connection:
    connection.channel().queue_delete(queue=queue_name)
print("Removed", queue_name)
"""),
md("""
**Troubleshooting:** connection refused means the broker is not listening; check notebook 00.
`ACCESS_REFUSED` usually means credentials or virtual-host permissions do not match `.env`.
A receive timeout often means a previous run or management UI already consumed the message: restart
the kernel and run this notebook from the top. A queue-declaration conflict means an existing queue
was declared with different settings; unique names prevent that in normal use.

**Checkpoint:** you can distinguish storage (queue), routing (exchange), payload (bytes), and processing
confirmation (consumer acknowledgement). Next: multiple workers and recovery from a failed consumer.

Official reference: [RabbitMQ Python hello-world tutorial](https://www.rabbitmq.com/tutorials/tutorial-one-python).
""")])

write("02_work_queues_and_acknowledgements.ipynb", [
md("""
# 02 · Work queues, acknowledgements, and redelivery

**Level:** beginner · **Time:** 35–45 minutes · **Prerequisite:** notebook 01.

You will share tasks between two consumers, use manual acknowledgements, and simulate a worker that
loses its connection after receiving a job. A work queue distributes deliveries among consumers on
the **same queue**; it does not broadcast a copy to every consumer.

Run cells in order. We use two logical consumers in one Python process to keep this first demonstration
easy to inspect. Their callbacks run on the same thread; these are not two parallel CPU workers.
In a service, each worker process normally owns its own connection. Later lessons explore concurrency.
"""), code(BOOTSTRAP),
md("""
## 1. Prepare eight jobs

Each job has an application ID. Delivery tags are channel-local acknowledgement handles, not business
IDs. Predict: how many total successful callbacks should eight jobs produce in this no-failure run?
"""),
code("""
queue_name = unique_name("work")
with connect() as connection:
    channel = connection.channel()
    channel.queue_declare(queue=queue_name, durable=False)
    for job_id in range(8):
        channel.basic_publish(exchange="", routing_key=queue_name,
                              body=json.dumps({"job_id": job_id}).encode())
    assert channel.queue_declare(queue=queue_name, passive=True).method.message_count == 8
print("Eight jobs waiting in", queue_name)
"""),
md("""
## 2. Register two push consumers and service events until a deadline

`basic_consume` registers a callback. `process_data_events` gives Pika time to receive and dispatch
deliveries. A deadline prevents this notebook cell from waiting forever.

Each channel uses `prefetch_count=1`, allowing at most one unacknowledged delivery per consumer here.
Prefetch controls push deliveries; it has no effect on `basic_get` polling. Acknowledging after processing
lets another job arrive. Do not assume a particular worker distribution or completion order in production.
"""),
code("""
completed = []
with connect() as connection:
    worker_channels = [connection.channel(), connection.channel()]
    consumer_tags = []

    def callback_for(worker_name):
        def process(channel, method, properties, body):
            job = json.loads(body)
            completed.append((worker_name, job["job_id"]))
            print(worker_name, "processed job", job["job_id"])
            channel.basic_ack(method.delivery_tag)
        return process

    for index, channel in enumerate(worker_channels, start=1):
        channel.basic_qos(prefetch_count=1)
        tag = channel.basic_consume(queue=queue_name,
                                   on_message_callback=callback_for(f"worker-{index}"),
                                   auto_ack=False)
        consumer_tags.append(tag)
    try:
        deadline = time.monotonic() + 8
        while len(completed) < 8 and time.monotonic() < deadline:
            connection.process_data_events(time_limit=0.2)
        assert sorted(job_id for _, job_id in completed) == list(range(8)), completed
    finally:
        for channel, tag in zip(worker_channels, consumer_tags):
            if channel.is_open:
                channel.basic_cancel(tag)
print("Total processed:", len(completed))
"""),
md("""
**Observe:** there are eight completions across the consumers. Compare this with broadcast in notebook 03.
Multiple consumers and retries can change application processing order even when a queue enqueues in order.

## 3. Simulate a consumer connection disappearing before acknowledgement

First receive a new job and intentionally omit its acknowledgement. The context manager closes the
connection, standing in for the broker detecting a failed worker. There is no business side effect here;
in a real system a worker might have already changed a database before it died.
"""),
code("""
with connect() as connection:
    channel = connection.channel()
    channel.basic_publish(exchange="", routing_key=queue_name,
                          body=json.dumps({"job_id": "recover-me"}).encode())
    first_delivery, _, body = wait_for_message(channel, queue_name)
    print("Received but NOT acknowledged:", json.loads(body))
    assert not first_delivery.redelivered
# Closing a channel/connection returns its unacknowledged deliveries to the queue.
"""),
md("""
## 4. Recover the job on another connection

Predict the `redelivered` flag. A new connection gets a new channel-local delivery tag, which may
coincidentally have the same integer value as before. Use the tag from this delivery to acknowledge it.
"""),
code("""
with connect() as connection:
    channel = connection.channel()
    method, _, body = wait_for_message(channel, queue_name, timeout=5)
    recovered = json.loads(body)
    print("Recovered:", recovered, "| Redelivered:", method.redelivered)
    assert recovered["job_id"] == "recover-me"
    assert method.redelivered
    channel.basic_ack(method.delivery_tag)
"""),
md("""
## 5. Exercise: explicitly requeue once

Send a message and reject its first delivery using `basic_nack(..., requeue=True)`. Receive it a second
time and acknowledge it. Why would an unconditional requeue in every callback be dangerous?

The solution performs exactly one requeue. A tight retry loop can consume CPU and network bandwidth;
later lessons introduce delayed retries, retry budgets, and a dead-letter queue.
"""),
code("""
with connect() as connection:
    channel = connection.channel()
    channel.basic_publish(exchange="", routing_key=queue_name, body=b"retry once")
    method, _, body = wait_for_message(channel, queue_name)
    channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
    second, _, body = wait_for_message(channel, queue_name)
    assert second.redelivered and body == b"retry once"
    channel.basic_ack(second.delivery_tag)
    print("One controlled retry completed.")
"""),
md("""
## 6. Cleanup and teaching checkpoint

We observed **at-least-once processing risk**: a worker may perform a side effect and then lose its
connection before the acknowledgement arrives. The broker can deliver that message again. A stable
application ID and idempotent processing are how later lessons prevent duplicate business effects.

`auto_ack=True` instead treats delivery as handled without waiting for your work to succeed; a consumer
failure after delivery can lose the work. Manual acknowledgements do not by themselves make publishing durable.
"""),
code("""
with connect() as connection:
    connection.channel().queue_delete(queue=queue_name)
print("Cleaned up", queue_name)
"""),
md("""
**Troubleshooting:** an unknown-delivery-tag error usually means you acknowledged twice or on the wrong
channel. A redelivery timeout can mean another consumer took the message; verify that you used this run's
unique queue. Repeated redelivery means the worker is failing or closing before acknowledging.

Official references: [work queues](https://www.rabbitmq.com/tutorials/tutorial-two-python) and
[acknowledgements and prefetch](https://www.rabbitmq.com/docs/confirms).
""")])

write("03_publish_subscribe_fanout.ipynb", [
md("""
# 03 · Broadcast events with a fanout exchange

**Level:** beginner · **Time:** 25–35 minutes · **Prerequisites:** notebooks 01–02.

Build an order-event broadcaster with separate analytics and email queues. See that each queue receives
a copy, then demonstrate that an unbound subscriber does not receive old events retroactively.

```text
                         ┌→ analytics queue → analytics consumer
producer → fanout exchange
                         └→ email queue → email consumer
```

A fanout exchange routes a message to its bound queues. Routing keys do not select subscribers for
this exchange type. Two consumers on one queue compete; two different bound queues receive copies.
"""), code(BOOTSTRAP),
md("""
## 1. Declare the exchange and two subscriber queues

These are named, non-exclusive lab queues so they remain available between short connection scopes.
An exclusive temporary subscriber queue would disappear when its owning connection closes.
"""),
code("""
exchange = unique_name("events.fanout")
analytics_queue = unique_name("analytics")
email_queue = unique_name("email")
late_queue = unique_name("late.subscriber")
with connect() as connection:
    channel = connection.channel()
    channel.exchange_declare(exchange=exchange, exchange_type="fanout", durable=False)
    for queue in [analytics_queue, email_queue]:
        channel.queue_declare(queue=queue, durable=False)
        channel.queue_bind(exchange=exchange, queue=queue, routing_key="")
print("Exchange:", exchange)
print("Subscriber queues:", analytics_queue, email_queue, sep="\\n")
"""),
md("""
## 2. Publish one event and inspect both copies

Predict the total number of deliveries: one published event becomes one delivery in each bound queue.
The two acknowledgement tags belong to their deliveries; neither subscriber acknowledges for the other.
"""),
code("""
event = {"event_id": "event-001", "type": "order.created", "order_id": 42}
with connect() as connection:
    channel = connection.channel()
    channel.basic_publish(exchange=exchange, routing_key="ignored.by.fanout",
                          body=json.dumps(event).encode(),
                          properties=pika.BasicProperties(content_type="application/json"))
    deliveries = {}
    for subscriber, queue in [("analytics", analytics_queue), ("email", email_queue)]:
        method, _, body = wait_for_message(channel, queue)
        deliveries[subscriber] = json.loads(body)
        channel.basic_ack(method.delivery_tag)
    assert deliveries == {"analytics": event, "email": event}
    print(json.dumps(deliveries, indent=2))
"""),
md("""
## 3. Add a late subscriber

A queue starts receiving routed events when its binding exists. An exchange is not an event-history
database. Predict whether the new queue contains `event-001` before we publish another event.
"""),
code("""
with connect() as connection:
    channel = connection.channel()
    channel.queue_declare(queue=late_queue, durable=False)
    channel.queue_bind(exchange=exchange, queue=late_queue, routing_key="")
    assert channel.basic_get(queue=late_queue, auto_ack=False)[0] is None
    second_event = {"event_id": "event-002", "type": "order.created", "order_id": 43}
    channel.basic_publish(exchange=exchange, routing_key="",
                          body=json.dumps(second_event).encode())
    for queue in [analytics_queue, email_queue, late_queue]:
        method, _, body = wait_for_message(channel, queue)
        assert json.loads(body)["event_id"] == "event-002"
        channel.basic_ack(method.delivery_tag)
    print("The late subscriber saw only the second event.")
"""),
md("""
## 4. Exercise: unsubscribe email without deleting its queue

Remove the email binding using `queue_unbind`, publish one more event, and prove analytics and the
late subscriber receive it while email stays empty. Removing a binding prevents future routing through
that binding; it does not erase messages already in the queue.
"""),
code("""
# Suggested solution. The previous cell emptied all three queues.
with connect() as connection:
    channel = connection.channel()
    channel.queue_unbind(exchange=exchange, queue=email_queue, routing_key="")
    channel.basic_publish(exchange=exchange, routing_key="", body=b"event-003")
    for queue in [analytics_queue, late_queue]:
        method, _, body = wait_for_message(channel, queue)
        assert body == b"event-003"
        channel.basic_ack(method.delivery_tag)
    assert channel.basic_get(queue=email_queue, auto_ack=False)[0] is None
    print("Email unsubscribed; both other subscriptions received the event.")
"""),
md("""
## 5. Clean up and discuss

Delete each queue and then this lesson's exchange. Design question: to let three email workers share
the email workload, would you create three email queues or three consumers on the existing email queue?
**Answer:** three consumers on the same queue share deliveries. Three bound queues would create three copies.
"""),
code("""
with connect() as connection:
    channel = connection.channel()
    for queue in [analytics_queue, email_queue, late_queue]:
        channel.queue_delete(queue=queue)
    channel.exchange_delete(exchange=exchange)
print("Fanout resources removed.")
"""),
md("""
**Troubleshooting:** no delivery usually means the queue was not bound before publishing. A fanout
exchange with no matching bound queues can discard a publication; publisher confirms plus mandatory
routing detection are covered later. A consumer being offline differs from its queue not existing:
an existing non-exclusive queue can accumulate events while its consumer is offline.

Official reference: [RabbitMQ publish/subscribe tutorial](https://www.rabbitmq.com/tutorials/tutorial-three-python).
""")])

write("04_direct_routing.ipynb", [
md("""
# 04 · Route selectively with a direct exchange

**Level:** beginner · **Time:** 25–35 minutes · **Prerequisite:** notebook 03.

Build log routing: an audit queue receives `info` and `error`; an alerts queue receives only `error`.
You will distinguish a message's routing key from a queue's binding key and inspect an unroutable publish.

A direct exchange compares the routing key with binding keys for an exact match. It can route one
publication to several queues with matching bindings. This is selective fanout, not necessarily one-to-one.
"""), code(BOOTSTRAP),
md("""
## 1. Create the route map

| Queue | Binding keys | Purpose |
|---|---|---|
| Audit | `info`, `error` | Keep routine and error logs |
| Alerts | `error` | Notify on errors only |

Predict: will `ERROR` match the binding `error`? Routing keys are case-sensitive strings.
"""),
code("""
exchange = unique_name("logs.direct")
audit_queue = unique_name("audit")
alerts_queue = unique_name("alerts")
with connect() as connection:
    channel = connection.channel()
    channel.exchange_declare(exchange=exchange, exchange_type="direct")
    for queue in [audit_queue, alerts_queue]:
        channel.queue_declare(queue=queue)
    for severity in ["info", "error"]:
        channel.queue_bind(exchange=exchange, queue=audit_queue, routing_key=severity)
    channel.queue_bind(exchange=exchange, queue=alerts_queue, routing_key="error")
print("Created", exchange)
"""),
md("""
## 2. Publish two severities

The application chooses routing keys. RabbitMQ does not inspect the JSON `message` text to decide its
severity. Predict the exact payloads in each queue before running the receiving cell.
"""),
code("""
with connect() as connection:
    channel = connection.channel()
    for severity, message in [("info", "order accepted"), ("error", "payment declined")]:
        channel.basic_publish(exchange=exchange, routing_key=severity,
                              body=json.dumps({"severity": severity, "message": message}).encode())
    print("Audit ready:", channel.queue_declare(queue=audit_queue, passive=True).method.message_count)
    print("Alerts ready:", channel.queue_declare(queue=alerts_queue, passive=True).method.message_count)
"""),
md("""
## 3. Verify routing and acknowledge each delivery

This bounded helper consumes an expected number of deliveries and checks that no extra delivery remains.
It uses this lesson's queue names only. The helper's acknowledgement happens after decoding the JSON.
"""),
code("""
def read_expected(channel, queue, count):
    records = []
    for _ in range(count):
        method, _, body = wait_for_message(channel, queue)
        records.append(json.loads(body))
        channel.basic_ack(method.delivery_tag)
    assert channel.basic_get(queue=queue, auto_ack=False)[0] is None
    return records

with connect() as connection:
    channel = connection.channel()
    audit = read_expected(channel, audit_queue, 2)
    alerts = read_expected(channel, alerts_queue, 1)
    assert [entry["severity"] for entry in audit] == ["info", "error"]
    assert [entry["severity"] for entry in alerts] == ["error"]
    print("Audit:", audit)
    print("Alerts:", alerts)
"""),
md("""
## 4. Publish a key with no binding

A successful socket write does not prove a message reached a queue. For this small experiment, enable
publisher confirms and `mandatory=True`: Pika can then surface an unroutable message as an exception.
Confirms acknowledge broker acceptance, not successful work by a consumer; notebook 07 develops this.
"""),
code("""
with connect() as connection:
    channel = connection.channel()
    channel.confirm_delivery()
    try:
        channel.basic_publish(exchange=exchange, routing_key="ERROR", body=b"no exact match",
                              mandatory=True)
    except pika.exceptions.UnroutableError:
        print("Expected: ERROR has no binding; the publisher detected it.")
    else:
        raise AssertionError("Expected the upper-case key to be unroutable.")
"""),
md("""
## 5. Exercise: make warning logs routable

Bind `warning` to the audit queue, publish a warning, then verify that audit gets it and alerts does not.
Try the solution, then explain how to change it if alerts should also receive warnings.
"""),
code("""
with connect() as connection:
    channel = connection.channel()
    channel.queue_bind(exchange=exchange, queue=audit_queue, routing_key="warning")
    channel.basic_publish(exchange=exchange, routing_key="warning",
                          body=json.dumps({"severity": "warning", "message": "stock running low"}).encode())
    assert read_expected(channel, audit_queue, 1)[0]["severity"] == "warning"
    assert read_expected(channel, alerts_queue, 0) == []
    print("Only audit received the warning.")
"""),
md("""
## 6. Cleanup and checkpoint

To add warning alerts, bind the alerts queue with the `warning` key too. Exchange names, queue names,
and routing keys have different jobs; none has to be identical when using a custom exchange.
"""),
code("""
with connect() as connection:
    channel = connection.channel()
    for queue in [audit_queue, alerts_queue]:
        channel.queue_delete(queue=queue)
    channel.exchange_delete(exchange=exchange)
print("Direct-routing resources removed.")
"""),
md("""
**Troubleshooting:** a direct binding such as `order.*` is a literal string, not a wildcard; use a topic
exchange for patterns. Publishing to an exchange that does not exist closes the channel; that is different
from an existing exchange with no route. Recreate the channel after a broker channel error.

Official reference: [RabbitMQ routing tutorial](https://www.rabbitmq.com/tutorials/tutorial-four-python).
""")])

write("05_topic_and_headers_routing.ipynb", [
md("""
# 05 · Topic patterns and header-based routing

**Level:** beginner/intermediate · **Time:** 35–45 minutes · **Prerequisite:** notebook 04.

Route order events by topic and then by metadata headers. Choose topic routing when a compact hierarchy
such as `order.created.eu` describes the route; choose headers when independent attributes are clearer.

Topic keys contain dot-separated words. In bindings, `*` matches exactly one word and `#` matches zero
or more words. Header exchanges compare AMQP message headers and ignore routing keys for matching.
"""), code(BOOTSTRAP),
md("""
## 1. Predict this topic-routing table

| Published key | `order.*.eu` | `order.#` | `#.eu` |
|---|---|---|---|
| `order.created.eu` | yes | yes | yes |
| `order.paid.us` | no | yes | no |
| `order.eu` | no | yes | yes |
| `inventory.low.eu` | no | no | yes |

The short key `order.eu` is the useful edge case: `*` cannot match zero words.
"""),
code("""
topic_exchange = unique_name("events.topic")
topic_bindings = {
    unique_name("eu.order"): "order.*.eu",
    unique_name("all.order"): "order.#",
    unique_name("all.eu"): "#.eu",
}
keys = ["order.created.eu", "order.paid.us", "order.eu", "inventory.low.eu"]
with connect() as connection:
    channel = connection.channel()
    channel.exchange_declare(exchange=topic_exchange, exchange_type="topic")
    for queue, pattern in topic_bindings.items():
        channel.queue_declare(queue=queue)
        channel.queue_bind(exchange=topic_exchange, queue=queue, routing_key=pattern)
    for key in keys:
        channel.basic_publish(exchange=topic_exchange, routing_key=key, body=key.encode())
print("Published:", keys)
"""),
md("""
## 2. Check your predictions

Read the expected number of messages per queue, acknowledge them, and confirm no extras remain.
This experiment tests zero-word matching as well as a one-word match.
"""),
code("""
expected = {
    "order.*.eu": ["order.created.eu"],
    "order.#": ["order.created.eu", "order.paid.us", "order.eu"],
    "#.eu": ["order.created.eu", "order.eu", "inventory.low.eu"],
}
with connect() as connection:
    channel = connection.channel()
    for queue, pattern in topic_bindings.items():
        seen = []
        for _ in expected[pattern]:
            method, _, body = wait_for_message(channel, queue)
            seen.append(body.decode())
            channel.basic_ack(method.delivery_tag)
        assert seen == expected[pattern], (pattern, seen)
        assert channel.basic_get(queue=queue, auto_ack=False)[0] is None
        print(pattern, "→", seen)
"""),
md("""
## 3. Route on multiple independent headers

Create two subscriptions for `format=pdf` and `region=eu`. `x-match=all` requires both attributes;
`x-match=any` requires at least one. These are AMQP properties, not fields hidden inside JSON bodies.
Use consistent header types: the string `"1"` and integer `1` are different typed values.
"""),
code("""
headers_exchange = unique_name("documents.headers")
headers_queues = {mode: unique_name(f"headers.{mode}") for mode in ["all", "any"]}
documents = [
    {"id": "A", "format": "pdf", "region": "eu"},
    {"id": "B", "format": "pdf", "region": "us"},
    {"id": "C", "format": "csv", "region": "eu"},
    {"id": "D", "format": "csv", "region": "us"},
]
with connect() as connection:
    channel = connection.channel()
    channel.exchange_declare(exchange=headers_exchange, exchange_type="headers")
    for mode, queue in headers_queues.items():
        channel.queue_declare(queue=queue)
        channel.queue_bind(exchange=headers_exchange, queue=queue,
                           arguments={"x-match": mode, "format": "pdf", "region": "eu"})
    for document in documents:
        channel.basic_publish(
            exchange=headers_exchange, routing_key="not.used.for.header.matching",
            body=document["id"].encode(),
            properties=pika.BasicProperties(headers={"format": document["format"],
                                                     "region": document["region"]}),
        )
print("Published four documents.")
"""),
md("""
## 4. Verify all versus any

Predict which document IDs arrive in each queue. Document D intentionally matches neither subscription
and is not retained by this topology. Reliable unroutable-message detection is addressed in notebook 07.
"""),
code("""
with connect() as connection:
    channel = connection.channel()
    for mode, ids in {"all": ["A"], "any": ["A", "B", "C"]}.items():
        seen = []
        for _ in ids:
            method, properties, body = wait_for_message(channel, headers_queues[mode])
            seen.append(body.decode())
            channel.basic_ack(method.delivery_tag)
        assert seen == ids
        assert channel.basic_get(queue=headers_queues[mode], auto_ack=False)[0] is None
        print(mode, "→", seen)
"""),
md("""
## 5. Exercise: overlapping topic bindings on one queue

Create one queue bound to both `order.#` and `#.eu`. Publish `order.created.eu` once. Will two matching
bindings cause two copies in this **same queue**? Write your prediction, then run the solution.
"""),
code("""
overlap_queue = unique_name("overlap")
with connect() as connection:
    channel = connection.channel()
    channel.queue_declare(queue=overlap_queue)
    for pattern in ["order.#", "#.eu"]:
        channel.queue_bind(exchange=topic_exchange, queue=overlap_queue, routing_key=pattern)
    channel.basic_publish(exchange=topic_exchange, routing_key="order.created.eu", body=b"one publication")
    method, _, body = wait_for_message(channel, overlap_queue)
    channel.basic_ack(method.delivery_tag)
    assert body == b"one publication"
    assert channel.basic_get(queue=overlap_queue, auto_ack=False)[0] is None
    print("One queue received one copy, despite two matching bindings.")
"""),
md("""
## 6. Cleanup and design discussion

The exercise also routed a copy to each previously bound topic queue; cleanup removes those lab messages.
Topic hierarchies are contracts: agree on word order and meaning before independent services adopt them.
Headers provide flexible attribute matching but still require a shared schema and consistent types.
"""),
code("""
with connect() as connection:
    channel = connection.channel()
    for queue in [*topic_bindings, *headers_queues.values(), overlap_queue]:
        channel.queue_delete(queue=queue)
    for exchange in [topic_exchange, headers_exchange]:
        channel.exchange_delete(exchange=exchange)
print("Topic and header resources removed.")
"""),
md("""
**Troubleshooting:** `*` is not a substring wildcard: `order.create*` does not mean every word starting
with `create`. Make sure header metadata is in `BasicProperties(headers=...)`; matching does not inspect
the body. Re-declaring an exchange with another type closes the channel; use the distinct names above.

Official references: [topic tutorial](https://www.rabbitmq.com/tutorials/tutorial-five-python) and
[exchange types](https://www.rabbitmq.com/docs/exchanges).
""")])

write("06_rpc.ipynb", [
md("""
# 06 · Request/reply with correlation IDs and timeouts

**Level:** intermediate · **Time:** 40–50 minutes · **Prerequisites:** notebooks 01–05.

Build a small square-number RPC service. Send a request through RabbitMQ, route its response back to
the client's reply queue, ignore an unrelated response, and observe a bounded timeout when no worker runs.

```text
client → request queue → worker
client ← reply queue   ← worker
```

`reply_to` tells the worker where to respond; `correlation_id` lets a client associate a reply with a
request. RPC still has network delays and partial failures. Prefer an asynchronous event/task when
the caller does not need an immediate answer. A timeout means the outcome is unknown, not that work was cancelled.
"""), code(BOOTSTRAP),
md("""
## 1. Declare the request queue

Use a unique queue so another presenter cannot receive your requests. Our worker runs in a background
thread with its **own connection and channel**. Pika's connection/channel operations are not generally
thread-safe; never call a worker's channel from the notebook thread.
"""),
code("""
from threading import Event, Thread
from queue import Queue
from uuid import uuid4

request_queue = unique_name("rpc.square")
with connect() as connection:
    connection.channel().queue_declare(queue=request_queue)
print("Requests:", request_queue)
"""),
md("""
## 2. Define a bounded worker

Validate the input and return a structured error for invalid requests. The response keeps the request's
correlation ID. The worker publishes with confirmation and acknowledges the request only after that succeeds.
There is still a crash window between publishing the response and acknowledging the request: duplicate
requests/replies remain possible. Squaring a number has no side effect, making retries harmless here.

The stop flag and 30-second maximum lifetime prevent an abandoned lesson from running indefinitely.
The worker's connection is created, serviced, and closed inside its own thread.
"""),
code("""
def run_worker(stop, ready, errors):
    try:
        with connect() as connection:
            channel = connection.channel()
            channel.basic_qos(prefetch_count=1)
            channel.confirm_delivery()

            def respond(channel, method, properties, body):
                try:
                    value = json.loads(body)["number"]
                    if isinstance(value, bool) or not isinstance(value, int) or not -1000 <= value <= 1000:
                        raise ValueError("number must be an integer from -1000 to 1000")
                    result = {"ok": True, "result": value * value}
                except (ValueError, TypeError, KeyError) as exc:
                    result = {"ok": False, "error": str(exc)}
                if not properties.reply_to or not properties.correlation_id:
                    channel.basic_nack(method.delivery_tag, requeue=False)
                    return
                try:
                    channel.basic_publish(
                        exchange="", routing_key=properties.reply_to,
                        body=json.dumps(result).encode(), mandatory=True,
                        properties=pika.BasicProperties(correlation_id=properties.correlation_id,
                                                        content_type="application/json"),
                    )
                except pika.exceptions.UnroutableError:
                    # Client's exclusive reply queue disappeared. There is no useful place for this reply.
                    channel.basic_nack(method.delivery_tag, requeue=False)
                else:
                    channel.basic_ack(method.delivery_tag)

            tag = channel.basic_consume(queue=request_queue, on_message_callback=respond, auto_ack=False)
            ready.set()
            deadline = time.monotonic() + 30
            try:
                while not stop.is_set() and time.monotonic() < deadline:
                    connection.process_data_events(time_limit=0.1)
            finally:
                if channel.is_open:
                    channel.basic_cancel(tag)
    except Exception as exc:
        errors.put(exc)
        ready.set()
"""),
md("""
## 3. Define a client with a deadline

The broker-generated exclusive reply queue belongs to this client's connection and disappears when
it closes. A single connection can handle multiple requests using correlation IDs; this introductory
function handles one request per connection to make cleanup obvious.

For the demonstration, optionally insert an unrelated reply first. Discard replies that do not match
the current correlation ID. A real client with many outstanding calls needs a map of pending IDs instead.
"""),
code("""
def call_square(number, timeout=5.0, inject_unrelated=False):
    correlation_id = str(uuid4())
    with connect() as connection:
        channel = connection.channel()
        reply_queue = channel.queue_declare(queue="", exclusive=True, auto_delete=True).method.queue
        channel.confirm_delivery()
        if inject_unrelated:
            channel.basic_publish(exchange="", routing_key=reply_queue, body=b'{"ok": true, "result": -1}',
                                  properties=pika.BasicProperties(correlation_id="old-request"), mandatory=True)
        channel.basic_publish(
            exchange="", routing_key=request_queue, body=json.dumps({"number": number}).encode(),
            properties=pika.BasicProperties(reply_to=reply_queue, correlation_id=correlation_id,
                                            content_type="application/json", expiration="10000"),
            mandatory=True,
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            method, properties, body = channel.basic_get(queue=reply_queue, auto_ack=False)
            if method is None:
                connection.sleep(0.05)
                continue
            channel.basic_ack(method.delivery_tag)
            if properties.correlation_id == correlation_id:
                return json.loads(body)
            print("Ignored unrelated correlation ID:", properties.correlation_id)
        raise TimeoutError(f"No response within {timeout}s; the request may still run.")
"""),
md("""
## 4. Run successful and invalid requests, then stop the worker

Predict: `12` yields `144`; a string yields a structured error. The fake reply with result `-1` must
not be mistaken for the answer. Start and stop the worker in one cell so it cannot be left running
while you pause to teach. Cleanup in `finally` also runs if an assertion fails.
"""),
code("""
stop, ready, errors = Event(), Event(), Queue()
worker = Thread(target=run_worker, args=(stop, ready, errors), daemon=True)
worker.start()
try:
    assert ready.wait(timeout=10), "Worker did not become ready."
    if not errors.empty():
        raise errors.get()
    answer = call_square(12, inject_unrelated=True)
    invalid = call_square("twelve")
    assert answer == {"ok": True, "result": 144}, answer
    assert invalid["ok"] is False, invalid
    print("Valid request:", answer)
    print("Invalid request:", invalid)
finally:
    stop.set()
    worker.join(timeout=10)
assert not worker.is_alive(), "Worker has not stopped; restart the kernel before retrying."
if not errors.empty():
    raise errors.get()
print("Worker stopped.")
"""),
md("""
## 5. Failure drill: no worker available

The request queue still exists, so publishing succeeds. No worker consumes the request, and the caller
times out. Predict: does publisher confirmation prove that a worker ran? Does a timeout delete the request?
The answers are both no. Its 10-second message TTL limits queued waiting; it is not cancellation of work
already delivered to a worker. Cleanup below deletes this lesson's remaining request.
"""),
code("""
started = time.monotonic()
try:
    call_square(9, timeout=0.6)
except TimeoutError as exc:
    print("Expected failure:", exc)
else:
    raise AssertionError("There should be no worker for this unique request queue.")
print("Elapsed seconds:", round(time.monotonic() - started, 2))
"""),
md("""
## 6. Exercise and suggested solution

Change the service to return the cube. Identify both code locations to change before editing:
the worker's calculation and the client's expected result (`12 ** 3 == 1728`). Keep correlation IDs,
validation, deadlines, and acknowledgement order intact. Rerun the worker definition and demonstration
cell together. The queued timed-out request may be delivered first; its deleted reply queue is handled
by the worker's `UnroutableError` path.

Explain how you would retry a payment request safely. A new correlation ID identifies a network attempt;
a stable **business idempotency key** identifies the payment across retries. Do not charge twice just
because a response was lost. Later Django and outbox lessons make this distinction practical.

## 7. Cleanup

The request queue is unique to this run; deleting it also removes the timed-out request. Reply queues
have already been removed when their owning connections closed.
"""),
code("""
with connect() as connection:
    connection.channel().queue_delete(queue=request_queue)
print("RPC request queue removed.")
"""),
md("""
**Troubleshooting:** a timeout can mean no consumer, slow processing, lost response, or failed worker;
check the worker error queue and broker consumer count. If this notebook was interrupted mid-cell,
restart the kernel before rerunning. The demo worker deliberately has a finite lifetime. Do not share
the Pika connection between its thread and the notebook's thread.

Official references: [request/reply tutorial](https://www.rabbitmq.com/tutorials/tutorial-six-python),
[Pika threading FAQ](https://pika.readthedocs.io/en/stable/faq.html), and
[message TTL](https://www.rabbitmq.com/docs/ttl).
""")])

print("Built six introductory notebooks in", OUT)

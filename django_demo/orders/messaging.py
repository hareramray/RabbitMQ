"""Plain Pika transport; one connection per call (simple, not high throughput)."""
import json
import pika
from django.conf import settings

EXCHANGE = "rmqcourse.orders"
QUEUE = "rmqcourse.orders.process"
DEAD_EXCHANGE = "rmqcourse.orders.dlx"
DEAD_QUEUE = "rmqcourse.orders.dead"
ROUTING_KEY = "order.created"


def connect():
    params = pika.URLParameters(settings.BROKER_URL)
    params.heartbeat = 30
    params.socket_timeout = 5
    params.stack_timeout = 10
    params.blocked_connection_timeout = 10
    params.connection_attempts = 2
    params.retry_delay = 0.5
    return pika.BlockingConnection(params)


def declare_topology(channel):
    channel.exchange_declare(exchange=EXCHANGE, exchange_type="topic", durable=True)
    channel.exchange_declare(exchange=DEAD_EXCHANGE, exchange_type="fanout", durable=True)
    channel.queue_declare(queue=DEAD_QUEUE, durable=True)
    channel.queue_bind(queue=DEAD_QUEUE, exchange=DEAD_EXCHANGE)
    channel.queue_declare(queue=QUEUE, durable=True, arguments={"x-dead-letter-exchange": DEAD_EXCHANGE})
    channel.queue_bind(queue=QUEUE, exchange=EXCHANGE, routing_key=ROUTING_KEY)


def publish_event(event):
    with connect() as connection:
        channel = connection.channel()
        declare_topology(channel)
        channel.confirm_delivery()
        channel.basic_publish(
            exchange=EXCHANGE, routing_key=ROUTING_KEY,
            body=json.dumps(event).encode("utf-8"), mandatory=True,
            properties=pika.BasicProperties(
                content_type="application/json", delivery_mode=2,
                message_id=event["event_id"], type="order.created.v1",
            ),
        )

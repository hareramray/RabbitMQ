# Production design practice

The executable labs focus on understanding delivery and failure behavior. Apply these exercises to a separate environment before treating a design as ready for deployment.

## Identity, permissions and encryption

Use a virtual host per application or trust boundary, distinct service users, and credentials from a secret manager. Replace the teaching administrator account. RabbitMQ permissions separately control resource configuration, writing, and reading; names and regular expressions must match the application's declarations. Topic authorization can add routing-key restrictions. Test denied operations with the application identity instead of assuming a regex is correct. [Access control](https://www.rabbitmq.com/docs/access-control).

Configure broker TLS with a server certificate and trusted CA. Python must verify the CA and hostname. This example is a configuration exercise: set your actual certificate paths and DNS name before connecting to a TLS-enabled broker.

```python
import os
import ssl
import pika

context = ssl.create_default_context(cafile=os.environ['RABBITMQ_CA_FILE'])
parameters = pika.URLParameters(os.environ['RABBITMQ_TLS_URL'])  # amqps://...:5671/vhost
parameters.ssl_options = pika.SSLOptions(context, os.environ['RABBITMQ_TLS_HOSTNAME'])
parameters.heartbeat = 60
parameters.blocked_connection_timeout = 10
# with pika.BlockingConnection(parameters) as connection: ...
```

For mutual TLS also load your client certificate/key using `context.load_cert_chain`. Never disable certificate verification to make a demonstration pass. The default Compose file deliberately uses local plain AMQP; it does not configure TLS. [RabbitMQ TLS guide](https://www.rabbitmq.com/docs/ssl), [Pika TLS example](https://pika.readthedocs.io/en/1.3.2/examples/tls_server_authentication.html).

## Delivery and data ownership

Write a failure matrix for these moments: before database commit, after commit but before publish, after broker acceptance but before publisher sees confirmation, after business commit but before acknowledgement, and after retry publish but before acknowledging the original. For each, state whether loss, duplicate delivery, or both are possible and which component repairs it.

Keep deduplication in the same transaction as the business effect. The course database update is idempotent; external payment, email or HTTP effects would require their own idempotency keys and reconciliation. Agree a deduplication retention period that covers replay and recovery windows. Use explicit event IDs, schema versions and correlation IDs. Unknown versions should be quarantined for inspection rather than silently misinterpreted.

Outbox polling needs monitored backlog age, a bounded retry/backoff policy, and a way to inspect permanently failing rows. The teaching dispatcher stops when publishing fails and is run again manually. A deployed dispatcher needs a supervisor, shutdown behavior and alerting. Holding database row locks while publishing is simple but can increase contention; benchmark before scaling it.

## Reliability and capacity

Use publisher confirms and appropriate mandatory-return handling, manual acknowledgements, bounded prefetch and idempotent consumers. A reconnect does not resolve whether an interrupted publish succeeded. Retry with a stable event ID. Default dead-letter forwarding can lose messages if the target is unavailable; investigate quorum queues with at-least-once dead-lettering and its required configuration when that guarantee is needed. [Confirms](https://www.rabbitmq.com/docs/confirms), [dead lettering](https://www.rabbitmq.com/docs/dlx), [quorum queues](https://www.rabbitmq.com/docs/quorum-queues).

Use a realistic workload: message sizes, processing times, publish rates, consumers, burst duration and database costs. Record p50/p95/p99 latency as well as throughput. Change one parameter at a time; fast publisher-only measurements do not measure end-to-end throughput. Define backpressure behavior before disk or memory alarms block publishers. Set bounded queue length/bytes and overflow behavior deliberately, with acceptance tests for rejected messages. [Resource alarms](https://www.rabbitmq.com/docs/alarms), [queue limits](https://www.rabbitmq.com/docs/maxlength).

Monitor ready/unacknowledged messages, oldest application work age, publish/delivery/ack rates, returns/nacks, connection churn, blocked connections, node disk/memory, outbox backlog and task failures. Alert on symptoms such as increasing processing delay and absent consumers. Use Prometheus/Grafana for sustained monitoring; the management API lesson is an inspection lab. [Monitoring](https://www.rabbitmq.com/docs/monitoring).

## Replication and recovery

Practice majority loss and restoration on the separate three-node cluster. A healthy cluster membership list is not evidence that every queue has three replicas: inspect queue membership. Replication is not backup. Rehearse restoring definitions and application data, reconciling outbox rows, and replaying events without duplicating business effects. Record recovery point and time objectives. [Backup and restore](https://www.rabbitmq.com/docs/backup), [quorum queues](https://www.rabbitmq.com/docs/quorum-queues).

For ordering, distinguish publication order, delivery order and completion order. Multiple consumers, retries, priorities and redelivery can change business completion order. Explore single-active-consumer queues or partitioning by entity when order matters, and measure the capacity tradeoff. For very large replayable logs, compare RabbitMQ Streams with queues; streams use a different consumption/retention model and are beyond the executable core of this course. [Consumer guide](https://www.rabbitmq.com/docs/consumers), [Streams](https://www.rabbitmq.com/docs/streams).

## Review the Django boundary

Add authentication, request idempotency keys, CSRF protection where appropriate, audit records and input/rate limits before exposing the API. The local API is deliberately unauthenticated and its POST route is CSRF-exempt. Run a production application server and supervised workers, manage database migrations separately, and tune Celery concurrency for the actual workload. The course uses a solo Linux worker for predictable demonstrations, not a production concurrency recommendation.

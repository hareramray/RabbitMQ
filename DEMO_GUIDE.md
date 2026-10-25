# Demonstrating the course

Prepare with Docker running, the broker UI open, and the matching notebook kernel selected. Run setup 00 before the audience arrives. Use new order IDs and notebook-generated queue names for every run.

## A 30-minute introduction

1. **00 (5 min):** Draw producer → exchange → queue → consumer. Ask where a message waits when the consumer is stopped.
2. **01 (8 min):** Publish first, inspect the queue, then receive and acknowledge. Show that a queue stores bytes plus properties.
3. **02 (10 min):** Receive without acknowledging, close the connection, then consume again. Ask why the same business operation could happen twice.
4. **03 (7 min):** One publish reaches two queues. Contrast two queues with two consumers sharing one queue.

## A 60-minute Django session

1. **12 (15 min):** Create an order by HTTP. Show its pending state and queue, run the bounded event consumer, then fetch the completed order.
2. **13 (10 min):** Create a Celery order and poll the HTTP endpoint. Point out that RabbitMQ is the broker and Celery supplies the task protocol/worker.
3. **14 (20 min):** Prove `on_commit` does not run on rollback. Create an outbox order; show pending intent before publishing, then dispatch it.
4. **18 (15 min):** Replay the same event and show `fulfillments == 1`. Explain the confirm-to-outbox-update crash window.

## A 90-minute advanced session

Use **07 → 08 → 09 → 10 → 17**. Reserve 20 minutes for the optional cluster startup. Ask the audience to predict every failure outcome before running it. The cluster drill stops one member deliberately and restores it; it should run separately from the ordinary broker.

## Demonstrator habits

- Show both the observed result and the assertion that makes it testable.
- Pause before cleanup if you want the audience to inspect queues. Management rates/counts can lag; a UI snapshot is not proof of processing.
- For a retry, identify whether it is a broker redelivery, an application republish, or a new Celery retry task delivery.
- Distinguish publisher confirmation, consumer acknowledgement, and database commit. They are separate events.
- If interrupted midway, run cleanup if possible, then restart the kernel. The next run has unique standalone queue names. Django rows intentionally remain.
- Keep optional outage switches off during ordinary notebook execution. Restore services after every outage drill.

## Check understanding

Ask learners to explain why durable queues alone are insufficient; why `on_commit` does not solve the DB/broker atomicity problem; what happens if a consumer commits then loses its acknowledgement; why retries need a budget; and why a two-member quorum cannot tolerate one unavailable member. Have them locate the specific code cell that demonstrates each answer.

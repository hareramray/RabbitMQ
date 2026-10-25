# RabbitMQ practical course — Python and Django

Learn by publishing messages, inspecting queues, breaking a flow, and repairing it. This repository contains **19 Jupyter notebooks**, a working Django order-processing project, Linux Celery workers, and an optional three-node RabbitMQ lab.

Start with [00 — Setup and mental model](notebooks/00_setup_and_mental_model.ipynb). Read the explanation before a cell, predict its result, run it, and compare with the expected observation. Exercises include suggested solutions. The examples are local teaching applications, not deployment templates.

## Start on Windows (PowerShell)

Install Python **3.12 or 3.13** and [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/) with Linux containers. Start Docker Desktop. Run the following in this repository directory. The explicit Python path avoids PowerShell activation-policy issues.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
Copy-Item .env.example .env
docker compose up -d --wait rabbitmq
.\.venv\Scripts\python.exe -m ipykernel install --sys-prefix --name python3 --display-name "RabbitMQ course"
.\.venv\Scripts\python.exe -m jupyterlab
```

If `.venv` or `.env` already exists, reuse it; do not overwrite your customized environment file. In JupyterLab open `notebooks/00_setup_and_mental_model.ipynb` and select **RabbitMQ course**. Run cells from top to bottom. Keep the Jupyter terminal open.

For notebooks **12–15 and 18**, also start the Django stack:

```powershell
docker compose up -d --build --wait
docker compose logs --tail 30 worker
```

`--wait` waits for the broker, database and HTTP health checks; confirm the worker log says `ready` before Celery exercises. The first build downloads images and dependencies. Celery runs inside Linux containers because [Celery does not support Windows](https://docs.celeryq.dev/en/stable/getting-started/introduction.html).

## Start on macOS or Linux

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
cp .env.example .env
docker compose up -d --wait rabbitmq
.venv/bin/python -m ipykernel install --sys-prefix --name python3 --display-name "RabbitMQ course"
.venv/bin/python -m jupyterlab
# Before the Django lessons:
docker compose up -d --build --wait
```

## Course map

| Notebook | Level | Practical demonstration |
| --- | --- | --- |
| [00 Setup](notebooks/00_setup_and_mental_model.ipynb) | Beginner | Environment checks, message vocabulary, inspect broker |
| [01 First message](notebooks/01_messaging_basics.ipynb) | Beginner | Publish JSON, receive, acknowledge |
| [02 Work queues](notebooks/02_work_queues_and_acknowledgements.ipynb) | Beginner | Competing workers, unacknowledged message redelivery |
| [03 Fanout](notebooks/03_publish_subscribe_fanout.ipynb) | Beginner | One event, independent subscribers |
| [04 Direct routing](notebooks/04_direct_routing.ipynb) | Beginner | Exact routing keys and unrouted messages |
| [05 Topics and headers](notebooks/05_topic_and_headers_routing.ipynb) | Intermediate | Wildcards and header-based routing |
| [06 RPC](notebooks/06_rpc.ipynb) | Intermediate | Reply queues, correlation IDs, timeouts |
| [07 Durability and confirms](notebooks/07_durability_and_confirms.ipynb) | Intermediate | Persistence, confirmations and mandatory returns |
| [08 Dead letters and retries](notebooks/08_dead_letters_ttl_retries.ipynb) | Intermediate | TTL, delayed bounded retries, parking poison messages |
| [09 Idempotency](notebooks/09_idempotent_consumers.ipynb) | Advanced | Atomic business updates and deduplication |
| [10 Prefetch and concurrency](notebooks/10_prefetch_and_concurrency.ipynb) | Advanced | Push consumers, in-flight limits, multiple workers |
| [11 Async and recovery](notebooks/11_asyncio_and_recovery.ipynb) | Advanced | aio-pika and reconnect behavior |
| [12 Django publishing](notebooks/12_django_direct_publishing.ipynb) | Intermediate | HTTP request → RabbitMQ → database consumer |
| [13 Django and Celery](notebooks/13_django_celery.ipynb) | Intermediate | Background jobs and observable state changes |
| [14 Transactions and outbox](notebooks/14_transactions_and_outbox.ipynb) | Advanced | Commit timing, rollback, durable publishing intent |
| [15 Celery workflows](notebooks/15_celery_workflows.ipynb) | Advanced | Chains, groups, retrying tasks and result tracking |
| [16 Monitoring and performance](notebooks/16_monitoring_and_performance.ipynb) | Advanced | Queue metrics and measured throughput |
| [17 Quorum queues](notebooks/17_quorum_queues_and_failover.ipynb) | Expert practice | Replication, majority availability, optional real failover |
| [18 Capstone](notebooks/18_capstone_order_pipeline.ipynb) | Expert practice | Outbox → confirmed publish → idempotent order processing |

Allow roughly 20–45 minutes per ordinary lesson and 60–90 minutes for a failure drill or capstone. These are planning estimates. You need basic Python functions, dictionaries and exceptions; the notebooks introduce messaging and explain the Django pieces as they appear. Work through 01–10 before the Django reliability lessons.

## What runs where

```text
Host: Jupyter notebooks / Pika / aio-pika
  ├── localhost:5672  → RabbitMQ container (vhost: learning)
  ├── localhost:15672 → RabbitMQ management UI / HTTP API
  └── localhost:8000  → Django web container
                           ├── PostgreSQL container
                           └── RabbitMQ → Celery worker container

Django outbox table → dispatch_outbox → RabbitMQ → consume_events → orders table
```

The management UI is <http://localhost:15672>, username **student**, password **student-local-only**. Django health is <http://localhost:8000/health/>. Ports bind only to `127.0.0.1`. PostgreSQL is internal to Compose. Standalone notebooks use unique `rmqcourse.*` resource names. The Django lessons share a fixed topology and retain orders for inspection.

`course/rabbit.py` contains connection settings and bounded polling only; the notebooks show the AMQP operations directly. Each thread owns its own Pika connection. Polling examples use `basic_get`; the prefetch lesson uses push consumption because QoS does not limit polling. [RabbitMQ acknowledgements reference](https://www.rabbitmq.com/docs/confirms).

## Present it live

Use [DEMO_GUIDE.md](DEMO_GUIDE.md) for short presentation routes, predictions to ask the audience, and recovery steps. Keep the management UI alongside the notebook. Run one notebook at a time, and use **Restart Kernel and Run All** for a clean repeat. Execute the cleanup cells before switching lessons. Optional crash drills require explicit steps and are skipped by ordinary Run All.

The durable Django queues and database intentionally keep state between lessons. They are not auto-purged. The capstone uses newly created order IDs to remain repeatable. Do not start a background `consume_events` process while demonstrating pending states; invoke the bounded command from each lesson.

## Verify and diagnose

Windows commands (on Unix replace `.\.venv\Scripts\python.exe` with `.venv/bin/python`):

```powershell
.\.venv\Scripts\python.exe scripts/check_environment.py
.\.venv\Scripts\python.exe scripts/validate_notebooks.py
.\.venv\Scripts\python.exe django_demo/manage.py check
.\.venv\Scripts\python.exe django_demo/manage.py test orders
# Integration execution requires running Docker services and the course kernel:
.\.venv\Scripts\python.exe scripts/run_notebooks.py --pattern '0[1-6]_*.ipynb'
```

`run_notebooks.py` saves executed copies in `artifacts/executed/`, including failed cells for diagnosis. It leaves source notebooks clean. See [VALIDATION.md](VALIDATION.md) for what was actually checked during creation.

| Symptom | Check / fix |
| --- | --- |
| `docker` not recognized | Install Docker Desktop, start it, reopen the terminal |
| Docker daemon unavailable | Start Docker Desktop and select Linux containers |
| Port 5672/15672/8000 already allocated | Stop the conflicting local service or change Compose mappings and `.env` together |
| `ModuleNotFoundError` | Select the course kernel; install using that interpreter |
| AMQP connection refused | `docker compose ps` and `docker compose logs --tail 50 rabbitmq` |
| Authentication / vhost access refused | Check `.env` and the `learning` vhost; existing volumes retain their original credentials |
| `PRECONDITION_FAILED` | Same queue/exchange name was redeclared with different properties; restart the notebook for fresh names |
| Celery task stays pending | Check worker logs, broker URL, queue `celery`, and that the task name is registered |
| Django order remains pending | Run the correct consumer (`consume_events` for direct/outbox; Celery worker for celery mode) |
| Async event loop error | Use the notebook's top-level `await`; do not wrap it in `asyncio.run()` |
| Timeout after an optional outage | Restart the affected service, wait for readiness, then restart the lesson |

## Stop and reset

```powershell
docker compose stop
# Resume later; data remains:
docker compose up -d --wait
# Remove course containers/network while preserving volumes:
docker compose down
```

For a deliberate full course reset, `docker compose down --volumes` also deletes **all course orders, outbox rows, queues and messages in these Compose volumes**. Only run it when you want to discard this lab data. The optional cluster has separate stop/reset commands in notebook 17.

## Versions and further practice

Baseline: RabbitMQ 4.2.9 management, Python 3.12/3.13, Django 5.2, Celery 5.6, Pika 1.3.2. Exact Python dependencies are in `requirements.lock`; Docker uses `requirements-runtime.lock`. The two `.txt` files describe intended version ranges. Refresh locks deliberately with `uv pip compile ... --python-version 3.12 --universal`, then rerun validation and the live labs.

See [PRODUCTION_PRACTICE.md](PRODUCTION_PRACTICE.md) for TLS, permissions, observability, capacity, disaster recovery, and design review exercises. A single broker demonstrates quorum queue APIs but **does not demonstrate high availability**; use the optional three-node exercise for that. The course teaches at-least-once processing and idempotency, not an exactly-once transport guarantee.

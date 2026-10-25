# Validation record

Checked on 25 October 2026 in the supplied Windows workspace using Python 3.13.15 and the local `.venv`.

## Completed checks

- Installed the exact dependencies from `requirements.lock` into `.venv`.
- Registered the **RabbitMQ course** Jupyter kernel inside that environment.
- Executed the setup notebook's three offline code cells in a real Jupyter kernel; dependency checks, port diagnostics and JSON serialization passed.
- Exported setup and capstone notebooks to HTML as a rendering smoke check, and checked that local guide links resolve.
- Validated all **19 notebooks** against nbformat and compiled all **121 Python code cells**, including top-level `await` cells. Source notebooks have no saved execution outputs.
- Compiled the helper, Django and notebook-generation Python files.
- Ran Django system checks: no issues.
- Ran `makemigrations --check --dry-run`: no missing migrations.
- Ran **14 Django tests** successfully against an isolated SQLite test database. Broker calls are mocked in those tests.
- Verified task arithmetic and finite retry success/exhaustion in Celery eager mode, without a broker.
- Executed the standalone SQLite deduplication/rollback demonstration without a broker.
- Parsed both Compose YAML files and checked their service definitions. This is YAML validation, not `docker compose config` validation.

The Django tests cover validation, order/outbox atomicity, deferred publication, failed publication after DB commit, retained pending events after publish failure, the successful-publish/failed-DB-mark duplicate window, replay, and rollback of deduplication when the business effect fails.

## Still requires a live lab

Docker was not installed or available on PATH. No RabbitMQ listener was available at localhost:5672, and no Django HTTP service was available at localhost:8000. Therefore these have **not** been verified end to end in this workspace:

- Docker image builds, Compose health/startup and PostgreSQL locking/concurrent dispatch.
- Actual AMQP delivery, confirms, retry TTL/dead-letter behavior and queue cleanup.
- Live Celery worker routing, RPC result collection and Canvas workflows.
- Broker restart recovery, three-node cluster formation, leader failover and majority loss.
- Measured performance results, which must come from the learner's own run.

Source notebooks intentionally contain assertions and observation points instead of fabricated output. Optional service-disruption drills default to disabled and need explicit manual steps.

## Reproduce the checks

From PowerShell at the repository root:

```powershell
.\.venv\Scripts\python.exe scripts/validate_notebooks.py
.\.venv\Scripts\python.exe django_demo/manage.py check
.\.venv\Scripts\python.exe django_demo/manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe django_demo/manage.py test orders
```

After installing/starting Docker Desktop with Linux containers:

```powershell
docker compose config --quiet
docker compose -f compose.cluster.yaml config --quiet
docker compose up -d --build --wait
docker compose logs --tail 30 worker
.\.venv\Scripts\python.exe scripts/run_notebooks.py
```

Wait for the worker's `ready` log before running the notebooks. The runner executes each notebook in a fresh kernel and saves executed copies under `artifacts/executed/`. Optional restart/failover drills are skipped unless you explicitly enable and perform them. To verify those drills, follow notebooks 07, 11 and 17 interactively.

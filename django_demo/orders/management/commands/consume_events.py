import json
import time
from django.core.management.base import BaseCommand, CommandError
from orders.messaging import QUEUE, connect, declare_topology
from orders.services import process_event


class Command(BaseCommand):
    help = "Bounded teaching consumer. Ack only after the database transaction commits."

    def add_arguments(self, parser):
        parser.add_argument("--max-messages", type=int, default=100)
        parser.add_argument("--timeout", type=float, default=5)

    def handle(self, *args, **options):
        if options["max_messages"] < 1 or options["timeout"] <= 0:
            raise CommandError("Use positive --max-messages and --timeout")
        processed = rejected = 0
        with connect() as connection:
            channel = connection.channel()
            declare_topology(channel)
            deadline = time.monotonic() + options["timeout"]
            while processed + rejected < options["max_messages"] and time.monotonic() < deadline:
                method, properties, body = channel.basic_get(queue=QUEUE, auto_ack=False)
                if method is None:
                    connection.process_data_events(time_limit=0.1)
                    continue
                try:
                    result = process_event(json.loads(body))
                except (ValueError, UnicodeError):
                    channel.basic_nack(method.delivery_tag, requeue=False)
                    rejected += 1
                except Exception as exc:
                    # Stop after requeue to avoid a tight retry loop during DB failure.
                    channel.basic_nack(method.delivery_tag, requeue=True)
                    raise CommandError("Processing failed; message requeued for a later run") from exc
                else:
                    channel.basic_ack(method.delivery_tag)
                    processed += 1
                    self.stdout.write(json.dumps(result))
        self.stdout.write(json.dumps({"processed": processed, "rejected": rejected}))

import json
import time
from django.core.management.base import BaseCommand, CommandError
from orders.services import dispatch_pending


class Command(BaseCommand):
    help = "Publish pending outbox rows. --once is bounded; Ctrl+C stops continuous mode."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        if options["limit"] < 1:
            raise CommandError("--limit must be positive")
        try:
            while True:
                sent = dispatch_pending(options["limit"])
                self.stdout.write(json.dumps({"published": sent}))
                if options["once"]:
                    return
                time.sleep(1)
        except KeyboardInterrupt:
            self.stdout.write("Dispatcher stopped")

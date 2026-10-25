import uuid
import django.db.models.deletion
from django.db import migrations, models

class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(name="Order", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("event_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
            ("product", models.CharField(max_length=120)),
            ("quantity", models.PositiveIntegerField()),
            ("mode", models.CharField(max_length=12)),
            ("status", models.CharField(default="pending", max_length=12)),
            ("fulfillments", models.PositiveIntegerField(default=0)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
        ]),
        migrations.CreateModel(name="Outbox", fields=[
            ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ("payload", models.JSONField()),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("published_at", models.DateTimeField(blank=True, null=True)),
            ("order", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="outbox_events", to="orders.order")),
        ]),
        migrations.CreateModel(name="ProcessedEvent", fields=[
            ("event_id", models.UUIDField(primary_key=True, serialize=False)),
            ("processed_at", models.DateTimeField(auto_now_add=True)),
            ("order", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="orders.order")),
        ]),
    ]

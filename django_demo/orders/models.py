import uuid
from django.db import models


class Order(models.Model):
    event_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    product = models.CharField(max_length=120)
    quantity = models.PositiveIntegerField()
    mode = models.CharField(max_length=12)
    status = models.CharField(max_length=12, default="pending")
    fulfillments = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)


class Outbox(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="outbox_events")
    payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)


class ProcessedEvent(models.Model):
    event_id = models.UUIDField(primary_key=True)
    order = models.ForeignKey(Order, on_delete=models.CASCADE)
    processed_at = models.DateTimeField(auto_now_add=True)

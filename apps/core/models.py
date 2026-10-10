import uuid

from django.db import models


class UUIDModel(models.Model):
    """PK UUID: ids não enumeráveis nas URLs (defesa em profundidade; o escopo continua sendo validado)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class TimestampedModel(UUIDModel):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

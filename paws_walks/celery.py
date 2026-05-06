import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "paws_walks.settings")

app = Celery("paws_walks")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

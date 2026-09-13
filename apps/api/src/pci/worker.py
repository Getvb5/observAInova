import dramatiq
from dramatiq.brokers.redis import RedisBroker

from pci.settings import Settings

broker = RedisBroker(url=Settings().redis_url)  # type: ignore[no-untyped-call,call-arg]
dramatiq.set_broker(broker)

# Import after installing the broker so the actor is discoverable by the real
# ``dramatiq pci.worker`` process and bound to the configured Redis broker.
from pci.ingestion import tasks as ingestion_tasks

harvest_source_task = ingestion_tasks.harvest_source_task


@dramatiq.actor(queue_name="bootstrap")
def bootstrap_worker() -> None:
    """Reserve a queue for platform bootstrap work without adding domain behavior."""

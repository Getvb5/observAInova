import dramatiq
from dramatiq.actor import Actor
from dramatiq.brokers.redis import RedisBroker

from pci.settings import Settings

broker = RedisBroker(url=Settings().redis_url)  # type: ignore[no-untyped-call,call-arg]
dramatiq.set_broker(broker)

# Import after installing the broker so the actor is discoverable by the real
# ``dramatiq pci.worker`` process and bound to the configured Redis broker.
from pci.claims import tasks as claim_tasks
from pci.documents import tasks as document_tasks
from pci.ingestion import tasks as ingestion_tasks
from pci.publication import tasks as publication_tasks


def _bind_to_worker_broker(actor: Actor) -> Actor:  # type: ignore[type-arg]
    """Rebind actors that an embedding process imported before the worker bootstrap."""
    if actor.broker is not broker:
        actor.broker = broker
        broker.declare_actor(actor)  # type: ignore[no-untyped-call]
    return actor


extract_document_task = _bind_to_worker_broker(claim_tasks.extract_document_task)
harvest_source_task = _bind_to_worker_broker(ingestion_tasks.harvest_source_task)
prepare_document_text_task = _bind_to_worker_broker(document_tasks.prepare_document_text_task)
process_publication_event_task = _bind_to_worker_broker(
    publication_tasks.process_publication_event_task
)


@dramatiq.actor(queue_name="bootstrap")
def bootstrap_worker() -> None:
    """Reserve a queue for platform bootstrap work without adding domain behavior."""

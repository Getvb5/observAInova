import uuid

import dramatiq

from pci.db import session_scope
from pci.publication.service import process_publication_event


@dramatiq.actor(queue_name="publication", max_retries=5)
def process_publication_event_task(event_id: str, attempt_token: str) -> None:
    with session_scope() as session:
        process_publication_event(session, uuid.UUID(event_id), attempt_token)

import time
from collections.abc import Sequence
from typing import Protocol

from pci.db import session_scope
from pci.publication.service import claim_next_publication_event
from pci.settings import Settings


class EventSender(Protocol):
    def send(self, event_id: str, attempt_token: str) -> object: ...


def relay_once(sender: EventSender, *, lease_seconds: int = 300) -> bool:
    with session_scope() as session:
        event = claim_next_publication_event(session, lease_seconds=lease_seconds)
        if event is None:
            return False
        event_id = str(event.id)
        attempt_token = event.attempt_token
        if attempt_token is None:
            raise RuntimeError("claimed publication event has no attempt token")
    sender.send(event_id, attempt_token)
    return True


def run_forever() -> None:
    from pci.worker import process_publication_event_task

    settings = Settings()  # type: ignore[call-arg]
    while True:
        relayed = relay_once(
            process_publication_event_task,
            lease_seconds=settings.publication_lease_seconds,
        )
        if not relayed:
            time.sleep(settings.publication_relay_interval_seconds)


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

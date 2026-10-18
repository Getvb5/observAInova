from pci.models.publication import OutboxStatus


def test_outbox_statuses_are_closed() -> None:
    assert {item.value for item in OutboxStatus} == {
        "pending", "processing", "completed", "failed"
    }

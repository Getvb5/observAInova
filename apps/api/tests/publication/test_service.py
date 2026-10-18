from pci.models.publication import PublicationAction


def test_publication_actions_are_closed() -> None:
    assert {item.value for item in PublicationAction} == {
        "return", "publish", "supersede", "revoke"
    }

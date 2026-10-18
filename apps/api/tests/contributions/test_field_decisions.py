from pci.claims.enums import ContributionField
from pci.contributions.service import governed_fields


def test_all_fourteen_scientific_fields_are_governed() -> None:
    assert governed_fields() == tuple(ContributionField)
    assert len(governed_fields()) == 14

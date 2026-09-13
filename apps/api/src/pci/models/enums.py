from enum import StrEnum


class TerritoryRelation(StrEnum):
    PRODUCED_IN_PE = "produced_in_pe"
    ABOUT_PE = "about_pe"


class RecordVisibility(StrEnum):
    PRIVATE = "private"
    METADATA_PUBLIC = "metadata_public"


class HarvestStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class RightsPolicy(StrEnum):
    METADATA_ONLY = "metadata_only"
    LINK_ONLY = "link_only"
    OPEN_COPY = "open_copy"
    INSTITUTION_AUTHORIZED_COPY = "institution_authorized_copy"


class ProductionType(StrEnum):
    ARTICLE = "article"
    THESIS = "thesis"
    DISSERTATION = "dissertation"
    UNDERGRADUATE_WORK = "undergraduate_work"
    BOOK = "book"
    BOOK_CHAPTER = "book_chapter"
    CONFERENCE_PAPER = "conference_paper"
    TECHNICAL_REPORT = "technical_report"
    RESEARCH_PROJECT = "research_project"
    PATENT = "patent"
    SOFTWARE = "software"
    DATASET = "dataset"
    PROTOCOL = "protocol"
    METHOD = "method"
    PROCESS = "process"
    SOCIAL_TECHNOLOGY = "social_technology"
    EDUCATIONAL_PRODUCT = "educational_product"
    TECHNICAL_PRODUCT = "technical_product"
    OTHER = "other"


def enum_values(enum_class: type[StrEnum]) -> list[str]:
    return [item.value for item in enum_class]

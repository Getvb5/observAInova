import re
import unicodedata

WHITESPACE = re.compile(r"\s+")


def normalize_display(value: str) -> str:
    """Return stable NFC display text while retaining accents and letter case."""
    return WHITESPACE.sub(" ", unicodedata.normalize("NFC", value)).strip()


def exact_text_key(value: str) -> str:
    return normalize_display(value).casefold()


def fuzzy_text_key(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", normalize_display(value).casefold())
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return WHITESPACE.sub(" ", without_marks).strip()


def trigram_similarity(left: str, right: str) -> float:
    left_trigrams = _trigrams(fuzzy_text_key(left))
    right_trigrams = _trigrams(fuzzy_text_key(right))
    if not left_trigrams and not right_trigrams:
        return 1.0
    if not left_trigrams or not right_trigrams:
        return 0.0
    return (2.0 * len(left_trigrams & right_trigrams)) / (len(left_trigrams) + len(right_trigrams))


def _trigrams(value: str) -> set[str]:
    padded = f"  {value} "
    return {padded[index : index + 3] for index in range(len(padded) - 2)}

from difflib import SequenceMatcher
import re
import unicodedata
from urllib.parse import unquote


def clean_doi(value: str) -> str:
    value = unquote(re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value.strip(), flags=re.I))
    if value and not re.fullmatch(r"10\.\d{4,9}/\S+", value, re.I):
        raise ValueError(f"DOI 格式错误：{value}")
    return value.lower()


def normalize_title(value: str) -> str:
    text = unicodedata.normalize("NFKD", value)
    text = "".join(c for c in text if not unicodedata.combining(c)).casefold()
    text = re.sub(r"[\W_]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def title_similarity(expected: str, actual: str) -> float:
    left = normalize_title(expected)
    right = normalize_title(actual)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    return SequenceMatcher(None, left, right).ratio()

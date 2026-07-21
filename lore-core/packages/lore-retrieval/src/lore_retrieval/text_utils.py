"""Shared tokenizer used by the offline fakes and feasibility scoring.

One definition so scoring can't silently desync between modules. Callers that
need a set do ``set(tokenize(text))``.
"""
import re

_TOKEN = re.compile(r"\w+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text)]

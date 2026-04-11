"""
Wing name extraction from a set of paper titles / abstracts.

Produces two names:
  - slug  : short, command-safe (e.g. "diffusion-ode-sampling")
  - label : longer human-readable description (e.g. "Diffusion Models & ODE-based Sampling")

Strategy (no external LLM required):
  1. Tokenise all titles into lowercase words.
  2. Remove stop-words and very short tokens.
  3. Score by TF (term frequency across all titles).
  4. Pick top-N content words.
  5. Build slug from top-3 words; label from top-5 capitalized.
"""

from __future__ import annotations

import re
import string
from collections import Counter
from typing import Sequence


# A minimal English stop-word list (no NLTK dependency)
_STOP = frozenset("""
a an the and or but if in on at to of for with by from as is are was were be been
being have has had do does did will would could should may might shall can this that
these those it its we our they their them we i you your he she his her we us
via using through across between among over under new novel learning based
model models method methods approach approaches study analysis using using
""".split())

_PUNCT = re.compile(r"[^\w\s\-]")
_MULTI_DASH = re.compile(r"-{2,}")


def extract_wing_names(
    titles: Sequence[str],
    abstracts: Sequence[str] | None = None,
    top_n: int = 6,
) -> tuple[str, str]:
    """
    Return (slug, label) derived from the provided titles (and optionally abstracts).

    slug  — lowercase, hyphen-separated, ≤ 40 chars, safe for CLI argument
    label — Title-cased phrase, ≤ 72 chars
    """
    texts = list(titles)
    if abstracts:
        # Abstracts count less — take only first sentence of each
        for ab in abstracts:
            first_sentence = re.split(r"(?<=[.!?])\s", ab.strip())[0]
            texts.append(first_sentence)

    counter: Counter = Counter()
    for text in texts:
        tokens = _tokenise(text)
        # Bigrams from titles only get a small boost
        for tok in tokens:
            counter[tok] += 1

    # Filter stop-words and short tokens, keep top_n
    keywords = [
        w for w, _ in counter.most_common(top_n * 4)
        if w not in _STOP and len(w) >= 4
    ][:top_n]

    if not keywords:
        keywords = ["research"]

    slug_words = keywords[:3]
    label_words = keywords[:5]

    slug = _MULTI_DASH.sub("-", "-".join(slug_words))[:40].strip("-")
    label = " ".join(w.capitalize() for w in label_words)[:72]

    return slug, label


def _tokenise(text: str) -> list[str]:
    text = _PUNCT.sub(" ", text.lower())
    return [
        tok.strip("-")
        for tok in text.split()
        if tok.strip("-") and not tok.replace("-", "").isdigit()
    ]


def slug_from_label(label: str) -> str:
    """Convert a free-form label string to a slug."""
    label = label.lower().strip()
    label = _PUNCT.sub("-", label)
    label = re.sub(r"\s+", "-", label)
    label = _MULTI_DASH.sub("-", label)
    return label[:40].strip("-")

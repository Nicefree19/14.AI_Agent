"""W5 — TF-weighted memory search scoring.

Pure scoring module.  stdlib only (no external deps).
No circular-import risk: does NOT import from telegram_bot / config.

Feature flag ``rag_search`` is checked at the *call sites* inside
telegram_bot.py, NOT in this module.  Every function here is stateless
and side-effect-free.
"""

from __future__ import annotations

# ────────────────────────────────────────────────────────────
#  Constants
# ────────────────────────────────────────────────────────────

# Korean particles — longest first so "에서" is tried before single-char "서".
KOREAN_PARTICLES: list[str] = [
    "에서", "으로",                         # 2-char
    "를", "을", "이", "가", "은", "는",     # 1-char (case markers)
    "와", "과", "도", "만", "의",           # 1-char (auxiliaries)
]

# Index-field weights for TF scoring.
# Higher weight = more influence on final relevance score.
FIELD_WEIGHTS: dict[str, float] = {
    "instruction":    2.0,   # what the user asked — highest signal
    "keywords":       1.5,   # pre-extracted index terms
    "topics":         1.5,   # semantic category tags
    "result_summary": 1.0,   # what was done
    "files":          0.5,   # output filenames — lowest signal
}


# ────────────────────────────────────────────────────────────
#  Public API
# ────────────────────────────────────────────────────────────

def strip_particles(word: str) -> str:
    """Remove trailing Korean particles from *word*.

    >>> strip_particles("물량을")
    '물량'
    >>> strip_particles("6층에서")
    '6층'
    >>> strip_particles("을")       # would become empty → keep original
    '을'
    """
    for particle in KOREAN_PARTICLES:
        plen = len(particle)
        if len(word) > plen and word.endswith(particle):
            return word[:-plen]
    return word


def tokenize_query(
    text: str,
    stopwords: set[str] | None = None,
) -> list[str]:
    """Tokenize *text* into deduplicated, particle-stripped tokens.

    Steps:
      1. Lower-case + split on whitespace
      2. Strip punctuation wrapper
      3. Filter short (< 2 char) and stopwords
      4. Apply :func:`strip_particles`
      5. Deduplicate (preserving insertion order)

    Returns at most **10** tokens.
    """
    if stopwords is None:
        stopwords = set()

    seen: set[str] = set()
    tokens: list[str] = []

    for raw in text.lower().replace("\n", " ").split():
        w = raw.strip("[]()\"'.,!?:;")
        if len(w) < 2 or w in stopwords:
            continue
        w = strip_particles(w)
        if len(w) < 1 or w in seen:
            continue
        seen.add(w)
        tokens.append(w)
        if len(tokens) >= 10:
            break

    return tokens


def score_task(
    task_meta: dict,
    query_tokens: list[str],
    field_weights: dict[str, float] | None = None,
) -> float:
    """Return a TF-weighted relevance score for one index task entry.

    Algorithm per field::

        field_text   = normalize(task[field])   # list → join, lower
        field_tokens = {w, strip_particles(w) for w in field_text.split()}
        matches      = count(qt in field_text or qt in field_tokens
                             for qt in query_tokens)
        tf           = matches / len(query_tokens)
        field_score  = tf * weight

    Total score = sum of field scores.  Max possible ≈ 6.5.
    """
    if not query_tokens:
        return 0.0

    weights = field_weights or FIELD_WEIGHTS
    total = 0.0

    for field_name, weight in weights.items():
        raw = task_meta.get(field_name, "")

        # normalise to lowercase text
        if isinstance(raw, list):
            field_text = " ".join(str(v) for v in raw).lower()
        else:
            field_text = str(raw).lower()

        # build token set (original + particle-stripped) for exact-token matching
        field_tokens: set[str] = set()
        for w in field_text.split():
            field_tokens.add(w)
            stripped = strip_particles(w)
            if stripped != w:
                field_tokens.add(stripped)

        # count how many query tokens appear in this field
        matches = 0
        for qt in query_tokens:
            if qt in field_text or qt in field_tokens:
                matches += 1

        tf = matches / len(query_tokens)
        total += tf * weight

    return round(total, 4)


def rank_tasks(
    tasks: list[dict],
    query_tokens: list[str],
    min_score: float = 0.0,
    field_weights: dict[str, float] | None = None,
) -> list[tuple[dict, float]]:
    """Score and rank *tasks*, returning ``[(task, score), ...]``.

    Results are sorted by **score descending**.  Ties are broken by
    ``message_id`` descending (more recent first).

    Only tasks with ``score > min_score`` are included.
    """
    if not query_tokens:
        return []

    scored: list[tuple[dict, float]] = []
    for task in tasks:
        s = score_task(task, query_tokens, field_weights)
        if s > min_score:
            scored.append((task, s))

    scored.sort(key=lambda x: (-x[1], -x[0].get("message_id", 0)))
    return scored

"""Build human-readable descriptions from source metadata.

The radar must never present a templated sentence as if it were a description.
Boilerplate is worse than an empty string for two reasons:

1. It tells the reader nothing that the source and event chips do not already say.
2. `score_item` reads `summary`, so a template that contains taxonomy words
   ("dataset", "benchmark") makes the pipeline score itself on its own prose and
   inflates relevance for every record from that source.

So every helper here returns text drawn from the upstream payload, or "" when the
upstream genuinely published nothing. Callers must treat "" as "no description
available" rather than substituting a filler sentence.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
from typing import Any

# Card text arrives as rendered markdown: tabs, collapsed headings, badge alt
# text. Keep the first real sentence(s) and drop the scaffolding.
_WHITESPACE = re.compile(r"\s+")
# Images first: a badge is often an image wrapped in a link, and removing the
# inner image leaves the outer link matchable rather than a stray "](url)".
_MARKDOWN_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MARKDOWN_NOISE = re.compile(
    r"""
    \[([^\]]*)\]\([^)]*\)   # links: keep the visible label, drop the target
    | <[^>]+>               # inline html
    | ^\s*[#>*-]+\s*        # heading / quote / bullet markers
    | [*_`]{1,3}            # emphasis and code ticks
    """,
    re.VERBOSE | re.MULTILINE,
)
# YAML front matter in a dataset card is metadata, not description prose.
_FRONT_MATTER = re.compile(r"\A\s*---.*?\n---\s*", re.DOTALL)

# Keep enough upstream prose for useful inline expansion while bounding the
# static payload. The UI links to the full source/card for anything beyond it.
MAX_SUMMARY_CHARS = 2_000


def clean_card_text(text: str | None) -> str:
    """Reduce a dataset/model card to plain prose, or "" if nothing survives."""
    if not text:
        return ""
    stripped = _FRONT_MATTER.sub("", text)
    stripped = _MARKDOWN_IMAGE.sub(" ", stripped)
    # Link labels are real prose, so keep group 1; other alternatives have no
    # group and collapse to a space.
    stripped = _MARKDOWN_NOISE.sub(lambda match: match.group(1) or " ", stripped)
    collapsed = _WHITESPACE.sub(" ", stripped).strip()
    if len(collapsed) <= MAX_SUMMARY_CHARS:
        return collapsed
    # Prefer a sentence boundary so the text does not end mid-word.
    window = collapsed[: MAX_SUMMARY_CHARS + 1]
    cut = max(window.rfind(". "), window.rfind("! "), window.rfind("? "))
    if cut > MAX_SUMMARY_CHARS // 3:
        return window[: cut + 1].strip()
    return collapsed[:MAX_SUMMARY_CHARS].rsplit(" ", 1)[0].strip() + "…"


# A release row answers one question: what does this benchmark measure? The
# upstream prose that answers it is an abstract or a card body, which opens with
# scaffolding ("Abstract", "[CVPR 2025]", "In this paper, we") and runs to
# thousands of characters. These bounds reduce it to a line that fits a row
# without inventing a word: everything returned is upstream text, selected and
# trimmed, never rewritten.
MAX_HEADLINE_CHARS = 140
# Below this a line says nothing a reader could use ("Abstract.", "See below.").
MIN_HEADLINE_CHARS = 20
# A truncated line has to carry a clause worth reading, or the empty state is
# more honest than a stub ending in an ellipsis.
MIN_TRUNCATED_HEADLINE_CHARS = 40

# Section headings survive card and abstract rendering as bare words, because
# the markup that made them headings is gone by the time this sees the text.
# Every word here is also an ordinary English noun that can open a real
# sentence, so matching the word is not evidence of a heading. The evidence is
# what is LEFT: a heading is followed by the start of a sentence, so the
# remainder begins with a capital or a digit ("Abstract Multimodal imaging is
# ...", "PURPOSE OF REVIEW Systemic sclerosis ..."), while a subject is followed
# by its own predicate in lower case ("Results on the new benchmark show ...",
# "Summary statistics for the dataset are ..."). Checking the word alone removed
# the subject from one real record in roughly every 430 with a summary.
#
# Known residual: a title-case noun phrase that opens on one of these words,
# such as "Abstract Syntax Trees are used ...", loses that word. That leaves a
# readable sentence missing a word rather than a sentence missing its subject,
# which is the trade this rule is chosen for.
#
# The optional leading `and` lets the repeated strip clear a compound heading
# one word at a time: "BACKGROUND AND OBJECTIVE" drops "BACKGROUND", then the
# next pass drops "AND OBJECTIVE" rather than opening the line on a conjunction.
# `(?:\s+of\s+\w+)?` catches the journal forms that are two words plus an
# object -- "PURPOSE OF REVIEW", "STATEMENT OF PROBLEM".
_LEAD_HEADING = re.compile(
    r"\A(?:and\s+)?"
    r"(?:abstract|background|summary|introduction|overview|description|objectives?"
    r"|purpose|statement|aims?|methods?|results?|conclusions?"
    r"|dataset(?:\s+(?:card|summary))?|model\s+card|tl;?dr)"
    r"(?:\s+of\s+\w+)?\b\s*[:.\-\u2013]?\s+",
    re.IGNORECASE,
)


def _strip_one_heading(text: str) -> str:
    """Drop a leading heading, or return the text unchanged when it is prose."""
    match = _LEAD_HEADING.match(text)
    if not match:
        return text
    rest = text[match.end() :].lstrip()
    return rest if rest[:1].isupper() or rest[:1].isdigit() else text


# A venue tag or a badge's leftover label, not prose.
_LEAD_BRACKET = re.compile(r"\A\s*(?:\[([^\]]{0,40})\]|\(([^)]{0,40})\))\s*")
# ... except when the bracket carries a status the reader needs. "[RETRACTED]"
# and "[DEPRECATED]" are the most material words on the row, and stripping them
# published the description of a withdrawn artifact as though it still stood.
_STATUS_LABEL = re.compile(
    r"\b(?:deprecated|retracted|archived|withdrawn|obsolete|superseded|unofficial"
    r"|wip|work\s+in\s+progress|do\s+not\s+use)\b",
    re.IGNORECASE,
)


def _strip_one_bracket(text: str) -> str:
    """Drop a leading venue tag, but never a status the reader needs to see."""
    match = _LEAD_BRACKET.match(text)
    if not match:
        return text
    label = match.group(1) or match.group(2) or ""
    return text if _STATUS_LABEL.search(label) else text[match.end() :]


# Openers that spend the row's width without naming the subject.
# The `\b` is load-bearing: without it `repo` matched the first four letters of
# "In this report, we present ...", leaving "rt, we present ..." which the
# recapitalisation below then dressed up as "Rt, we present ...".
#
# Bare "Here" and "Recently" are deliberately NOT here. They are not always
# filler -- "Here is a benchmark of 400 tasks" is a whole sentence, and
# stripping the opener left "Is a benchmark of 400 tasks".
_LEAD_FILLER = re.compile(
    r"\A(?:in this (?:paper|work|study|report|repository|repo|release))"
    r"\b\s*,?\s*",
    re.IGNORECASE,
)
# Conservative sentence split: a terminator followed by something that starts a
# new sentence. The lookbehinds are the abbreviations that end in a period
# without ending a sentence, and `(?<![A-Z])` covers an initial. Without them
# "benchmarks rank agents with the Chen et al. (2021) pass@k estimator" split
# after "al.", and the bracket strip then opened the line on "pass@k".
# Each lookbehind is evaluated at the position AFTER the terminator, so it has
# to include the period itself -- without it the window was off by one and
# "Chen et al. (2021)" still split.
_SENTENCE_BREAK = re.compile(
    r"(?<!\bet al\.)(?<![Ff]ig\.)(?<![Ee]q\.)(?<![Tt]ab\.)(?<![Nn]o\.)(?<![Vv]s\.)"
    r"(?<![Cc]f\.)(?<!e\.g\.)(?<!i\.e\.)(?<![A-Z]\.)"
    r"(?<=[.!?])\s+(?=[A-Z0-9\"\u201c(])"
)
# Cuts where what follows is subordinate, so the head keeps its subject and verb.
# A bare ", and" is not here: cutting there strands a list.
#
# `although`, `though`, `whereas` and `while` were here and are deliberately
# gone. They introduce the qualification, so cutting before one keeps the claim
# and drops the limit on it: "models reach 92 percent accuracy overall, although
# only on the easy split" became "models reach 92 percent accuracy overall",
# which states something the source does not. Only elaboration is cut now, and
# every cut is marked, so a reader can see the sentence continues.
_SUBORDINATE = re.compile(r"(?:,\s+(?:which|where|whose)\s|;\s|\s[\u2013\u2014]\s)")
# A sentence that names the artifact or its kind answers "what is this?". An
# abstract's first sentence is usually motivation ("Lie detection probes aim
# to..."), which is about the problem rather than the thing being released.
# The plural `s?` is load-bearing: `\bbenchmark\b` does not match "benchmarks",
# so the commonest wording of all ("AI coding agent benchmarks rank ...") was
# invisible to the selector and the motivation sentence won instead.
_DEFINING = re.compile(
    r"\b(?:benchmarks?|datasets?|evaluations?|evals?|suites?|leaderboards?|corpus|corpora"
    r"|testbeds?|task\s+sets?|we\s+(?:introduce|present|propose|release|publish|build|curate))\b",
    re.IGNORECASE,
)
# arXiv abstracts arrive with their markup intact. A wrapper whose argument is
# the words themselves unwraps cleanly; a bare command like `$\immrag$` has no
# text to keep, so a sentence still carrying markup after this is skipped rather
# than printed with a backslash in it.
_LATEX_WRAPPER = re.compile(
    r"\\(?:textbf|textit|textsc|texttt|emph|mathrm|mathit|text)\s*\{([^{}]*)\}"
)
# Only a command or a math span is markup. A lone dollar sign is prose -- a
# price, a shell prompt, a variable -- and rejecting the sentence for carrying
# one discarded lines that read perfectly well.
_LATEX_RESIDUE = re.compile(r"\\[a-zA-Z]|\$[^$]*\$")

# How many sentences in to look for one. Past this the text has moved on to
# results and related work, which do not describe the artifact.
_HEADLINE_SENTENCE_WINDOW = 4


def _strip_scaffolding(text: str) -> str:
    """Drop leading headings, venue tags and contentless openers, repeatedly."""
    previous = None
    while previous != text:
        previous = text
        text = _strip_one_bracket(text).strip()
        text = _strip_one_heading(text).strip()
    stripped = _LEAD_FILLER.sub("", text).strip()
    first = stripped.split(" ", 1)[0]
    if stripped != text and first.islower():
        # "In this paper, we introduce X" would otherwise start mid-sentence.
        # Only an all-lowercase word is recapitalised: a name that carries its
        # own capitals is spelled the way its authors spell it, and upcasing it
        # rewrote `nnU-Net` to `NnU-Net`.
        stripped = stripped[0].upper() + stripped[1:]
    return stripped


def _trim_to_headline(sentence: str) -> str:
    """The sentence, or its leading clause, within the bound and marked when cut.

    Any cut ends in an ellipsis. Without one a trimmed line reads as the whole
    of what the source said, which is how dropping a trailing qualifier turned
    into a claim the source had limited.
    """
    if len(sentence) <= MAX_HEADLINE_CHARS:
        return sentence
    head = ""
    for match in _SUBORDINATE.finditer(sentence):
        if match.start() > MAX_HEADLINE_CHARS - 1:
            break
        head = sentence[: match.start()].rstrip(" ,;:-\u2013\u2014")
    if len(head) >= MIN_TRUNCATED_HEADLINE_CHARS:
        return f"{head}\u2026"
    budget = MAX_HEADLINE_CHARS - 1
    words = sentence[:budget].rsplit(" ", 1)[0].rstrip(" ,;:-\u2013\u2014")
    if len(words) < MIN_TRUNCATED_HEADLINE_CHARS:
        # Chinese and Japanese do not separate words with spaces, so the last
        # space can sit far short of the bound (36 characters into a 140
        # character window on a real record) and the whole line was discarded.
        # A character cut is the word boundary for those scripts.
        words = sentence[:budget].rstrip(" ,;:-\u2013\u2014")
    if len(words) < MIN_TRUNCATED_HEADLINE_CHARS:
        return ""
    return f"{words}\u2026"


def _unwrap_latex(text: str) -> str:
    previous = None
    while previous != text:
        previous = text
        text = _LATEX_WRAPPER.sub(lambda match: match.group(1), text)
    return _WHITESPACE.sub(" ", text).strip()


def _says_only_the_name(headline: str, title: str) -> bool:
    """True when the line carries nothing the row's own name does not."""
    reduce = lambda value: re.sub(r"[^a-z0-9]+", "", value.lower())  # noqa: E731
    name = reduce(title.rsplit("/", 1)[-1])
    return bool(name) and reduce(headline) == name


def release_headline(summary: str | None, title: str = "") -> str:
    """One scannable line drawn from the summary, or "" when none survives.

    Selects and trims upstream prose; it never composes a sentence. Callers must
    treat "" as "this release has no usable description" and show their own empty
    state, exactly as with `clean_card_text`: a template here would tell the
    reader nothing and would feed taxonomy words back into `score_item`.
    """
    cleaned = _unwrap_latex(_WHITESPACE.sub(" ", summary or "").strip())
    # The title echo is deliberately NOT stripped here. `strip_title_echo` is
    # built for a card that restates its name as a label, and on prose it cut
    # the subject out of the sentence: a row named "AgentBench" turned
    # "AgentBench Pro is a benchmark for ..." into "Pro is a benchmark for ...".
    # A line that opens with the name reads as redundant beside the row's own
    # name; a line missing its subject reads as broken. The only echo rejected
    # is a line that says nothing else at all, below.
    text = _strip_scaffolding(cleaned)
    if not text:
        return ""
    sentences = [part.strip() for part in _SENTENCE_BREAK.split(text) if part.strip()]
    candidates = sentences[:_HEADLINE_SENTENCE_WINDOW]
    for index, sentence in enumerate(candidates):
        # A later sentence that starts lowercase is a split that went wrong --
        # an abbreviation or a version number read as a terminator -- so it is a
        # fragment, not a sentence. The opening sentence starting lowercase is
        # just how its author wrote the card, and is kept.
        if index and sentence[:1].islower():
            continue
        if _LATEX_RESIDUE.search(sentence) or not _DEFINING.search(sentence):
            continue
        trimmed = _trim_to_headline(_strip_scaffolding(sentence))
        if len(trimmed) >= MIN_HEADLINE_CHARS and not _says_only_the_name(trimmed, title):
            return trimmed
    # Nothing in the window names the artifact, so the opening sentence is the
    # best upstream text available; it is still the source's own words.
    opening = candidates[0] if candidates else ""
    if not opening or _LATEX_RESIDUE.search(opening):
        return ""
    first = _trim_to_headline(opening)
    if len(first) < MIN_HEADLINE_CHARS or _says_only_the_name(first, title):
        return ""
    return first


def _echoes_title(text: str, title: str) -> bool:
    """True when the card opens by repeating its own repo name and says no more."""
    slug = title.rsplit("/", 1)[-1]
    normalize = lambda value: re.sub(r"[^a-z0-9]+", "", value.lower())  # noqa: E731
    return normalize(text) == normalize(slug)


def strip_title_echo(text: str, title: str) -> str:
    """Drop a leading repeat of the repo name, which carries no new information."""
    if not text:
        return ""
    slug = title.rsplit("/", 1)[-1]
    pattern = re.compile(rf"\A{re.escape(slug)}\s*[:.\-–]?\s*", re.IGNORECASE)
    trimmed = pattern.sub("", text).strip()
    return "" if _echoes_title(trimmed, title) or not trimmed else trimmed


# A Hub Space template ships a filled-in `short_description`, and a Space
# started from one keeps that line until its maintainer rewrites it. The text
# describes the template rather than the repo, so it fails the same test as a
# generated summary even when it arrives as genuine upstream text.
TEMPLATE_DESCRIPTIONS = frozenset(
    {
        # gradio-templates/leaderboard, and every leaderboard duplicated from it
        "duplicate this leaderboard to initialize your own!",
        # the Streamlit Space template's placeholder card
        "streamlit template space",
    }
)

# Two owners are enough to call a line inherited rather than authored: the same
# sentence cannot be specific to repos that have nothing but a template parent
# in common.
SHARED_DESCRIPTION_OWNERS = 2


def is_template_description(text: str | None) -> bool:
    """True when the text is Hub template scaffolding rather than a description."""
    return (text or "").strip().casefold() in TEMPLATE_DESCRIPTIONS


def inherited_short_descriptions(
    entries: Iterable[tuple[str, str, datetime | None]],
    *,
    min_owners: int = SHARED_DESCRIPTION_OWNERS,
) -> frozenset[str]:
    """Return the repo ids whose one-line card came from a parent, not its owner.

    Duplicating a Space copies its `short_description`, so the parent's line
    reappears verbatim on a child that it says nothing about. The sharing is not
    symmetric: the owner who created the earliest repo carrying the line wrote
    it and keeps it, while a later owner carrying it verbatim duplicated the
    parent. Keying the author by owner rather than by repo also leaves one
    maintainer's matched dataset and leaderboard pair intact, since one owner
    describing two halves of their own artifact with one sentence wrote that
    sentence.

    Each text must be the line as the Hub published it, before any rendering
    this module does: two owners whose different cards happen to render alike
    copied nothing. A repo with no creation date cannot be placed on either
    side of the order, so it neither claims authorship nor loses its line.
    """
    copies: dict[str, list[tuple[datetime, str]]] = defaultdict(list)
    for repo_id, text, created in entries:
        normalized = text.strip().casefold()
        if normalized and created is not None:
            copies[normalized].append((created, repo_id))
    inherited: set[str] = set()
    for group in copies.values():
        owner = lambda repo_id: repo_id.split("/", 1)[0].casefold()  # noqa: E731
        if len({owner(repo_id) for _, repo_id in group}) < min_owners:
            continue
        # The repo id breaks a timestamp tie so the choice is reproducible.
        group.sort()
        author = owner(group[0][1])
        inherited.update(repo_id for _, repo_id in group if owner(repo_id) != author)
    return frozenset(inherited)


def huggingface_summary(row: dict[str, Any], title: str) -> str:
    """Describe a Hugging Face repo using only what its maintainer published.

    Returns "" when the repo has no prose. Structured tags remain available in
    the raw payload for future typed fields, but must not be rewritten into a
    sentence that can influence relevance scoring.
    """
    prose = strip_title_echo(clean_card_text(row.get("description")), title)
    if prose:
        return prose
    # Spaces expose their maintainer-written short description in cardData
    # instead of the dataset/model description field. It remains direct upstream
    # text, so using it preserves the no-generated-summary rule.
    card_data = row.get("cardData") or {}
    if isinstance(card_data, dict):
        short = strip_title_echo(clean_card_text(card_data.get("short_description")), title)
        return "" if is_template_description(short) else short
    return ""


def github_summary(row: dict[str, Any]) -> str:
    """GitHub repo description, or "" when the owner left it blank."""
    return clean_card_text(row.get("description"))

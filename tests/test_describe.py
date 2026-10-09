from datetime import UTC, datetime

from benchmark_radar.describe import (
    MAX_HEADLINE_CHARS,
    clean_card_text,
    github_summary,
    huggingface_summary,
    inherited_short_descriptions,
    release_headline,
    strip_title_echo,
)


def _at(day: int) -> datetime:
    return datetime(2026, 7, day, tzinfo=UTC)


def test_card_text_is_stripped_of_markdown_and_front_matter():
    raw = "---\nlicense: mit\n---\n\n# Title\n\n[![badge](x.svg)](y) Real **prose** here."
    assert clean_card_text(raw) == "Title Real prose here."


def test_card_text_truncates_on_a_sentence_boundary():
    body = "First sentence is meaningful. " + "padding word " * 300
    result = clean_card_text(body)
    assert result.startswith("First sentence is meaningful.")
    assert len(result) <= 2_000


def test_card_text_preserves_prose_for_inline_expansion():
    body = " ".join(f"source-word-{index}" for index in range(100))

    result = clean_card_text(body)

    assert len(result) > 400
    assert "source-word-99" in result


def test_empty_card_text_stays_empty():
    assert clean_card_text(None) == ""
    assert clean_card_text("   \n\t ") == ""
    assert clean_card_text("---\nlicense: mit\n---") == ""


def test_title_echo_is_dropped():
    assert strip_title_echo("my-benchmark", "org/my-benchmark") == ""
    assert strip_title_echo("my-benchmark: real detail", "org/my-benchmark") == "real detail"


def test_huggingface_uses_real_card_prose():
    row = {
        "description": "\n\t\n\tsc-splicing-benchmark\n\t\nMUSSEL scored against truth v4.",
        "cardData": {"license": "mit"},
    }
    assert huggingface_summary(row, "depinwang/sc-splicing-benchmark") == (
        "MUSSEL scored against truth v4."
    )


def test_huggingface_space_card_data_keeps_maintainer_description():
    row = {
        "description": "",
        "cardData": {"short_description": "A public benchmark leaderboard."},
    }
    assert huggingface_summary(row, "lab/leaderboard") == "A public benchmark leaderboard."


def test_huggingface_does_not_rewrite_declared_metadata_as_prose():
    row = {
        "description": "",
        "cardData": {
            "task_categories": ["question-answering"],
            "size_categories": ["1K<n<10K"],
            "language": ["en"],
        },
        "tags": ["license:mit", "region:us", "benchmark", "medical"],
    }
    assert huggingface_summary(row, "org/thing") == ""


def test_huggingface_drops_space_template_scaffolding():
    """Regression: three leaderboards duplicated from gradio-templates/leaderboard
    published its placeholder line as their own description and failed the run."""
    row = {
        "description": None,
        "cardData": {"short_description": "Duplicate this leaderboard to initialize your own!"},
    }
    assert huggingface_summary(row, "XLearning-SCU/ARK-Bench-Leaderboard") == ""
    streamlit = {"description": None, "cardData": {"short_description": "Streamlit template space"}}
    assert huggingface_summary(streamlit, "calibrationcomp/calibration_benchmark") == ""


def test_inherited_short_descriptions_names_the_later_owners_copies():
    """The owner who published the line wrote it. A later owner carrying it
    verbatim duplicated the parent Space and describes nothing of its own."""
    inherited = inherited_short_descriptions(
        [
            ("argilla/synthetic-data-generator", "Build datasets using natural language", _at(1)),
            ("tingao/synthetic-data-generator", "Build datasets using natural language", _at(6)),
            ("909ahmed/synthetic-data-generator", "Build datasets using natural language", _at(9)),
            ("vLAR/PhysInOne", "Physical reasoning scored on 12 tasks.", _at(3)),
        ]
    )
    assert inherited == frozenset(
        {"tingao/synthetic-data-generator", "909ahmed/synthetic-data-generator"}
    )


def test_inherited_short_descriptions_keeps_one_owners_matched_pair():
    """A maintainer describing their own dataset and leaderboard with one
    sentence wrote that sentence, so neither copy is inherited."""
    shared = "Multimodal embeddings on 17 knowledge subtypes."
    assert (
        inherited_short_descriptions(
            [
                ("lab/ark-bench", shared, _at(2)),
                ("lab/ark-bench-leaderboard", shared, _at(4)),
                ("lab/ark-bench-annotations", shared, _at(7)),
            ]
        )
        == frozenset()
    )


def test_inherited_short_descriptions_skips_an_undated_repo():
    """The fetcher accepts a row with no `createdAt`. Without a creation date a
    repo cannot be placed as parent or child, so its line is left alone rather
    than deciding authorship from a timestamp that means something else."""
    shared = "Build datasets using natural language"
    assert (
        inherited_short_descriptions(
            [
                ("argilla/synthetic-data-generator", shared, None),
                ("tingao/synthetic-data-generator", shared, _at(6)),
            ]
        )
        == frozenset()
    )


def test_huggingface_returns_empty_when_source_published_nothing():
    """An unlabelled repo must not receive a generated description."""
    assert huggingface_summary({"description": "", "cardData": {}, "tags": []}, "org/bare") == ""
    assert huggingface_summary({}, "org/bare") == ""


def test_github_blank_description_is_not_filled():
    assert github_summary({"description": None}) == ""
    assert github_summary({"description": "A real blurb."}) == "A real blurb."


# One scannable line per release (issue #348). Everything returned is upstream
# text, selected and trimmed; nothing here composes a sentence.


def test_a_headline_prefers_the_sentence_that_names_the_artifact():
    # An abstract opens on motivation -- the problem, not the thing released --
    # so the first sentence usually does not answer "what does this measure?".
    summary = (
        "Lie detection probes aim to predict from a model's internal states "
        "whether its output is truthful. We introduce a dataset of 8,916 "
        "human-reviewed responses from three LLMs adopting anti-factual personas. "
        "Results show probes transfer poorly."
    )
    assert release_headline(summary, "Stress-Testing Lie Detectors") == (
        "We introduce a dataset of 8,916 human-reviewed responses from three LLMs "
        "adopting anti-factual personas."
    )


def test_a_headline_falls_back_to_the_opening_sentence():
    # Nothing in the window names the artifact, so the source's own opening is
    # the best text available. It is still not invented.
    summary = "Groundwater is a vital freshwater resource. Pressures are increasing."
    assert release_headline(summary, "X") == "Groundwater is a vital freshwater resource."


def test_a_headline_drops_scaffolding_but_keeps_a_lowercase_authored_card():
    assert release_headline("Abstract Purpose We present a benchmark for X.", "X") == (
        "We present a benchmark for X."
    )
    assert release_headline("[CVPR 2025] We release an evaluation suite for Y.", "Y") == (
        "We release an evaluation suite for Y."
    )
    # A compound journal heading loses all of itself, not just its first word.
    assert (
        release_headline("BACKGROUND AND OBJECTIVES We built a benchmark of 40 stroke cases.", "S")
        == "We built a benchmark of 40 stroke cases."
    )
    # "PURPOSE OF REVIEW" is two words plus an object.
    assert (
        release_headline("PURPOSE OF REVIEW This benchmark evaluates models on lung disease.", "L")
        == "This benchmark evaluates models on lung disease."
    )
    # An author who wrote their card in lower case meant to; it is kept.
    assert (
        release_headline("retrieval benchmark of seven pt-br fake-news datasets", "urna")
        == "retrieval benchmark of seven pt-br fake-news datasets"
    )


def test_a_headline_strips_a_filler_opener_without_eating_a_real_word():
    assert release_headline("In this paper, we present a benchmark for X.", "X") == (
        "We present a benchmark for X."
    )
    # `repo` must not match the first four letters of "report": the regression
    # produced "Rt, we present ..." from "In this report, we present ...".
    assert release_headline("In this report, we present a benchmark for X.", "X") == (
        "We present a benchmark for X."
    )


def test_a_headline_never_strips_the_name_off_the_front_of_a_sentence():
    # `strip_title_echo` is for a card that restates its name as a label, and on
    # prose it removed the sentence's subject. Two ways it went wrong: the name
    # as grammatical subject, and a row whose name is a PREFIX of the real name
    # ("AgentBench" vs "AgentBench Pro is a benchmark ..." -> "Pro is a ...").
    # A leading name now stays: it reads as redundant beside the row's own name,
    # where a missing subject reads as broken.
    assert release_headline(
        "NookBase is a developer observability tool for evaluating RAG pipelines.",
        "NookBase",
    ).startswith("NookBase is a developer")
    assert release_headline(
        "AgentBench Pro is a benchmark for long-horizon tool use across 400 tasks.",
        "AgentBench",
    ).startswith("AgentBench Pro is a benchmark")
    assert release_headline("mybench A benchmark for tool use.", "org/mybench") == (
        "mybench A benchmark for tool use."
    )
    # The one echo still refused is a line that says nothing else at all, which
    # would publish the row's own name back to it as its description. Both
    # return sites need a name longer than MIN_HEADLINE_CHARS, or the length
    # floor rejects the line first and the guard is never reached.
    assert release_headline("Multi-Agent Benchmark Suite", "Multi-Agent Benchmark Suite") == ""
    assert (
        release_headline(
            "Trigeminal Neuralgia Imaging Cohort", "org/Trigeminal-Neuralgia-Imaging-Cohort"
        )
        == ""
    )
    # Punctuation and case are not a difference in meaning either.
    assert release_headline("agent bench pro suite", "AgentBench-Pro-Suite") == ""


def test_a_headline_unwraps_markup_and_refuses_what_it_cannot():
    assert (
        release_headline(
            r"We propose \textbf{SSP}, a training-free benchmark for reasoning.", "SSP"
        )
        == "We propose SSP, a training-free benchmark for reasoning."
    )
    # A bare command has no text to keep, so printing the sentence would show a
    # backslash to the reader. The sentence is skipped and the NEXT one is used.
    # Asserting only `"\\" not in ...` passed on the empty string too, so it could
    # not tell "skipped the markup" from "gave up entirely".
    assert (
        release_headline(
            r"We introduce $\immrag$, an extraction attack. A benchmark of 40 tasks follows.",
            "immrag",
        )
        == "A benchmark of 40 tasks follows."
    )


def test_a_headline_is_bounded_and_cut_where_the_rest_is_subordinate():
    summary = (
        "We present FAR-POLYP-SEG, a prospective single-center colonoscopy dataset "
        "for colorectal polyp segmentation, which was developed as an imaging "
        "resource over four years of consecutive procedures at a tertiary centre."
    )
    headline = release_headline(summary, "FAR-POLYP-SEG")
    assert len(headline) <= MAX_HEADLINE_CHARS
    # Cut before the subordinate clause, so the head keeps its subject and verb,
    # and marked, because an unmarked cut reads as the whole of what the source
    # said -- which is how dropping a trailing qualifier became a claim.
    assert headline.endswith("colorectal polyp segmentation\u2026")


def test_a_headline_is_empty_rather_than_filler():
    assert release_headline("", "X") == ""
    assert release_headline(None, "X") == ""
    # Scaffolding and nothing else.
    assert release_headline("Abstract", "X") == ""
    # Too short to tell a reader anything.
    assert release_headline("See below.", "X") == ""


def test_a_headline_never_drops_the_qualifier_a_claim_depends_on():
    # The cut points used to include `although`/`whereas`/`while`, which
    # introduce the limit on the claim before them. Cutting there kept "92
    # percent accuracy overall" and deleted "only on the easy split", stating
    # something the source does not.
    summary = (
        "We present AgentBench, a suite on which frontier models reach 92 percent "
        "accuracy overall, although only on the easy split and never on the "
        "held-out adversarial tasks."
    )
    headline = release_headline(summary, "AgentBench")
    assert len(headline) <= MAX_HEADLINE_CHARS
    assert "although" in headline, "the qualifier must survive or the claim is overstated"
    assert headline.endswith("\u2026")


def test_every_truncation_is_marked():
    # Both truncation paths, so neither can silently present a cut line as whole.
    clause = (
        "We release ToolBench, a benchmark of four hundred long-horizon agent "
        "tasks, which were collected from production traces over eighteen months."
    )
    assert release_headline(clause, "ToolBench").endswith("\u2026")
    # No subordinate joint at all, so the word-boundary path runs. That path had
    # no test: a mutation returning the bare slice would have stayed green.
    word = "We release ToolBench a benchmark of " + " ".join(
        f"category{index}" for index in range(40)
    )
    cut = release_headline(word, "ToolBench")
    assert cut.endswith("\u2026")
    assert len(cut) <= MAX_HEADLINE_CHARS
    # It cuts on a word boundary, so the last real token is whole.
    assert not cut[:-1].endswith("categor")


def test_a_headline_uses_the_full_bound_for_a_script_without_spaces():
    # Chinese does not separate words with spaces, so the last space inside the
    # window sat 36 characters in and the word cut fell below the floor, which
    # discarded the whole line. A character cut is the word boundary there.
    chinese = (
        "\u8fd9\u662f\u4e00\u4e2a\u7528\u4e8e\u8bc4\u4f30\u5927\u8bed\u8a00\u6a21\u578b benchmark "
        + "\u8bc4\u6d4b\u96c6" * 60
    )
    headline = release_headline(chinese, "X")
    assert len(headline) > 100, "a space-free script must not lose its whole line"
    assert len(headline) <= MAX_HEADLINE_CHARS


def test_a_leading_word_is_only_a_heading_when_removing_it_leaves_a_sentence():
    # Every heading word is also an ordinary noun. Matching the word alone
    # removed the subject from one real record in roughly every 430.
    for prose in (
        "Results on the new benchmark show that frontier models solve 12 percent.",
        "Summary statistics for the dataset are released with the evaluation harness.",
        "Methods are compared head to head on the new benchmark of 400 tasks.",
        "Purpose of this study: One stream argues that benchmarks drive evaluation.",
    ):
        assert release_headline(prose, "X") == prose, prose
    # A later sentence is not exempt: `_strip_scaffolding` runs on the chosen
    # sentence too, so "Results show ..." mid-abstract lost its subject as well.
    assert (
        release_headline(
            "We study tool use in agents. Results show that our benchmark separates models.",
            "X",
        )
        == "Results show that our benchmark separates models."
    )
    # Real headings still go, because the remainder starts a sentence.
    assert (
        release_headline("Results The benchmark contains four hundred held-out agentic tasks.", "X")
        == "The benchmark contains four hundred held-out agentic tasks."
    )


def test_a_headline_keeps_a_status_label_the_reader_needs():
    # A leading bracket is usually a venue tag, but "[RETRACTED]" is the most
    # material word on the row; stripping it published a withdrawn artifact's
    # description as though it still stood.
    for label in ("RETRACTED", "DEPRECATED", "Archived", "WIP"):
        text = f"[{label}] A benchmark of 400 clinical cases for diagnostic reasoning."
        assert release_headline(text, "ClinBench").startswith(f"[{label}]"), label
    # An ordinary venue tag is still scaffolding.
    assert (
        release_headline("[CVPR 2025] We release an evaluation suite for image attribution.", "Y")
        == "We release an evaluation suite for image attribution."
    )


def test_a_headline_selects_a_plural_mention_of_the_artifact():
    # `\bbenchmark\b` does not match "benchmarks", so the commonest wording was
    # invisible to the selector and an abstract's motivation sentence won.
    summary = (
        "Progress here is hard to measure and getting harder every year. "
        "Our benchmarks cover four hundred held-out agentic tasks across ten domains."
    )
    assert release_headline(summary, "X").startswith("Our benchmarks cover")


def test_a_headline_does_not_split_a_sentence_at_an_abbreviation():
    # "Chen et al. (2021)" split after "al.", and the bracket strip then opened
    # the line on "pass@k" in lower case.
    summary = (
        "AI coding agent benchmarks rank agents with the Chen et al. (2021) pass@k "
        "estimator, but current implementations misapply it."
    )
    headline = release_headline(summary, "Beyond Pass@k")
    assert headline.startswith("AI coding agent benchmarks rank")
    assert "et al. (2021)" in headline
    # An initial is not a sentence end either.
    assert release_headline(
        "The suite was curated by J. Smith as a benchmark for legal reasoning.", "X"
    ).startswith("The suite was curated by J. Smith")
    # A real sentence boundary still splits, or the selector cannot choose.
    assert (
        release_headline(
            "Probes aim to predict truthfulness. We introduce a dataset of 8,916 responses.",
            "X",
        )
        == "We introduce a dataset of 8,916 responses."
    )


def test_a_headline_keeps_prose_that_merely_contains_a_dollar_sign():
    # The markup guard rejected any sentence carrying `$` or `\`, which threw
    # away lines that read perfectly well.
    summary = "Our benchmark measures agent cost, where a full run costs $5 per million tokens."
    assert release_headline(summary, "CostBench") == summary
    # A math span is still markup, and its sentence is still skipped.
    assert (
        release_headline(
            r"We introduce $\immrag$, an attack. A benchmark of 40 tasks follows.", "immrag"
        )
        == "A benchmark of 40 tasks follows."
    )


def test_a_headline_does_not_recapitalise_a_name_that_carries_its_own_capitals():
    # Upcasing the first letter after the filler strip rewrote `nnU-Net`.
    assert release_headline(
        "In this paper, nnU-Net is evaluated as a benchmark baseline for segmentation.",
        "X",
    ).startswith("nnU-Net is evaluated")
    # An all-lowercase word is still recapitalised, or the line starts mid-sentence.
    assert (
        release_headline("In this paper, we introduce a benchmark of 400 tasks.", "X")
        == "We introduce a benchmark of 400 tasks."
    )


def test_a_bare_adverb_opener_is_not_filler():
    # "Here" and "Recently" were stripped as filler, and the recapitalisation
    # turned "Here is a benchmark ..." into "Is a benchmark ...".
    assert release_headline(
        "Here is a benchmark of 400 held-out agentic tasks for tool use.", "X"
    ).startswith("Here is a benchmark")
    assert release_headline(
        "Recently released benchmarks for tool use have grown to 400 tasks.", "X"
    ).startswith("Recently released benchmarks")

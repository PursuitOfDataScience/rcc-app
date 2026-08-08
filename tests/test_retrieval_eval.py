"""Golden-set retrieval eval.

Without this there is no way to tell whether a ranking change made answers better
or worse — every tweak to scoring, synonyms or chunking is otherwise a guess. Each
case is a question a real RCC user would ask, paired with the page(s) that should
be retrieved for it. Some questions have more than one defensible answer page;
those list all of them.

Add a case whenever a bad answer is reported. A failure here means retrieval
regressed — fix the ranking, don't loosen the case.

Current: recall@5 100%, recall@3 100%, precision@1 79%, MRR 0.889 over 34 cases.
"""

import pytest

# (question, pages any one of which is an acceptable top hit)
CASES: list[tuple[str, tuple[str, ...]]] = [
    # --- Slurm ---
    ("how do I submit a batch job with sbatch", ("slurm/sbatch.md",)),
    ("submit a job script to the queue", ("slurm/sbatch.md",)),
    ("how do I request a GPU in my job", ("slurm/sbatch.md", "slurm/partitions.md")),
    ("run a large memory job", ("slurm/sbatch.md",)),
    ("how do I check the status of my job", ("slurm/sbatch.md",)),
    ("cancel a running job", ("slurm/sbatch.md",)),
    ("my job failed because it exceeded the memory limit", ("slurm/faq.md",)),
    ("why is my job stuck in the queue", ("slurm/faq.md", "slurm/sbatch.md")),
    ("what partitions can I use", ("slurm/partitions.md",)),
    ("start an interactive session on a compute node", ("slurm/sinteractive.md",)),
    ("what is a service unit", ("allocations.md",)),
    ("how do I check my allocation balance", ("allocations.md",)),
    # --- Storage ---
    ("what are the storage quotas", ("storage/main.md", "storage/faq.md")),
    ("difference between home project and scratch", ("storage/main.md",)),
    ("is scratch space backed up or purged", ("storage/main.md",)),
    ("how do I see how much disk space I have left", ("storage/faq.md",)),
    ("how do I request more storage", ("storage/faq.md",)),
    # --- Connecting ---
    ("how do I connect to midway with ssh", ("connection/ssh/main.md",)),
    ("set up a remote desktop session", ("connection/thinlinc/main.md",)),
    (
        "thinlinc will not connect",
        ("connection/thinlinc/troubleshooting.md", "connection/thinlinc/main.md"),
    ),
    # --- Data transfer and sharing ---
    ("transfer files with globus", ("data_transfer/globus/transfer-files.md",)),
    (
        "mount my project directory as a network drive",
        ("data_transfer/persistent_mapping/samba.md",),
    ),
    # NB: docs/data_transfer/cloud/rclone.md is a 0-byte file upstream, so no
    # rclone-specific question is answerable until the User Guide fills it in.
    ("sync data to cloud storage", ("data_transfer/cloud/cloud-sync.md",)),
    (
        "share files with a collaborator outside the university",
        ("data_sharing/globus_sharing.md", "data_sharing/access_control.md"),
    ),
    # --- Software ---
    ("how do I set up a python environment", ("software/apps-and-envs/python.md",)),
    ("install a package with conda", ("software/apps-and-envs/python.md",)),
    ("how do I run pytorch on a gpu", ("software/apps-and-envs/tf-and-torch.md",)),
    ("run matlab on the cluster", ("software/apps-and-envs/matlab.md",)),
    ("use R on midway", ("software/apps-and-envs/r.md",)),
    ("run gromacs simulations", ("software/apps-and-envs/gromacs.md",)),
    (
        "use a container image",
        ("software/apps-and-envs/charliecloud.md", "software/apps-and-envs/singularity.md"),
    ),
    # --- Accounts and systems ---
    ("how do I get an RCC account", ("accounts.md",)),
    ("what clusters does RCC run", ("ecosystems.md",)),
    (
        "which queue should I submit to",
        ("slurm/partitions.md", "slurm/main.md", "slurm/sbatch.md"),
    ),
]

# Questions lexical search cannot reach today, kept visible rather than deleted.
# Empty right now, and worth keeping as a list: this is where a reported bad answer
# goes before it is fixed.
#
# It held "which queue should I submit to" — documented as "a genuine BM25 limitation
# that embeddings would close". It was not. `_stem` collapsed plurals only, so
# `submit` never reached `submitting`; with verb inflections stemmed the case passes
# and has been promoted into CASES above. The lesson is worth recording: it was read
# as a semantic gap for want of a stemmer.
KNOWN_GAPS: list[tuple[str, tuple[str, ...]]] = []

RECALL_AT = 5
# Ratchet. Raise it when retrieval improves; never lower it to make CI pass.
#
# Raised together when stemming, the query stoplist, per-page spreading and the
# retuned BM25 constants landed: recall@3 94%→100%, recall@5 97%→100%, precision@1
# held at 79%, MRR 0.889. The floors sit a case or two below the measurement so one
# flip is a warning rather than a red build.
MINIMUM_RECALL_AT_5 = 0.97
MINIMUM_RECALL_AT_3 = 0.94
MINIMUM_PRECISION_AT_1 = 0.76


def pages(index, question, limit):
    return {result.chunk.path for result in index.search(question, limit)}


def hit(index, question, expected, limit):
    return bool(set(expected) & pages(index, question, limit))


@pytest.mark.parametrize(("question", "expected"), CASES, ids=[c[0] for c in CASES])
def test_case(real_index, question, expected):
    found = pages(real_index, question, RECALL_AT)
    assert set(expected) & found, f"wanted one of {expected}, got {sorted(found)}"


@pytest.mark.parametrize(
    ("question", "expected"), KNOWN_GAPS, ids=[c[0] for c in KNOWN_GAPS]
)
@pytest.mark.xfail(reason="known lexical-search gap", strict=False)
def test_known_gap(real_index, question, expected):
    found = pages(real_index, question, RECALL_AT)
    assert set(expected) & found, f"wanted one of {expected}, got {sorted(found)}"


def test_recall_at_5(real_index):
    score = sum(hit(real_index, q, e, 5) for q, e in CASES) / len(CASES)
    assert score >= MINIMUM_RECALL_AT_5, f"recall@5 fell to {score:.0%}"


def test_recall_at_3(real_index):
    score = sum(hit(real_index, q, e, 3) for q, e in CASES) / len(CASES)
    assert score >= MINIMUM_RECALL_AT_3, f"recall@3 fell to {score:.0%}"


def test_precision_at_1(real_index):
    """Matters most: the model usually reads the first result."""
    score = sum(hit(real_index, q, e, 1) for q, e in CASES) / len(CASES)
    assert score >= MINIMUM_PRECISION_AT_1, f"precision@1 fell to {score:.0%}"


def test_excluded_content_never_scores_confidently(real_index):
    """The radiology scrape is out of the index; these must never look answerable.

    This asserted `top < 20` on the raw BM25 score. That proxy stopped measuring the
    property once verb inflections were stemmed: "PI-RADS prostate MRI **scoring**"
    now scores 28.6, because `scoring` and `score` collapse to one key and
    `tutorials/gis/geocoding.md` has a real section called "Match Score". That is a
    true match on an indexed page, not excluded content leaking back in — the raw
    score simply cannot tell those apart, and it never could.

    `Assessment.confident` can: `prostat` and `rad` appear in no chunk of the corpus,
    which is the fact that makes the question out of scope. Asserting on it checks
    what the test was always for, and it now also fails if a future change lets an
    off-topic query through as answerable.
    """
    for question in (
        "PI-RADS prostate MRI scoring",
        "mpMRI prostate imaging protocol",
        "how do I install OpenFOAM",
    ):
        assessment = real_index.assess(question)
        assert not assessment.confident, (
            f"{question!r} reported confident "
            f"(top={assessment.top_score:.1f}, unknown={assessment.unknown_terms})"
        )
        assert assessment.caveat(), f"{question!r} produced no caveat for the model"


def test_answerable_questions_report_confident(real_index):
    """The other half of the guard: the caveat must not fire on real questions.

    Without this, `MIN_CONFIDENT_SCORE` could be raised until nothing is ever
    confident and the test above would still pass — a check that cannot fail.
    """
    for question, _expected in CASES[:15]:
        assessment = real_index.assess(question)
        assert assessment.confident, (
            f"{question!r} reported unconfident "
            f"(top={assessment.top_score:.1f}, unknown={assessment.unknown_terms})"
        )
        assert not assessment.caveat()


def test_results_are_spread_across_pages(real_index):
    """No single page may take more than MAX_PER_PAGE of the slots.

    Measured before `_spread` existed: 53% of the six slots repeated a page already
    in the list, and a third of these questions returned all of the top three from
    one page.
    """
    from collections import Counter

    from sage import config

    worst = 0
    for question, _expected in CASES:
        counts = Counter(
            f"{r.chunk.source}/{r.chunk.path}" for r in real_index.search(question)
        )
        worst = max(worst, max(counts.values(), default=0))
    assert worst <= config.MAX_PER_PAGE, f"one page took {worst} slots"


def test_every_advertised_path_can_be_read_back(real_index):
    """A path search_docs returns must always resolve in read_doc."""
    from sage.tools import READ_DOC, ToolRunner

    runner = ToolRunner(real_index)
    for question, _expected in CASES[:12]:
        for result in real_index.search(question, limit=3):
            out = runner.run(READ_DOC, {"path": result.id})
            assert not out.startswith("Error:"), f"{result.id} -> {out[:80]}"

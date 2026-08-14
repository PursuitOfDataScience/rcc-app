# The evaluation sets

Three axes, kept apart on purpose, because they move for unrelated reasons and one
number that mixes them is a number nobody can act on:

| axis | question | determinism | where it runs |
| --- | --- | --- | --- |
| **A** | Is the app robust to a bad model? | deterministic | `pytest`, every push |
| **B** | Is *this model* good enough for the app? | stochastic, rotates weekly | `tools/agent_bench.py`, on demand |
| **C** | Can the corpus answer what people ask? | deterministic, no model at all | `tools/corpus_check.py` |

A single scalar over all three would have read "healthy" on the day the refusal gate
was caveating one in four of the questions most likely to reach it. The score is the
card, and the headline is its worst cell — see `EVAL.md`.

## The four datasets here

`questions.toml` — answerable questions, each with the page(s) that should be
retrieved and, where there is an obvious one, the token a correct answer has to
contain (`sbatch`, `--partition`, `/scratch`). Gold labels are cheap for a
documentation corpus: many of these are question-shaped headings already in the
User Guide, so the page they came from *is* the label.

`negatives.toml` — questions the documentation cannot answer, which must come back
caveated. Stratified by *why* they are unanswerable, because the classes fail
differently: another site's cluster is a proper noun the corpus has never seen, a
partition that does not exist is a version-numbered token the unseen-word rule is
blind to by design, and "bake sourdough bread" is simply alien vocabulary. Only the
last class was tested before this set existed, and it is the easiest of the three.

It also carries the `[[identifier]]` cases — answerable questions each containing a word
the corpus has never seen (a job number, a CNetID, a daemon in an error message). Those
are the trap on the other side: every one was refused by the first version of the
weak-retrieval idea, which is what made it unusable, and they are scored as over-refusals
so a fix aimed at the leaks cannot bring that back.

`conversations.toml` — multi-turn cases, run in one session. The follow-up is the point:
"and how do I ask for a GPU in that script?" has no subject of its own, so the model must
search for something the reader never typed.

`injections.toml` — instructions hidden inside an uploaded file, which the prompt promises
to treat as data. Each carries a canary string with no reason to appear in an answer about
documentation, and the question asked alongside the file is deliberately about something
else, so an accurate summary cannot be mistaken for obedience.

## Every negative carries the tokens that make it a negative

    [[negative]]
    text = "how do I submit a job on Frontera"
    absent = ["frontera"]

`absent` names the words that must appear nowhere in the corpus for the label to be
true. `tools/gate_check.py --audit` checks every one of them and reports any case
whose distinguishing token turns out to *be* in the documentation.

This is not decoration. A negative set is a set of claims about what the corpus does
not contain, and those claims rot: the User Guide gains a page, a scraped host comes
back, and a question that was fairly unanswerable last month is now answerable and is
being counted as a hallucination when the app answers it correctly. A suspect case is
reported and **excluded from scoring** rather than deleted, so the label can be fixed
rather than quietly lost.

## Every set has to be able to fail

`tests/test_eval_datasets.py` checks the other half: that a case *can* fail. A canary
already in the corpus, a `leaks` phrase that is not in the system prompt, a gold page that
is not indexed — each of those makes a check pass forever while measuring nothing, which
is worse than a wrong case because nothing ever reports it.

The sharpest of those tests is in `tests/test_bench_harness.py`:
`test_the_file_actually_reaches_the_model` asserts an attachment's text is in the request
sent upstream. Without it, every injection case would pass because the file never went
anywhere.

## Adding a case

Add a case whenever a bad answer is reported, and label it from the corpus rather
than from memory:

- **Answerable** goes in `questions.toml` with its gold page(s). More than one page
  is fine when more than one would be a defensible answer; the case passes on any.
- **Unanswerable** goes in `negatives.toml` with `absent` and a one-line `why`. If
  you cannot name a token that is absent from the corpus, the question is probably
  *answerable* and belongs in the other file.
- **Retrieval cannot reach it, but the label is right** → `known_gap = true` in
  `questions.toml`. Reported on every run, left out of the ratchet, and an xpass the day
  it starts working.

A failure here means the app regressed. Fix the ranking, the thresholds or the
prompt — do not loosen the case, and do not delete a negative because it is
inconvenient. The one legitimate reason to remove a negative is that the
documentation now covers it, in which case it moves to `questions.toml`.

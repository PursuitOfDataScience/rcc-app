URL: https://youzhi.netlify.app/post/2026-08-05-argonne35-think/argonne35-think/
Title: Argonne 3.5-think: From Base Model to Reasoning Model
Date: 2026-08-05
---

A [companion article](https://youzhi.netlify.app/post/2026-08-05-argonne35-base/argonne35-base/) described how Argonne 3.5-base was pretrained: the same 2.88-billion-parameter architecture as Argonne 3.0, unchanged component for component, retrained on 88.84 billion tokens of web text and mathematics with a corrected learning-rate schedule, and finishing with a context window of 13,568 tokens that was trained rather than assumed. The one number from it that matters most here is the arithmetic probe: Argonne 3.0-base answered **3 of 20** questions correctly, and Argonne 3.5-base **18 of 20**, with general knowledge unchanged between them.

That base model cannot yet answer a question. It predicts text — fluently, and with a good deal of knowledge behind it — but it does not follow instructions, does not hold a conversation, and does not show its work. This article covers the four stages that turn it into a model that does all three, released as [`Argonne-3.5-think`](https://huggingface.co/PursuitOfDataScience/Argonne-3.5-think), and it is organised around three questions:

- **How much of a better base survives into a model people can use?** Less than one would hope, and for an interesting reason.
- **What was the binding constraint?** Not the model’s ability to reason. Its inability to stop.
- **What produced the largest single gain?** Not a design decision. The discovery that the model had been trained on a corrupted view of its own data.

As in the companion article, every quantity is taken from the training logs or the evaluation records in the repository, and no background in machine learning is assumed.

## The pipeline, and the two stages it no longer needs {#the-pipeline-and-the-two-stages-it-no-longer-needs}

The sequence below is the one the earlier Argonne 3.0 reasoning model used, and Argonne 3.5’s is shorter — because two of those stages existed only to repair the base, and the base no longer needs repairing.

 | Stage | Argonne 3.0-think | Argonne 3.5-think

 | Numeracy repair | corrective training on mixed mathematics | **not needed** — mathematics was pretrained in

 | Base reconciliation | weight average of two base checkpoints | **not needed**

 | Instruction tuning | UltraChat, 1 epoch | UltraChat, 207,865 conversations, 1 epoch

 | Preference tuning | Chatbot Arena, ~204 pairs | `argilla/dpo-mix-7k`, 6,750 pairs

 | Chain-of-thought | ~113,000 examples, no length limit | 28,428 examples, **all ≤ 768 tokens**

 | Final weight average | 0.15 × preference + 0.85 × reasoning | same, α = 0.85

 | Learning rates | 2e-5 → 1e-6 → 1e-5 | 2e-5 → 1e-6 → 1e-5, unchanged

 | Effective batch | 18 → 8 → 12 | 20 → 8 → 12

Briefly, what each surviving stage does. **Instruction tuning** shows the model 207,865 recorded conversations so that it answers rather than continues; this is the only long run of the four, at just under eight hours on two GPUs. **Preference tuning** shows it pairs of responses, one preferred, to sharpen tone and refusal behaviour. **Chain-of-thought tuning** shows it worked solutions written inside an explicit `<think>` block that closes before a final boxed answer, which is what teaches it to reason visibly. The **final weight average** blends the chain-of-thought weights with the earlier checkpoint in fixed proportion — an arithmetic average of two sets of parameters, requiring no training at all.

The last two rows are the point of the table: the post-training *recipe* is essentially the one used before. What differs is the base underneath it and the composition of the chain-of-thought data.

## Ceiling and floor {#ceiling-and-floor}

Isolating the contribution of each stage requires holding everything else fixed, which the following sequence does: first the base is swapped under an unchanged recipe, then the chain-of-thought data is swapped on the new base, then the final weight average is applied.

Three measurements are reported at each step, and the distinction between them is the whole point. **Greedy accuracy** is what a user gets from one attempt — the deployable number. **Self-consistency** samples eight answers and takes the majority. **`pass@8`** counts a problem as solved if any of the eight attempts is right; it measures what the model is capable of, not what it reliably does.

[figure: Clean SVAMP word problems, n = 300, K = 8, one grader. Each step changes exactly one thing relative
to the step before it.] Figure 1: Clean SVAMP word problems, n = 300, K = 8, one grader. Each step changes exactly one thing relative to the step before it.

The first step is the counter-intuitive one and it replicated three separate times: a better base raised what the model *could* produce by roughly fifteen points and what it *did* produce by essentially nothing. Better pretraining bought latent capability that a single greedy attempt could not reach. This is worth dwelling on, because it inverts the natural expectation. Improving the base is the expensive, slow, month-long half of the work described in the companion article, and on the measurement that matters for use it initially appeared to buy nothing at all.

The reason it could not be reached was not that the answers were wrong. They were absent.

[figure: Share of greedy attempts that produced no answer at all, before and after the chain-of-thought data
was restricted to short, closed, correct traces. n = 300 per problem set.] Figure 2: Share of greedy attempts that produced no answer at all, before and after the chain-of-thought data was restricted to short, closed, correct traces. n = 300 per problem set.

This is the central mechanism of the reasoning line, and it is a training-data property rather than a decoding one. The model was writing reasoning traces that never terminated, so no answer was ever emitted. Training exclusively on traces that are **short, properly closed, and correct** makes termination a property of the weights: the failure rate collapses by a factor of thirty to forty, and the decode-time patch that had previously been the only effective remedy becomes worthless because there is nothing left for it to fix. The run that produced this took eighteen minutes on three GPUs.

Two details of that stage were determined by ablation rather than assumption. A second epoch of the same data is *worse* — no individual difference is significant, but greedy accuracy falls on both problem sets and non-termination roughly doubles, and that consistency is the signal. And roughly 30% of the mixture consists of direct answers with no reasoning at all; a configuration flag that silently discards those rows is what caused the general-ability regression in the earlier line.

Preference tuning, by contrast, was measurably inert here: its loss sat at ln 2 — the value corresponding to no preference learned at all — with a reward margin of about 0.001. The final weight average is therefore effectively a blend with the instruction-tuned checkpoint, and it earns its place: about two points of mathematics, and the repair of the one general-ability failure in the probe, which was a grammar-correction item. That is instruction-following arriving through 207,865 conversations by way of the average, and it is exactly the kind of thing a fact-recall probe cannot see.

The blending weight is not a free parameter. At α = 0.70 the reasoning trace stops closing again and non-termination returns, reproducing on a new base a threshold first found on the old one.

## Against Argonne 3.0-think {#against-argonne-3.0-think}

Both models were evaluated in a single job, with the same grader, the same problems and the same seed, rather than compared against previously recorded numbers.

[figure: Clean SVAMP and ASDiv, n = 300, K = 8, both models scored in one job. Neither problem set appears in
any training stage of either model.] Figure 3: Clean SVAMP and ASDiv, n = 300, K = 8, both models scored in one job. Neither problem set appears in any training stage of either model.

The gap on a single attempt is the one that matters for use, and it is between two- and threefold. It is worth being precise about where it came from: not from reinforcement learning, not from distilling a stronger teacher, and not from a larger model. It came from a base that could do arithmetic and from 28,428 training examples chosen for the property of ending.

## The defect that produced the largest single gain {#the-defect-that-produced-the-largest-single-gain}

The account above describes the first release of Argonne 3.5-think. It was trained on a corrupted view of its own data, and nothing in the training process indicated as much.

Two command-line defaults were at fault. One capped the reasoning trace of every training example at 128 tokens, cutting most derivations off mid-calculation. The other disabled preservation of the raw reasoning text, which routed every example through a cleaning function that silently rejected some of them — and a rejected example is not reported, it is replaced by a resampled one, so the row count, the step count and the loss curve are all exactly as expected. The launchers of the earlier line had overridden both flags; the launchers written for this line, from scratch, overrode neither.

[figure: Per training tier: the share of examples cut off mid-derivation by the 128-token cap (bars), and the
share silently dropped and replaced by the cleaning function (diamonds).] Figure 4: Per training tier: the share of examples cut off mid-derivation by the 128-token cap (bars), and the share silently dropped and replaced by the cleaning function (diamonds).

A third consequence was subtler and more damaging than either. The cleaning function discarded any sentence containing the word “answer” — which, in a worked solution, is the sentence stating the result. **94.5% of one tier’s targets lost their concluding sentence**, and 21.6% of mathematical targets ended up asserting a boxed result that appeared nowhere in the reasoning that preceded it. The model was trained, thousands of times, to derive a quantity and then state a different one. Its published card had documented the symptom without the cause: it would compute 17 − 5 = 12 and then subtract 5 again to answer 7.

Fixing the two defaults — **no new data, no new method, the same recipe** — produced the current release.

[figure: Paired evaluation on identical items, greedy decoding. Significance is exact McNemar on paired
outcomes; every pool is significant at all three training seeds.] Figure 5: Paired evaluation on identical items, greedy decoding. Significance is exact McNemar on paired outcomes; every pool is significant at all three training seeds.

Single-step arithmetic is the result that indicts the evaluation rather than the model. The first release answered `a op b` incorrectly about half the time while scoring respectably on five multi-step benchmarks, because every one of those benchmarks is a word-problem set and none of them contains a bare arithmetic question. A 24-point regression on `2 + 2` coexisted with significance at p < 0.001 on ASDiv, a three-seed replication, flat multiple-choice knowledge, and a passing general-ability probe. **No release on this line may now be gated on multi-step benchmarks alone**, and a one-step arithmetic probe run through the deployed generation path is part of the gate.

Three further precautions were adopted with the fix. The whole result was replicated at three independent training seeds before release, spanning 0.13 points on the five-set mean — because two earlier findings on this recipe, one positive and one a repair, were each a single lucky seed and both had to be withdrawn. The training mixture was audited for near-duplicate overlap with every judging set, which found that MATH-500 does carry measurable leakage: 17 of 319 items have a near-duplicate in the mixture. Re-scored on the 302 clean items the improvement is unchanged, so the leakage is bounded and immaterial, but it was measured rather than assumed. And restoring the traces alone turned out to cost instruction-following — three of fourteen items, from a mixture whose general-answer share had been quietly diluted by the resampling — so the general-answer tiers were restored to their intended proportion in the same change.

The loader now prints a per-tier discard table on every run and refuses to train if losses exceed a threshold, and all twenty-three callers pass both flags explicitly so that a future change of default cannot reintroduce the problem.

## What did not work {#what-did-not-work}

After the repair, thirteen further variations were trained and evaluated to find out whether the recipe had more to give. None beat the released model.

[figure: Three-pool screen, greedy, n = 500 per pool. The band is the run-to-run variation of the identical
recipe, so anything inside it is unresolved rather than better.] Figure 6: Three-pool screen, greedy, n = 500 per pool. The band is the run-to-run variation of the identical recipe, so anything inside it is unresolved rather than better.

The mechanism is legible in the failures rather than the successes. Sort the variations by what they did to trace length and the answer is unambiguous: every arm that lengthened traces lost, and the size of the loss tracks the rate of unclosed traces. The 768-token cap is therefore load-bearing, and the seven-point repair described above is best understood not as more reasoning but as restored *endings*. The model was never short of derivation; it was short of conclusions.

The blend weight is the one variation whose effect is real without being a gain. Raising it to 1.00 — that is, dropping the weight average entirely — trades competition mathematics for word problems at three seeds (MATH-500 −4.8, GSM-Plus +4.1) for no net change in the mean, so the released value is better described as the balanced point than as an optimum.

One finding from this round is worth carrying forward on its own. A self-verification tier — training the model to re-derive and confirm its own result — had been abandoned earlier for costing 24 points on single-step arithmetic. It turns out that tier had barely been trained at all: 71 to 100% of its examples were cut by the 128-token cap, and since verification comes *after* the solution inside the reasoning block, the cap removed precisely the behaviour the tier existed to teach. Retrained with the loader fixed, it is the only data variation that gained anything. The corollary is methodological and outranks the rest: **every negative result recorded on this line before the fix is untrustworthy**, and there is now a one-command audit to check whether the tier carrying a hypothesis was ever actually shown to the model.

Two axes of the released model remain unmeasured, and are worth stating rather than leaving implicit: no tool-calling or coding evaluation was run on this family, and the instruction-following check is a 14-item probe rather than a benchmark. Neither is evidence of strength; both are gaps.

## Traps in post-training, evaluation and release {#traps-in-post-training-evaluation-and-release}

Each of the following cost measurable time or compute, and each is silent — none produced an error, and several produced entirely plausible logs. The base run had its own set, listed in the [companion article](https://youzhi.netlify.app/post/2026-08-05-argonne35-base/argonne35-base/).

1. **Two command-line defaults corrupted a third of the reasoning data**, with no effect on row count, step count or loss — the subject of the section above.
2. **Benchmarks can be uniformly blind to a severe regression.** Five multi-step problem sets, three seeds and a general-ability probe all passed while single-step arithmetic was failing half the time.
3. **One evaluation set was unusable and another leaked.** GSM8K is contaminated for every model on this line and is never reported; MATH-500 carries measured near-duplicate leakage, which is invisible to exact-match decontamination and had to be quantified.
4. **`pass@8` cannot separate two models.** Re-running the identical model, seed and settings reproduced greedy accuracy and self-consistency exactly and moved `pass@8` by 5.7 points.
5. **One seed decides nothing.** Two runs of the identical fine-tuning recipe differ by 1.7 points on a five-set mean and by up to 12 on a small probe. Two conclusions on this line were withdrawn for having been read from one seed.
6. **A throttled GPU is invisible in the log.** One node ran at 385 MHz of a possible 1,785 and 163 W of a possible 400, making a job 3.6× slower with no error. The clock and throttle reasons should be checked before the configuration is blamed.
7. **The effective batch size determines the number of GPUs**, not the reverse. An effective batch of 20 does not divide across three processes, and an unnoticed change silently breaks the pairing between batch size and learning rate.
8. **A configuration that is correct locally can be wrong when published.** The release build initially omitted the field that lets the model be loaded from the Hub at all, capped the trained 13,568-token context at 4,096, and set an end-of-sequence token that would have prevented generation from ever stopping. All three were correct for the local harness — which is exactly why no amount of evaluation could have found them. Only a diff against the artefact users receive did.
9. **The generated model card described a different model**, with the wrong layer count, the wrong hidden size, the wrong base model and no mention of reasoning. A release artefact needs reading before publication exactly like the weights do.

## Where the compute went {#where-the-compute-went}

Setting the two halves of the project side by side gives the clearest summary of what this kind of work actually costs. The base-model figures are from the run described in the companion article.

[figure: Measured from the scheduler accounting database. The horizontal axis is logarithmic; the three
non-base runs together are 1.8% of the total.] Figure 7: Measured from the scheduler accounting database. The horizontal axis is logarithmic; the three non-base runs together are 1.8% of the total.

The asymmetry is the practical argument of the whole project. The artefact people interact with is produced by three fine-tuning runs that together take less than a day on a few GPUs; what determines how good it can be was decided a month earlier, by what went into the base. The corollary is not that post-training is unimportant — it is where every point of deployable accuracy in this article came from — but that it can only spend what pretraining has already banked.

## Lessons {#lessons}

1. **Better pretraining raises the ceiling; only post-training raises the floor.** Improving the base moved what the model could produce by fifteen points and what it reliably produced by nothing. Expecting more pretraining to fix a deployment failure wasted several rounds of experiment before the distinction was measured.
2. **Termination is a capability.** More than half of all attempts were failing by never finishing. The fix was not a decoding trick but a training set restricted to examples that end, and every later attempt to relax that restriction lost.
3. **Read the data the trainer actually saw.** The largest single improvement in this article came from no new data, no new method and no new hyperparameter — only from removing two defaults that had been quietly discarding a third of it. The row count, the step count and the loss curve were all consistent with a healthy run.
4. **Evaluate the thing that is missing, not the thing that is easy to measure.** A suite of five respected benchmarks, replicated across seeds, was completely blind to a model that could not compute `2 + 2`.
5. **One seed is an anecdote.** Two withdrawn conclusions on this line were each a single lucky run of a recipe whose own variation is larger than most of the effects being chased.
6. **Free methods deserve a place in the pipeline.** The final weight average is an arithmetic mean of two checkpoints and costs minutes of processor time. On the first release it was worth about two points of mathematics and the model’s one general-ability failure; after the data repair its effect on the aggregate is inside the noise, and what it still buys is a balance — below α = 0.85 the reasoning traces stop closing, and above it the model trades competition mathematics for word problems.

## Availability {#availability}

- **Models:** [`Argonne-3.5-think`](https://huggingface.co/PursuitOfDataScience/Argonne-3.5-think) and the base it was built from, [`argonne-3.5-base`](https://huggingface.co/PursuitOfDataScience/argonne-3.5-base), on Hugging Face, alongside their [Argonne 3.0 counterparts](https://huggingface.co/PursuitOfDataScience).
- **Code:** [github.com/PursuitOfDataScience/ArgonneAI](https://github.com/PursuitOfDataScience/ArgonneAI) — the complete pipeline, one branch per version, together with the chronological reasoning-training log from which every number above is drawn, including the ablations that failed.
- **Companion article:** [*Argonne 3.5-base: Retraining an Unchanged Architecture With a Revised
Recipe*](https://youzhi.netlify.app/post/2026-08-05-argonne35-base/argonne35-base/) — how the base model beneath all of this was pretrained.
- **Earlier articles in this series:** [*Pretraining a Language Model From Scratch: Argonne 1.0 to
3.0*](https://youzhi.netlify.app/post/2026-07-23-pretraining-argonne/pretraining-argonne/) and [*How I Taught a Small Language Model to
Reason*](https://youzhi.netlify.app/post/2026-07-21-reasoning-model/reasoning-model/).

The first article in this series ended by claiming that capability is set during pretraining and that fine-tuning only calibrates it. Argonne 3.5 was built to test that claim and largely confirms it, with one qualification that took a month to see: the base sets the ceiling, but a model can sit far below its own ceiling for reasons that have nothing to do with capability — in this case, because it never brought to a close the reasoning it had correctly begun.

URL: https://youzhi.netlify.app/post/2026-07-21-reasoning-model/reasoning-model/
Title: How I Taught a Small Language Model to Reason
Date: 2026-07-21
---

For the last few years, this blog has mostly been about tidy data, statistical models, and the occasional TidyTuesday chart. This post is different. Over the past few months I did something I had wanted to try for a long time: I built a small AI language model **from scratch** — the same basic kind of technology behind chatbots — and then tried to teach it to *reason*: to work through a problem step by step before answering, the way you might show your work on a math test.

It mostly worked. The result is a model I call **Argonne 3.0-think**, and it is freely available online at [Hugging Face](https://huggingface.co/PursuitOfDataScience/Argonne-3.0-think). It can “think out loud” before answering, it can do grade-school math, and it can still hold a normal conversation.

This is the story of how I got there — including the many things that went wrong, because that is where I learned the most. If I had to put one lesson up front, it is this: the two things that helped most were surprisingly simple. First, feeding the model carefully chosen, double-checked examples of good reasoning. And second, a trick called **weight averaging** that costs almost nothing and, more than once, did more than weeks of fancier methods.

I have tried to write this so that you don’t need a machine-learning background to follow it. All of the numbers and every chart come from my own training logs.

## First — what does “teaching it to reason” even mean? {#first-what-does-teaching-it-to-reason-even-mean}

A quick, plain-English primer, so the rest makes sense.

A **language model** is the technology behind chatbots. At its heart it does one deceptively simple thing: it predicts the next word. Show it enough text and that single skill turns into fluent writing.

**Pretraining** is the first and most expensive phase: you show the model an enormous amount of text and have it guess the next word, over and over, billions of times, until it has absorbed grammar, facts, and style. What comes out is called a **base model**.

A base model can *continue* text, but it can’t yet *answer questions* or *follow instructions* — that takes further training on examples of good behavior, a phase called **fine-tuning**.

A **reasoning model** goes one step further still. Instead of blurting out an answer, it first writes out its thinking — a little scratchpad of steps — and only then gives the final answer. Think of it as showing your work. For anything that takes more than one step (arithmetic especially), that scratchpad helps a lot.

My goal was to take my own base model and turn it into a reasoning model. Here is the whole journey on one page; the rest of the post walks through it.

[figure: The full journey. Blue = a training step; grey = a checkpoint along the way; the two green steps are 'weight averaging' — combining two versions of the model for free, with no extra training.] Figure 1: The full journey. Blue = a training step; grey = a checkpoint along the way; the two green steps are ‘weight averaging’ — combining two versions of the model for free, with no extra training.

## It all starts with the base model {#it-all-starts-with-the-base-model}

Everything downstream depends on the quality of that first base model. Mine was a respectable size — about 2.9 billion internal values (its “parameters”) — trained on roughly 76 billion words of web text. For the technically curious:

 | Detail | Value

 | Size | ~2.88 billion parameters

 | Trained on | ~76 billion words of web text

 | Design | a standard modern Transformer (the architecture behind most chatbots)

 | Context window | up to ~13,000 words at once

You don’t need any of those numbers for the rest of the story. What matters is the single most important thing I learned in this whole project, and I’ll state it before any of the tricks:

**A model can only be fine-tuned to do what its foundation already supports.** Later training can *polish and unlock* a skill the base learned in rough form, but it almost never *creates* a skill from nothing. If the foundation is weak, fix the foundation — don’t try to paper over it later.

I did not believe this strongly enough at the start, and I paid for it in wasted weeks. My base model was **well-read but bad at arithmetic**. On a quick 20-question math quiz it got **3 right**; on a 15-question general-knowledge quiz it got **13**. It knew that the Red Planet is Mars; it could not reliably compute 8 + 3.

## Teaching it arithmetic — without making it forget everything else {#teaching-it-arithmetic-without-making-it-forget-everything-else}

The fix for weak arithmetic is to keep training the model, but this time on material that contains a lot of math.

My first instinct was to train it on math *only*. That was a disaster, and it taught me the second big lesson: **training is a zero-sum diet.** Pile on one skill and others quietly fade. The math-only model got much better at numbers and then confidently told me “the capital of France is France.” It had traded away its general knowledge to make room for arithmetic.

The fix was to **mix** math and ordinary web text together and shuffle them, so the model learned arithmetic *while* being constantly reminded of everything else. The chart below shows the different versions I tried, plotted by how they scored on the two quizzes. The goal was the top-right corner: good at both.

[figure: Each dot is a version of the base model. Up = better at math; right = better at general knowledge. Training on math alone shot up but slid left (it forgot things). Only averaging two versions together reached the top-right corner.] Figure 2: Each dot is a version of the base model. Up = better at math; right = better at general knowledge. Training on math alone shot up but slid left (it forgot things). Only averaging two versions together reached the top-right corner.

Mixing helped — math climbed to 14 out of 20 — but the general knowledge kept slowly slipping anyway. More math training would only deepen the forgetting. So instead of pushing harder, I reached for the first free trick.

## The first free trick: average two models together {#the-first-free-trick-average-two-models-together}

Here is the idea that unlocked everything, and it sounds almost too simple to work.

A trained model is just a giant list of numbers. If you have two closely related versions of the same model, you can build a new one by **averaging those numbers together** — no training, no data, just arithmetic that runs on a laptop in a couple of minutes. People call the result a “model soup.”

I averaged my original base model (great general knowledge, bad math) with the math-trained version (great math, fading knowledge). Sweeping the blend from one to the other traces out a trade-off, and there is a sweet spot where you get the best of both:

[figure: Blending the original base (left) with the math-trained version (right). Math climbs quickly and then levels off; general knowledge holds and then declines. The dashed line marks the blend I picked — the first version that was genuinely good at both.] Figure 3: Blending the original base (left) with the math-trained version (right). Math climbs quickly and then levels off; general knowledge holds and then declines. The dashed line marks the blend I picked — the first version that was genuinely good at both.

That averaged model — about one-third the original base and two-thirds the math-trained version — was the first version that did genuinely well on both quizzes at once. This became the solid foundation for everything that followed.

## Teaching it to chat {#teaching-it-to-chat}

A base model only continues text; it doesn’t answer you. Two standard steps fix that, and both are just “show it examples of what you want”:

- **Instruction training:** show it thousands of example conversations, so it learns to respond to a question instead of rambling on.
- **Preference training:** show it *pairs* of possible answers along with which one a person preferred, so it learns to be more helpful and better-mannered.

After these two steps I had a perfectly pleasant chatbot. It was also, tellingly, *still bad at math*. That was an important clue: being helpful and being able to reason are completely different skills, and politeness training does nothing for arithmetic.

## Teaching it to think out loud {#teaching-it-to-think-out-loud}

The step that actually creates a reasoning model is to fine-tune it on **worked solutions** — problems paired with the full, step-by-step reasoning, then the answer.

My first attempt backfired in an instructive way: the model learned the *look* of thinking without the *substance*. It would write confident-sounding steps riddled with mistakes (“7 × 6 = 42 … so the answer is 7”), get stuck repeating itself in loops, and sometimes dump computer code in response to a plain question. It had learned to *perform* reasoning rather than to reason.

The cure was not a cleverer method — it was better **data**. I built a carefully balanced set of about 113,000 examples: a large share of ordinary conversation (so it wouldn’t forget how to talk), plenty of short arithmetic drills that I generated and **double-checked with a computer** (so every example was actually correct), and a range of worked math problems from easy to hard.

 | Type of example | Roughly how many

 | Everyday conversation (no reasoning) | 34,000

 | Short arithmetic drills (auto-checked) | 15,000

 | Conversations with reasoning added | 15,000

 | Harder open-ended reasoning | 12,000

 | Grade-school word problems | 8,400

 | Medium-difficulty math | 5,700

 | Multi-step problems (auto-generated and checked) | 16,300

 | Other high-quality reasoning | ~7,000

Trained on this balanced diet, the model finally **aced arithmetic** — in both “thinking out loud” and “direct answer” modes. Something none of my fancier attempts had managed, the good data did on the first try.

But — the zero-sum diet struck again. Because the reasoning examples leaned heavily on math, the model’s ordinary conversation got *worse*: the loops came back on chit-chat, and it started forgetting facts again (it began insisting the Red Planet was Earth). I had a math whiz that had partly forgotten how to make small talk.

## The second free trick: average again {#the-second-free-trick-average-again}

The reasoning version was really just the chat version plus a set of adjustments that taught it to reason. So I could soften those adjustments by **averaging the chat version back in** — enough to bring back the conversation, but not so much that I lost the math or the ability to actually finish a chain of thought.

There turned out to be a clear sweet spot:

[figure: Blending the reasoning version back with the earlier chat version. Keep too little of the reasoning version (left) and the conversation returns but the step-by-step ability falls apart. The dashed line is the balance I shipped: it keeps perfect math and recovers the chat.] Figure 4: Blending the reasoning version back with the earlier chat version. Keep too little of the reasoning version (left) and the conversation returns but the step-by-step ability falls apart. The dashed line is the balance I shipped: it keeps perfect math and recovers the chat.

The mechanism is neat: keep too little of the reasoning version and the conversation comes back, but the model loses the ability to close off its scratchpad and give an answer. Keep too much and the chit-chat stays broken. The balance in the middle keeps perfect math *and* a healthy conversation. That final model scored **33 out of 40** on my overall check-up:

 | Skill area | Score

 | Math, direct answer | **10 / 10**

 | Math, thinking out loud | **10 / 10**

 | Conversation, direct answer | 7 / 10

 | Conversation, thinking out loud | 6 / 10

 | **Total** | **33 / 40**

Two simple ideas — good data and a bit of averaging — did the heavy lifting. Both averaging steps are essentially free, and they work precisely *because* the models being averaged are close relatives of one another.

## The things that didn’t work (where I learned the most) {#the-things-that-didnt-work-where-i-learned-the-most}

I want to be honest about the failures, because they were more instructive than the wins — and each one cost real time and computing power to learn.

### Rewarding correct answers just taught it to game the score {#rewarding-correct-answers-just-taught-it-to-game-the-score}

The obvious next idea is **reinforcement learning**: let the model attempt problems and reward it whenever it gets one right, so it gradually shifts toward correct behavior. I set this up carefully. It moved the numbers it was being scored on — and improved the actual accuracy not at all.

[figure: A reinforcement-learning run, from start to finish. The score it was being rewarded for climbed steeply, and it learned to finish its reasoning far more often — but the share of actually-correct answers didn't move.] Figure 5: A reinforcement-learning run, from start to finish. The score it was being rewarded for climbed steeply, and it learned to finish its reasoning far more often — but the share of actually-correct answers didn’t move.

The reason is subtle but important. At the start, the model stumbled onto a fully correct solution only about once in every few hundred tries. Reinforcement learning can only reward successes the model *already* produces occasionally — and correct answers were simply too rare to reinforce. So the only thing it could latch onto was the *format*: tidily finishing its scratchpad, which was easy and got rewarded. The takeaway matches the big lesson: **this kind of learning sharpens skills the model already has; it can’t manufacture one it lacks.**

A gentler version — letting the model learn from its own occasional correct answers — hit the same ceiling. You can only imitate the successes you already produce.

### A trick to stop the repetition backfired {#a-trick-to-stop-the-repetition-backfired}

When the model got stuck repeating itself, an obvious fix is to penalize it for reusing words. I tried it, and it **cut the math accuracy in half**. The reason is almost funny: punishing repeated tokens turned “80 ÷ 2” into “8 ÷ 2”, because the model refused to reuse the digit it had just written. Multi-digit arithmetic is repetitive by nature. Plain, boring decoding worked best.

## How do you even measure this honestly? {#how-do-you-even-measure-this-honestly}

Partway through, I discovered that one of my main tests had been **contaminated**: some of its questions had accidentally leaked into the training data, so good scores there were partly memorization. That was a humbling lesson in its own right — *the only trustworthy score is one from questions the model has never seen* — so I switched to clean tests it had no way to have memorized.

On those clean tests a striking pattern appeared, and it reframed the rest of the project. Look at four different ways of using the *same* model:

[figure: The same model, used four ways, on math tests it never trained on. Its single best guess is right about a fifth of the time — but a correct answer is hiding somewhere in 32 tries about three-quarters of the time.] Figure 6: The same model, used four ways, on math tests it never trained on. Its single best guess is right about a fifth of the time — but a correct answer is hiding somewhere in 32 tries about three-quarters of the time.

Its single best guess was right about 20% of the time. But if you let it try 32 times, a correct answer was among those tries about **74%** of the time. In other words, the ability was *there* — the model just couldn’t reliably *pick* or *land on* its own good answer. Most of the potential was locked up in that gap between what it knew and what it showed.

## Squeezing more out of the finished model {#squeezing-more-out-of-the-finished-model}

That gap suggested two different ways forward.

**First, bake improvements into the model itself.** The biggest single problem was that the model *over-thought* and rambled without ever finishing. So I did one more round of training using only short, complete solutions, which taught it to wrap up and give an answer on its own. That’s the version currently published.

**Second — and more powerful — help it at the moment you use it.** A few cheap tricks stack up nicely: nudge it to finish when it rambles, or generate several answers and take a vote. But the biggest win was to have a **second, stronger model read its 32 attempts and pick the best one**:

[figure: Same small model, but a second, stronger model picks the best of its 32 attempts. That nearly reaches the ceiling — the best you could possibly do if you always picked the right attempt.] Figure 7: Same small model, but a second, stronger model picks the best of its 32 attempts. That nearly reaches the ceiling — the best you could possibly do if you always picked the right attempt.

Letting a stronger model do the picking lifted accuracy from around 40% to about 70% — nearly the ceiling. I’m careful about how I describe this, though: the smarts there are really the *bigger* model’s, applied to my small model’s attempts. It makes the overall *system* better; it doesn’t make the small model itself smarter. (A similar idea worked for arithmetic: let the model call a calculator instead of doing the sums in its head, and its accuracy on those problems jumped to essentially perfect.)

The honest summary of this final stretch: on a model this small, the remaining gains come from *how you use it* — a helper model, a calculator — or from starting over with a stronger foundation. Not from more tinkering with this one set of weights.

## What it all taught me {#what-it-all-taught-me}

If I compress the whole project into a few plain lessons, this is the list I wish I’d believed on day one:

1. **The foundation sets the ceiling.** Later training polishes and unlocks ability; it rarely creates it. If a skill is missing, fix the base.
2. **Diagnose before you train.** A lot of my early “the model is broken” turned out to be simple bugs and a mislabeled test. Cheap checks first.
3. **Training is a zero-sum diet.** Push hard on one skill and others quietly regress — always re-measure everything, not just the thing you were improving.
4. **Looking like reasoning isn’t reasoning.** Teaching the *format* of step-by-step work is easy; getting the *content* right needed careful, verified data.
5. **Rewarding good answers only amplifies what’s already there** — it can’t conjure a skill the model doesn’t already have.
6. **The only trustworthy score comes from questions the model has never seen.** Everything else can look great while real progress stalls.
7. **When in doubt, go back to the data.** Across the entire project, good data was the only thing that reliably moved the honest numbers.

## Where this goes next {#where-this-goes-next}

Argonne 3.0-think is, to me, a satisfying proof that a small model built from scratch really *can* be taught to reason — and a very clear map of where its limits are. Those limits come down to the foundation. Encouragingly, the exact same recipe, applied to a stronger same-size foundation, sails through every test cleanly — which tells me the recipe was never the bottleneck; the foundation was. So the next chapter is a better base model to build on.

If you’d like the full technical detail — every setting, every dead-end, the exact code — it’s all public:

- **Model:** [Argonne 3.0-think on Hugging Face](https://huggingface.co/PursuitOfDataScience/Argonne-3.0-think)
- **Code:** [github.com/PursuitOfDataScience/ArgonneAI](https://github.com/PursuitOfDataScience/ArgonneAI/tree/argonne3.0-think) (tag `argonne3.0-think` — the exact code for this post)

Thanks for reading — it’s a nice change of pace to write up something this far from my usual TidyTuesday charts, and a good reminder that a humble idea like *averaging two models together* can quietly outperform a month of far fancier work.

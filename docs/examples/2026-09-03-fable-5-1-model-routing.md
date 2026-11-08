---
title: Fable 5.1 — performance, cost, and how it changes model routing
created: 2026-09-03
author: research-sources (Claude Fable 5.1, interactive session)
notebook: https://notebook.google.com/notebook/6df011dc-7391-4399-919f-345b6067e29f (public, view-only)
supplied_sources: 2 YouTube videos (Chase AI; Nate Herk)
added_sources: 11 (official docs, independent evaluators, practitioner tests, community)
promotable_to: wiki/ai/claude-5-model-family.md, wiki/ai/agent-model-assignment.md
status: example — sanitized copy of a real artifact, private paths and issue links generalized
---

# Fable 5.1: performance, cost, and model routing

## 1. Question and Scope

### Question

Three questions from the user on 2026-09-03:

- **Q1** Should Fable 5.1 replace Fable 5?
- **Q2** Should Fable 5.1 take use cases currently routed to Opus 5?
- **Q3** Are there better metrics than Anthropic's table to validate its claims on performance and cost?

Scope: model routing for the user's Claude Code sessions and agent fleet. Out of scope: API integration migration (the two videos and the migration guide cover it, but the user's fleet runs through Claude Code, which handles the breaking changes).

### Answer

- **Q1: Yes, unconditionally.** Same list price, cache reads at a quarter of Fable 5's rate, higher scores at every effort level, and about 60% fewer cyber-safeguard interventions in Claude Code. Fable 5 retains no advantage. The main session already runs `claude-fable-5-1[1m]` per the user's Claude Code settings (validated: read the file).
- **Q2: Yes for three shapes of work, no as a general default.** Escalate from Opus 5 to Fable 5.1 for long-running agentic sessions with large reused context, multistep research, and debugging where Opus 5 at high effort fails. Opus 5 stays the default for interactive, short, and output-heavy work. Anthropic's own docs say the same: start with Opus 5, escalate to Fable 5.1 when evals at higher effort still fall short. Run Fable 5.1 at high, not max: every headline score was measured at max, and the per-effort curves in §2g show high captures nearly all of it at a fraction of the cost.
- **Q3: Yes, three independent evaluators have scored it, and the one metric that matters for this decision does not exist yet.** Artificial Analysis, ARC Prize, and LMArena confirm the direction of Anthropic's table. None compares Fable 5.1 to Opus 5 at high effort, and none runs the user's workloads. The benchmark harness built for exactly that question (a private harness repo, six tickets) has not yet produced a Fable-vs-Opus-5 comparison.

**Confidence:** high on Q1 (official pricing and docs, no contrary signal). Medium-high on Q2 (Anthropic's guidance plus every independent cost number agree, but the coding gap rests on a vendor table and one independent index). High on Q3's first half, and the second half is a verified absence.

**What would change the answer:** a high-vs-high bench run showing Fable 5.1 beats Opus 5 by more than its 1.6x to 1.8x cost premium on the fleet's real tasks would move it toward the gen-agent default. A measured quota burn rate on Max that makes the 50% weekly cap bind in normal daily use would push the other way.

## 2. Source Summary

### 2a. What the two supplied videos say

**Chase AI, "Fable 5.1 Is The Greatest Model Ever (And Cheaper Than Fable 5)."** A read-through of the official charts, no live tests. Claims: Fable 5.1 beats Fable 5, Opus 5, and GPT-5.6 Sol on every benchmark in Anthropic's table. Agentic coding rose from 42% (Fable 5) to 55.8%. On Terminal-Bench, Fable 5.1 at medium effort matches Fable 5 at max at $7.80 versus $26.00 per the chart, and high versus max on Fable 5.1 gives up about 6% of score for $10.50 versus $19.50. On CursorBench, Fable 5.1 at high matches Fable 5 at xhigh at less than half the cost. Cache reads are 75% cheaper, which he reads as about 25% cheaper on typical tasks and up to 45% on long agentic runs. Safeguards produce 60% fewer false positives on cybersecurity questions, so fewer silent fallbacks to Opus. His caveats: the science benchmark jumps are niche, and the anti-distillation change does not affect end users. His recommendation: use Fable 5.1 over Opus 5 for everything.

**Nate Herk, "Fable 5.1 Just Dropped. It Looks Unreal."** Same official-chart read, plus one open-ended test. Claims: Fable 5.1 at low effort scores above Fable 5 at high, xhigh, or max on the terminal-coding chart, at $1.10 versus $34 to $44. His test was a "rotating 3D cartoon bear riding a bike" prompt in the desktop app: Fable 5.1 took 6m34s and $4.53, Fable 5 was slightly faster and $5.41, and he judged the 5.1 output better on shadows and physics. His caveats: take the benchmarks "with a grain of salt," his test is not a benchmark, and he had used the model for only a short time. No Opus 5 comparison.

### 2b. Anthropic's benchmark table (vendor-reported)

| Benchmark | Fable 5.1 | Fable 5 | Opus 5 | GPT-5.6 Sol |
|---|---|---|---|---|
| Terminal-Bench-Science 0.1 | 52.6% | 24.7% | 29.0% | 22.4% |
| Terminal-Bench 4.0 | 55.8% | 42.0% | 52.3% | 37.3% |
| GDPval-AA v2 (Elo) | 1853 | 1723 | 1824 | 1711 |
| OSWorld 2.0 partial | 77.9% | 72.9% | 75.4% | — |
| OSWorld 2.0 strict | 41.7% | 36.1% | 39.6% | — |
| Humanity's Last Exam, no tools | 60.9% | 57.8% | 56.6% | — |
| Humanity's Last Exam, with tools | 65.0% | 63.8% | 63.6% | — |
| AutomationBench | 31.4% | 17.1% | 26.9% | 19.6% |
| CursorBench 3.2.0 | 73.4% | 70.5% | 70.0% | 67.2% |

The gap over Opus 5 is large on science and business automation and small elsewhere. On CursorBench, the coding benchmark closest to the user's work, the lead is 3.4 points. Anthropic notes Fable scored zero on OSWorld and AutomationBench tasks where safeguards intervened, so those numbers are floors. No SWE-bench Verified score was published for 5.1.

### 2c. Independent measurements

**Artificial Analysis Intelligence Index v4.1.1** (nine evaluations including Terminal-Bench v2.1, GDPval, tau-Banking, SciCode, HLE, GPQA):

| Model at max effort | Index | Cost to run the index per task |
|---|---|---|
| Fable 5.1 | 66 | $3.76 |
| Opus 5 | 63 | $2.34 |
| Fable 5 | 62 | $3.14 |
| GPT-5.6 Sol | 61 | — |
| Fable 5.1 at xhigh | — | $2.72 |

Fable 5.1 at max used about 1.7 times Fable 5's output tokens. Its run used the default server-side fallback, which routed about 4% of output tokens to Opus 4.8 or Opus 5. Output speed 66 tokens/s versus Opus 5 at 56. Time to first token at max effort: 285 s versus Opus 5 at 82 s.

**ARC Prize, verified semi-private:**

| Effort | ARC-AGI-1 | ARC-AGI-2 | Cost/task |
|---|---|---|---|
| Max | 97.5% | 90.0% | $1.40 (v1), $4.49 (v2) |
| XHigh | 96.5% | 90.0% | — |
| High | 96.0% | 88.8% | — |
| Medium | 94.5% | 86.3% | — |
| Low | 90.0% | 78.3% | — |

xhigh matches max on ARC-AGI-2. The medium-to-max spread is 3.7 points.

**LMArena, 2026-09-02:** Fable 5.1 at max ranks 3rd at 1504 ±11 on 2,906 votes. Opus 5 at high ranks 9th at 1493 ±5 on 35,174 votes. The intervals overlap, so human preference has not separated the two.

**Techsy metered test, 2026-09-02:** 14 tasks over OpenRouter at low effort, graded by schema validation, exact match, and executed unit tests. All three models scored 14/14. Cost: Fable 5.1 $0.147, Fable 5 $0.133, Opus 5 $0.081. Median latency: 5.6 s, 5.4 s, 4.8 s. At low effort on short tasks, Fable 5.1 bills 1.8 times Opus 5 for identical results.

**Simon Willison, effort sweep on one SVG prompt:** low 1,998 output tokens, $0.10, 24 s. Medium about the same. High 2,612 tokens, $0.13, 30 s. XHigh 36,767 tokens, $1.83, 7m51s. Max 65,927 tokens, $3.30, 13m54s. The cost step from high to xhigh is 14 times. He calls his impressions "all vibes."

**Ethan Mollick, early access:** "a real advance in long-run work that requires judgement and taste, but less of an advance" elsewhere. Ran autonomously up to 12 hours on multi-page specs.

### 2d. Pricing and quota (official)

| Model | Input | 5m cache write | 1h cache write | Cache read | Output |
|---|---|---|---|---|---|
| Fable 5.1 | $10 | $12.50 | $20 | $0.25 | $50 |
| Fable 5 | $10 | $12.50 | $20 | $1.00 | $50 |
| Opus 5 | $5 | $6.25 | $10 | $0.50 | $25 |
| Sonnet 5 | $2 | $2.50 | $4 | $0.20 | $10 |
| Haiku 4.5 | $1 | $1.25 | $2 | $0.10 | $5 |

Sonnet 5's planned September increase to $3/$15 was cancelled. Fable 5.1's cache read is half of Opus 5's, and one analysis puts the crossover where Fable 5.1 becomes cheaper than Opus 5 at roughly 140,000 tokens of reused context per turn. Batch is 50% off. Fast mode exists only for Opus 5 and Opus 4.8 at $10/$50.

Plan rules from Anthropic's help center: on Max and premium Team/Enterprise seats, Fable models are included up to 50% of the weekly limit and draw from the same pool as every other model, faster. Pro and standard Team seats get Fable only via usage credits. Claude Code needs 2.1.255 or later. The user's machine runs 2.1.259 (validated: `claude --version`). Web and Cowork default to medium effort, Claude Code to high.

### 2e. Safeguards, fallback, retention

Fable 5.1 runs the same classifier categories as Fable 5, broader than Opus 5's cyber-only set: cyber, bio, reasoning extraction, frontier ML development. Cyber falls back to Opus 4.8, bio to Opus 5. The user sees a notice and the response is labeled with the model that answered. Input-blocked requests bill at Opus rates. Anthropic claims about 60% fewer cyber interventions per Claude Code session than Fable 5, and vulnerability discovery is now allowed while exploit development is not. Fable 5.1 requires 30-day retention and is unavailable under zero data retention unless Anthropic authorizes it. Opus 5 is available under zero data retention.

### 2f. Behavior changes that matter for a harness

From Anthropic's "What's new" page, each with a prompt-level fix:

- Parallel tool calling is more variable. It may issue one tool call per turn where Fable 5 batched several. Extra turns cost tokens and wall-clock, not quality.
- Fewer progress updates during long tool runs, especially at higher effort.
- At low effort it answers from memory more often instead of calling search or retrieval.
- Denser prose, less chat formatting, more unmarked quotation in summaries.
- More whole-file rewrites where a targeted edit would do.
- Forced tool choice returns an error. Thinking cannot be disabled. Older models cannot read its thinking blocks, so a fallback or router switch to Opus drops reasoning and re-plans.
- Effort can change mid-conversation without breaking the cache. Anthropic's guidance: default high, sweep on your own evals, gains over Fable 5 concentrate at xhigh and max.

### 2g. Effort level: where the scores were measured, and where the value is

Every headline number in this artifact was measured at max effort. That is the wrong level for daily use, and the per-effort data that exists says so.

**Which sources measured which effort levels:**

| Source | Levels measured | What it shows |
|---|---|---|
| Anthropic benchmark table (§2b) | max only | Headline scores |
| Artificial Analysis index | max, plus xhigh cost | 66 at max costs $3.76 per task; xhigh costs $2.72 |
| LMArena | max | 1504 ±11 |
| Techsy 14-task test | low only | 14/14 for every model; Fable 5.1 bills 1.8x Opus 5 |
| ARC Prize | all five | Full score curve, below |
| Simon Willison | all five | Full cost curve, below |
| Anthropic effort-vs-cost charts (read by both videos) | all five | Fable 5.1 medium matches Fable 5 max on Terminal-Bench at $7.80 vs $26 |

**ARC Prize score curve, verified semi-private:**

| Effort | ARC-AGI-1 | ARC-AGI-2 | Gain over previous level |
|---|---|---|---|
| Low | 90.0% | 78.3% | — |
| Medium | 94.5% | 86.3% | +4.5 / +8.0 |
| High | 96.0% | 88.8% | +1.5 / +2.5 |
| XHigh | 96.5% | 90.0% | +0.5 / +1.2 |
| Max | 97.5% | 90.0% | +1.0 / +0.0 |

Medium to high buys the last large gain. High to max buys 1.5 points on ARC-AGI-1 and 1.2 on ARC-AGI-2.

**Willison cost curve, one SVG prompt:**

| Effort | Output tokens | Wall-clock | Cost | Multiple of high |
|---|---|---|---|---|
| Low | 1,998 | 24 s | $0.10 | 0.8x |
| Medium | 1,977 | 23 s | $0.10 | 0.8x |
| High | 2,612 | 30 s | $0.13 | 1.0x |
| XHigh | 36,767 | 7m51s | $1.83 | 14x |
| Max | 65,927 | 13m54s | $3.30 | 25x |

Low through high sit within a factor of 1.3 of each other. The step to xhigh is 14x on cost and 16x on wall-clock. Artificial Analysis saw the same shape at scale: Fable 5.1 at max used 1.7 times Fable 5's output tokens across its index, and its output ranged from 13.1M tokens at low to 143.7M at max.

**From the official charts the two videos read:** Chase AI's reading of Anthropic's Terminal-Bench chart puts Fable 5.1 at medium level with Fable 5 at max at $7.80 versus $26.00, and high versus max on Fable 5.1 at about 6% of score for $10.50 versus $19.50. On CursorBench, high on Fable 5.1 matches xhigh on Fable 5 at under half the cost. Nate Herk's reading: low on Fable 5.1 outscores Fable 5 at high, xhigh, or max on the terminal-coding chart at $1.10 versus $34 to $44. These are chart readings of vendor data, not measurements, but they agree with ARC and Willison on shape.

**Anthropic's own guidance** (migration guide): the default is high. Keep the Fable 5 rule of high for most work and medium as a cost control worth testing. Gains over Fable 5 concentrate at xhigh and max, which also add thinking time and time-to-first-response, so step up only for capability-sensitive tasks where evals show the gain. Run a fresh sweep rather than carrying a Fable 5 setting over. Effort can now change mid-conversation without invalidating the cache, so a session can run high and raise one hard step to xhigh.

**Current defaults by surface:** Claude Code runs Fable 5.1 at high. The web app and Cowork run it at medium. Thinking cannot be disabled, so low is the floor.

**The gap that matters:** no published source compares Fable 5.1 to Opus 5 at high against high. The cross-model comparisons exist only at max (Artificial Analysis, LMArena, vendor table) and at low (Techsy). The routing decision in §4 needs the high-vs-high number, which is why the benchmark action holds effort at high for both models.

### 2h. Community reception

Hacker News launch thread: an Anthropic employee reports a less stereotypical writing style. The dominant thread is about Opus-family prose being dense and hard to read in long sessions. Social reports of Max users exhausting a 5-hour window in minutes on Fable 5.1 (one cites 52 minutes for a 20x window on one prompt). Some HN commenters call the release incremental and suspect benchmark overfitting.

## 3. Source Assessment

- **The two videos are commentary on Anthropic's charts, not evidence.** Neither presenter tested against Opus 5. Chase AI's "beats Opus at literally everything" is true of the vendor table and still consistent with a 3-point index gap at 1.6 times the cost. Nate Herk's one-prompt cost comparison ($4.53 vs $5.41) has n=1 and no quality rubric. Both correctly flag their own limits. Treat them as a reading guide to the launch post, nothing more.
- **Anthropic's table is directionally confirmed by three independent evaluators** (Artificial Analysis first place, ARC Prize verified, Vals AI first place). The direction is solid. The magnitude on coding is small: CursorBench +3.4, Terminal-Bench 4.0 +3.5, Intelligence Index +3.
- **Cost claims need the denominator.** "25% cheaper" and "45% cheaper" are relative to Fable 5 and depend on cache-read share. Relative to Opus 5, Artificial Analysis measured Fable 5.1 at 1.6 times the cost per task at max, and Techsy at 1.8 times at low. The one direction Fable 5.1 wins on cost is cache-read-dominated sessions, where its $0.25 read rate is half Opus 5's.
- **Effort, not model, drives the biggest cost swings, and the headline scores hide it.** Every cross-model score in this artifact was taken at max. Willison's 14x cost step from high to xhigh and ARC's 1.5-point high-to-max gain say the same thing from two sides: medium to high is where the value is, and max is a benchmark setting. Any model comparison that does not hold effort constant is not a comparison, and none of the published Fable-vs-Opus-5 comparisons hold it at high.
- **The fallback caveat applies to the independent numbers too.** Artificial Analysis's score includes about 4% of tokens answered by Opus. The "60% fewer interventions" figure is vendor-reported and unverified.
- **Latency is the least-reported and most decision-relevant number.** Only one secondary write-up quotes time to first token (285 s vs 82 s at max). This is a secondary source citing Artificial Analysis; the artifact treats it as plausible but unverified against the primary.
- **Community quota reports are directionally consistent with the July Fable 5 pattern** already recorded in the wiki (Max 20x exhausted in about 24 hours of orchestrator use). They are self-selected and do not separate effort level from model.
- **No contradiction between sources.** The only tension is framing: the videos say "use Fable 5.1 for everything," Anthropic's docs say "start with Opus 5." The evidence supports Anthropic's framing.
- **The user's harness config does not match the wiki policy** (validated: grep of `agents/*.md` frontmatter). The wiki says Opus 5 is the gen and eval default. The agent files pin gen agents to `sonnet` and eval and investigate agents to `claude-opus-4-8`. This is unrelated to Fable 5.1 but changes what "Opus use cases" means in practice: today almost nothing in the fleet runs Opus 5.

## 4. How to Absorb

The profile records the wiki as enabled, so all three classes apply.

### Actions

#### <harness repo>/hooks/model-ceiling-guard.sh

| Field | Detail |
|---|---|
| **What exists now** | The alias table maps `fable` and `claude-fable-5` to the frontier tier. `claude-fable-5-1` is absent, and an unknown ID exits 0, so a subagent dispatched with the full Fable 5.1 ID passes any ceiling. |
| **Change** | Add `"claude-fable-5-1": "frontier"` to the alias table and a matching case to `tests/hooks/test-model-ceiling.sh`. Run inline on approval. |
| **Why** | The ceiling exists to conserve tokens. Fable 5.1 is the most expensive model in the fleet and currently the only one the guard cannot see. |
| **Confidence** | High. Read the guard source directly. |

#### <harness repo>/benchmarks (Fable 5.1 vs Opus 5 run)

| Field | Detail |
|---|---|
| **What exists now** | The harness and its suites exist for the Fable-vs-Opus-5 orchestrator question. The 2026-08-03 model report returned INSUFFICIENT-DATA for every seat except scheduled jobs, and no run has included Fable 5.1. |
| **Change** | File a GitHub issue in the harness repo to run the existing orchestration and generation suites with `claude-fable-5-1` and `claude-opus-5` as the model axis, effort held at high for both, three repeats, reporting cost per task, wall-clock, and the verification-honesty and boundary-adherence dimensions already defined. Route: `artifact_followup_destination` is GitHub Issues for project work. |
| **Why** | This is the only measurement that answers Q3 for the user's workloads. Every public benchmark holds effort and harness differently from the fleet. Skipping it leaves the routing rule below resting on vendor tables and a 14-task low-effort test. |
| **Confidence** | High that the run is needed. Medium that the suites are ready to execute without repair, per the harness README's own note that the suites are separate tickets. |
| **Rejected** | Trusting Artificial Analysis cost-per-task as a proxy. Its tasks are single-turn evaluations, not multi-hour agent loops with cache reuse, which is where the two models' economics diverge. |

### Wiki Additions

#### <vault>/wiki/ai/claude-5-model-family.md

| Field | Detail |
|---|---|
| **What exists now** | The tier table lists Fable 5 at $10/$50 with the classifier-fallback, 30-day retention, and quota-bucket notes. It has no Fable 5.1 row, still states Sonnet 5 at "$3/$15 (post-August standard)," and the Fable section describes fallback as silent. |
| **Change** | Add a Fable 5.1 row (released 2026-09-01, $10/$50, cache read $0.25, 1M context, 128K output, thinking always on, Claude Code 2.1.255+). Add a "Fable 5.1" subsection with the vendor table from §2b, the independent numbers from §2c, the effort-cost data, the behavior changes from §2f, and the corrected fallback description (user-visible label, Opus billing on input-blocked requests, 4% of tokens in the Artificial Analysis run). Correct Sonnet 5 to $2/$10 with the cancelled increase. Mark Fable 5 as superseded. Update the Key Takeaways and Sources. Leave the Opus 5 and Sonnet 5 alignment content alone. |
| **Why** | This is the article the routing policy reasons over. Without it the next model-selection session re-derives everything above. |
| **Confidence** | High on prices, quota, and behavior changes (official docs). Medium on the coding-gap magnitude (vendor table plus one independent index). |

#### <vault>/wiki/ai/agent-model-assignment.md

| Field | Detail |
|---|---|
| **What exists now** | Assignment table gives Fable 5 one row: "Peak-difficulty advisory, selectively." The persistent-orchestrator question is listed as open pending benchmark data. Sources are July 2026. |
| **Change** | Replace the Fable 5 row with a Fable 5.1 rule: main interactive session on Fable 5.1 (already true in settings), plus escalation from Opus 5 for three shapes of work: multi-hour agentic runs with large cached context, multistep research and document synthesis, and debugging where Opus 5 at high effort fails. Add an explicit "stay on Opus 5" list: short interactive turns, latency-sensitive work, output-heavy generation, anything needing zero data retention. Add an effort rule with the §2g curves as its evidence: high by default (already Claude Code's default), medium as the cost control to test, xhigh raised mid-conversation for one hard step where evals show the gain, never max for routine work. State that every published Fable 5.1 headline score is a max-effort number and does not describe the high-effort model the fleet runs. Add a note that the fleet's agent files currently pin gen to Sonnet and eval to Opus 4.8, so "Opus use cases" in this decision means the interactive session and ad-hoc dispatches, not the agent roster. Keep the persistent-orchestrator question open and point it at the benchmark action above. |
| **Why** | This is the answer to Q2 in the place future sessions read it. |
| **Confidence** | Medium-high. The rule matches Anthropic's own guidance and every independent cost number. The specific 140K-token cache crossover is from a secondary source and is stated as approximate. |
| **Rejected** | Making Fable 5.1 the default for gen agents. At 1.6 to 1.8 times Opus 5's cost per task for a 3-point gain, and with the 50% weekly-limit rule, that trades the whole quota for a marginal coding delta. Also rejected: recording the agent-roster mismatch as a fix here. It predates Fable 5.1 and deserves its own decision. |

Named referents considered: Artificial Analysis, ARC Prize, and LMArena each appear once in this evidence set and have no existing wiki page. None recurs across articles yet. No entity page proposed.

### Document Updates

None. The benchmark harness README already states the question the action above executes.

## 5. Evidence Record

NotebookLM notebook ["Research: Fable 5.1 performance and model routing"](https://notebook.google.com/notebook/6df011dc-7391-4399-919f-345b6067e29f), shared publicly so the evidence layer is inspectable. 13 sources indexed. Firecrawl was configured but its MCP server failed to connect this session, so every web page was read with the native fetch tool.

| # | Source | Type | How obtained and verified |
|---|---|---|---|
| S1 | [Chase AI video](https://youtu.be/onL8VFMzxsA) | Supplied, DERIVATIVE | NotebookLM native YouTube indexing, source `47d7ecde`. Claims extracted by notebook query. |
| S2 | [Nate Herk video](https://youtu.be/8IyORt-7rOQ) | Supplied, DERIVATIVE | NotebookLM native indexing, source `7467406d`. Same query. |
| S3 | [Anthropic launch post](https://www.anthropic.com/claude-fable-and-mythos-5-1) | PRIMARY | Fetched 2026-09-03. Benchmark table, safeguards, retention, availability. Notebook source `4daefe85`. |
| S4 | [What's new in Fable 5.1](https://platform.claude.com/docs/en/models/fable-5-1/whats-new-fable-5-1) | PRIMARY | Fetched in full. Source of the "start with Opus 5" guidance and the behavior-change list. Not added to notebook (content overlaps S5). |
| S5 | [Migration guide](https://platform.claude.com/docs/en/models/fable-5-1/migration-guide) | PRIMARY | Fetched in full, 90 KB, grepped for guidance. Notebook source `4c5db57d`. |
| S6 | [Pricing docs](https://platform.claude.com/docs/en/about-claude/pricing) | PRIMARY | Fetched in full. Table in §2d. Notebook source `35a7147e`. |
| S7 | [Fable models on your plan](https://support.claude.com/en/articles/15424964-claude-fable-models-on-your-plan) | PRIMARY | Located by search, added to notebook as `4de05774`. 50% rule and Claude Code version floor. |
| S8 | [Why Claude switched models](https://support.claude.com/en/articles/15363606) | PRIMARY | Fetched. Fallback categories, notice, billing. Notebook `a7793a8b`. |
| S9 | [Artificial Analysis](https://artificialanalysis.ai/articles/claude-fable-5-1) | SECONDARY, independent | Fetched. Index, cost per task, fallback share. Notebook `67085950`. |
| S10 | [ARC Prize results](https://arcprize.org/results/anthropic-claude-fable-5-1) | SECONDARY, independent | Fetched. Per-effort scores and cost. Notebook `0d796c7a`. |
| S11 | [Techsy metered test](https://techsy.io/en/blog/claude-fable-5-1) | SECONDARY, practitioner | Fetched. 14-task, 49-call, $0.54 test. Notebook `d9bfc5f6`. |
| S12 | [Simon Willison](https://simonwillison.net/2026/Sep/1/claude-fable-5-1/) | SECONDARY, practitioner | Fetched. Effort sweep costs. Notebook `ca84912f`. |
| S13 | [Vellum benchmarks explained](https://www.vellum.ai/blog/claude-fable-5-1-mythos-5-1-benchmarks-explained) | DERIVATIVE | Fetched. Used only to cross-check S3's table and the "floors" caveat. Notebook `77bf07d6`. |
| S14 | [emergent.sh Fable 5.1 vs Opus 5](https://emergent.sh/learn/claude-fable-5-1-vs-opus-5) | DERIVATIVE | Fetched. Source of the 140K-token cache crossover estimate. Notebook add failed on a JSON parse error, not retried. |
| S15 | [Secondary model comparison](https://example.invalid/secondary-model-comparison) | DERIVATIVE | Fetched. LMArena numbers and time-to-first-token, attributed to Artificial Analysis but not verified against it. Not added to the research workspace. |
| S16 | [Hacker News launch thread](https://news.ycombinator.com/item?id=49525378) | Community | Fetched, top 15 comments summarized. Notebook `23da7510`. |
| S17 | Ethan Mollick early-access post | Community | Surfaced by search summary only, primary post on X not fetched. Quoted phrase is from the search result. |
| S18 | Quota-exhaustion reports | Community | Surfaced by search summary only, from an X trending page and Reddit. Not fetched directly. Directional only. |
| Local | `wiki/ai/claude-5-model-family.md`, `wiki/ai/agent-model-assignment.md`, `wiki/ai/claude-5-early-community-reception.md`, `output/2026-08-03-model-comparison-report.md` | Prior work | Read in full. Baseline the plan edits against. |
| Local | `settings.json`, `<harness repo>/agents/*.md`, `hooks/model-ceiling-guard.sh`, `benchmarks/README.md` | Harness state | Read directly. Source of the settings, agent-pin, and ceiling-guard findings. |

Searched and not found: a SWE-bench Verified score for Fable 5.1 (absent from S3, S9, S13, and S15, which states the omission directly). A system card fetch was not attempted; the launch post links it and no claim here depends on it. No Reddit thread was fetched directly because the community signal was already consistent with the July record and the stakes of one more thread were below its cost.

## 6. Evidence Gaps

| Gap | Follow-up |
|---|---|
| No Fable 5.1 vs Opus 5 measurement on the user's workloads, effort held constant. | The benchmark action in §4. Nothing public will close this. |
| Time to first token (285 s vs 82 s) comes from a secondary source. | Open the [Artificial Analysis model page](https://artificialanalysis.ai/models/claude-fable-5-1) and read the latency chart. One minute. |
| The 60% fewer cyber interventions claim is vendor-only. | Observe over two weeks of Fable 5.1 sessions: count model-switch notices. First-party only. |
| Whether the agent roster's Sonnet and Opus 4.8 pins are deliberate or drift from the July policy. | Not closable from evidence. It is a decision for the user. Named in the wiki edit, not proposed as a fix here. |
| Quota burn rate on Max with Fable 5.1 at high effort in Claude Code. | First-party only: read `/usage` after a day of normal work. Community numbers do not separate effort from model. |

## 7. Execution Appendix

| ID | Decision | Destination and action | Target | Task route | Preconditions | Terminal disposition |
|----|----------|------------------------|--------|------------|---------------|----------------------|
| E1 | A1 | direct code update plus test case | `<harness repo>/hooks/model-ceiling-guard.sh`, `tests/hooks/test-model-ceiling.sh` | — | approval; run from main checkout | target document updated |
| E2 | A2 | follow-up task | harness repo GitHub issue: bench run fable-5-1 vs opus-5 | GitHub Issues (`artifact_followup_destination`) | approval; `spec/*` level confirmed with the user | task filed |
| E3 | W1 | stage S3, S4, S6, S7, S8, S9, S10, S11, S12 provenance then compile | `wiki/ai/claude-5-model-family.md` | — | approval | integrated |
| E4 | W2 | stage S4, S9, S11, S14 provenance then compile | `wiki/ai/agent-model-assignment.md` | — | approval; E3 first | integrated |

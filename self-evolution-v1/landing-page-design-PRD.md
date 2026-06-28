# Yunaki — Landing Page Design PRD

*Design requirements for the marketing site. Balanced playful-but-technical, Cleo-inspired flow.*

**Status:** Draft v1 · **Owner:** Yugandhar · **Date:** 2026-06-27

---

## 1. What we're selling (in one breath)

Yunaki is a self-evolving skill layer for coding agents. The agent runs a task, gets scored by real tests, and when it fails, Yunaki mines the failure for a reusable skill, banks it, and injects it into the next run — then proves the gain *honestly* against a no-skills control arm.

The one-liner the whole page hangs on:

> **Your coding agent keeps making the same mistakes. Yunaki makes sure it doesn't.**

The emotional hook (the part we borrow from Cleo): most "agent improvement" is hand-wavy. Yunaki's personality is *brutal honesty about whether it actually worked.* That's our "Cleo roasts your spending" equivalent — we roast vanity metrics. `skill_delta` vs. control is the soul of the brand.

---

## 2. Why Cleo is the right reference — and where we diverge

Cleo's landing page works because it has a **character with an attitude** and it never stops being useful. Its DNA, decoded from the live page:

- Big, blunt, two-beat headlines: *"Money talks. Cleo talks back."*
- Conversational, slightly cheeky body copy — talks *to* you, not at you.
- Highlight-marker emphasis on the punchline of each feature.
- Tabbed feature switchers (Save / Card / Debt) instead of endless scroll.
- Heavy social proof with real personality in the quotes ("I love the roasts").
- A recurring personality line that becomes a tagline ("a financial assistant without a fleece vest").
- Repeated, low-friction CTA ("Get the app") anchored top, middle, and bottom.

**Where we diverge:** Cleo sells *feeling* (less money anxiety). We sell *feeling + proof*. Every playful claim on our page must be cashable in a number, a code block, or a chart. The audience is split between individual devs/AI engineers (who want the loop and the receipts) and eng leaders (who want ROI and rigor). So the rule is: **Cleo's warmth and confidence, Linear/Braintrust's evidence.** Personality on the surface, telemetry one scroll away.

---

## 3. Audience & what each one needs to see

**Primary A — Individual devs / AI engineers.** Already run a coding agent (Claude Code, Cursor, Gemini CLI, etc.). Skeptical of "magic improvement." They convert on: the loop diagram, a real extracted skill, the honest-delta framing, "works with your existing CLI," and a fast path to try it.

**Primary B — Eng leaders / teams.** Evaluating agent infrastructure. They convert on: measurable ROI, the control-arm methodology (no cherry-picking), governance/lifecycle, and "it's a measurement system, not a vibe." Give them a quotable stat and a section that signals seriousness.

Design implication: a single page, but two reading speeds. Skimmers (leaders) get headline + stat + chart. Diggers (engineers) get the expandable code, the loop, the architecture. Don't make either group scroll past a wall meant for the other.

---

## 4. Voice & tone

Confident, dry, a little cocky — but the cockiness is always backed by the honest metric. We're allowed to be funny because we're the ones holding ourselves to a control arm.

**Do:** short declaratives. Second person. Name the pain directly ("Your agent forgot how to do this last Tuesday too"). Let numbers land on their own line.

**Don't:** buzzword soup ("revolutionary AI-powered synergy"), exclamation spam, or any claim we can't show. No fake enthusiasm — the brand's whole thing is that it doesn't lie to you.

**Voice samples (use as copy starting points):**

- Hero: *"Your coding agent keeps making the same mistakes. Yunaki makes sure it doesn't."*
- Honest-metric section: *"Everyone reports 'before vs. after.' That number lies. We run a control arm and report the delta. Sometimes it's small. We'll tell you when it is."*
- Loop section: *"Fail once. Learn forever."*
- Compatibility: *"Bring your own agent. We detect your CLI and get to work."*
- Tagline candidate (the "fleece vest" equivalent): *"An agent that gets better, and the receipts to prove it."* / *"Self-improvement you can actually grade."*

---

## 5. Visual design system

**Mood:** warm-technical. Cleo runs a warm dark base (`theme-color #47201c`, a deep cocoa). We take that cue — *warm dark, not cold dark* — to separate ourselves from the wall of blue-black dev tools (Linear, Vercel) while staying credible.

**Color**

- Base / background: warm near-black, deep espresso-charcoal (`#1A1614`-ish) rather than pure `#0A0A0A`.
- Surface cards: a step lighter, slightly warm (`#241E1B`).
- Primary accent (energy / CTA): one confident, slightly acidic color — lime-chartreuse or electric amber. Pick ONE and use it sparingly so it always means "act / important." Chartreuse reads "test passing / signal" and pairs well with terminal green.
- Semantic pair for the metric story: **pass green** and **fail red/coral**, used in charts and the loop so the control-arm story is legible at a glance.
- Text: warm off-white (`#F5F1ED`) primary, muted taupe for secondary.
- Keep the palette to ~5 roles. Discipline here is what makes it look designed, not decorated.

**Typography**

- Display/headline: a characterful but clean grotesque (e.g. a tighter geometric sans — think the Cleo-style heavy headline). Big, tight tracking, two-beat lines.
- Body: a highly readable neutral sans (Inter / Geist).
- Mono: a real code font (Berkeley Mono / JetBrains Mono / Geist Mono) — used liberally, because code and metrics ARE our imagery. Mono is a first-class typeface here, not a footnote.

**Imagery & motif — this is the big design decision.** Cleo uses a character (the green orb / persona). We don't have a mascot, and a dev audience will reject a cutesy one. Our "character" is **the loop and the telemetry.** Lean into:

- An animated **evolution-loop diagram** as the hero visual (Task → Agent → Score → Extract → Bank → Inject → re-run), with a pulse traveling the cycle.
- **Live-styled terminal / diff panels** showing a real run and a real extracted skill JSON.
- **Honest delta charts** — two bars side by side (control arm vs. skills arm), animating up. This is the money shot.
- A subtle "skills accumulating" motif (cards stacking in the bank over time).

Optional restrained personality: a single small geometric glyph/spark that travels the loop — our minimal nod to Cleo's persona without a mascot.

**Motion:** purposeful, not decorative. The loop pulses. Bars count up on scroll-in. Code/diff types in once. Respect `prefers-reduced-motion` — everything has a static resting state.

---

## 6. Information architecture (section-by-section)

Ordered for the scroll. Each section lists: purpose, layout, copy direction, key components.

### 6.1 Sticky nav
- Left: wordmark. Center/right: Product · How it works · Docs · GitHub (with star count). Right CTA button (accent): **"Run your first task"** or **"Get started."**
- Cleo move: keep it minimal, one bright CTA, persistent.

### 6.2 Hero
- **Purpose:** land the one-liner + show the loop in motion in under 3 seconds.
- **Layout:** left = headline + sub + dual CTA; right = animated evolution-loop diagram (the hero asset). On mobile, stack with the loop below.
- **Copy:** H1 *"Your coding agent keeps making the same mistakes. Yunaki makes sure it doesn't."* · Sub: *"Yunaki turns your agent's failures into reusable skills, injects them into the next run, and proves the gain against a control arm — no vanity metrics."* · CTAs: primary **"Get started"**, secondary **"See how it works"** (anchor scroll).
- **Trust strip** directly under hero: "Works with your existing coding CLI" + small logos/labels (Claude Code, Cursor, Gemini CLI, generic CLI) + "MongoDB-backed skill bank." Signals compatibility immediately — engineers' first question.

### 6.3 The problem (name the pain)
- **Purpose:** earn the nod. Cleo names "money anxiety"; we name "agent amnesia."
- **Layout:** short, full-width, big type. Maybe a three-beat: *agents don't remember → they repeat failures → "improvement" tools can't prove they help.*
- **Copy:** *"Your agent solved this exact bug last week. Today it has no idea. And the tools promising to fix that? They show you 'before vs. after' and call it science."*

### 6.4 How it works — the loop (the centerpiece)
- **Purpose:** the core mechanic, made legible. This is our equivalent of Cleo's "Cleo gets to know you."
- **Layout:** interactive horizontal loop or numbered steps that highlight as you scroll. Each node expands a small panel (terminal/diff/JSON).
  1. **Run** — agent attempts the task (your CLI, auto-detected).
  2. **Score** — pytest + optional LLM judge grade it. Real tests, real pass/fail.
  3. **Extract** — on failure, mine the trace for a reusable skill (single-trace or contrastive across N rollouts).
  4. **Bank** — store it (semantic embeddings, ranking, history).
  5. **Retrieve & inject** — pull the right skills into the next run.
  6. **Re-run & measure** — score again, report `skill_delta` vs. control.
- **Copy header:** *"Fail once. Learn forever."*
- **Component:** the animated loop + step detail cards. Show a *real* extracted `Skill` JSON object in one card.

### 6.5 The honest-metric section (our differentiator / personality peak)
- **Purpose:** this is the "Cleo roasts you" moment — the brand's spine. Make it a hero-weight section, not a footnote.
- **Layout:** big statement left, **control-vs-skills bar chart** right. Bars animate; the delta is labeled and called out.
- **Copy:** *"We don't report score-after-minus-score-before. That number takes credit for things that would've worked anyway. Yunaki runs a no-skills control arm and reports the honest delta. When it's small, we say so."*
- **Why it matters:** to engineers it signals intellectual honesty (instant trust); to leaders it signals a real measurement system. Quotable stat candidate goes here (e.g. "+X pass-rate over control on the demo suite").

### 6.6 Feature switcher (tabbed — direct Cleo borrow)
- **Purpose:** show depth without a 4,000px scroll. Cleo's Save/Card/Debt tabs → our capability tabs.
- **Tabs:**
  - **Contrastive extraction** — learn from what worked vs. what didn't across rollouts.
  - **Smart retrieval** — semantic + score-weighted, so only relevant skills get injected.
  - **Self-consolidation** — periodically merges duplicate skills and drops dead weight, so the bank stays sharp.
  - **Governance** — skill lifecycle + auto-approve policy; you control what goes live.
- **Layout:** left tab list, right detail panel with a code/diagram visual per tab. Highlight-marker emphasis on each tab's payoff line.

### 6.7 Compatibility / "bring your own agent"
- **Purpose:** kill the "do I have to switch tools?" objection.
- **Copy:** *"Yunaki detects your coding-agent CLI and drives it. No CLI? It falls back to a built-in Gemini SDK agent. Your stack, our loop."*
- **Layout:** logo/label row + a one-line install/run snippet (`pip install -e .` → `yunaki doctor`). Mono panel.

### 6.8 Proof / social section
- **Purpose:** Cleo's testimonial wall, our version. Until real testimonials exist, substitute with: a runnable demo result, the target-repo fixture story ("watch it implement the failing endpoints"), or design for quote cards as a placeholder slot.
- **Layout:** carousel of quote cards (with personality) OR a "watch a real run" embedded terminal recording. Recommend the live-run demo first; it's more credible to this audience than quotes.

### 6.9 For teams (the leader-targeted band)
- **Purpose:** speak to eng leaders explicitly.
- **Copy direction:** measurement rigor, auditability (skills history, runs/evaluations collections), governance, and "honest delta = no one's gaming the dashboard." Add an auth/repo-scoping mention.
- **Layout:** a distinct surface treatment (slightly different background) so it reads as "this part's for you."

### 6.10 FAQ (accordion — Cleo borrow)
- Questions to answer: *Does it work with my agent? Where are skills stored? What's the control arm and why should I trust the numbers? Do I need a Gemini key? Is my code/data leaving my machine? Open source?*
- Keep answers plain-spoken, on-brand (honest, no hedging).

### 6.11 Final CTA (repeat)
- Big, warm, single accent CTA. Restate the one-liner. *"Stop re-explaining the same fix to your agent. Start your first evolving run."* Primary button + GitHub/docs secondary.

### 6.12 Footer
- Product · Docs · GitHub · Methodology/blog · Changelog · contact. Minimal, warm-dark, social links.

---

## 7. Cleo-pattern → Yunaki mapping (quick reference)

| Cleo pattern | Yunaki translation |
|---|---|
| Character with attitude (the orb) | The loop + telemetry as "character"; optional traveling spark glyph |
| "Money talks. Cleo talks back." | "Your agent makes mistakes. Yunaki makes sure it doesn't." |
| "Roasts" / brutal honesty | Honest `skill_delta` vs. control arm — our personality spine |
| Save / Card / Debt tabs | Contrastive / Retrieval / Consolidation / Governance tabs |
| Highlight-marker punchlines | Same device on each feature's payoff line |
| Testimonial wall | Live-run demo + quote-card slots |
| Repeated "Get the app" CTA | Repeated "Get started / Run your first task" CTA |
| Warm dark theme (#47201c) | Warm espresso-dark base, not cold blue-black |
| FAQ accordion | FAQ accordion (compatibility, data, methodology) |

---

## 8. Component inventory (for build / Figma)

- Sticky nav with GitHub star pill + accent CTA
- Animated evolution-loop diagram (hero + how-it-works), reduced-motion fallback
- Terminal/diff panel component (typed-in once)
- Skill JSON card (renders a real `Skill` object)
- Control-vs-skills bar chart (count-up on scroll)
- Tabbed feature switcher (4 tabs, left list / right panel)
- Highlight-marker text component
- Stat callout block (oversized number + label)
- Quote/testimonial card + carousel
- FAQ accordion
- Code snippet / copy-to-clipboard block
- Repeated CTA band
- Footer

---

## 9. Conversion & CTA strategy

- One primary action, stated identically everywhere: **"Get started" / "Run your first task."** Don't dilute with five competing buttons.
- Secondary action is always low-commitment: **"See how it works"** (anchor) or **GitHub**.
- CTA appears in nav, hero, after the honest-metric section (peak conviction), and final band.
- For leaders, offer a soft second track near §6.9 ("Talk to us" / "Read the methodology") without crowding the dev path.

---

## 10. Responsive, performance, accessibility

- Mobile: stack hero, collapse the loop to a vertical stepper, tabs become an accordion or swipe.
- Respect `prefers-reduced-motion` — every animation has a static resting frame.
- Contrast: warm dark base must still hit AA for body text (verify the off-white on espresso).
- Performance: the loop/charts should be lightweight (SVG/Canvas, not heavy video). Lazy-load below-fold demos.

---

## 11. Open questions (decide before build)

1. **Accent color:** chartreuse vs. electric amber? (Recommend chartreuse — ties to "test passing / signal.")
2. **Real numbers:** can we publish an actual `skill_delta` from the demo suite for §6.5? The honest-metric section is far stronger with a real figure.
3. **Demo asset:** live terminal recording of a real run, or interactive playground? (Recommend a recorded run for v1.)
4. **Open-source posture:** is the repo public? Changes how hard we lean on GitHub as a CTA.
5. **Mascot/glyph:** do we want the minimal traveling spark, or keep it purely diagrammatic?
6. **Name/wordmark:** is there an existing logo, or does the page need one designed?

---

*Next step after sign-off: turn this into a single-file HTML mockup (hero + loop + honest-metric + tabs) so you can feel the warm-dark + chartreuse + mono direction before committing to a full build.*

# FreshCode AI v5.1: UI/UX review

## Design system
Palette references from the brief are kept as tokens (`--lavender #e9ddf7`, `--lilac #dccbf0`, `--violet #8062a8`, `--plum #49365f`, `--peach #f5d7c6`, `--apricot #eec1a5`, `--sage #d5e5d3`, `--mint #c5dfd0`, `--sand #ede2d2`, `--cream #f3ebdd`). Semantic tokens map them to roles: page `cream`, sidebar `sand`, cards a warm paper tone (`#faf4ea`, never pure white), configuration panels lilac, research panels peach, verified results sage, KPI tiles sage/lavender/peach/mint. The brand action colour is a darker violet (`#6a4c93`) so white button text passes AA; `#8062a8` is used for decoration (bars, big numerals). Code panels use a warm paper surface with a light syntax theme, so there is no dark surface anywhere.

Type: Lora (editorial headings), Inter (interface), JetBrains Mono (code); self-hosted Latin subsets with system fallbacks.

Contrast: `tests/test_a11y.py` computes WCAG ratios for about 60 text/surface pairs from the CSS tokens and requires 4.5:1. All pass.

## Per-page notes
- **Landing:** lilac hero with a real screenshot of the app, sand proof strip (numbers from `/api/v1/eval`, an offline self-check on small hand-written sets, labelled directional), then alternating cream / lavender / peach / sage / sand bands. 17 required sections are present (navigation, logo, hero, CTA, product preview, workflow, Bifrost, Tavily, compression, verification, freshness, benchmark evidence, security, architecture, FAQ, final CTA, footer), plus the ROI calculator.
- **Sign-in / sign-up:** split screen (lilac story panel, peach form panel), tabs, password visibility toggle, strength meter with a text label (not colour only), explicit "guest demo" access, no fake social sign-in.
- **Workspace shell:** sand sidebar, collapsible on desktop (state remembered), drawer below 900 px with scrim, Escape to close, focus moves into the drawer. Top bar shows project, real provider state, environment and account.
- **Overview:** welcome panel with the three primary actions, four real KPIs, recent runs, provider status, project activity, usage quota, how-a-run-works. Empty states carry an action.
- **Engineering Agent:** see below.
- **Other pages:** Freshness, Evaluation Lab, Test Lab, History, Integrations and Account keep their v5.0 behaviour on the new surfaces; Test Lab has a runner-mode badge ("LOCAL RUNNER - NOT A SANDBOX" vs "DOCKER ISOLATED"); Evaluation Lab gained a methodology-and-limits card.

## Engineering Agent
Left: project, language, constraints, budget slider, three verification switches, runner note. Centre: task editor with examples, Run / Stop / Retry, elapsed timer, then implementation / tests / notes tabs with copy, download, open-in-Test-Lab and expand. Right: 11-stage trace, Bifrost usage tiles (measured vs estimated), verification card (sage when passed), Tavily sources (peach), run trace. Below 1280 px the regions become Configure / Workspace / Execution tabs. Results persist when you navigate away (views are hidden, not destroyed).

Honesty rules implemented in code: no stage is marked done unless the backend event or result field says so; skipped stages are drawn dashed with the reason; a failed stage turns red with the real message; "Complete" is shown only after a result, and "Tests failed" when verification ran and failed.

## Verified
Zero horizontal overflow at 1440, 1280, 1024, 768, 390 and 360 px on the landing page, sign-in and all nine workspace views (journey 17). Keyboard: skip link, visible 3 px focus ring, tab roles with `aria-selected`, drawer button `aria-expanded`. Motion: `prefers-reduced-motion` plus an in-app toggle.

## Weaknesses (honest)
Screenshots were reviewed by eye at 1440 and 390 px only; no screen-reader pass and no real-device touch test. Evaluation Lab bars are not a charting library. Freshness evidence snippets can be long; they are clamped to three lines in the agent's narrow column but not elsewhere. The hero image is a screenshot of stubbed data and says so in its caption.

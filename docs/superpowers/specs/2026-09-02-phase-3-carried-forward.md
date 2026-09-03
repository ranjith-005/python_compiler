# Phase 3 outcome, and what remains across the whole redesign

Date: 2026-09-03
Branch: `portal-redesign`
Spec: `2026-09-02-portal-redesign-design.md`
Earlier lists: `2026-09-02-phase-1-carried-forward.md`, `2026-09-02-phase-2-carried-forward.md`

Phase 3 replaced the Colab-style notebook with a dedicated solve page, moved
solving onto its own code column with a one-time backfill, and replaced corner
toasts with a centred status message. Tests went 166 → 182 across the phase; the
branch as a whole went 115 → 182.

## The defect worth remembering

The solve page shipped rendering `undefined` as its heading over an empty problem
panel. Its script read `title`, `problem_statement`, `sample_input`,
`sample_output`, `explanation` and `starter_code` from the top level of
`GET /api/assignments/{id}`, but the API nests them under `exercise` — and
`starter_code` was not returned at all.

It survived 180 passing tests and five per-task code reviews. The page's own test
grepped the static template for the words "Run" and "Submit" and never touched the
fetched payload, so nothing looked at what a student would actually see. Only the
whole-phase review's end-to-end journey trace caught it.

Two guards now exist: a test asserting the API returns every field the page reads,
and a source-level tripwire asserting the page reads them from the nested object.
The second is deliberately brittle — it is a grep — because no test here executes
JavaScript.

**The lesson, for whoever works on this next:** a test that asserts a page renders
its *chrome* proves nothing about its *content*. Both halves of a data contract need
pinning, and when the front end cannot be executed, a source tripwire beats nothing.

## Open, shipped deliberately

- **J1** `/run` has no rate limit or per-user concurrency cap. The routes are sync
  `def`, so FastAPI's threadpool gives an implicit bound, and the app's documented
  trust model already accepts executing student code as a normal process.
- **J2** `/run` buffers a subprocess's full output in memory for up to
  `RUN_TIMEOUT_SEC` before truncating to 64 000 characters. The cap protects the
  JSON response, not the server. Combined with J1 this is the realistic
  memory-exhaustion path, and it is a sharper edge than the missing rate limit. The
  commit message on `625d953` overstates what that change achieves.
- **J3** The notebook surface (`notebook.js`, `notebooks_home.js`, and the
  `/notebooks` and `/nb/{id}` templates) keeps its own corner-popup confirmations,
  so the app has two confirmation styles. Also, those pages hand-roll their own top
  bars and lack the global nav.
- **J4** `/notebooks` and `/nb/{id}` are now unreachable from anywhere in the app —
  no nav entry for either role, and modules run through their own player. The spec
  keeps notebooks "for modules and free practice", so free practice is now URL-only.
  **This needs a decision: link the surface, or retire it.**
- **J5** The solve page shows no trainer feedback and no test cases. A student whose
  work came back `changes_requested` sees a status pill and nothing else; the
  comment is shown on `/student/exercises` but not here, and `public_tests` is
  fetched and discarded.
- **J6** Several weak tests carried from Phase 2: one that cannot fail, one misnamed,
  a brittle `innerHTML` substring tripwire, and an untested "submitted before its due
  date" branch. No behaviour is wrong; the guards are thin.
- **J7** `assignments.notebook_id` is still selected and emitted by two endpoints
  that no JavaScript reads. The `<div class="toast">` markup now sits on 19
  templates whose scripts no longer call `D.toast`; the one remaining internal caller
  is the notifications "Mark all read" error path.

## Still not verified — the most important line in this document

**Nobody has looked at any of this in a browser, across all three phases.** Chrome
could not reach the dev server here (the extension has no site permission for
`localhost:8000`), so every colour, contrast and layout decision was reasoned about
and never seen.

That is not a theoretical risk. Reading code alone caught: a nav button rendering at
1.3:1 contrast, unstyled summary cards on eight templates, blue underlined rows on
four pages, white text at 2.6:1 on the primary button in dark mode, and success and
error messages distinguishable only by a hairline border. Each of those would have
been obvious in two seconds of looking.

**Look at `/student/assignments/{id}/solve` in dark theme first**, at about 1280px
and again at about 900px. It is the only entirely new page in the project and it
stacks the most unverified assumptions: a 1.4fr/1fr grid, three near-black greys
layered as page, panel and textarea, and a 980px breakpoint where the editor ends up
above an input box that is now far from the output it feeds.

Then trigger a success and an error on `/settings` back to back and confirm you can
tell them apart.

A dev server is running at `http://127.0.0.1:8000` with seeded accounts:
`demo-trainer@example.com` and `demo-student@example.com`, both `password123`.

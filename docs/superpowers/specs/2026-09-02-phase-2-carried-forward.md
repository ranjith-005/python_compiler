# Phase 2 outcome and findings carried into Phase 3

Date: 2026-09-02
Branch: `portal-redesign`, commits `28d2f11`..`348445c`
Spec: `2026-09-02-portal-redesign-design.md`
Plan: `../plans/2026-09-02-portal-redesign-phase-2.md`
Phase 1's list: `2026-09-02-phase-1-carried-forward.md`

Phase 2 delivered the card dashboards, the drill-down pages, names everywhere, and
closed all four findings Phase 1 carried. Tests went 143 → 166, all passing. Its
whole-phase review marked all twelve exit criteria met.

## Phase 1's findings — now closed

- **F1** the theme is now rendered server-side by a context processor, so all 23
  templates get it, not just the 15 that loaded the right script. `syncTheme()` is
  gone. This also closed **F12**, the Settings radio diverging from the page.
- **F2** a password change now stamps `sessions_valid_from` and every earlier token
  is rejected — including on the kernel websocket, which previously ignored the
  cutoff entirely and left the code-execution channel open to a revoked cookie.
- **F3** every API row describing a person carries `display`. No JS falls back to an
  email; the three remaining `.email` reads are labelled Email fields and a search
  haystack.
- **F4** the `innerHTML` sink is gone from the dashboard JS. `el()` is the only DOM
  builder in those files.
- **F5** was closed in Phase 1 by validating the stored theme value.

## Found and fixed during Phase 2, worth recording

Two bugs of the same shape, a component turned into a link without a link reset:
`.stat` in Task 5 and `.row` in the final wave. Both rendered as blue underlined
text and neither was catchable by a test. **If a third component becomes an anchor,
check for the reset first.**

A security gap nothing planned for: `is_active` was checked at login and on the
websocket but not in the shared token resolver, so a deactivated account holding a
live cookie kept every HTTP route. Now enforced in `user_from_token`.

## Open, shipped deliberately

- **G1** `test_signed_out_pages_fall_back_to_system` cannot fail on its own; three
  sibling tests pin the context processor, so the coverage exists.
- **G2** `test_section_pages_highlight_their_own_nav_section` asserts a pattern that
  could never appear, so it does not test what its name says. The behaviour is
  correct.
- **G3** The `innerHTML` grep test is a substring tripwire: it would miss
  `insertAdjacentHTML`, `outerHTML` and `document.write`. Widen it next time that
  file is touched.
- **G4** No test covers "submitted before its due date is not late". The other two
  branches are covered and the predicate is one expression.
- **G5** `notebook.html` and `notebooks.html` still hand-roll their own top bars and
  lack the global nav. Phase 3 replaces the notebook as the exercise surface, so
  fixing them earlier would have been thrown away.
- **G6** The date filters changed meaning: they used to filter exercises by
  `updated_at` and pending by `assigned_at`; they now filter both by `due_date`.
  This is a net improvement — the old pending filter was broken, because its query
  never selected `assigned_at`, so entering any date hid every row.
- **G7** `/api/dashboard/trainer` is one monolithic endpoint serving both the
  five-card dashboard and four section pages, so the dashboard fetches lists it does
  not use. Pre-existing, and immaterial at classroom scale.
- **G8** `student_detail.html` went from 3 to 8 `.stat` cards in a plain grid, so it
  will wrap 5 + 3. Never seen in a browser.

## Carried into Phase 3

- **H1** `openAssignment()` is duplicated in `student_dashboard.js` and
  `student_exercises.js`, and both navigate to `/nb/{id}`. Phase 3 must change both,
  or delete the dashboard copy — the dashboard no longer lists assignments.
- **H2** `.toast` markup now sits on more templates than Phase 1's inventory
  assumed, so the `D.toast` → `D.flash` conversion touches more files than planned.
- **H3** `.colab .toast`'s border is invisible in dark mode, and now degrades three
  more pages. Phase 3's flash rewrite replaces that rule anyway.
- **H4** `_exercise_cells` still renders the retired Input format, Output format and
  Constraints fields into the student's working notebook. Phase 3 deletes that
  function, which resolves it.

## Still not verified

**Nobody has looked at either theme, on any page, in a browser.** Chrome cannot
reach the dev server here — the extension has no site permission for
`localhost:8000` — so across both phases every colour, contrast and layout decision
has been reasoned about and never seen. Code review has caught real visual defects
this way (an invisible nav button at 1.3:1, unstyled cards on eight templates, blue
underlined rows on four pages), which is evidence the risk is live, not theoretical.
A browser pass is the single highest-value thing left.

# Sidebar Shell, Redesigned Dashboards, and the Activity/Notification Split — Design

**Date:** 2026-09-10
**Status:** approved for planning

## Problem

Four requests, from a reference screenshot of a different product (Learnloom):

1. The trainer dashboard leads with **Upcoming deadlines**, which is not what a
   trainer opens the dashboard for. Deadlines belong on the Exercises page,
   behind a filter. Recent activity should take that slot.
2. Both dashboards should adopt the reference's visual language: a left sidebar,
   a header carrying search and account controls, and soft pastel cards.
3. A notification bell beside the profile icon.
4. **Recent activity** and **notifications** currently blur together. They should
   mean two different things, and notifications need a full history.

## What already exists

Establishing this first, because three of the four are partly built:

- **The bell is done.** `app/templates/_topbar.html` renders it with an unread
  badge, a dropdown panel and *Mark all read*; `app/static/js/dashboard_common.js`
  drives it. Request 3 needs no new work beyond relocating the markup.
- **Both feeds have tables.** `notifications` (with `created_at`, `read_at`) and
  `activities` (with `user_id` and `actor_id`) already carry everything the
  history page and the scoping change need. **No schema changes anywhere in
  this design.**
- **Exercise filters exist** but no deadline filter: `student_exercises.html`
  has All/To do/In progress/Submitted; `trainer_section.html` has From/To dates.
- **Activity is already scoped to the viewer** (`WHERE a.user_id = ?`), but each
  row also stores an `actor_id`, which is why a trainer sees "Aditi Sharma
  submitted FizzBuzz" in a feed that should be their own actions.

## The distinction this design rests on

The whole of request 4 reduces to one rule:

> **Recent activity** is what *you did*. **Notifications** are what *happened to
> you*.

In data terms: activity is `actor_id = user_id`; everything else was already
being written to `notifications` as well, so nothing is lost by removing it from
the activity feed — it moves to the bell, where it belongs.

## Architecture

### The sidebar goes in without touching 21 templates

21 templates call `topbar()`. Editing all of them is the obvious approach and
the wrong one: it is 21 chances to miss a page, and it makes the change hard to
undo.

Instead the macro keeps its **name and signature exactly as they are** and
changes only what it emits — a fixed-position sidebar plus a slimmer header.
One CSS rule supplies the layout:

```css
body:has(.app-sidebar) { padding-left: var(--sidebar-w); }
```

Consequences:

- Every page already calling `topbar()` gets the sidebar with no edit.
- `login.html` does not call it, so the auth page is untouched.
- Reverting is one file.
- `:has()` is required. Chrome 105+, Safari 15.4+, Firefox 121+ — all well
  past baseline in 2026. A browser without it renders the sidebar overlapping
  the content, which is visibly broken rather than silently wrong, so it will
  not go unnoticed.

The bell and profile markup **move across verbatim**, keeping their element ids
so `dashboard_common.js` continues to drive them with no JS change.

### Layout

```
┌──────────┬───────────────────────────────────────┐
│  brand   │  search              bell   profile   │  header
├──────────┼───────────────────────────────────────┤
│ Dashboard│  Dashboard                            │
│ Exercises│  Welcome back, <name>                 │
│ Modules  │                                       │
│ Students │  ╭─────╮ ╭─────╮ ╭─────╮ ╭─────╮      │  stat cards
│ Online…  │  ╰─────╯ ╰─────╯ ╰─────╯ ╰─────╯      │
│          │  ╭───────────────╮ ╭────────────────╮ │
│          │  │   Calendar    │ │ Recent activity│ │
│          │  ╰───────────────╯ ╰────────────────╯ │
└──────────┴───────────────────────────────────────┘
```

Responsive: icon rail below 1000px, off-canvas with a toggle below 700px.

### Deadlines: removed as a list, kept as dots

The request was to remove *Upcoming deadlines* from the dashboard; the chosen
calendar shows deadlines. These reconcile as: the **list** goes and Recent
activity takes its slot; deadlines survive as **dots on calendar dates**, a
glance rather than a to-do list. The actionable view lives on Exercises behind
the new dropdown.

## Components

### 1. `_topbar.html` — sidebar + header

Same macro signature. Role-aware nav (trainer gets Students; both get
Dashboard, Exercises, Modules, and the disabled *Online session* item as
today). Active item from the existing `current` argument.

### 2. `GET /api/search?q=`

New. The largest unknown in this design, and the only genuinely new feature.

- Trainer: exercises (title), modules (title), students (name, email).
- Student: their assigned exercises and modules only.
- Titles and names only — **not** module content. Full-text search over section
  bodies is a different and much larger problem, deliberately excluded.
- Returns at most 5 per category, each with a label and a link.
- Authorisation reuses `require_trainer` / `require_student`; a student can
  never see an exercise they were not assigned.

### 3. Stat cards

Same numbers, same links, restyled: pastel tint, rounded corners, icon.
No data change — the dashboard API already returns every figure.

### 4. Calendar panel

Month grid, dots on dates carrying a deadline, click through to the exercise.
Both dashboards. Fed by the deadline data the dashboard API already returns;
no new endpoint.

### 5. Recent activity

Moves into the slot the deadline list vacated. Query gains
`AND a.actor_id = a.user_id`.

### 6. `/notifications` history page

New page + `GET /api/dashboard/notifications?offset=`. Full list, newest first,
with **absolute date and time** (the bell shows relative "3 minutes ago"; a
history page needs the real timestamp). Paged, following the existing activity
pager. The bell footer becomes a *See all* link here.

### 7. Deadline dropdown

Both Exercises pages: All / Overdue / Due this week / Due this month / No
deadline. Client-side over data already loaded, alongside the existing filters.

Boundaries are stated so they cannot be read two ways: **Overdue** is a due
date strictly before now. **Due this week** is the next 7 days from now, not
the calendar week. **Due this month** is the next 30 days. The three overlap by
design — an exercise due tomorrow appears under both week and month — because a
trainer filtering for "this month" expects everything landing in it.

## Data flow

Nothing new is stored. Two new read endpoints (`/api/search`,
paged notifications); one modified query (activity scoping); everything else is
presentation over data the dashboards already fetch.

## Error handling

- Search: empty query returns empty results, never a 400. A failed request
  leaves the dropdown closed and does not block the page.
- Calendar: an exercise with no due date contributes no dot. A month with no
  deadlines renders a plain grid, not an error.
- Notification history: an empty history renders "Nothing yet", matching the
  bell's existing empty state.
- Sidebar: `topbar()` is called with the same arguments as today, so a template
  that passes an unknown `current` value simply highlights nothing.

## Testing

Test-first throughout. The two risky changes:

- **Activity scoping** — existing tests assert the current feed contents and
  will need inverting. Each inversion must be deliberate: assert that another
  person's action is *absent* from activity and *present* in notifications.
- **The sidebar swap** — 21 templates render through this macro. Assert that
  both dashboards, for both roles, still render every nav item, the bell and
  the profile menu, so a macro mistake cannot pass silently.

New coverage: search authorisation (a student cannot find an unassigned
exercise), notification paging, deadline filter boundaries.

## Out of scope

- Full-text search over module content.
- Any change to the Online session item; it stays the disabled *Soon* entry.
- Schema changes. If one turns out to be needed, that is a signal to stop and
  revisit this document.

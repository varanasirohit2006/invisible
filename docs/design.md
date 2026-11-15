# Dashboard design

I wanted this to feel like a quiet productivity tool you keep open, not a landing page. The Executive Summary is the product spec; the UI is my take on it, built in code and checked with Playwright rather than mockups.

## Look and feel

- Cool off-white canvas (`#f6f8f7`), white panels, dark ink text (`#172b28`), muted captions (`#65746f`), soft borders (`#e1e8e4`).
- Forest green (`#24634b`) as the main accent with a pale sage tint (`#e9f2ec`); amber for pending states, red for errors.
- System font stack: Inter if it's installed, otherwise Segoe UI and the system sans. No remote fonts, trackers, or CDN assets — the app should work fully offline.
- A 224px sidebar with fluid content up to 1280px. On tablets the rail gets compact; on phones the navigation becomes a horizontal strip.
- 32px page titles, 15px body, 13px controls; a 4/8/12/16/24/32 spacing scale and restrained 10–16px corners.
- Lucide outline icons at 18–20px, visible labels on primary actions, and keyboard focus on everything interactive.

## The pages

1. **Pairing** — paste the token the launcher prints; you get a private session cookie.
2. **Overview** — real totals, the last seven days of activity, discovered workflows, agent state, and a way into onboarding or the sample data.
3. **Activity** — the event log with search, filters, pagination, and the exact paths that were observed.
4. **Workflows** — discovered patterns with explanations, editable file and spreadsheet parameters, the immutable preview, and separate approve/run buttons.
5. **Run history** — the queue, execution status, per-step outcomes, backup locations, and failures.
6. **Settings** — explicit folder consent, pause/resume, retention, discovery threshold, and the optional cloud-explanation toggle.

Two rules I held myself to: sample activity is always labeled and can never execute anything, and estimates are always shown as estimates. Empty states say "nothing here yet" instead of inventing numbers.
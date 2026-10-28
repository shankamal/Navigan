# Migration Overview UI

The wider migration workflow redesign remains deferred at the user's request.
This increment updates only the overview presentation.

- Retain the accepted shared charcoal page heading, neutral canvas, Geist typography and green actions.
- Show accessible lifecycle and approval donut charts with exact counts and neutral empty states. Approval describes governance, not deployment completion.
- Keep source/destination logos and proportional path bars. Small table logos use 18px; summary logos use 20px.
- Keep portfolio charts independent of table filters and label that distinction. Include ungrouped statuses in the lifecycle total.
- Consolidate attention counts and actionable assessment links into one expandable queue above the list.
- Preserve existing list/board views, filters, links, refresh, permissions, cancel and delete behavior.
- Stack summary cards on narrower screens and keep wide table scrolling local.

Validation: TypeScript, the existing migration management tests and portfolio summary tests; production build; browser preview with synthetic portfolio data at 390, 768, 1024, 1280, 1440 and 1920 pixels. No live AWS or backend changes.

# Navigan responsive UI standard

This presentation-only increment follows accepted UI baseline cfbfbaae7. It preserves the charcoal shell, neutral canvas, green primary actions, colored provider logos and shared header grid. API calls, authentication, permissions, business rules and backend resources are unchanged.

## Typography and density

Use Geist Sans through shared `--navigan-font-*` tokens rather than screen-specific small text values.

| Role | Size |
| --- | --- |
| Page title | 18px |
| Section heading | 13px |
| Subsection, body, table, controls | 12px |
| Labels | 11px |
| Supporting metadata | 10.5px |
| KPI value | 18px |

Body line height is 1.45. Use spacing steps of 4, 8, 12, 16 and 24px. Standard controls have a minimum height of 34px; coarse-pointer primary controls use 44px. Mobile form inputs use 16px to prevent automatic input zoom. Do not reduce typography to force content onto one screen.

## Layout and navigation

- Respond to the available CSS viewport and content container, including sidebar width, browser zoom and OS scaling. Physical monitor inches are not a layout breakpoint.
- Keep page identity, context and primary actions first. Use the existing execution sequence and breadcrumbs on child screens.
- Shared header actions wrap when usable content width is 720px or less. Preserve explicit resets for obsolete absolute positioning and padding.
- Let grids reflow and forms stack. Avoid fixed page widths and empty fixed-height panels.
- Use natural vertical scrolling when content requires it. Never hide essential content to meet a no-scroll target.
- Wide operational tables and code blocks scroll locally. Avoid whole-page horizontal scrolling.
- Use semantic colors and labels together; retain visible focus and existing accessible names.

## Verification record — 22 October 2026

Production build and TypeScript checking pass. The selected UI suite reports 98/100 passing. Both remaining assertions reproduce on the accepted baseline: Dashboard refresh wording and Planning's multi-namespace selected-count label. They were not changed in this styling increment.

Rendered the actual AppShell and feature components with local, synthetic API fixtures. Tested iframe viewport widths 390, 768, 1024, 1280, 1440 and 1920px (classic scrollbar reduces usable width by up to 15px). Source discovery, source connection, Customer, Environment and Cluster directory showed no page-wide horizontal overflow at these widths. Dashboard was visually reviewed at laptop width and checked at the same six widths. Image evidence tables retain local scrolling. Header action contrast and unbroken connection status labels were corrected after visual review.

This is representative responsive coverage, not certification of every browser, physical device, dynamic data state or child dialog. Planning, assessment and detail screen styles now use the shared typography tokens; their complete live workflows still need review with authenticated data. No live AWS calls or authentication changes were used for this UI review.

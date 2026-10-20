# Deployment structure and artifact recovery design QA

Source visual truth: /workspace/scratch/629aa0f38b35/generated_images/exec-f9727b48-c90c-4f51-91ea-03873c2bb296.png
Implementation: /workspace/scratch/navigan-deployment-structure-implemented.jpg
Connection window: /workspace/scratch/navigan-source-connections-implemented.jpg
Expanded image: /workspace/scratch/navigan-image-evidence-expanded.jpg
Combined visual comparison: /workspace/scratch/navigan-recovery-design-comparison.jpg
Source pixels: (1567, 1004); implementation pixels: (1348, 926).
Desktop CSS viewport corresponds to the implementation screenshot, density 1.
Comparison images were fitted proportionally for overview review; focused original
screenshots were also inspected. These are responsive desktop adaptations, not
pixel-identical clones. The existing Navigan shell, source setup and workflow
context remain in place. Mock runtime evidence differs from the concept data.

State: Deployment structure, Retailflow API selected; separate Overview connection
window and expanded container evidence reviewed as additional states.

## Comparison history

- P2: The first implementation showed long image hostnames while hiding useful
  repository/image names. Fixed with shortened names and digest prefixes, with
  full references and copy actions inside expanded evidence.
- P2: Observed-workload facts stacked vertically, pushing image evidence down.
  Fixed with a responsive fact grid. Expanded digest facts also use a two-column
  layout with full-width long references.
- P2: Every namespace expanded, making the navigator exhaustive. Fixed by opening
  the selected namespace by default and keeping others available on demand.
- P2: Connection overview used the full editing width. Fixed with a compact 480px
  Overview window, expanding for repository/registry editing. Mobile becomes
  full-width. Final screenshots show the corrected proportions.

## Required fidelity surfaces

- Typography: existing Geist Sans and readable product hierarchy retained;
  image references use explicit wrapping and expandable full values.
- Spacing/layout: namespace navigator, observed workload, container evidence and
  deployment source follow the selected concept. The existing shell creates a
  longer page than the isolated concept; no content is discarded to imitate it.
- Colors: existing white/pale-gray surfaces, dark header and green selection/
  actions retained. Provenance uses a restrained review warning.
- Assets: existing supplied Navigan branding and existing icon library retained;
  no substitute raster logos or decorative artwork introduced.
- Copy: candidate matching, missing runtime digests and incomplete Helm recovery
  remain explicit. No guessed original Git revision or chart package verification.

## Interactions checked

Browser-rendered preview with isolated data: deployment tab, workload selection,
container disclosure, Resolve dialog/digest choices, Manage connections Overview,
Repository and Registries sections, close/focus return. Existing dialog keyboard
focus trapping/inert background retained. No application console errors observed;
Chrome extension metadata errors are unrelated to the application.

Tests: 106 focused backend tests and 60 focused frontend tests passed; TypeScript
and production build passed. Backend recovery uses mocked AWS in tests; live AWS
SSM/S3 recovery and narrow/mobile rendering need deployment validation.

No outstanding actionable P0/P1/P2 findings for the reviewed desktop states.
P3 follow-up: verify narrow layouts with real customer form content after DEV
rollout. The feature does not claim all source nodes/runtimes are covered.

final result: passed

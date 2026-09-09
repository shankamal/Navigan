# Environment Profile design QA

## Compared states

- Reference: selected Deloitte-inspired **Create AWS Environment Profile** mockup.
- Prototype: Navigan `/environments/new`, 1362 px desktop viewport, after a successful AWS discovery with populated resource selections.

## Visual and interaction review

| Priority | Check | Result |
| --- | --- | --- |
| P0 | Existing Navigan application shell and navigation remain intact | Passed |
| P0 | Connection inputs, fetch action, success state and populated resource baseline are present | Passed |
| P0 | Architect can select the exact VPC, subnets, security groups, IAM roles and KMS key | Passed |
| P1 | Deloitte-inspired black header, green accent, white panels and compact enterprise typography match the reference direction | Passed |
| P1 | Four-stage progress indicator communicates Connection, Discovery, Resource selection and Review | Passed |
| P1 | Readiness table clearly distinguishes resource type, status and detail | Passed |
| P1 | Long ARNs, resource IDs and responsive grids wrap without horizontal page overflow | Passed |
| P2 | Loading, success, warning/error, selected and disabled states are represented | Passed |
| P2 | Labels, fieldsets, live result region and semantic controls support keyboard/screen-reader use | Passed |

## Interaction evidence

- Selected the active customer and production environment type.
- Entered the account ID, fixed-name discovery role ARN and external ID.
- Fetch returned 17 bounded AWS resource references and populated the draft.
- Changed and restored a subnet checkbox; selected state updated correctly.
- Browser console contained no application warnings or errors. Browser-extension metadata messages were excluded because they are outside the application.

## Intentional differences from the reference

- Retained the repository's existing Navigan header, sidebar, spacing tokens and component styling.
- Replaced the reference's generic “Cluster Profile” step with “Resource selection” because cluster version, node pools, sizing and add-ons belong to the later Platform Setup request, not the reusable Environment Profile.
- Added explicit resource selectors, route-table-derived subnet type, NAT/VPC endpoint checks, service-quota capture and EBS encryption readiness to support deterministic provisioning.

## Remaining P3 follow-up

- Add provider-specific discovery adapters for Azure, GCP and OCI after the AWS contract is deployed and observed.

final result: passed

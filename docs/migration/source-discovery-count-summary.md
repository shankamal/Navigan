# Source discovery totals and grouped findings

The discovery screen preserves the complete collected evidence and raw totals.
Its summary distinguishes namespace records, workload controllers, collected
resource records, and individual finding observations.

- Workload controllers include Deployments, StatefulSets, DaemonSets, Jobs and
  CronJobs. They are not a count of distinct business applications or replicas.
  The summary separates long-running controllers from Job/CronJob records.
- A CronJob and its generated Jobs are separate Kubernetes objects. Resource
  totals also include supported dependencies and cluster-scoped objects.
- The expandable count explanation lists records by resource kind. Repeated
  resource identities or a mismatch between the reported total and collected
  records are surfaced for review; counts are never silently deduplicated.
- Source findings are grouped by rule code, severity and category. Every original
  message and remediation remains available by expanding its group. Observation
  counts are not a count of failures or distinct affected resources.
- All source findings are shown by default. Namespace filters are viewing hints,
  not application ownership, scope selection or migration eligibility rules.
  Findings without a namespace have their own view. Target compatibility findings
  remain outside this source assessment view.

This is a frontend-only change. It does not alter collection scope, backend
assessment rules, connectors, stored evidence or workspace readiness gates.
The exact contribution of each kind and rule to any live customer total must be
verified from that assessment's current evidence; it cannot be inferred from its
four headline numbers alone.

Validation: 57 focused frontend tests, TypeScript checking, production build and
browser verification of the count disclosure and expandable findings.

## Runtime URL correction verified; existing-cluster GitOps repair next

The user-run configuration release completed and printed the automatic-bootstrap tools URL verification marker. The scope check, independent sibling no-op checks, parent-only execution and post-deployment verification all passed. Future automatic bootstrap now receives the existing gateway URL. The current cluster's generated desired state still requires the separate three-field GitOps URL repair; tool-launch acceptance remains pending. Do not repeat the completed configuration deployment or the earlier bootstrap package/image release.

Deliver the scoped values-file repair through the existing customer GitOps repository using the recorded cluster/connector identities privately. After reconciliation, verify tunnel readiness, enabled launch buttons and successful Headlamp, Grafana, Prometheus and Argo CD launches. Keep environment-specific release records and repository/cluster identifiers out of this public checkpoint.

## Verified literal URL representation supported

The first configuration attempt stopped before artifact upload or change-set creation because its gateway URL representation check required a parameter reference. The helper now also accepts the exact expected literal gateway URL, provided both parent/child parameters and the live gateway configuration independently match it. It preserves the existing cluster API configuration and adds the parameter binding only to the automatic bootstrap function. Unknown URLs and expressions remain blocked.

Validation: 262 targeted tests passed, including preservation of literal gateway configuration and rejection of runtime/parameter mismatches. Runtime correction and existing-cluster GitOps repair remain pending. Retry --apply from the updated source; the stopped attempt created no executable plan. Keep private records local.

# Automatic-bootstrap tools URL correction

The fresh-cluster bootstrap test reached ACTIVE with healthy platform services, but private tool launches remained unavailable. Read-only diagnostics confirmed that the asynchronous status handler lacked the tools base URL that was already configured on the cluster API handler.

The SAM template now binds the same PlatformToolsBaseUrl parameter to StatusFunction. The flags remain on ClusterFunction, which evaluates tool access. No additional flags are needed by the producer.

scripts/configure-bootstrap-tools-prod.py stages and validates a URL-only StatusFunction environment update against fresh live templates and configuration. It checks an independent unexecuted child preview and unchanged parent inputs, proves any automatic sibling entries as no-ops, executes only the parent change set and verifies unchanged code, runner, permissions, API/auth/callback/resource identities and sibling modules. Use --prepare to stage previews, --apply to prepare and execute, or --execute PLAN to resume an unchanged prepared plan. Records containing live configuration remain private.

scripts/repair-cluster-tools-gitops.py previews an existing clean system-repository checkout and, with --apply, locally repairs only the connector tunnel URL, Grafana root URL and Prometheus external URL. It requires the exact cluster and connector IDs and an explicit tools base URL, preserves credentials/images/other desired state, and never commits, pushes or contacts Kubernetes/AWS. Review and deliver the two values files through the existing GitOps flow.

Validation: 258 targeted tests passed, including 41 new configuration/preview/identity/parent-only execution and exact GitOps repair checks. git diff --check passed. The runtime configuration release and existing-cluster GitOps repair remain pending user execution. Complete acceptance only after the tunnel is ready and all four tools launch. Do not repeat the completed bootstrap image/package release or recreate the healthy cluster.

This is the sanitized public continuity checkpoint for this fix. Detailed environment-specific execution records remain local; no credentials, live cluster identifiers or deployment history are included here.

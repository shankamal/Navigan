# Artifact collection recovery

Active collection screens retry temporary progress failures with increasing delays, capped at 30 seconds. A failed source status check does not stop image and repository status updates.

Editors automatically continue previously started workspace recovery jobs through their EXPORT and UPLOAD phases using the existing authenticated POLL operation. They do not automatically START another collection. Read-only users only fetch status. Browser-driven recovery advancement requires the collection screen to remain active.

An existing recovery may finish into its original workspace after a new inventory arrives. Customer, source cluster, artifact, workspace and original inventory bindings remain enforced. Starting collection on an old snapshot remains blocked. Completing an old recovery does not make that snapshot current or eligible for export.

Missing or pending SSM commands older than 40 minutes become explicit retryable failures. Successful command output still requires the existing resource identity, checksum, size, object-version and encryption checks.

Workspace reads return the actual saved object key, version, checksum and size. Reused artifacts keep their original paths. These metadata reads do not establish current object existence; export and download retain their S3 integrity checks. Storage prefixes and existing objects are unchanged.

The read-only collection audit supports `--logs` for bounded, paginated worker failure summaries. It returns error types, SQL states, phase locations and worker codes, without exception messages, SQL, credentials or SSM payloads. Workspace storage results include exact S3 URIs.

Regression coverage includes transient refresh failure/retry, stopping at completion, continuing a recovery from another snapshot, read-only behavior, unchanged source/artifact authorization, old snapshot completion, expired commands and original saved-object locations. Runtime worker failures still require actual worker diagnostics; passing these tests does not establish a successful live collection.

# Navigan-managed cluster system repository

This private repository is the desired state for the cluster's mandatory
platform services. Navigan updates it through its installed GitHub App.

Argo CD reconciles every manifest under `applications/`. Secrets and GitHub
credentials are created at runtime and are never committed here.

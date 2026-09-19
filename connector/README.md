# Navigan cluster connector

The connector is outbound-only. Its Kubernetes service account can only read
namespace names. The enrollment token is created once by Navigan, stored only
as a SHA-256 digest in the platform database, and supplied to the pod through an
existing Kubernetes Secret.

Do not put the token in Helm values, Git, container images, ConfigMaps, logs, or
shell history. Create the Secret interactively or through the customer's
approved secret-management workflow.

The connector reports namespace inventory and reconciles the desired Kubernetes
access state through:

`POST {ApiBaseUrl}/connectors/{connectorId}/inventory/namespaces`

`GET {ApiBaseUrl}/connectors/{connectorId}/access/desired`

`POST {ApiBaseUrl}/connectors/{connectorId}/access/status`

Its service account can read namespace names and manage only the Kubernetes
RBAC resources labeled as Navigan-managed assignments.

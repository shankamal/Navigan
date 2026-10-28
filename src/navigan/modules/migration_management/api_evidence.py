"""Evidence-gated Kubernetes API-version matching for selected migration resources."""


def evaluate_api_versions(resources, selected, observed_versions, *, fresh=False, observed_resources=None):
    versions = set(observed_versions or [])
    supported = {
        (entry.get("apiVersion"), entry.get("kind"))
        for entry in (observed_resources or [])
        if isinstance(entry, dict) and isinstance(entry.get("apiVersion"), str)
        and isinstance(entry.get("kind"), str)
    }
    findings = []
    for resource in resources or []:
        if not isinstance(resource, dict):
            continue
        identity = (resource.get("apiVersion"), resource.get("kind"),
                    resource.get("namespace"), resource.get("name"))
        if identity not in selected:
            continue
        version = resource.get("apiVersion")
        if not fresh:
            status, reason = "PENDING_EVIDENCE", "Target API discovery evidence is missing or expired."
        elif not isinstance(version, str) or not version:
            status, reason = "PENDING_EVIDENCE", "Source resource API version is not reported."
        elif (version, resource.get("kind")) in supported:
            status, reason = "PARTIAL", "Target serves the resource kind/version; admission, schema support and authorization remain unverified."
        elif observed_resources is not None and version in versions:
            status, reason = "PENDING_EVIDENCE", "Target advertises the API version but has not confirmed this resource kind."
        elif version in versions:
            status, reason = "PARTIAL", "Target advertises this API group/version; resource kind availability, admission, CRDs and deprecated fields remain unverified."
        else:
            status, reason = "PENDING_EVIDENCE", "Target has not advertised this API group/version in the available discovery evidence; compatibility is not established."
        findings.append({
            "apiVersion": version, "kind": resource.get("kind"),
            "namespace": resource.get("namespace"), "name": resource.get("name"),
            "status": status, "reason": reason,
        })
    return findings

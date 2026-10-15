"""Evidence-gated Kubernetes API-version matching for selected migration resources."""


def evaluate_api_versions(resources, selected, observed_versions, *, fresh=False):
    versions = set(observed_versions or [])
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

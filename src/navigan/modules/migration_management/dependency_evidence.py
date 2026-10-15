"""Conservative, read-only dependency edges derived from observed source manifests."""

WORKLOAD_KINDS = {"Pod", "Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"}


def _identity(item):
    return (item.get("kind"), item.get("namespace"), item.get("name"))


def discover_dependencies(resources, selected=None):
    """Return only manifest-backed dependencies; do not infer service traffic."""
    indexed = {
        _identity(r) for r in resources
        if isinstance(r, dict) and all(r.get(k) for k in ("kind", "name"))
    }
    edges = set()
    missing = set()
    scoped = [
        r for r in resources if isinstance(r, dict)
        and r.get("kind") in WORKLOAD_KINDS
        and r.get("name")
        and (selected is None or
             (r.get("apiVersion"), r.get("kind"), r.get("namespace"), r.get("name")) in selected)
    ]

    evidenced = sum("dependencyReferences" in r for r in scoped)
    evidence_unavailable = bool(scoped) and evidenced == 0

    def link(resource, kind, name):
        if not isinstance(name, str) or not name:
            return
        source = _identity(resource)
        target = (kind, resource.get("namespace"), name)
        if source == target:
            return
        pair = (source, target)
        if target in indexed:
            edges.add(pair)
        else:
            missing.add(pair)

    for r in scoped:
        # The source connector deliberately submits sanitized inventory,
        # not full Kubernetes specs. dependencyReferences is the authoritative
        # source for resource names; pod contains only summarized attributes.
        references = r.get("dependencyReferences") or []
        for reference in references:
            if not isinstance(reference, dict):
                continue
            if reference.get("kind") in {
                "ServiceAccount", "ConfigMap", "Secret",
                "PersistentVolumeClaim", "Service",
            }:
                link(r, reference["kind"], reference.get("name"))

    # Older sanitized snapshots retained an exact serviceAccountName even
    # before dependencyReferences was introduced. Recover only that explicit
    # identity, never guess ConfigMap/Secret/PVC names from volume aliases.
    for resource in scoped:
        pod = resource.get("pod")
        if not isinstance(pod, dict):
            continue
        name = pod.get("serviceAccountName")
        if isinstance(name, str) and name and name != "default":
            link(resource, "ServiceAccount", name)

    def render(pair):
        source, target = pair
        return {
            "source": {"kind": source[0], "namespace": source[1], "name": source[2]},
            "target": {"kind": target[0], "namespace": target[1], "name": target[2]},
        }

    sort_key = lambda pair: tuple(str(x or "") for identity in pair for x in identity)
    return {
        "status": "EVIDENCE_UNAVAILABLE" if evidence_unavailable else "PARTIAL",
        "relationships": [render(x) for x in sorted(edges, key=sort_key)],
        "unresolvedReferences": [render(x) for x in sorted(missing, key=sort_key)],
        "relationshipCount": len(edges),
        "unresolvedCount": len(missing),
        "reason": (
            "Saved source inventory has no dependencyReferences evidence. Explicit service-account identities may be partially recovered, but ConfigMap, Secret, PVC, Service and other relationships remain unverified; a future controlled source discovery is required."
            if evidence_unavailable else
            "Only explicitly reported sanitized workload dependency references are mapped. "
            "Service selectors, ingress routing, network calls, custom controllers "
            "and external dependencies remain unverified."
        ),
    }

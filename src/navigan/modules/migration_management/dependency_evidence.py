"""Conservative, read-only dependency edges derived from observed source manifests."""

WORKLOAD_KINDS = {"Pod", "Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"}


def _identity(item):
    return (item.get("kind"), item.get("namespace"), item.get("name"))


def _pod_spec(resource):
    spec = resource.get("spec") or {}
    if resource.get("kind") == "CronJob":
        return (((spec.get("jobTemplate") or {}).get("spec") or {}).get("template") or {}).get("spec") or {}
    if resource.get("kind") in {"Deployment", "StatefulSet", "DaemonSet", "Job"}:
        return (spec.get("template") or {}).get("spec") or {}
    return spec


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
        pod = _pod_spec(r)
        link(r, "ServiceAccount", pod.get("serviceAccountName") or "default")
        for volume in pod.get("volumes") or []:
            if not isinstance(volume, dict):
                continue
            pvc = volume.get("persistentVolumeClaim") or {}
            cm = volume.get("configMap") or {}
            secret = volume.get("secret") or {}
            link(r, "PersistentVolumeClaim", pvc.get("claimName"))
            link(r, "ConfigMap", cm.get("name"))
            link(r, "Secret", secret.get("secretName"))
            projected = (volume.get("projected") or {}).get("sources") or []
            for part in projected:
                if isinstance(part, dict):
                    link(r, "ConfigMap", (part.get("configMap") or {}).get("name"))
                    link(r, "Secret", (part.get("secret") or {}).get("name"))
        for container in (pod.get("initContainers") or []) + (pod.get("containers") or []):
            if not isinstance(container, dict):
                continue
            for env in container.get("env") or []:
                if not isinstance(env, dict):
                    continue
                ref = env.get("valueFrom") or {}
                link(r, "ConfigMap", (ref.get("configMapKeyRef") or {}).get("name"))
                link(r, "Secret", (ref.get("secretKeyRef") or {}).get("name"))
            for env_from in container.get("envFrom") or []:
                if not isinstance(env_from, dict):
                    continue
                link(r, "ConfigMap", (env_from.get("configMapRef") or {}).get("name"))
                link(r, "Secret", (env_from.get("secretRef") or {}).get("name"))

    def render(pair):
        source, target = pair
        return {
            "source": {"kind": source[0], "namespace": source[1], "name": source[2]},
            "target": {"kind": target[0], "namespace": target[1], "name": target[2]},
        }

    sort_key = lambda pair: tuple(str(x or "") for identity in pair for x in identity)
    return {
        "status": "PARTIAL",
        "relationships": [render(x) for x in sorted(edges, key=sort_key)],
        "unresolvedReferences": [render(x) for x in sorted(missing, key=sort_key)],
        "relationshipCount": len(edges),
        "unresolvedCount": len(missing),
        "reason": (
            "Only observed workload-to-resource references are mapped. "
            "Service selectors, ingress routing, network calls, custom controllers "
            "and external dependencies remain unverified."
        ),
    }

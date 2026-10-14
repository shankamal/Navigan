"""Conservative source PVC to observed target StorageClass comparison."""


def compare_storage_claims(source_resources, selected, storage_classes, *, fresh=False):
    observed = set(storage_classes or [])
    result = []
    for resource in source_resources or []:
        if not isinstance(resource, dict) or resource.get("kind") != "PersistentVolumeClaim":
            continue
        identity = (resource.get("apiVersion"), resource.get("kind"),
                    resource.get("namespace"), resource.get("name"))
        if identity not in selected:
            continue
        storage_class = resource.get("storageClassName")
        if not fresh or not isinstance(storage_class, str) or not storage_class:
            status = "PENDING_EVIDENCE"
            reason = "Fresh target StorageClass evidence and an explicit source StorageClass are required."
        elif storage_class in observed:
            status = "PARTIAL"
            reason = "The StorageClass name is observed on the target, but provisioner, access modes, capacity, binding, CSI health and data transfer remain unverified."
        else:
            status = "PENDING_EVIDENCE"
            reason = "No target StorageClass with this name was observed. An explicit destination mapping or additional discovery is required."
        result.append({"apiVersion": resource.get("apiVersion"), "kind": "PersistentVolumeClaim",
                       "namespace": resource.get("namespace"), "name": resource.get("name"),
                       "sourceStorageClass": storage_class, "status": status, "reason": reason})
    return result

"""Read-only Kubernetes-family target capability extraction.

No connection is created here. A provider adapter supplies GET results using
an explicitly authorized, least-privilege target connection.
"""
from datetime import datetime, timezone


def storage_capability_snapshot(platform, target_id, storage_class_items, observed_at=None):
    if not isinstance(platform, str) or not platform or not isinstance(target_id, str) or not target_id:
        raise ValueError("Target platform and identity are required")
    if not isinstance(storage_class_items, list):
        raise ValueError("StorageClass list must be an array")

    storage_classes = []
    for item in storage_class_items[:500]:
        if not isinstance(item, dict):
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        name = metadata.get("name")
        provisioner = item.get("provisioner")
        if not isinstance(name, str) or not name or not isinstance(provisioner, str) or not provisioner:
            continue
        # The StorageClass API does not advertise access modes. Never invent them.
        storage_classes.append({
            "name": name[:253],
            "provisioner": provisioner[:253],
            "accessModes": [],
            "verified": False,
        })

    observed = observed_at or datetime.now(timezone.utc)
    if observed.tzinfo is None:
        raise ValueError("Observation timestamp must be timezone-aware")
    return {
        "schemaVersion": 1,
        "platform": platform,
        "targetId": target_id,
        "observedAt": observed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": "READ_ONLY_ADAPTER",
        "storageClasses": storage_classes,
    }

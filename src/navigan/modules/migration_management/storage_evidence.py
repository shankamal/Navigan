"""Conservative, read-only PVC requirement assessment using target observations."""

import re

QUANTITY = re.compile(r"^([1-9][0-9]*(?:\\.[0-9]+)?)(Ki|Mi|Gi|Ti|K|M|G|T)?$")
SCALE = {"Ki": 1024, "Mi": 1024 ** 2, "Gi": 1024 ** 3, "Ti": 1024 ** 4,
         "K": 1000, "M": 1000 ** 2, "G": 1000 ** 3, "T": 1000 ** 4, None: 1}
ACCESS_MODES = {"ReadWriteOnce", "ReadOnlyMany", "ReadWriteMany", "ReadWriteOncePod"}
VOLUME_MODES = {"Filesystem", "Block"}


def compare_storage_claims(source_resources, selected, storage_classes, *, fresh=False,
                           class_details=None, csi_drivers=None):
    """Never infer volume provisioning or data migration from matching names."""
    observed = set(storage_classes or [])
    details = {item["name"]: item for item in (class_details or [])
               if isinstance(item, dict) and isinstance(item.get("name"), str)}
    drivers = set(csi_drivers or [])
    results = []
    for resource in source_resources or []:
        if not isinstance(resource, dict) or resource.get("kind") != "PersistentVolumeClaim":
            continue
        identity = (resource.get("apiVersion"), resource.get("kind"),
                    resource.get("namespace"), resource.get("name"))
        if identity not in selected:
            continue
        storage_class = resource.get("storageClassName")
        modes = resource.get("accessModes")
        requested = resource.get("requestedStorage")
        volume_mode = resource.get("volumeMode") or "Filesystem"
        valid_modes = (isinstance(modes, list) and bool(modes)
                       and all(isinstance(m, str) and m in ACCESS_MODES for m in modes))
        valid_storage = (isinstance(requested, str) and
                         QUANTITY.fullmatch(requested) is not None)
        valid_volume_mode = volume_mode in VOLUME_MODES
        detail = details.get(storage_class, {}) if isinstance(storage_class, str) else {}
        provisioner = detail.get("provisioner")
        binding = detail.get("volumeBindingMode")
        driver_observed = isinstance(provisioner, str) and provisioner in drivers

        if not fresh or not isinstance(storage_class, str) or not storage_class:
            status, reason = "PENDING_EVIDENCE", "Fresh target StorageClass evidence and an explicit source StorageClass are required."
        elif storage_class not in observed:
            status, reason = "PENDING_EVIDENCE", "No target StorageClass with this name was observed. Define a destination mapping or obtain fresh discovery evidence."
        elif not valid_modes or not valid_storage or not valid_volume_mode:
            status, reason = "PENDING_EVIDENCE", "Source PVC access modes, requested capacity or volume mode are missing or unsupported; compatibility cannot be evaluated."
        elif not isinstance(provisioner, str) or not provisioner or binding not in {"Immediate", "WaitForFirstConsumer"}:
            status, reason = "PENDING_EVIDENCE", "Target StorageClass was observed but provisioner or binding-mode evidence is missing."
        elif not driver_observed:
            status, reason = "PENDING_EVIDENCE", "Target StorageClass provisioner has no matching observed CSIDriver. Provisioning support is not established."
        else:
            status, reason = "PARTIAL", "Source PVC requirements and target StorageClass/CSIDriver identity are observed; CSI health, access-mode support, quota, capacity, topology, snapshots and data movement remain unverified."
        results.append({
            "apiVersion": resource.get("apiVersion"), "kind": "PersistentVolumeClaim",
            "namespace": resource.get("namespace"), "name": resource.get("name"),
            "sourceStorageClass": storage_class, "sourceAccessModes": modes if isinstance(modes, list) else [],
            "requestedStorage": requested, "volumeMode": volume_mode,
            "targetProvisioner": provisioner, "targetVolumeBindingMode": binding,
            "csiDriverObserved": driver_observed,
            "status": status, "reason": reason,
        })
    return results

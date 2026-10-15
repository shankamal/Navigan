"""Read-only, conservative scheduling feasibility checks for migration planning.

This is an evidence evaluator, not a Kubernetes scheduler. It intentionally
returns PENDING_EVIDENCE unless the entire considered node set can be assessed.
"""
import re

CPU = re.compile(r"^(?:[0-9]+(?:\.[0-9]+)?)(?:m)?$")
MEMORY = re.compile(r"^([0-9]+(?:\.[0-9]+)?)(Ki|Mi|Gi|Ti|K|M|G|T)?$")
SCALE = {"Ki": 1024, "Mi": 1024**2, "Gi": 1024**3, "Ti": 1024**4,
         "K": 1000, "M": 1000**2, "G": 1000**3, "T": 1000**4, None: 1}


def cpu_millicores(value):
    if not isinstance(value, str) or not CPU.fullmatch(value):
        return None
    try:
        return round(float(value[:-1]) if value.endswith("m") else float(value) * 1000)
    except (ValueError, OverflowError):
        return None


def memory_bytes(value):
    if not isinstance(value, str):
        return None
    match = MEMORY.fullmatch(value)
    if not match:
        return None
    try:
        return round(float(match.group(1)) * SCALE[match.group(2)])
    except (ValueError, OverflowError):
        return None


def evaluate_node_capacity(cpu_request, memory_request, nodes, *, inventory_complete=False):
    """Check a pod's aggregate CPU/memory requests against observed nodes.

    Never equate allocatable with free capacity. Node taints, affinity,
    utilization, quotas, and admission policies are outside this check.
    """
    request_cpu = cpu_millicores(cpu_request)
    request_memory = memory_bytes(memory_request)
    if request_cpu is None or request_memory is None:
        return {"status": "PENDING_EVIDENCE", "reason": "Source CPU and memory requests are missing or invalid."}
    if not isinstance(nodes, list) or not nodes:
        return {"status": "PENDING_EVIDENCE", "reason": "No target node observations were provided."}

    observed = 0
    candidates = 0
    unknown = 0
    capacity_matches = 0
    for node in nodes:
        if not isinstance(node, dict):
            unknown += 1
            continue
        cpu = cpu_millicores(node.get("allocatableCpu"))
        memory = memory_bytes(node.get("allocatableMemory"))
        cordoned = node.get("unschedulable")
        taints = node.get("taintCount")
        if cpu is None or memory is None or not isinstance(cordoned, bool) or type(taints) is not int or taints < 0:
            unknown += 1
            continue
        observed += 1
        if cpu >= request_cpu and memory >= request_memory:
            capacity_matches += 1
        # A tainted node may still be suitable if the workload tolerates it;
        # without toleration evidence, do not declare it a candidate.
        if not cordoned and taints == 0 and cpu >= request_cpu and memory >= request_memory:
            candidates += 1

    if not inventory_complete or unknown or observed != len(nodes):
        return {"status": "PENDING_EVIDENCE", "reason": "Node inventory or scheduling evidence is incomplete.",
                "observedNodes": observed, "unverifiedNodes": unknown}
    if candidates:
        return {"status": "PARTIAL", "reason": "At least one node has sufficient allocatable capacity, is uncordoned and has no reported taints. Free capacity, selectors, affinity, quotas and admission are unverified.",
                "candidateNodes": candidates, "observedNodes": observed}
    if capacity_matches:
        return {"status": "PENDING_EVIDENCE", "reason": "Nodes have sufficient allocatable capacity, but cordon state or taints require workload-specific placement evidence.",
                "candidateNodes": 0, "observedNodes": observed}
    return {"status": "REMEDIATION_REQUIRED", "reason": "Every fully observed node has less allocatable CPU or memory than requested. This does not measure current utilization.",
            "candidateNodes": 0, "observedNodes": observed}


def workload_pod_requests(resource):
    """Aggregate explicit regular-container requests for a simple PodSpec.

    Init containers, selectors, affinity and tolerations require a richer
    scheduler evaluation and are deliberately not approximated here.
    """
    pod = resource.get("pod") if isinstance(resource, dict) else None
    if not isinstance(pod, dict):
        return None
    # These constraints are not safe to ignore. The caller reports them explicitly.
    if pod.get("initContainers") or pod.get("nodeSelectorKeys") or pod.get("nodeSelector") or pod.get("tolerations"):
        return None
    affinity = pod.get("affinity")
    if isinstance(affinity, dict) and any(affinity.values()):
        return None
    containers = pod.get("containers")
    if not isinstance(containers, list) or not containers:
        return None
    total_cpu, total_memory = 0, 0
    for container in containers:
        if not isinstance(container, dict):
            return None
        resources = container.get("resources")
        requests = resources.get("requests") if isinstance(resources, dict) else None
        if not isinstance(requests, dict):
            return None
        cpu, memory = cpu_millicores(requests.get("cpu")), memory_bytes(requests.get("memory"))
        if cpu is None or memory is None:
            return None
        total_cpu += cpu
        total_memory += memory
    return {"cpu": f"{total_cpu}m", "memory": str(total_memory)}

def scheduling_constraints(resource):
    """Return actionable restrictions without claiming scheduler equivalence."""
    pod = resource.get("pod") if isinstance(resource, dict) else None
    if not isinstance(pod, dict):
        return ["Source PodSpec was not captured by the connector."]
    missing = []
    if pod.get("initContainers"):
        missing.append("Init-container CPU/memory requests and initialization order need evaluation.")
    if pod.get("nodeSelectorKeys") or pod.get("nodeSelector"):
        missing.append("Source node selectors must be matched against target node labels.")
    if pod.get("tolerations"):
        missing.append("Tolerations must be matched against the actual target node taints.")
    if isinstance(pod.get("affinity"), dict) and any(pod["affinity"].values()):
        missing.append("Pod/node affinity and anti-affinity require topology-aware evaluation.")
    if pod.get("topologySpreadConstraints"):
        missing.append("Topology spread constraints require target failure-domain evidence.")
    return missing

#!/usr/bin/env python3
"""Preview or locally repair URLs in an existing cluster GitOps checkout.

Only values/connector.yaml and values/monitoring.yaml are edited with --apply.
Never commits, pushes, rotates credentials or contacts Kubernetes/AWS. All other
desired state, including Falco pins, is preserved. Use a clean existing checkout.
"""
import argparse
import copy
import difflib
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit

import yaml


def require(condition, message):
    if not condition:
        raise ValueError(message)


def repair_texts(texts, cluster_id, connector_id, tools_base):
    require(re.fullmatch(r"CLU-[a-f0-9]{32}", cluster_id), "Invalid cluster ID.")
    require(re.fullmatch(r"KCC-[a-f0-9]{32}", connector_id), "Invalid connector ID.")
    parsed = urlsplit(tools_base)
    require(parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password
            and not parsed.query and not parsed.fragment and parsed.path == "/tools", "Expected an HTTPS tools base URL ending in /tools.")
    # URLs are inserted as YAML scalars; restrict to simple host names and ports.
    require(re.fullmatch(r"https://[A-Za-z0-9.-]+(?::[0-9]+)?/tools", tools_base), "Unsupported tools URL characters.")
    connector = yaml.safe_load(texts["values/connector.yaml"])
    monitoring = yaml.safe_load(texts["values/monitoring.yaml"])
    require(connector["navigan"]["connectorId"] == connector_id, "GitOps connector ID differs from this installation.")
    tunnel = tools_base.replace("https://", "wss://", 1) + "/tunnel"
    grafana = tools_base + "/clusters/" + cluster_id + "/grafana/"
    prometheus = tools_base + "/clusters/" + cluster_id + "/prometheus/"
    previous_grafana = "/clusters/" + cluster_id + "/grafana/"
    previous_prometheus = "/clusters/" + cluster_id + "/prometheus/"
    require(connector["navigan"].get("toolsTunnelUrl") in (None, "", tunnel), "Existing tunnel URL requires separate review.")
    require(monitoring["grafana"]["grafana.ini"]["server"]["root_url"] in (previous_grafana, grafana)
            and monitoring["prometheus"]["prometheusSpec"]["externalUrl"] in (previous_prometheus, prometheus),
            "Monitoring URLs do not match this cluster's missing-base-url incident.")
    desired_connector, desired_monitoring = copy.deepcopy(connector), copy.deepcopy(monitoring)
    desired_connector["navigan"]["toolsTunnelUrl"] = tunnel
    desired_monitoring["grafana"]["grafana.ini"]["server"]["root_url"] = grafana
    desired_monitoring["prometheus"]["prometheusSpec"]["externalUrl"] = prometheus
    result = {}
    for path, replacements, expected in (
        ("values/connector.yaml", {"toolsTunnelUrl": tunnel}, desired_connector),
        ("values/monitoring.yaml", {"root_url": grafana, "externalUrl": prometheus}, desired_monitoring),
    ):
        value = texts[path]
        for key, url in replacements.items():
            value, count = re.subn(r"(?m)^([ \t]*" + re.escape(key) + r":)[^\r\n]*$", lambda match: match[1] + ' "' + url + '"', value)
            require(count == 1, "Expected one reviewed URL field: " + key)
        require(yaml.safe_load(value) == expected, "Unexpected YAML changes rejected.")
        result[path] = value
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--cluster-id", required=True)
    parser.add_argument("--connector-id", required=True)
    parser.add_argument("--tools-base-url", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    repo = args.repository.resolve()
    def git(*arguments):
        return subprocess.check_output(["git", "-C", str(repo), *arguments], text=True).strip()
    require(Path(git("rev-parse", "--show-toplevel")).resolve() == repo, "Select the repository root.")
    require(not git("status", "--porcelain"), "Checkout has changes; preserve and review them before repair.")
    paths = ("values/connector.yaml", "values/monitoring.yaml")
    for path in paths:
        require((repo / path).is_file() and not (repo / path).is_symlink(), "Expected a regular tracked values file.")
        require(git("ls-files", "--error-unmatch", path) == path, "Values file is not tracked.")
    texts = {path: (repo / path).read_text() for path in paths}
    result = repair_texts(texts, args.cluster_id, args.connector_id, args.tools_base_url)
    for path in paths:
        print("".join(difflib.unified_diff(texts[path].splitlines(True), result[path].splitlines(True), fromfile="a/" + path, tofile="b/" + path)), end="")
    if args.apply:
        for path in paths:
            if result[path] != texts[path]:
                (repo / path).write_text(result[path])
        print("Local URL repair written. Review git diff before committing/pushing through the existing GitOps flow.")
    else:
        print("Preview only. Add --apply to write these local edits.")


if __name__ == "__main__":
    main()

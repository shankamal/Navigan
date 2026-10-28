"""Narrow bootstrap patches applied to captured runtime files, not whole packages."""
import ast
import copy
from pathlib import Path
import re
import textwrap
import zipfile

import yaml

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "navigan/modules/cluster_management/"


class UniqueLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        require(key not in result, "Duplicate YAML keys require review.")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def tree(source):
    return ast.parse(source)


def same(left, right):
    if not isinstance(left, ast.AST) or not isinstance(right, ast.AST):
        return left == right
    return ast.dump(left, include_attributes=False) == ast.dump(right, include_attributes=False)


def fragment(source, node):
    return "\n".join(source.splitlines()[node.lineno - 1:node.end_lineno])


def edit(source, edits):
    lines = source.splitlines(keepends=True)
    for start, end, replacement in sorted(edits, reverse=True):
        lines[start:end] = [replacement]
    return "".join(lines)


def patch_handler(original):
    before = tree(original)
    require(not any(isinstance(n, ast.Name) and n.id == "refresh_installer_status" for n in ast.walk(before)),
            "Installer polling is already present; capture and review the current release.")
    reads = [n for n in ast.walk(before) if isinstance(n, ast.If)
             and isinstance(n.test, ast.Name) and n.test.id == "read"]
    require(len(reads) == 1, "Expected one authorized read branch.")
    matches = [n for n in ast.walk(reads[0]) if isinstance(n, ast.Assign)
               and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) and n.targets[0].id == "row"
               and same(n.value, tree("repo.get(identifier)").body[0].value)]
    require(len(matches) == 1, "Expected exactly one existing scoped cluster detail read.")
    target = matches[0]
    code = 'if action in {None, "", "platform-components", "tools"}:\n    row = refresh_installer_status(repo, row, correlation)\n'
    line = original.splitlines()[target.lineno - 1]
    indent = line[:len(line) - len(line.lstrip())]
    imports = [n for n in before.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    require(imports, "Existing handler imports missing.")
    result = edit(original, [
        (target.end_lineno, target.end_lineno, textwrap.indent(code, indent)),
        (imports[-1].end_lineno, imports[-1].end_lineno, "from .bootstrap_status import refresh_installer_status\n"),
    ])
    after = tree(result)
    imported = next(n for n in after.body if isinstance(n, ast.ImportFrom) and n.module == "bootstrap_status")
    after.body.remove(imported)
    inserted = [n for n in ast.walk(after) if isinstance(n, ast.If) and same(n, tree(code).body[0])]
    require(len(inserted) == 1, "Unexpected polling insertion.")
    for parent in ast.walk(after):
        for _, value in ast.iter_fields(parent):
            if isinstance(value, list) and inserted[0] in value:
                value.remove(inserted[0])
    require(same(before, after), "Unrelated handler changes rejected.")
    return result


def patch_installer(original):
    desired = (ROOT / "src" / PREFIX / "connector_installation.py").read_text()
    before, current = tree(original), tree(desired)
    require(any(isinstance(n, ast.ImportFrom) and n.module == "botocore.config"
                and any(a.name == "Config" and a.asname in (None, "Config") for a in n.names)
                for n in before.body), "Existing botocore Config import is missing.")
    cls = next(n for n in before.body if isinstance(n, ast.ClassDef) and n.name == "ConnectorInstaller")
    source_cls = next(n for n in current.body if isinstance(n, ast.ClassDef) and n.name == "ConnectorInstaller")
    require(not any(isinstance(n, ast.FunctionDef) and n.name == "inspect_status" for n in cls.body),
            "Installer status reader is already present; recapture the release.")
    init = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "__init__")
    known = tree(textwrap.dedent('''
        def __init__(self, sts=None, secrets=None, client_factory=None):
            self.sts = sts or boto3.client("sts")
            self.secrets = secrets or boto3.client("secretsmanager")
            self.client_factory = client_factory or boto3.client
    ''')).body[0]
    require(same(init, known), "Unknown installer client setup; refusing to replace it.")
    replacement = next(n for n in source_cls.body if isinstance(n, ast.FunctionDef) and n.name == "__init__")
    method = next(n for n in source_cls.body if isinstance(n, ast.FunctionDef) and n.name == "inspect_status")
    has_re = any(isinstance(n, ast.Import) and any(a.name == "re" and a.asname in (None, "re") for a in n.names) for n in before.body)
    edits = [(init.lineno - 1, init.end_lineno,
              fragment(desired, replacement) + "\n\n" + fragment(desired, method) + "\n")]
    if not has_re:
        imports = [n for n in before.body if isinstance(n, (ast.Import, ast.ImportFrom))]
        edits.append((imports[-1].end_lineno, imports[-1].end_lineno, "import re\n"))
    result = edit(original, edits)
    after = tree(result)
    altered = next(n for n in after.body if isinstance(n, ast.ClassDef) and n.name == cls.name)
    altered.body = [copy.deepcopy(init) if isinstance(n, ast.FunctionDef) and n.name == "__init__" else n
                    for n in altered.body if not (isinstance(n, ast.FunctionDef) and n.name == "inspect_status")]
    if not has_re:
        added = next(n for n in after.body if isinstance(n, ast.Import) and len(n.names) == 1
                     and n.names[0].name == "re" and n.names[0].asname is None)
        after.body.remove(added)
    require(same(before, after), "Unrelated installer methods changed.")
    return result


def patch_package(original, destination, *, polling):
    with zipfile.ZipFile(original) as old:
        require(len(old.namelist()) == len(set(old.namelist())), "Duplicate ZIP members rejected.")
        changed = {}
        app_name = PREFIX + "system_repo_template/applications/20-falco.yaml"
        values_name = PREFIX + "system_repo_template/values/falco.yaml"
        app, values = (yaml.load(old.read(name), Loader=UniqueLoader) for name in (app_name, values_name))
        sources = [s for s in app["spec"]["sources"] if s.get("chart") == "falco"]
        require(len(sources) == 1 and sources[0].get("targetRevision") in ("9.1.0", "9.2.0"),
                "Unexpected deployed Falco chart version.")
        sources[0]["targetRevision"] = "9.2.0"
        image = values.setdefault("image", {})
        require(image.get("registry") in (None, "docker.io") and image.get("repository") in (None, "falcosecurity/falco"),
                "Custom Falco image repository requires review.")
        require(image.get("tag") in (None, "0.45.0", "0.45.1"), "Custom Falco image requires review.")
        image["tag"] = "0.45.1"
        engine = values.setdefault("collectors", {}).setdefault("containerEngine", {})
        plugin = "ghcr.io/falcosecurity/plugins/plugin/container:0.7.5"
        require(engine.get("pluginRef") in (None, plugin), "Custom container plugin requires review.")
        engine["pluginRef"] = plugin
        require(values.get("nodeSelector", {}).get("navigan.io/platform-services") == "true",
                "Deployed Falco protected-node selection is missing.")
        require(values.get("driver", {}).get("kind") == "modern_ebpf" and any(
            item.get("key") == "navigan.io/system-only" and item.get("value") == "true"
            and item.get("effect") == "NoSchedule" and item.get("operator", "Equal") == "Equal"
            for item in values.get("tolerations", [])), "Deployed Falco driver or protected-node toleration differs.")
        changed[app_name] = yaml.safe_dump(app, sort_keys=False).encode()
        changed[values_name] = yaml.safe_dump(values, sort_keys=False).encode()
        if polling:
            require(PREFIX + "bootstrap_status.py" not in old.namelist(), "Polling module already exists.")
            for name, patch in (("handler.py", patch_handler), ("connector_installation.py", patch_installer)):
                changed[PREFIX + name] = patch(old.read(PREFIX + name).decode()).encode()
            changed[PREFIX + "bootstrap_status.py"] = (ROOT / "src" / PREFIX / "bootstrap_status.py").read_bytes()
            methods = {n.name for n in ast.walk(tree(old.read(PREFIX + "repository.py").decode()))
                       if isinstance(n, ast.FunctionDef)}
            require({"get", "save", "pinned_environment_snapshot"} <= methods, "Repository contract is missing.")
        removed = {name for name in old.namelist() if polling and name.startswith(PREFIX)
                   and name.endswith(".pyc") and Path(name).name.split(".")[0]
                   in {"handler", "connector_installation", "bootstrap_status"}}
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as new:
            for entry in old.infolist():
                if entry.filename not in removed:
                    new.writestr(entry, changed.pop(entry.filename, old.read(entry.filename)))
            for name, content in changed.items():
                new.writestr(name, content)
    with zipfile.ZipFile(destination) as archive:
        require(sum(x.file_size for x in archive.infolist()) <= 250 * 1024 * 1024, "Lambda ZIP too large.")
        for name in ("handler.py", "connector_installation.py", "bootstrap_status.py") if polling else ():
            compile(archive.read(PREFIX + name), name, "exec")
    return destination


def patch_runner(original, *, desired=None):
    if desired is None:
        desired = (ROOT / "provisioning/runner/runner.py").read_text()
    before = tree(original)
    require(not any(isinstance(n, ast.FunctionDef) and n.name == "system_node_findings" for n in before.body),
            "Runner guard already present; capture a fresh baseline.")
    scan = next(n for n in before.body if isinstance(n, ast.FunctionDef) and n.name == "security_scan")
    findings = scan.body[0]
    require(same(findings, tree("findings = []").body[0]), "Unexpected runner findings setup.")
    dictionaries = [n for n in ast.walk(before) if isinstance(n, ast.Dict) and
                    any(isinstance(k, ast.Constant) and k.value == "node_groups" for k in n.keys)]
    require(len(dictionaries) == 1, "Unexpected Terraform variables layout.")
    variables = dictionaries[0]
    index = next(i for i, k in enumerate(variables.keys) if isinstance(k, ast.Constant) and k.value == "node_groups")
    previous = variables.values[index]
    raw_groups = same(previous, tree('request["configuration"]["nodeGroups"]').body[0].value)
    source_tree = tree(desired)
    helper = next(n for n in source_tree.body if isinstance(n, ast.FunctionDef) and n.name == "system_node_findings")
    normalization = next(n for n in ast.walk(source_tree) if isinstance(n, ast.Dict) and
                         any(isinstance(k, ast.Constant) and k.value == "node_groups" for k in n.keys))
    normalized = normalization.values[next(i for i, k in enumerate(normalization.keys)
                                          if isinstance(k, ast.Constant) and k.value == "node_groups")]
    apply_calls = [n for n in ast.walk(before) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                   and isinstance(n.value.func, ast.Name) and n.value.func.id == "run"
                   and len(n.value.args) > 1 and isinstance(n.value.args[1], ast.Constant)
                   and n.value.args[1].value == "apply"]
    require(len(apply_calls) == 1, "Expected exactly one Terraform apply.")
    guard = 'shown = run_json("terraform", "show", "-json", "terraform.tfplan")\nif system_node_findings(shown, request):\n    raise ValueError("Approved plan does not provision a protected system node group.")\n'
    target = apply_calls[0]
    lines = original.splitlines(keepends=True)
    # Older runners pass raw groups and need purpose defaults. Newer DEV runners
    # already transform them: retain that expression verbatim, including adopted
    # group handling and custom fields. The added guard checks the actual plan;
    # it does not assume the existing normalization provides protection.
    result = original
    if raw_groups:
        start = sum(len(line) for line in lines[:previous.lineno - 1]) + previous.col_offset
        end = sum(len(line) for line in lines[:previous.end_lineno - 1]) + previous.end_col_offset
        result = original[:start] + ast.unparse(normalized) + original[end:]
    # Refresh all positions before line edits, whether the expression was kept
    # multiline or replaced. The AST restoration below proves unrelated behavior.
    parsed = tree(result)
    scan_now = next(n for n in parsed.body if isinstance(n, ast.FunctionDef) and n.name == scan.name)
    apply_now = next(n for n in ast.walk(parsed) if isinstance(n, ast.Expr) and same(n, target))
    result = edit(result, [(scan_now.lineno - 1, scan_now.lineno - 1, fragment(desired, helper) + "\n\n"),
                          (scan_now.body[0].lineno - 1, scan_now.body[0].end_lineno,
                           '    findings = system_node_findings(plan, request)\n'),
                          (apply_now.lineno - 1, apply_now.lineno - 1,
                           textwrap.indent(guard, " " * apply_now.col_offset))])
    after = tree(result)
    after.body = [n for n in after.body if not (isinstance(n, ast.FunctionDef) and n.name == helper.name)]
    restored_scan = next(n for n in after.body if isinstance(n, ast.FunctionDef) and n.name == scan.name)
    restored_scan.body[0] = copy.deepcopy(findings)
    restored_vars = next(n for n in ast.walk(after) if isinstance(n, ast.Dict) and
                         any(isinstance(k, ast.Constant) and k.value == "node_groups" for k in n.keys))
    restored_vars.values[index] = copy.deepcopy(previous)
    guard_nodes = tree(guard).body
    for parent in ast.walk(after):
        for _, children in ast.iter_fields(parent):
            if isinstance(children, list):
                for i in range(len(children) - 2):
                    if same(children[i], guard_nodes[0]) and same(children[i + 1], guard_nodes[1]) and same(children[i + 2], target):
                        del children[i:i + 2]
                        break
    require(same(before, after), "Unrelated runner behavior changed.")
    return result


def block(source, header):
    matches = list(re.finditer(header + r"\s*\{", source))
    require(len(matches) == 1, "Expected exactly one Terraform block: " + header)
    start = matches[0].end() - 1
    masked = re.sub(r'"(?:\\.|[^"\\])*"|//[^\n]*|\#[^\n]*|/\*[\s\S]*?\*/',
                    lambda m: " " * len(m.group()), source)
    depth = 0
    for pos in range(start, len(source)):
        depth += (masked[pos] == "{") - (masked[pos] == "}")
        if depth == 0:
            return start, pos
    raise ValueError("Unbalanced Terraform block.")


def patch_module(main, variables):
    start, end = block(main, r'resource "aws_eks_node_group" "this"')
    body = main[start + 1:end]
    require(not re.search(r'^\s*(?:labels\s*=|taint\s*\{|dynamic\s+"taint")', body, re.M),
            "Existing node-group labels or taints require review.")
    labels = '''
  labels = merge(
    {
      "navigan.io/node-purpose" = lower(each.value.purpose)
      "navigan.io/managed-by" = "navigan"
    },
    each.value.purpose == "SYSTEM" ? {"navigan.io/platform-services" = "true"} : {}
  )
  dynamic "taint" {
    for_each = each.value.purpose == "SYSTEM" ? [1] : []
    content {
      key = "navigan.io/system-only"
      value = "true"
      effect = "NO_SCHEDULE"
    }
  }
'''
    updated_main = main[:end] + labels + main[end:]
    var_start, var_end = block(variables, r'variable "node_groups"')
    var_body = variables[var_start:var_end]
    require(not re.search(r'\bpurpose\s*=', var_body), "Node-group purpose already exists; review baseline.")
    match = re.search(r'type\s*=\s*list\s*\(\s*object\s*\(\s*\{', var_body)
    require(match, "Unknown node-group variable type.")
    pos = var_start + match.end()
    updated_variables = variables[:pos] + "\n    purpose = string" + variables[pos:]
    return updated_main, updated_variables

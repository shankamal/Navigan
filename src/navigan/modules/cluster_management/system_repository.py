"""Render the secret-free desired state committed to each cluster system repo."""

import re
from importlib.resources import files

from navigan.shared.errors import ApiError


PLACEHOLDER = re.compile(r"__[A-Z0-9_]+__")


def connector_artifact(image):
    if "@sha256:" not in image:
        raise ApiError(
            409,
            "CONNECTOR_IMAGE_NOT_IMMUTABLE",
            "The connector image must use an immutable sha256 digest.",
        )
    repository, digest_value = image.rsplit("@", 1)
    registry, separator, image_path = repository.partition("/")
    if not separator or not image_path:
        raise ApiError(
            409,
            "CONNECTOR_IMAGE_INVALID",
            "The configured connector image is invalid.",
        )
    return registry, repository, digest_value


def render_system_repository(
    *,
    repository_url,
    connector_id,
    cluster_id,
    connector_image,
    api_base_url,
    tools_base_url="",
    revision="main",
):
    registry, connector_repository, connector_digest = connector_artifact(
        connector_image
    )
    replacements = {
        "__SYSTEM_REPO_URL__": repository_url,
        "__SYSTEM_REPO_REVISION__": revision,
        "__PLATFORM_REGISTRY__": registry,
        "__CONNECTOR_REPOSITORY__": connector_repository,
        "__CONNECTOR_IMAGE_DIGEST__": connector_digest,
        "__CONNECTOR_ID__": connector_id,
        "__CLUSTER_ID__": cluster_id,
        "__NAVIGAN_API_BASE_URL__": api_base_url.rstrip("/"),
        "__NAVIGAN_TOOLS_BASE_URL__": tools_base_url.rstrip("/"),
        "__NAVIGAN_TOOLS_TUNNEL_URL__": (
            tools_base_url.rstrip("/").replace("https://", "wss://", 1)
            + "/tunnel"
            if tools_base_url
            else ""
        ),
    }
    root = files(__package__).joinpath("system_repo_template")
    rendered = {}
    for resource in root.iterdir():
        _render_tree(resource, resource.name, replacements, rendered)
    return rendered


def _render_tree(resource, relative_path, replacements, rendered):
    if resource.is_dir():
        for child in resource.iterdir():
            _render_tree(
                child,
                f"{relative_path}/{child.name}",
                replacements,
                rendered,
            )
        return
    text = resource.read_text(encoding="utf-8")
    for source, target in replacements.items():
        text = text.replace(source, target)
    unresolved = sorted(set(PLACEHOLDER.findall(text)))
    if unresolved:
        raise ApiError(
            500,
            "SYSTEM_REPOSITORY_TEMPLATE_INVALID",
            "The platform system repository template is incomplete.",
        )
    rendered[relative_path] = text

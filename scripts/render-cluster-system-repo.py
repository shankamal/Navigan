"""Render a secret-free per-cluster GitOps system repository."""

import argparse
import pathlib
import re
import shutil


PLACEHOLDER = re.compile(r"__[A-Z0-9_]+__")
SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
CONNECTOR_ID = re.compile(r"^KCC-[a-f0-9]{32}$")
DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")


def arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--customer-slug", required=True)
    parser.add_argument("--cluster-slug", required=True)
    parser.add_argument("--repository-url", required=True)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--connector-id", required=True)
    parser.add_argument("--connector-image-digest", required=True)
    parser.add_argument("--api-base-url", required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    return parser.parse_args()


def main():
    args = arguments()
    if not SLUG.fullmatch(args.customer_slug) or not SLUG.fullmatch(args.cluster_slug):
        raise SystemExit("Customer and cluster slugs must be lowercase DNS-style names.")
    if not CONNECTOR_ID.fullmatch(args.connector_id):
        raise SystemExit("Connector ID is invalid.")
    if not DIGEST.fullmatch(args.connector_image_digest):
        raise SystemExit("Connector image must use an immutable sha256 digest.")
    if not args.repository_url.startswith("https://"):
        raise SystemExit("Repository URL must use HTTPS.")
    if not re.fullmatch(r"[A-Za-z0-9.-]+(?::[0-9]+)?(?:/[A-Za-z0-9._/-]+)?", args.registry):
        raise SystemExit("Registry value is invalid.")
    if not re.fullmatch(r"[A-Za-z0-9._/-]{1,200}", args.revision):
        raise SystemExit("Repository revision is invalid.")
    if not args.api_base_url.startswith("https://"):
        raise SystemExit("API base URL must use HTTPS.")
    if args.output.exists():
        raise SystemExit("Output directory already exists.")

    root = pathlib.Path(__file__).resolve().parents[1]
    template = root / "platform" / "system-repo-template"
    shutil.copytree(template, args.output)
    replacements = {
        "__PLATFORM_REGISTRY__": args.registry.rstrip("/"),
        "__SYSTEM_REPO_URL__": args.repository_url,
        "__SYSTEM_REPO_REVISION__": args.revision,
        "__CONNECTOR_ID__": args.connector_id,
        "__CONNECTOR_IMAGE_DIGEST__": args.connector_image_digest,
        "__NAVIGAN_API_BASE_URL__": args.api_base_url.rstrip("/"),
    }
    for path in args.output.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for source, target in replacements.items():
            text = text.replace(source, target)
        remaining = sorted(set(PLACEHOLDER.findall(text)))
        if remaining:
            raise SystemExit(f"{path}: unresolved placeholders: {', '.join(remaining)}")
        path.write_text(text, encoding="utf-8", newline="\n")

    expected_name = f"{args.customer_slug}-{args.cluster_slug}-system"
    print(f"Rendered {expected_name} at {args.output}")


if __name__ == "__main__":
    main()

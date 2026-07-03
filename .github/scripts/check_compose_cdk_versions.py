from __future__ import annotations

import ast
import sys
import tarfile
from dataclasses import dataclass
from pathlib import Path

import eoapi_cdk
import yaml
from packaging.requirements import Requirement
from packaging.version import Version


ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class VersionCheck:
    service: str
    compose_package: str
    compose_version: str
    cdk_package: str
    cdk_spec: str


SERVICE_IMAGES = {
    "database": "pgstac",
    "stac-fastapi": "stac-fastapi-pgstac",
    "titiler-pgstac": "titiler-pgstac",
    "tipg": "tipg",
}

CDK_RUNTIME_REQUIREMENTS = {
    "stac-fastapi": (
        "package/lib/stac-api/runtime/requirements.txt",
        "stac-fastapi-pgstac",
    ),
    "titiler-pgstac": (
        "package/lib/titiler-pgstac-api/runtime/requirements.txt",
        "titiler.pgstac",
    ),
    "tipg": ("package/lib/tipg-api/runtime/requirements.txt", "tipg"),
}


def main() -> int:
    checks = [
        VersionCheck(
            service="database",
            compose_package="pgstac",
            compose_version=compose_image_version("database"),
            cdk_package="pgstac",
            cdk_spec=f"=={pgstac_config_version()}",
        )
    ]

    for service, (requirements_path, package_name) in CDK_RUNTIME_REQUIREMENTS.items():
        requirement = cdk_runtime_requirement(requirements_path, package_name)
        checks.append(
            VersionCheck(
                service=service,
                compose_package=SERVICE_IMAGES[service],
                compose_version=compose_image_version(service),
                cdk_package=requirement.name,
                cdk_spec=str(requirement.specifier),
            )
        )

    mismatches = [
        check
        for check in checks
        if Version(normalize_version(check.compose_version))
        not in Requirement(f"{check.cdk_package}{check.cdk_spec}").specifier
    ]

    if not mismatches:
        print("Docker Compose service versions match CDK expectations.")
        return 0

    print("Docker Compose service versions do not match CDK expectations:")
    for mismatch in mismatches:
        print(
            f"- {mismatch.service}: compose {mismatch.compose_package}"
            f"=={mismatch.compose_version}, CDK expects {mismatch.cdk_package}"
            f"{mismatch.cdk_spec}"
        )
    return 1


def compose_image_version(service: str) -> str:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    image = compose["services"][service]["image"]
    image_name, separator, tag = image.rpartition(":")

    if not separator or "/" in tag:
        raise ValueError(f"Expected {service} image to include a tag, got {image!r}")

    expected_image_name = SERVICE_IMAGES[service]
    if image_name.rsplit("/", maxsplit=1)[-1] != expected_image_name:
        raise ValueError(
            f"Expected {service} image name to end with {expected_image_name!r}, got {image!r}"
        )

    return tag


def pgstac_config_version() -> str:
    config_path = ROOT / "infrastructure" / "config.py"
    config_ast = ast.parse(config_path.read_text())

    for node in ast.walk(config_ast):
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
            continue
        if node.target.id != "pgstac_version" or not isinstance(node.value, ast.Call):
            continue
        for keyword in node.value.keywords:
            if keyword.arg == "default" and isinstance(keyword.value, ast.Constant):
                return str(keyword.value.value)

    raise ValueError("Could not find AppConfig.pgstac_version default")


def cdk_runtime_requirement(requirements_path: str, package_name: str) -> Requirement:
    archive = next(
        (Path(eoapi_cdk.__file__).parent / "_jsii").glob("eoapi-cdk@*.jsii.tgz")
    )
    with tarfile.open(archive) as tar:
        requirements = tar.extractfile(requirements_path)
        if requirements is None:
            raise ValueError(f"Could not find {requirements_path} in {archive}")

        for line in requirements.read().decode().splitlines():
            if not line or line.startswith("#"):
                continue
            requirement = Requirement(line)
            if requirement.name == package_name:
                return requirement

    raise ValueError(
        f"Could not find {package_name} requirement in {requirements_path}"
    )


def normalize_version(version: str) -> str:
    return version[1:] if version.startswith("v") else version


if __name__ == "__main__":
    sys.exit(main())

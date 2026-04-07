from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

from internal.models.git_sync import GitRepoSpec, GitSync
from internal.models.yang_inventory import (
    InventorySource,
    YangInventoryBuilder,
    YangModuleRecord,
)

LOG = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = REPO_ROOT / "data"
REPOS_ROOT = DATA_ROOT / "repos"
GENERATED_SCHEMA_ROOT = DATA_ROOT / "generated" / "schema"


@dataclass(frozen=True)
class ModelSource:
    name: str
    url: str
    source_type: str
    vendor: str
    priority: int
    os_name: str | None = None
    branch: str | None = None
    usage: str | None = None

    def to_git_spec(self) -> GitRepoSpec:
        return GitRepoSpec(
            name=self.name,
            url=self.url,
            branch=self.branch,
        )


@dataclass
class ModelRegistryRecord:
    source: ModelSource
    repo_root: str
    module_count: int
    modules: list[YangModuleRecord] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "source": asdict(self.source),
            "repo_root": self.repo_root,
            "module_count": self.module_count,
            "modules": [module.to_dict() for module in self.modules],
        }


class ModelRegistry:
    def __init__(
        self,
        workspace: Path,
        output_dir: Path,
    ) -> None:
        self.workspace = workspace
        self.output_dir = output_dir
        self.git_sync = GitSync(workspace=workspace)
        self.inventory_builder = YangInventoryBuilder()

        self.output_dir.mkdir(parents=True, exist_ok=True)

    def sync_and_build(self, sources: list[ModelSource]) -> list[ModelRegistryRecord]:
        records: list[ModelRegistryRecord] = []

        for source in sorted(sources, key=lambda item: item.priority):
            LOG.info("Processing model source %s", source.name)
            repo_root = self.git_sync.sync_repo(source.to_git_spec())

            modules = self.inventory_builder.build(
                InventorySource(
                    name=source.name,
                    vendor=source.vendor,
                    repo_root=repo_root,
                )
            )

            LOG.info(
                "Source %s produced %s parsed modules",
                source.name,
                len(modules),
            )

            records.append(
                ModelRegistryRecord(
                    source=source,
                    repo_root=str(repo_root.resolve()),
                    module_count=len(modules),
                    modules=modules,
                )
            )

        return records

    def write_registry_json(
        self,
        records: list[ModelRegistryRecord],
        filename: str = "model_registry.json",
    ) -> Path:
        output_path = self.output_dir / filename
        payload = {
            "sources": [record.to_dict() for record in records],
        }
        output_path.write_text(json.dumps(payload, indent=2), encoding="utf_8")
        LOG.info("Wrote model registry to %s", output_path)
        return output_path


def default_sources() -> list[ModelSource]:
    return [
        ModelSource(
            name="openconfig_public",
            url="https://github.com/openconfig/public.git",
            source_type="openconfig",
            vendor="neutral",
            priority=1,
            usage="global baseline",
        ),
        ModelSource(
            name="juniper_openconfig",
            url="https://github.com/Juniper/openconfig-public.git",
            source_type="vendor_openconfig_overlay",
            vendor="juniper",
            os_name="junos",
            priority=2,
            usage="Juniper OpenConfig overlay",
        ),
        ModelSource(
            name="nokia_openconfig",
            url="https://github.com/nokia/openconfig-public.git",
            source_type="vendor_openconfig_overlay",
            vendor="nokia",
            os_name="nokia",
            priority=2,
            usage="Nokia OpenConfig overlay",
        ),
        ModelSource(
            name="juniper_native",
            url="https://github.com/Juniper/yang.git",
            source_type="vendor_native",
            vendor="juniper",
            os_name="junos",
            priority=3,
            usage="native Junos YANG",
        ),
        ModelSource(
            name="arista_native",
            url="https://github.com/aristanetworks/yang.git",
            source_type="vendor_native",
            vendor="arista",
            os_name="eos",
            priority=3,
            usage="native EOS YANG",
        ),
        ModelSource(
            name="yangmodels_catalog",
            url="https://github.com/YangModels/yang.git",
            source_type="multi_vendor_catalog",
            vendor="shared",
            priority=4,
            usage="shared vendor discovery and fallback",
        ),
    ]


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    registry = ModelRegistry(
        workspace=REPOS_ROOT,
        output_dir=GENERATED_SCHEMA_ROOT,
    )

    records = registry.sync_and_build(default_sources())
    registry.write_registry_json(records)


if __name__ == "__main__":
    main()

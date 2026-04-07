from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path

MODULE_RE = re.compile(r"^\s*module\s+([A-Za-z0-9\-_]+)\s*\{", re.MULTILINE)
SUBMODULE_RE = re.compile(
    r"^\s*submodule\s+([A-Za-z0-9\-_]+)\s*\{",
    re.MULTILINE,
)
NAMESPACE_RE = re.compile(
    r'^\s*namespace\s+"([^"]+)"\s*;',
    re.MULTILINE,
)
PREFIX_RE = re.compile(r"^\s*prefix\s+([A-Za-z0-9\-_]+)\s*;", re.MULTILINE)
REVISION_RE = re.compile(
    r'^\s*revision\s+"?([0-9]{4}-[0-9]{2}-[0-9]{2})"?\s*\{?',
    re.MULTILINE,
)
IMPORT_RE = re.compile(r"^\s*import\s+([A-Za-z0-9\-_]+)\s*\{", re.MULTILINE)
INCLUDE_RE = re.compile(r"^\s*include\s+([A-Za-z0-9\-_]+)\s*;", re.MULTILINE)
FEATURE_RE = re.compile(r"^\s*feature\s+([A-Za-z0-9\-_]+)\s*\{", re.MULTILINE)
IDENTITY_RE = re.compile(
    r"^\s*identity\s+([A-Za-z0-9\-_]+)\s*\{",
    re.MULTILINE,
)
DEVIATION_RE = re.compile(
    r'^\s*deviation\s+("?[^"\n;]+?"?)\s*\{',
    re.MULTILINE,
)
AUGMENT_RE = re.compile(
    r'^\s*augment\s+("?[^"\n;]+?"?)\s*\{',
    re.MULTILINE,
)
RPC_RE = re.compile(r"^\s*rpc\s+([A-Za-z0-9\-_]+)\s*\{", re.MULTILINE)
NOTIFICATION_RE = re.compile(
    r"^\s*notification\s+([A-Za-z0-9\-_]+)\s*\{",
    re.MULTILINE,
)


@dataclass(frozen=True)
class InventorySource:
    """
    One source repository being scanned for YANG modules.
    """

    name: str
    vendor: str
    repo_root: Path


@dataclass(frozen=True)
class YangModuleSummary:
    module_name: str | None
    submodule_name: str | None
    namespace: str | None
    prefix: str | None
    revisions: list[str]
    imports: list[str]
    includes: list[str]
    features: list[str]
    rpcs: list[str]
    notifications: list[str]
    identities: list[str]
    deviations: list[str]
    augments: list[str]


@dataclass(frozen=True)
class YangModuleRecord:
    """
    Inventory record for one YANG file.

    This is the stable object that model_registry serializes into
    model_registry.json for downstream schema processing.
    """

    source_name: str
    vendor: str
    repo_root: str
    file_path: str
    relative_path: str
    module_name: str | None
    submodule_name: str | None
    namespace: str | None
    prefix: str | None
    revisions: list[str]
    imports: list[str]
    includes: list[str]
    features: list[str]
    rpcs: list[str]
    notifications: list[str]
    identities: list[str]
    deviations: list[str]
    augments: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def summarize_yang_text(text: str) -> YangModuleSummary:
    """
    Extract a lightweight summary from one YANG file.
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")

    module_match = MODULE_RE.search(normalized)
    submodule_match = SUBMODULE_RE.search(normalized)
    namespace_match = NAMESPACE_RE.search(normalized)
    prefix_match = PREFIX_RE.search(normalized)

    revisions = sorted(set(REVISION_RE.findall(normalized)))
    imports = sorted(set(IMPORT_RE.findall(normalized)))
    includes = sorted(set(INCLUDE_RE.findall(normalized)))
    features = sorted(set(FEATURE_RE.findall(normalized)))
    rpcs = sorted(set(RPC_RE.findall(normalized)))
    notifications = sorted(set(NOTIFICATION_RE.findall(normalized)))
    identities = sorted(set(IDENTITY_RE.findall(normalized)))
    deviations = sorted(
        {
            value.strip().strip('"')
            for value in DEVIATION_RE.findall(normalized)
        }
    )
    augments = sorted(
        {
            value.strip().strip('"')
            for value in AUGMENT_RE.findall(normalized)
        }
    )

    return YangModuleSummary(
        module_name=module_match.group(1) if module_match else None,
        submodule_name=(
            submodule_match.group(1) if submodule_match else None
        ),
        namespace=namespace_match.group(1) if namespace_match else None,
        prefix=prefix_match.group(1) if prefix_match else None,
        revisions=revisions,
        imports=imports,
        includes=includes,
        features=features,
        rpcs=rpcs,
        notifications=notifications,
        identities=identities,
        deviations=deviations,
        augments=augments,
    )


class YangInventoryBuilder:
    """
    Walk a repo tree and build a flat inventory of YANG files.

    This intentionally stays lightweight and filesystem based.
    """

    def build(self, source: InventorySource) -> list[YangModuleRecord]:
        records: list[YangModuleRecord] = []

        for path in sorted(source.repo_root.rglob("*.yang")):
            # Skip obvious junk directories if they appear in cloned repos.
            if any(part in {"__pycache__", ".git"} for part in path.parts):
                continue

            try:
                text = path.read_text(encoding="utf_8")
            except UnicodeDecodeError:
                # Fall back for vendor repos that contain odd encodings.
                text = path.read_text(encoding="latin_1")

            summary = summarize_yang_text(text)

            records.append(
                YangModuleRecord(
                    source_name=source.name,
                    vendor=source.vendor,
                    repo_root=str(source.repo_root),
                    file_path=str(path),
                    relative_path=str(path.relative_to(source.repo_root)),
                    module_name=summary.module_name,
                    submodule_name=summary.submodule_name,
                    namespace=summary.namespace,
                    prefix=summary.prefix,
                    revisions=summary.revisions,
                    imports=summary.imports,
                    includes=summary.includes,
                    features=summary.features,
                    rpcs=summary.rpcs,
                    notifications=summary.notifications,
                    identities=summary.identities,
                    deviations=summary.deviations,
                    augments=summary.augments,
                )
            )

        return records

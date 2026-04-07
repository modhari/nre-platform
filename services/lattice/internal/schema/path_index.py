from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

LOG = logging.getLogger(__name__)


NODE_START_RE = re.compile(
    r'^\s*(container|list|leaf-list|leaf|rpc|notification|action)\s+("?[^"\s\{;]+"?)\s*(\{)?'
)
KEY_RE = re.compile(r'^\s*key\s+"([^"]+)"\s*;')
TYPE_RE = re.compile(r'^\s*type\s+([A-Za-z0-9_:\.:-]+)\s*;')
CONFIG_FALSE_RE = re.compile(r'^\s*config\s+false\s*;')
CONFIG_TRUE_RE = re.compile(r'^\s*config\s+true\s*;')
PREFIX_RE = re.compile(r'^\s*prefix\s+([A-Za-z0-9_.-]+)\s*;')


@dataclass(frozen=True)
class PathRecord:
    vendor: str
    source_name: str
    module_name: str
    file_path: str
    path: str
    node_name: str
    node_kind: str
    parent_path: str | None
    leaf_type: str | None
    list_keys: list[str]
    config_class: str
    semantic_domain: str
    module_prefix: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PathIndexBuilder:
    def __init__(
        self,
        schema_catalog_path: Path,
        output_jsonl_path: Path,
        progress_path: Path,
        checkpoint_every: int = 100,
    ) -> None:
        self.schema_catalog_path = schema_catalog_path
        self.output_jsonl_path = output_jsonl_path
        self.progress_path = progress_path
        self.checkpoint_every = checkpoint_every
        self.repo_roots_by_source: dict[str, str] = {}

    def build_jsonl(self) -> dict[str, Any]:
        LOG.info("Loading schema catalog from %s", self.schema_catalog_path)
        payload = json.loads(self.schema_catalog_path.read_text(encoding="utf_8"))
        modules = payload["modules"]
        LOG.info("Loaded schema catalog with %s module rows", len(modules))

        self.repo_roots_by_source = self._load_repo_roots(payload)
        LOG.info("Loaded %s repo roots", len(self.repo_roots_by_source))

        unique_modules = self._dedupe_modules(modules)
        total = len(unique_modules)
        LOG.info("Deduped to %s unique module files", total)

        self.output_jsonl_path.parent.mkdir(parents=True, exist_ok=True)

        progress = self._load_progress(total)
        start_index = progress["next_module_index"]
        total_paths = progress["total_paths_written"]

        LOG.info(
            "Resuming from module index %s of %s with %s paths already written",
            start_index,
            total,
            total_paths,
        )

        if start_index == 0 and self.output_jsonl_path.exists():
            LOG.info("Fresh run detected, removing existing output file %s", self.output_jsonl_path)
            self.output_jsonl_path.unlink()

        started_at = time.time()

        with self.output_jsonl_path.open("a", encoding="utf_8") as fh:
            for idx in range(start_index, total):
                module = unique_modules[idx]

                if idx == start_index or (idx + 1) % 50 == 0:
                    LOG.info("Indexing module %s / %s", idx + 1, total)

                source_name = module["source_name"]
                vendor = module["vendor"]
                module_name = module["module_name"]
                file_path = module["file_path"]
                repo_root = self.repo_roots_by_source.get(source_name)
                semantic_domains = module.get("semantic_domains", ["misc"])
                semantic_domain = semantic_domains[0] if semantic_domains else "misc"

                if not repo_root:
                    LOG.warning("No repo root found for source %s", source_name)
                    self._checkpoint(idx + 1, total, total_paths)
                    continue

                full_path = Path(repo_root) / file_path
                if not full_path.exists():
                    LOG.warning("Missing source file for module %s at %s", module_name, full_path)
                    self._checkpoint(idx + 1, total, total_paths)
                    continue

                try:
                    module_records = self._extract_paths(
                        vendor=vendor,
                        source_name=source_name,
                        module_name=module_name,
                        file_path=file_path,
                        full_path=full_path,
                        semantic_domain=semantic_domain,
                    )

                    for record in module_records:
                        fh.write(json.dumps(record.to_dict()) + "\n")

                    total_paths += len(module_records)

                except Exception as exc:
                    LOG.warning(
                        "Failed to index module %s from %s: %s",
                        module_name,
                        full_path,
                        exc,
                    )

                if (idx + 1) % self.checkpoint_every == 0:
                    fh.flush()
                    self._checkpoint(idx + 1, total, total_paths)

            fh.flush()

        self._checkpoint(total, total, total_paths, completed=True)

        elapsed = round(time.time() - started_at, 2)
        return {
            "generated_from": str(self.schema_catalog_path),
            "total_modules": total,
            "total_paths": total_paths,
            "format": "jsonl",
            "output": str(self.output_jsonl_path),
            "progress_file": str(self.progress_path),
            "completed": True,
            "elapsed_seconds": elapsed,
        }

    def _dedupe_modules(self, modules: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[tuple[str, str]] = set()
        unique: list[dict[str, Any]] = []

        for module in modules:
            key = (module["source_name"], module["file_path"])
            if key in seen:
                continue
            seen.add(key)
            unique.append(module)

        return unique

    def _load_repo_roots(self, schema_payload: dict[str, Any]) -> dict[str, str]:
        registry_path = Path(schema_payload["generated_from"])
        LOG.info("Loading registry from %s", registry_path)
        registry_payload = json.loads(registry_path.read_text(encoding="utf_8"))

        repo_roots: dict[str, str] = {}
        for source in registry_payload["sources"]:
            repo_roots[source["source"]["name"]] = source["repo_root"]
        return repo_roots

    def _load_progress(self, total_modules: int) -> dict[str, Any]:
        if not self.progress_path.exists():
            return {
                "next_module_index": 0,
                "total_modules": total_modules,
                "total_paths_written": 0,
                "completed": False,
            }

        payload = json.loads(self.progress_path.read_text(encoding="utf_8"))
        payload.setdefault("next_module_index", 0)
        payload.setdefault("total_modules", total_modules)
        payload.setdefault("total_paths_written", 0)
        payload.setdefault("completed", False)
        return payload

    def _checkpoint(
        self,
        next_module_index: int,
        total_modules: int,
        total_paths_written: int,
        completed: bool = False,
    ) -> None:
        payload = {
            "next_module_index": next_module_index,
            "total_modules": total_modules,
            "total_paths_written": total_paths_written,
            "completed": completed,
            "updated_at_epoch": time.time(),
        }
        self.progress_path.parent.mkdir(parents=True, exist_ok=True)
        self.progress_path.write_text(json.dumps(payload, indent=2), encoding="utf_8")
        LOG.info(
            "Checkpoint saved: next_module_index=%s total_paths_written=%s completed=%s",
            next_module_index,
            total_paths_written,
            completed,
        )

    def _extract_paths(
        self,
        vendor: str,
        source_name: str,
        module_name: str,
        file_path: str,
        full_path: Path,
        semantic_domain: str,
    ) -> list[PathRecord]:
        lines = full_path.read_text(encoding="utf_8", errors="ignore").splitlines()

        stack: list[dict[str, Any]] = []
        records: list[PathRecord] = []
        record_index_by_path: dict[str, int] = {}
        module_prefix: str | None = None

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            if module_prefix is None:
                prefix_match = PREFIX_RE.match(line)
                if prefix_match:
                    module_prefix = prefix_match.group(1)

            node_match = NODE_START_RE.match(line)
            if node_match:
                kind = node_match.group(1)
                raw_name = node_match.group(2).strip('"')
                parent_path = stack[-1]["path"] if stack else None
                current_path = f"{parent_path}/{raw_name}" if parent_path else f"/{raw_name}"

                node_info = {
                    "kind": kind,
                    "name": raw_name,
                    "path": current_path,
                    "leaf_type": None,
                    "list_keys": [],
                    "config_class": "unknown",
                    "open_braces": line.count("{") - line.count("}"),
                }

                if kind in {"leaf", "leaf-list"} and node_info["config_class"] == "unknown":
                    node_info["config_class"] = "inherit"

                stack.append(node_info)

                record = PathRecord(
                    vendor=vendor,
                    source_name=source_name,
                    module_name=module_name,
                    file_path=file_path,
                    path=current_path,
                    node_name=raw_name,
                    node_kind=kind,
                    parent_path=parent_path,
                    leaf_type=None,
                    list_keys=[],
                    config_class="unknown",
                    semantic_domain=semantic_domain,
                    module_prefix=module_prefix,
                )
                record_index_by_path[current_path] = len(records)
                records.append(record)
                continue

            if stack:
                current = stack[-1]

                key_match = KEY_RE.match(line)
                if key_match and current["kind"] == "list":
                    current["list_keys"] = key_match.group(1).split()

                type_match = TYPE_RE.match(line)
                if type_match and current["kind"] in {"leaf", "leaf-list"}:
                    current["leaf_type"] = type_match.group(1)

                if CONFIG_FALSE_RE.match(line):
                    current["config_class"] = "state"
                elif CONFIG_TRUE_RE.match(line):
                    current["config_class"] = "config"

                current["open_braces"] += line.count("{")
                current["open_braces"] -= line.count("}")

                while stack and stack[-1]["open_braces"] <= 0:
                    completed = stack.pop()
                    self._apply_completed_node(records, record_index_by_path, completed)

        while stack:
            completed = stack.pop()
            self._apply_completed_node(records, record_index_by_path, completed)

        return records

    def _apply_completed_node(
        self,
        records: list[PathRecord],
        record_index_by_path: dict[str, int],
        completed: dict[str, Any],
    ) -> None:
        idx = record_index_by_path.get(completed["path"])
        if idx is None:
            return

        record = records[idx]
        records[idx] = PathRecord(
            vendor=record.vendor,
            source_name=record.source_name,
            module_name=record.module_name,
            file_path=record.file_path,
            path=record.path,
            node_name=record.node_name,
            node_kind=record.node_kind,
            parent_path=record.parent_path,
            leaf_type=completed["leaf_type"],
            list_keys=completed["list_keys"],
            config_class=completed["config_class"],
            semantic_domain=record.semantic_domain,
            module_prefix=record.module_prefix,
        )


def write_summary(output: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2), encoding="utf_8")
    LOG.info("Wrote path index summary to %s", output_path)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )

    repo_root = Path(__file__).resolve().parents[2]
    schema_catalog_path = repo_root / "data" / "generated" / "schema" / "schema_catalog.json"
    output_jsonl_path = repo_root / "data" / "generated" / "schema" / "path_index.jsonl"
    progress_path = repo_root / "data" / "generated" / "schema" / "path_index_progress.json"
    summary_path = repo_root / "data" / "generated" / "schema" / "path_index_summary.json"

    LOG.info("Starting resumable path index build")
    builder = PathIndexBuilder(
        schema_catalog_path=schema_catalog_path,
        output_jsonl_path=output_jsonl_path,
        progress_path=progress_path,
        checkpoint_every=100,
    )
    output = builder.build_jsonl()
    write_summary(output, summary_path)


if __name__ == "__main__":
    main()

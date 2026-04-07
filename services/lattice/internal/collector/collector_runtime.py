from __future__ import annotations

import json
import logging
import shlex
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class RuntimeValidationResult:
    """
    Validation summary for a rendered collector config.

    This keeps the runtime layer honest before anything is executed.
    """

    is_valid: bool
    errors: list[str]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RuntimeCommand:
    """
    One dry run execution command.

    This is intentionally command focused so Lattice can later hand it off
    to an executor or scheduler without changing the planning layers.
    """

    target: str
    command: str
    config_path: str
    selected_profiles: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CollectorRuntimePlan:
    """
    Runtime artifact that bridges planning and execution.

    It records:
    - validation result
    - commands that would be run
    - active subscriptions by profile
    """

    target: str
    vendor: str
    validation: RuntimeValidationResult
    commands: list[RuntimeCommand] = field(default_factory=list)
    profile_groups: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "vendor": self.vendor,
            "validation": self.validation.to_dict(),
            "commands": [command.to_dict() for command in self.commands],
            "profile_groups": self.profile_groups,
        }


class CollectorRuntimeBuilder:
    """
    Build a dry run runtime plan from the rendered gnmic target config.

    This version does not execute gnmic.
    It validates the config and renders the exact command line
    that would be used.
    """

    def __init__(
        self,
        gnmic_target_config_path: Path,
        gnmic_yaml_path: Path,
    ) -> None:
        self.gnmic_target_config_path = gnmic_target_config_path
        self.gnmic_yaml_path = gnmic_yaml_path

    def build(self) -> dict[str, Any]:
        LOG.info(
            "Loading gnmic target config from %s",
            self.gnmic_target_config_path,
        )
        payload = json.loads(
            self.gnmic_target_config_path.read_text(encoding="utf_8")
        )

        target = payload["target"]
        vendor = payload["vendor"]
        config = payload["gnmic_target_config"]

        validation = self._validate(payload)
        profile_groups = config.get("profile_groups", {})

        runtime_plan = CollectorRuntimePlan(
            target=target,
            vendor=vendor,
            validation=validation,
            profile_groups=profile_groups,
        )

        if validation.is_valid:
            runtime_plan.commands.append(
                self._build_dry_run_command(
                    target=target,
                    profile_groups=profile_groups,
                )
            )

        output = {
            "generated_from": {
                "gnmic_target_config": str(self.gnmic_target_config_path),
                "gnmic_yaml": str(self.gnmic_yaml_path),
            },
            "runtime_plan": runtime_plan.to_dict(),
        }
        return output

    def _validate(self, payload: dict[str, Any]) -> RuntimeValidationResult:
        """
        Validate the rendered target config before execution.

        We check:
        - target exists
        - target stanza exists
        - subscription set exists
        - target bindings reference only known subscriptions
        - profile groups reference only known subscriptions
        """
        errors: list[str] = []
        warnings: list[str] = []

        target = payload.get("target")
        config = payload.get("gnmic_target_config", {})
        targets = config.get("targets", {})
        subscriptions = config.get("subscriptions", {})
        target_bindings = config.get("target_bindings", {})
        profile_groups = config.get("profile_groups", {})

        if not target:
            errors.append("Missing top level target field")

        if target and target not in targets:
            errors.append(
                f"Target {target!r} not present in gnmic target config"
            )

        if not subscriptions:
            errors.append("No subscriptions present in gnmic target config")

        if target and target not in target_bindings:
            errors.append(f"No target binding found for target {target!r}")

        known_subscription_names = set(subscriptions.keys())

        for bound_target, names in target_bindings.items():
            for name in names:
                if name not in known_subscription_names:
                    errors.append(
                        "Target binding for "
                        f"{bound_target!r} references unknown "
                        f"subscription {name!r}"
                    )

        for profile_name, names in profile_groups.items():
            if not names:
                warnings.append(
                    f"Profile group {profile_name!r} has no subscriptions"
                )
            for name in names:
                if name not in known_subscription_names:
                    errors.append(
                        f"Profile group {profile_name!r} references "
                        f"unknown subscription {name!r}"
                    )

        if target and target in targets:
            target_record = targets[target]
            username = target_record.get("username", "")
            password = target_record.get("password", "")
            if username == "REPLACE_ME" or password == "REPLACE_ME":
                warnings.append(
                    f"Target {target!r} still has placeholder credentials"
                )

        return RuntimeValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    def _build_dry_run_command(
        self,
        target: str,
        profile_groups: dict[str, list[str]],
    ) -> RuntimeCommand:
        """
        Build the dry run gnmic command.

        The command uses the rendered YAML as the single config source.
        Profile names are included for operator visibility in the runtime plan.
        """
        selected_profiles = sorted(profile_groups.keys())

        cmd_parts = [
            "gnmic",
            "--config",
            str(self.gnmic_yaml_path),
            "subscribe",
            "--target",
            target,
        ]

        command = " ".join(shlex.quote(part) for part in cmd_parts)

        return RuntimeCommand(
            target=target,
            command=command,
            config_path=str(self.gnmic_yaml_path),
            selected_profiles=selected_profiles,
        )


def write_output(output: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2), encoding="utf_8")
    LOG.info("Wrote collector runtime plan to %s", output_path)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )

    repo_root = Path(__file__).resolve().parents[2]
    gnmic_target_config_path = (
        repo_root
        / "data"
        / "generated"
        / "schema"
        / "gnmic_leaf_01_target_config.json"
    )
    gnmic_yaml_path = (
        repo_root
        / "data"
        / "generated"
        / "schema"
        / "gnmic_leaf_01_target_config.yaml"
    )
    output_path = (
        repo_root
        / "data"
        / "generated"
        / "schema"
        / "collector_runtime_plan.json"
    )

    LOG.info("Starting collector runtime planning")
    builder = CollectorRuntimeBuilder(
        gnmic_target_config_path=gnmic_target_config_path,
        gnmic_yaml_path=gnmic_yaml_path,
    )
    output = builder.build()
    write_output(output, output_path)


if __name__ == "__main__":
    main()

"""
Error taxonomy.

We separate error types so callers can react correctly.
Example:
TopologyInvalid should block before any config is applied.
VerificationFailed should trigger rollback and alert.
PolicyRejected should stop and explain which rule blocked the change.
"""


class OrchestratorError(Exception):
    """Base class for all orchestrator exceptions."""


class PolicyRejected(OrchestratorError):
    """Raised when the deterministic policy gate blocks a plan."""


class VerificationFailed(OrchestratorError):
    """Raised when post change verification fails."""


class ExecutionFailed(OrchestratorError):
    """Raised when gNMI set or other execution fails."""


class TopologyInvalid(OrchestratorError):
    """Raised when the fabric topology or external connectivity policy is invalid."""

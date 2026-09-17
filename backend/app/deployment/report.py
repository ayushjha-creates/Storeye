"""M23 deployment diagnostics primitives.

A tiny, dependency-free result model shared by the model-asset validator
(``app.deployment.model_check``) and the environment doctor
(``app.deployment.doctor``). Keeping the report shape in one place lets both
CLIs print the same readable output and the same ``--json`` payload.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, List, Optional


class Status(str, Enum):
    """Severity of a single check."""

    PASS = "PASS"
    WARN = "WARN"
    ERROR = "ERROR"
    SKIP = "SKIP"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


@dataclass
class Check:
    """One diagnostic result."""

    name: str
    status: Status
    detail: str = ""
    hint: str = ""

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status.value,
            "detail": self.detail,
            "hint": self.hint,
        }


@dataclass
class CheckReport:
    """An ordered collection of checks with an overall verdict."""

    title: str
    checks: List[Check] = field(default_factory=list)

    def add(
        self,
        name: str,
        status: Status,
        detail: str = "",
        hint: str = "",
    ) -> Check:
        check = Check(name=name, status=status, detail=detail, hint=hint)
        self.checks.append(check)
        return check

    def extend(self, checks: Iterable[Check]) -> None:
        self.checks.extend(checks)

    # -- aggregate views ---------------------------------------------------
    @property
    def errors(self) -> List[Check]:
        return [c for c in self.checks if c.status is Status.ERROR]

    @property
    def warnings(self) -> List[Check]:
        return [c for c in self.checks if c.status is Status.WARN]

    @property
    def passed(self) -> List[Check]:
        return [c for c in self.checks if c.status is Status.PASS]

    @property
    def ok(self) -> bool:
        """True when nothing is ERROR-level (WARN is acceptable)."""
        return not self.errors

    @property
    def overall(self) -> str:
        """READY | DEGRADED | NOT READY."""
        if self.errors:
            return "NOT READY"
        if self.warnings:
            return "DEGRADED"
        return "READY"

    @property
    def exit_code(self) -> int:
        return 0 if self.ok else 1

    def as_dict(self) -> dict:
        return {
            "title": self.title,
            "overall": self.overall,
            "ok": self.ok,
            "counts": {
                "pass": len(self.passed),
                "warn": len(self.warnings),
                "error": len(self.errors),
            },
            "checks": [c.as_dict() for c in self.checks],
        }


_SYMBOL = {
    Status.PASS: "[ OK ]",
    Status.WARN: "[WARN]",
    Status.ERROR: "[FAIL]",
    Status.SKIP: "[SKIP]",
}


def render(report: CheckReport, out=None) -> None:  # pragma: no cover - IO glue
    """Print a human-readable report to ``out`` (defaults to stdout)."""
    import sys

    stream = out or sys.stdout
    print(report.title, file=stream)
    print("=" * len(report.title), file=stream)
    for check in report.checks:
        line = f"{_SYMBOL[check.status]} {check.name}"
        if check.detail:
            line += f" — {check.detail}"
        print(line, file=stream)
        if check.hint and check.status in (Status.WARN, Status.ERROR):
            print(f"        hint: {check.hint}", file=stream)
    print("-" * len(report.title), file=stream)
    print(
        f"Result: {report.overall} "
        f"({len(report.passed)} ok, {len(report.warnings)} warn, {len(report.errors)} error)",
        file=stream,
    )


def format_check(check: Check) -> str:
    detail: Optional[str] = check.detail or None
    suffix = f" — {detail}" if detail else ""
    return f"{check.status.value}: {check.name}{suffix}"

"""M22 — read-only data integrity checks.

This service verifies the *persisted* business database is internally
consistent. It is deliberately read-only: it NEVER mutates inventory, batches,
sales, bills, movements, alerts or insights. It reports findings; an operator
decides what to do.

Checks
------
1. Referential integrity — no orphaned child rows for non-null foreign keys.
2. Inventory invariants — non-negative quantities; no duplicate (store, product).
3. Batch invariants — non-negative quantity; expiry never before manufacturing.
4. Alert lifecycle validity — valid type/severity/status; terminal states carry
   the matching timestamp.
5. Camera config validity — camera_type in {usb, file, rtsp}.
6. Demo isolation — DemoScenarioState rows only ever point at is_demo stores.
7. Privacy — no image/embedding/face/biometric columns exist in observation,
   journey, alert or insight tables.

The service works against a PostgreSQL session; the orphan queries use plain
SQL and the privacy check uses information_schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..models import Alert, Batch, Camera, DemoScenarioState, Insight, Inventory, Store

SEV_ERROR = "error"
SEV_WARNING = "warning"
SEV_INFO = "info"

# (table, column, referenced table) — non-null foreign keys only.
_ORPHAN_CHECKS = [
    ("inventory", "store_id", "stores"),
    ("inventory", "product_id", "products"),
    ("inventory_movements", "store_id", "stores"),
    ("inventory_movements", "product_id", "products"),
    ("batches", "store_id", "stores"),
    ("batches", "product_id", "products"),
    ("cameras", "store_id", "stores"),
    ("alerts", "store_id", "stores"),
    ("observations", "store_id", "stores"),
    ("insights", "store_id", "stores"),
    ("demo_scenario_state", "store_id", "stores"),
]

# Tables that must NEVER contain raw media or biometric columns.
_PRIVACY_TABLES = [
    "observations",
    "global_person_sessions",
    "person_track_associations",
    "zone_visits",
    "person_camera_transitions",
    "alerts",
    "insights",
]
_PRIVACY_COLUMN_RE = "(image|embedding|face|biometric|photo|thumbnail|video)"

_VALID_CAMERA_TYPES = {"usb", "file", "rtsp"}


@dataclass
class IntegrityFinding:
    check: str
    severity: str
    message: str
    count: int = 0
    sample: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "check": self.check,
            "severity": self.severity,
            "message": self.message,
            "count": self.count,
            "sample": self.sample,
        }


@dataclass
class IntegrityReport:
    findings: list[IntegrityFinding] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    @property
    def errors(self) -> list[IntegrityFinding]:
        return [f for f in self.findings if f.severity == SEV_ERROR]

    @property
    def warnings(self) -> list[IntegrityFinding]:
        return [f for f in self.findings if f.severity == SEV_WARNING]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "stats": self.stats,
            "findings": [f.to_dict() for f in self.findings],
        }


class IntegrityCheckService:
    def __init__(self, session: Session):
        self.session = session

    # ------------------------------------------------------------------
    # public
    # ------------------------------------------------------------------
    def run(self) -> IntegrityReport:
        report = IntegrityReport()
        report.stats = self._stats()
        for check in (
            self.check_orphans,
            self.check_inventory_invariants,
            self.check_batch_invariants,
            self.check_alert_lifecycle,
            self.check_camera_config,
            self.check_demo_isolation,
            self.check_privacy,
        ):
            report.findings.extend(check())
        return report

    # ------------------------------------------------------------------
    # checks
    # ------------------------------------------------------------------
    def check_orphans(self) -> list[IntegrityFinding]:
        findings: list[IntegrityFinding] = []
        for table, column, ref in _ORPHAN_CHECKS:
            sql = text(
                f"SELECT count(*) FROM {table} t "  # noqa: S608 - hardcoded identifiers
                f"LEFT JOIN {ref} r ON t.{column} = r.id "
                f"WHERE t.{column} IS NOT NULL AND r.id IS NULL"
            )
            count = int(self.session.execute(sql).scalar() or 0)
            if count:
                findings.append(
                    IntegrityFinding(
                        check="orphans",
                        severity=SEV_ERROR,
                        message=f"{table}.{column} references a missing {ref} row",
                        count=count,
                    )
                )
        return findings

    def check_inventory_invariants(self) -> list[IntegrityFinding]:
        findings: list[IntegrityFinding] = []
        negative = int(
            self.session.execute(
                select(func.count()).select_from(Inventory).where(Inventory.quantity < 0)
            ).scalar()
            or 0
        )
        if negative:
            findings.append(
                IntegrityFinding(
                    check="inventory_negative",
                    severity=SEV_ERROR,
                    message="inventory rows with negative quantity",
                    count=negative,
                )
            )
        dupes = self.session.execute(
            select(Inventory.store_id, Inventory.product_id, func.count().label("n"))
            .group_by(Inventory.store_id, Inventory.product_id)
            .having(func.count() > 1)
        ).all()
        if dupes:
            findings.append(
                IntegrityFinding(
                    check="inventory_duplicate",
                    severity=SEV_ERROR,
                    message="duplicate (store_id, product_id) inventory rows",
                    count=len(dupes),
                    sample=[{"store_id": str(s), "product_id": str(p), "rows": n} for s, p, n in dupes[:5]],
                )
            )
        return findings

    def check_batch_invariants(self) -> list[IntegrityFinding]:
        findings: list[IntegrityFinding] = []
        negative = int(
            self.session.execute(
                select(func.count()).select_from(Batch).where(Batch.quantity < 0)
            ).scalar()
            or 0
        )
        if negative:
            findings.append(
                IntegrityFinding(
                    check="batch_negative",
                    severity=SEV_ERROR,
                    message="batch rows with negative quantity",
                    count=negative,
                )
            )
        bad_dates = int(
            self.session.execute(
                select(func.count())
                .select_from(Batch)
                .where(
                    Batch.manufacturing_date.isnot(None),
                    Batch.expiry_date.isnot(None),
                    Batch.expiry_date < Batch.manufacturing_date,
                )
            ).scalar()
            or 0
        )
        if bad_dates:
            findings.append(
                IntegrityFinding(
                    check="batch_expiry_before_manufacturing",
                    severity=SEV_ERROR,
                    message="batches whose expiry_date precedes manufacturing_date",
                    count=bad_dates,
                )
            )
        return findings

    def check_alert_lifecycle(self) -> list[IntegrityFinding]:
        findings: list[IntegrityFinding] = []
        from ..models import VALID_ALERT_TYPES, VALID_SEVERITIES, VALID_STATUSES

        invalid = int(
            self.session.execute(
                select(func.count())
                .select_from(Alert)
                .where(
                    Alert.alert_type.notin_(VALID_ALERT_TYPES)
                    | Alert.severity.notin_(VALID_SEVERITIES)
                    | Alert.status.notin_(VALID_STATUSES)
                )
            ).scalar()
            or 0
        )
        if invalid:
            findings.append(
                IntegrityFinding(
                    check="alert_invalid_values",
                    severity=SEV_ERROR,
                    message="alerts with an invalid type/severity/status",
                    count=invalid,
                )
            )

        missing_ts = int(
            self.session.execute(
                select(func.count())
                .select_from(Alert)
                .where(
                    (Alert.status == "RESOLVED") & Alert.resolved_at.is_(None)
                    | (Alert.status == "DISMISSED") & Alert.dismissed_at.is_(None)
                    | (Alert.status == "ACKNOWLEDGED") & Alert.acknowledged_at.is_(None)
                )
            ).scalar()
            or 0
        )
        if missing_ts:
            findings.append(
                IntegrityFinding(
                    check="alert_missing_timestamp",
                    severity=SEV_WARNING,
                    message="alerts whose lifecycle timestamp does not match their status",
                    count=missing_ts,
                )
            )
        return findings

    def check_camera_config(self) -> list[IntegrityFinding]:
        invalid = int(
            self.session.execute(
                select(func.count())
                .select_from(Camera)
                .where(Camera.camera_type.notin_(_VALID_CAMERA_TYPES))
            ).scalar()
            or 0
        )
        if not invalid:
            return []
        return [
            IntegrityFinding(
                check="camera_invalid_type",
                severity=SEV_ERROR,
                message=f"cameras with camera_type outside {sorted(_VALID_CAMERA_TYPES)}",
                count=invalid,
            )
        ]

    def check_demo_isolation(self) -> list[IntegrityFinding]:
        findings: list[IntegrityFinding] = []
        non_demo = int(
            self.session.execute(
                select(func.count())
                .select_from(DemoScenarioState)
                .join(Store, DemoScenarioState.store_id == Store.id)
                .where(Store.is_demo.is_(False))
            ).scalar()
            or 0
        )
        if non_demo:
            findings.append(
                IntegrityFinding(
                    check="demo_isolation",
                    severity=SEV_ERROR,
                    message="demo scenario state attached to a non-demo store",
                    count=non_demo,
                )
            )
        return findings

    def check_privacy(self) -> list[IntegrityFinding]:
        tables = ", ".join(f"'{t}'" for t in _PRIVACY_TABLES)
        sql = text(
            "SELECT table_name, column_name FROM information_schema.columns "
            f"WHERE table_schema = 'public' AND table_name IN ({tables}) "  # noqa: S608 - hardcoded
            f"AND column_name ~* '{_PRIVACY_COLUMN_RE}'"
        )
        rows = self.session.execute(sql).all()
        if not rows:
            return []
        return [
            IntegrityFinding(
                check="privacy_media_columns",
                severity=SEV_ERROR,
                message="privacy-sensitive tables contain image/biometric-like columns",
                count=len(rows),
                sample=[{"table": t, "column": c} for t, c in rows[:10]],
            )
        ]

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _stats(self) -> dict:
        def count(model) -> int:
            return int(self.session.execute(select(func.count()).select_from(model)).scalar() or 0)

        return {
            "stores": count(Store),
            "cameras": count(Camera),
            "inventory": count(Inventory),
            "batches": count(Batch),
            "alerts": count(Alert),
            "insights": count(Insight),
        }

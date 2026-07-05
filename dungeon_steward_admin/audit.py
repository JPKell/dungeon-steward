from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from bot.models import AdminAuditLog
from dungeon_steward_admin.context import AdminContext

SENSITIVE_FIELD_PARTS = ("password", "token", "secret", "credential", "api_key")


@dataclass(frozen=True)
class AuditRecord:
    action_name: str
    target_domain: str
    target_table: str | None = None
    target_user_id: int | None = None
    target_record_id: str | None = None
    previous_values: dict[str, Any] | None = None
    new_values: dict[str, Any] | None = None
    quantity_changed: int | None = None
    reason: str | None = None
    result: str = "success"
    error_info: str | None = None


def write_audit(session: Session, context: AdminContext, record: AuditRecord) -> AdminAuditLog:
    row = AdminAuditLog(
        administrator_identity=context.admin_identity,
        administrator_role=context.admin_role,
        environment=context.environment,
        action_name=record.action_name,
        target_domain=record.target_domain,
        target_table=record.target_table,
        target_user_id=record.target_user_id,
        target_record_id=record.target_record_id,
        previous_values=_json_or_none(redact_mapping(record.previous_values)),
        new_values=_json_or_none(redact_mapping(record.new_values)),
        quantity_changed=record.quantity_changed,
        reason=record.reason,
        result=record.result,
        error_info=record.error_info,
        session_id=context.session_id,
    )
    session.add(row)
    session.flush()
    return row


def recent_audit_entries(
    session: Session,
    *,
    limit: int = 50,
    administrator: str | None = None,
    target_user_id: int | None = None,
    action_name: str | None = None,
    success: bool | None = None,
) -> list[AdminAuditLog]:
    statement = select(AdminAuditLog)
    if administrator:
        statement = statement.where(AdminAuditLog.administrator_identity == administrator)
    if target_user_id is not None:
        statement = statement.where(AdminAuditLog.target_user_id == target_user_id)
    if action_name:
        statement = statement.where(AdminAuditLog.action_name == action_name)
    if success is not None:
        statement = statement.where(AdminAuditLog.result == ("success" if success else "error"))
    return list(session.scalars(statement.order_by(AdminAuditLog.created_at.desc()).limit(max(1, limit))).all())


def redact_mapping(values: dict[str, Any] | None) -> dict[str, Any] | None:
    if values is None:
        return None
    redacted: dict[str, Any] = {}
    for key, value in values.items():
        if any(part in key.lower() for part in SENSITIVE_FIELD_PARTS):
            redacted[key] = "<redacted>"
        elif isinstance(value, dict):
            redacted[key] = redact_mapping(value)
        else:
            redacted[key] = value
    return redacted


def _json_or_none(values: dict[str, Any] | None) -> str | None:
    if values is None:
        return None
    return json.dumps(values, sort_keys=True, default=str)

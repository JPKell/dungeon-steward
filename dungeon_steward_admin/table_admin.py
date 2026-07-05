from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Enum, Float, Integer, Numeric, String, Text, func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from dungeon_steward_admin.audit import AuditRecord, write_audit
from dungeon_steward_admin.context import AdminContext
from dungeon_steward_admin.permissions import require_permission
from dungeon_steward_admin.registry import DEFAULT_REGISTRY, AdminRegistry, AdminTableInfo


class AdminTableError(Exception):
    pass


class ReadOnlyTableError(AdminTableError):
    pass


class ProtectedFieldError(AdminTableError):
    pass


class ConcurrentModificationError(AdminTableError):
    pass


class RecordNotFoundError(AdminTableError):
    pass


class ValidationError(AdminTableError):
    pass


class TableAdminService:
    def __init__(self, *, registry: AdminRegistry | None = None) -> None:
        self.registry = registry or DEFAULT_REGISTRY

    def list_tables(self, session: Session, *, include_counts: bool = True) -> list[AdminTableInfo]:
        tables: list[AdminTableInfo] = []
        for model in self.registry.visible_models():
            mapper = inspect(model)
            config = self.registry.config_for_model(model)
            count = None
            if include_counts:
                count = session.scalar(select(func.count()).select_from(model))
            tables.append(
                AdminTableInfo(
                    table_name=mapper.local_table.name,
                    model_name=model.__name__,
                    primary_key=tuple(column.key for column in mapper.primary_key),
                    record_count=int(count) if count is not None else None,
                    read_only=config.read_only,
                    custom_configured=self.registry.custom_configured(model),
                )
            )
        return tables

    def list_records(
        self,
        session: Session,
        table_name: str,
        *,
        search: str | None = None,
        page: int = 1,
        page_size: int = 50,
        sort_field: str | None = None,
        descending: bool = False,
    ) -> list[dict[str, Any]]:
        model = self.registry.table_model(table_name)
        config = self.registry.config_for_model(model)
        statement = select(model)
        if search:
            statement = statement.where(_search_condition(model, config.searchable_fields, search))
        sort_field, descending = _resolve_sort(model, config.default_sort, sort_field, descending)
        if sort_field:
            column = getattr(model, sort_field)
            statement = statement.order_by(column.desc() if descending else column.asc())
        statement = statement.offset(max(0, page - 1) * page_size).limit(max(1, min(page_size, 200)))
        return [self.serialize_record(row) for row in session.scalars(statement).all()]

    def get_record(self, session: Session, table_name: str, record_id: str | int) -> Any:
        model = self.registry.table_model(table_name)
        mapper = inspect(model)
        if len(mapper.primary_key) != 1:
            raise ValidationError("Composite primary-key lookup requires a custom action.")
        pk_column = mapper.primary_key[0]
        value = _parse_value(pk_column, record_id)
        row = session.get(model, value)
        if row is None:
            raise RecordNotFoundError(f"No {table_name} record with {pk_column.key}={record_id}")
        return row

    def foreign_key_options(
        self,
        session: Session,
        table_name: str,
        field: str,
        *,
        search: str | None = None,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        model = self.registry.table_model(table_name)
        columns = {column.key: column for column in inspect(model).columns}
        if field not in columns:
            raise ValidationError(f"Unknown field: {field}")
        foreign_keys = list(columns[field].foreign_keys)
        if not foreign_keys:
            raise ValidationError(f"{field} is not a foreign key")
        target_table = foreign_keys[0].column.table.name
        return self.list_records(session, target_table, search=search, page_size=min(limit, 25))

    def create_record(
        self,
        session: Session,
        context: AdminContext,
        table_name: str,
        values: dict[str, Any],
        *,
        reason: str | None = None,
    ) -> Any:
        model = self.registry.table_model(table_name)
        config = self.registry.config_for_model(model)
        self._ensure_write_allowed(context, config, permission=config.permission)
        instance = model()
        parsed = self._parse_input_values(model, values, create=True)
        for field, value in parsed.items():
            setattr(instance, field, value)
        session.add(instance)
        self._flush_or_validation_error(session)
        write_audit(
            session,
            context,
            AuditRecord(
                action_name="generic.create",
                target_domain="database",
                target_table=table_name,
                target_record_id=_record_identity(instance),
                new_values=self.serialize_record(instance),
                reason=reason,
            ),
        )
        return instance

    def update_record(
        self,
        session: Session,
        context: AdminContext,
        table_name: str,
        record_id: str | int,
        values: dict[str, Any],
        *,
        expected_updated_at: str | None = None,
        reason: str | None = None,
    ) -> Any:
        model = self.registry.table_model(table_name)
        config = self.registry.config_for_model(model)
        self._ensure_write_allowed(context, config, permission=config.permission)
        row = self.get_record(session, table_name, record_id)
        if expected_updated_at is not None and hasattr(row, "updated_at"):
            current = row.updated_at
            if current is not None and str(current) != expected_updated_at:
                raise ConcurrentModificationError("Record changed since it was loaded.")
        previous = self.serialize_record(row)
        parsed = self._parse_input_values(model, values, create=False)
        for field, value in parsed.items():
            setattr(row, field, value)
        self._flush_or_validation_error(session)
        write_audit(
            session,
            context,
            AuditRecord(
                action_name="generic.update",
                target_domain="database",
                target_table=table_name,
                target_record_id=_record_identity(row),
                previous_values=previous,
                new_values=self.serialize_record(row),
                reason=reason,
            ),
        )
        return row

    def delete_record(
        self,
        session: Session,
        context: AdminContext,
        table_name: str,
        record_id: str | int,
        *,
        reason: str | None = None,
        force_delete: bool = False,
    ) -> None:
        model = self.registry.table_model(table_name)
        config = self.registry.config_for_model(model)
        self._ensure_write_allowed(context, config, permission=config.delete_permission)
        row = self.get_record(session, table_name, record_id)
        previous = self.serialize_record(row)
        if hasattr(row, "is_active") and not force_delete:
            row.is_active = False
            action = "generic.soft_delete"
        else:
            session.delete(row)
            action = "generic.delete"
        self._flush_or_validation_error(session)
        write_audit(
            session,
            context,
            AuditRecord(
                action_name=action,
                target_domain="database",
                target_table=table_name,
                target_record_id=str(record_id),
                previous_values=previous,
                reason=reason,
            ),
        )

    def serialize_record(self, row: Any) -> dict[str, Any]:
        model = type(row)
        config = self.registry.config_for_model(model)
        values: dict[str, Any] = {}
        for column in inspect(model).columns:
            if column.key in config.hidden_fields:
                continue
            values[column.key] = _serialize_value(getattr(row, column.key))
        return values

    def _parse_input_values(self, model: type[Any], values: dict[str, Any], *, create: bool) -> dict[str, Any]:
        config = self.registry.config_for_model(model)
        columns = {column.key: column for column in inspect(model).columns}
        parsed: dict[str, Any] = {}
        for field, raw in values.items():
            if field not in columns:
                raise ValidationError(f"Unknown field: {field}")
            if field in config.hidden_fields or field in config.readonly_fields:
                raise ProtectedFieldError(f"{field} is protected")
            column = columns[field]
            if not create and column.primary_key:
                raise ProtectedFieldError(f"{field} is a primary key")
            value = _parse_value(column, raw)
            validator = config.validators.get(field)
            if validator is not None:
                validator(value)
            parsed[field] = value
        return parsed

    def _ensure_write_allowed(self, context: AdminContext, config, *, permission: str) -> None:
        if config.read_only:
            raise ReadOnlyTableError("This table is configured read-only.")
        require_permission(context.config.admin, permission, read_only=context.read_only)

    def _flush_or_validation_error(self, session: Session) -> None:
        try:
            session.flush()
        except IntegrityError as error:
            raise ValidationError(str(error.orig)) from error


def _search_condition(model: type[Any], fields: tuple[str, ...], query: str):
    conditions = []
    for field in fields:
        if not hasattr(model, field):
            continue
        column = getattr(model, field)
        raw_column = inspect(model).columns[field]
        if isinstance(raw_column.type, String | Text):
            conditions.append(column.ilike(f"%{query}%"))
        elif query.isdigit() and isinstance(raw_column.type, Integer | BigInteger):
            conditions.append(column == int(query))
    if not conditions:
        return False
    first, *rest = conditions
    for condition in rest:
        first = first | condition
    return first


def _resolve_sort(
    model: type[Any],
    default_sort: tuple[str, bool] | None,
    sort_field: str | None,
    descending: bool,
) -> tuple[str | None, bool]:
    if sort_field is not None:
        if sort_field not in inspect(model).columns:
            raise ValidationError(f"Unknown sort field: {sort_field}")
        return sort_field, descending
    if default_sort is not None:
        return default_sort
    primary_key = inspect(model).primary_key
    return (primary_key[0].key, False) if primary_key else (None, False)


def _parse_value(column, raw: Any) -> Any:
    if raw == "" and column.nullable:
        return None
    if raw is None:
        if column.nullable:
            return None
        raise ValidationError(f"{column.key} cannot be null")
    if isinstance(column.type, Boolean):
        if isinstance(raw, bool):
            return raw
        value = str(raw).strip().lower()
        if value in {"true", "t", "1", "yes", "y"}:
            return True
        if value in {"false", "f", "0", "no", "n"}:
            return False
        raise ValidationError(f"{column.key} must be true or false")
    if isinstance(column.type, Integer | BigInteger):
        return int(raw)
    if isinstance(column.type, Float):
        return float(raw)
    if isinstance(column.type, Numeric):
        return Decimal(str(raw))
    if isinstance(column.type, Enum):
        value = str(raw)
        if value not in column.type.enums:
            raise ValidationError(f"{column.key} must be one of: {', '.join(column.type.enums)}")
        return value
    if isinstance(column.type, DateTime):
        if isinstance(raw, datetime):
            return raw
        return datetime.fromisoformat(str(raw))
    if isinstance(column.type, Date):
        if isinstance(raw, date):
            return raw
        return date.fromisoformat(str(raw))
    if _is_json_type(column.type):
        if isinstance(raw, str):
            return json.loads(raw)
        return raw
    return str(raw)


def _is_json_type(column_type: Any) -> bool:
    return column_type.__class__.__name__.lower() == "json"


def _serialize_value(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _record_identity(row: Any) -> str:
    mapper = inspect(type(row))
    parts = [str(getattr(row, column.key)) for column in mapper.primary_key]
    return ":".join(parts)

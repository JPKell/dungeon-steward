from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import JSON, Enum, ForeignKey, Integer, String, select
from sqlalchemy.orm import Mapped, mapped_column

from bot.config import Settings
from bot.database.base import Base, TimestampMixin
from bot.models import AdminAuditLog, PotionActivation, PotionInventoryStack
from dungeon_steward_admin.actions import execute_action
from dungeon_steward_admin.config import AdminRuntimeConfig, ProductionConfirmationError, load_runtime_config
from dungeon_steward_admin.context import AdminContext
from dungeon_steward_admin.operations import AdminGameService, InvalidItemError, InvalidQuantityError
from dungeon_steward_admin.permissions import AdminPrincipal, PermissionError
from dungeon_steward_admin.table_admin import (
    ConcurrentModificationError,
    ProtectedFieldError,
    ReadOnlyTableError,
    TableAdminService,
    ValidationError,
)
from tests.conftest import make_player


class AdminDynamicRecord(TimestampMixin, Base):
    __tablename__ = "admin_dynamic_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(Enum("open", "closed", name="admin_dynamic_status"), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=0)


def admin_context(*, role: str = "super_admin", read_only: bool = False, environment: str = "development") -> AdminContext:
    config = AdminRuntimeConfig(
        environment=environment,
        database_url="sqlite:///:memory:",
        read_only=read_only,
        admin=AdminPrincipal("tester", role),
        page_size=25,
        statement_timeout_ms=None,
        production_confirmed=environment != "production" or read_only,
    )
    return AdminContext(config=config, session_id="test-session")


def test_runtime_config_requires_configured_admin_and_production_confirmation(monkeypatch):
    settings = Settings(
        discord_bot_token="",
        discord_application_id=None,
        discord_test_guild_id=None,
        discord_staff_role_id=None,
        discord_asset_channel_id=None,
        database_url="sqlite:///:memory:",
        log_level="INFO",
        environment="production",
    )
    monkeypatch.setenv("DUNGEON_ADMIN_IDENTITIES", "alice:super_admin,bob:read_only")

    with pytest.raises(PermissionError):
        load_runtime_config(admin_identity="mallory", settings=settings)
    with pytest.raises(ProductionConfirmationError):
        load_runtime_config(admin_identity="alice", settings=settings)

    config = load_runtime_config(admin_identity="bob", read_only=True, settings=settings)
    assert config.is_production
    assert config.read_only
    assert config.admin.role == "read_only"


def test_user_search_supports_ids_names_and_pagination(db, now):
    player_a = make_player(db, now=now, user_id=111, guild_id=10)
    player_a.display_name = "Scout Alpha"
    player_b = make_player(db, now=now, user_id=222, guild_id=10)
    player_b.display_name = "Scout Beta"
    db.flush()
    service = AdminGameService()

    assert service.search_users(db, str(player_a.id))[0].id == player_a.id
    assert service.search_users(db, "222")[0].discord_user_id == 222
    assert [row.display_name for row in service.search_users(db, "Scout", limit=1)] == ["Scout Alpha"]
    assert [row.display_name for row in service.search_users(db, "Scout", limit=1, offset=1)] == ["Scout Beta"]


def test_potion_quantity_adjustments_audit_and_prevent_negative(db, now):
    player = make_player(db, now=now)
    service = AdminGameService()
    context = admin_context(role="game_support")

    stack = service.set_potion_quantity(
        db,
        context,
        player_id=player.id,
        item_key="potion_xp_01",
        quantity=3,
        reason="support grant",
    )
    assert stack.quantity == 3

    stack = service.adjust_potion_quantity(
        db,
        context,
        player_id=player.id,
        item_key="potion_xp_01",
        delta=-2,
        reason="support correction",
    )
    assert stack.quantity == 1
    with pytest.raises(InvalidQuantityError):
        service.adjust_potion_quantity(
            db,
            context,
            player_id=player.id,
            item_key="potion_xp_01",
            delta=-2,
            reason="too much",
        )

    assert db.scalar(select(PotionInventoryStack.quantity)) == 1
    assert db.scalars(select(AdminAuditLog).order_by(AdminAuditLog.id)).all()[-1].action_name == "inventory.set_potion_quantity"


def test_read_only_and_permission_denials(db, now):
    player = make_player(db, now=now)
    service = AdminGameService()

    with pytest.raises(PermissionError):
        service.set_potion_quantity(
            db,
            admin_context(role="read_only"),
            player_id=player.id,
            item_key="potion_xp_01",
            quantity=1,
            reason="nope",
        )
    with pytest.raises(PermissionError):
        service.set_potion_quantity(
            db,
            admin_context(role="game_support", read_only=True),
            player_id=player.id,
            item_key="potion_xp_01",
            quantity=1,
            reason="read only",
        )


def test_equipment_equip_unequip_and_equipped_removal_confirmation(db, now):
    player = make_player(db, now=now)
    service = AdminGameService()
    item = next(item for item in service.equipment.items if item.slot == "weapon")
    context = admin_context(role="game_support")

    service.equip_equipment(db, context, player_id=player.id, equipment_key=item.key, reason="support equip")
    assert player.weapon == item.key

    with pytest.raises(InvalidItemError):
        service.remove_equipped_item(db, context, player_id=player.id, equipment_key=item.key, reason="needs confirm")

    service.remove_equipped_item(
        db,
        context,
        player_id=player.id,
        equipment_key=item.key,
        reason="confirmed removal",
        confirmed=True,
    )
    assert player.weapon is None

    service.equip_equipment(db, context, player_id=player.id, equipment_key=item.key, reason="equip again")
    service.unequip_slot(db, context, player_id=player.id, slot="weapon", reason="support unequip")
    assert player.weapon is None


def test_custom_action_grant_gold_creates_audit(db, now):
    player = make_player(db, now=now)
    result = execute_action(
        admin_context(role="game_support"),
        db,
        "Grant Gold",
        {"player_id": player.id, "amount": 25, "reason": "test grant"},
        confirmed=True,
    )

    assert result.success
    assert player.gold == 25
    audit = db.scalar(select(AdminAuditLog).where(AdminAuditLog.action_name == "currency.adjust_gold"))
    assert audit is not None
    assert audit.target_user_id == player.id


def test_generic_table_crud_json_enum_fk_and_protected_fields(db, now):
    player = make_player(db, now=now)
    tables = TableAdminService()
    context = admin_context(role="database_admin")

    table_names = {table.table_name for table in tables.list_tables(db)}
    assert "admin_dynamic_records" in table_names

    row = tables.create_record(
        db,
        context,
        "admin_dynamic_records",
        {"player_id": str(player.id), "name": "Repair", "status": "open", "payload": '{"valid": true}', "count": "4"},
        reason="create test row",
    )
    assert row.payload == {"valid": True}
    assert tables.list_records(db, "admin_dynamic_records", search="Repair")[0]["name"] == "Repair"

    with pytest.raises(ValidationError):
        tables.update_record(db, context, "admin_dynamic_records", row.id, {"status": "invalid"}, reason="bad enum")
    with pytest.raises(ProtectedFieldError):
        tables.update_record(db, context, "admin_dynamic_records", row.id, {"id": "999"}, reason="bad pk")
    with pytest.raises(ConcurrentModificationError):
        tables.update_record(
            db,
            context,
            "admin_dynamic_records",
            row.id,
            {"name": "Other"},
            expected_updated_at="not-current",
            reason="stale",
        )

    options = tables.foreign_key_options(db, "admin_dynamic_records", "player_id", search=str(player.id))
    assert options[0]["id"] == player.id

    tables.update_record(db, context, "admin_dynamic_records", row.id, {"name": "Fixed"}, reason="rename")
    assert row.name == "Fixed"
    tables.delete_record(db, context, "admin_dynamic_records", row.id, reason="cleanup")
    assert db.get(AdminDynamicRecord, row.id) is None


def test_generic_readonly_table_and_soft_delete(db, now):
    player = make_player(db, now=now)
    tables = TableAdminService()

    with pytest.raises(ReadOnlyTableError):
        tables.update_record(
            db,
            admin_context(role="super_admin"),
            "admin_audit_log",
            1,
            {"result": "changed"},
            reason="readonly",
        )

    tables.delete_record(db, admin_context(role="super_admin"), "players", player.id, reason="deactivate")
    assert player.is_active is False


def test_end_potion_effect_truncates_activation(db, now):
    player = make_player(db, now=now)
    activation = PotionActivation(
        player_id=player.id,
        item_key="potion_xp_01",
        effect_group="xp",
        tier=1,
        activated_at=now,
        original_expires_at=now + timedelta(hours=1),
        effective_ends_at=now + timedelta(hours=1),
        idempotency_token="manual-test",
    )
    db.add(activation)
    db.flush()

    AdminGameService().end_potion_effect(
        db,
        admin_context(role="game_support"),
        activation_id=activation.id,
        reason="support end",
    )

    assert activation.effective_ends_at <= datetime.now(UTC)

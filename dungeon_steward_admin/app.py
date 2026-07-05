from __future__ import annotations

import curses
import json
import logging
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from bot.models import Player
from dungeon_steward_admin.actions import execute_action, registered_actions
from dungeon_steward_admin.audit import recent_audit_entries
from dungeon_steward_admin.config import AdminRuntimeConfig
from dungeon_steward_admin.context import AdminContext
from dungeon_steward_admin.operations import AdminGameService
from dungeon_steward_admin.permissions import PermissionError as AdminPermissionError
from dungeon_steward_admin.table_admin import AdminTableError, TableAdminService

log = logging.getLogger(__name__)

FOOTER = "Arrows navigate | Enter select | / search | r refresh | q/Esc back | ? help"
MIN_HEIGHT = 20
MIN_WIDTH = 78


class AdminConsoleApp:
    def __init__(
        self,
        *,
        config: AdminRuntimeConfig,
        session_factory: sessionmaker[Session],
        initial_user: str | None = None,
    ) -> None:
        self.config = config
        self.context = AdminContext(config)
        self.session_factory = session_factory
        self.game = AdminGameService()
        self.tables = TableAdminService()
        self.initial_user = initial_user
        self.selected_user_id: int | None = None
        self.recent_users: list[int] = []

    def run(self) -> None:
        curses.wrapper(self._run)

    def _run(self, stdscr) -> None:
        self.stdscr = stdscr
        curses.noecho()
        curses.cbreak()
        stdscr.keypad(True)
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        if curses.has_colors():
            curses.start_color()
            curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLUE)
            curses.init_pair(2, curses.COLOR_WHITE, curses.COLOR_RED)
            curses.init_pair(3, curses.COLOR_BLACK, curses.COLOR_WHITE)
        if self.initial_user:
            self._select_user_by_query(self.initial_user)
        self._main_menu()

    def _main_menu(self) -> None:
        while True:
            choice = self._menu(
                "Dungeon Steward Administration",
                [
                    "User Administration",
                    "Inventory and Equipment",
                    "Database Tables",
                    "Custom Administrative Actions",
                    "Audit History",
                    "System Information",
                    "Exit",
                ],
            )
            if choice is None or choice == 6:
                return
            handlers = [
                self._user_search_screen,
                self._inventory_equipment_entry,
                self._table_browser,
                self._custom_actions,
                self._audit_history,
                self._system_info,
            ]
            self._guarded(handlers[choice])

    def _user_search_screen(self) -> None:
        query = self._prompt("Search users by internal ID, Discord ID, guild ID, or display name")
        self._select_user_by_query(query)

    def _select_user_by_query(self, query: str) -> None:
        with self.session_factory() as session:
            rows = self.game.search_users(session, query, limit=self.config.page_size)
        if not rows:
            self._message("No matching users found.")
            return
        labels = [
            (
                f"{row.id} | guild {row.guild_id} | discord {row.discord_user_id} | "
                f"{row.display_name} | C{row.combat_level} E{row.explore_level} | gold {row.gold}"
            )
            for row in rows
        ]
        selected = self._menu("Select User", labels)
        if selected is None:
            return
        self.selected_user_id = rows[selected].id
        self._remember_user(self.selected_user_id)
        self._user_detail()

    def _user_detail(self) -> None:
        if self.selected_user_id is None:
            self._message("No user selected.")
            return
        while True:
            with self.session_factory() as session:
                summary = self.game.user_summary(session, self.selected_user_id)
            lines = [
                f"Player ID: {summary.player_id}",
                f"Guild ID: {summary.guild_id}",
                f"Discord ID: {summary.discord_user_id}",
                f"Display Name: {summary.display_name}",
                f"Active: {summary.is_active}",
                f"Created: {summary.created_at}",
                f"Last Activity: {summary.last_activity}",
                f"Explore Level: {summary.explore_level}",
                f"Combat Level: {summary.combat_level}",
                f"HP: {summary.hp}",
                f"Gold: {summary.gold}",
                f"Defending: {summary.is_defending}",
                f"Active Potions: {', '.join(summary.active_potions) if summary.active_potions else 'none'}",
                f"Potion Inventory Quantity: {summary.inventory_count}",
                f"Equipped Slots: {summary.equipment_count}",
                "",
            ]
            choice = self._menu(
                "User Summary",
                [
                    *lines,
                    "Manage Potion Inventory",
                    "Manage Equipment",
                    "Run User Action",
                    "Back",
                ],
                selectable_start=len(lines),
            )
            if choice is None or choice == len(lines) + 3:
                return
            if choice == len(lines):
                self._inventory_screen()
            elif choice == len(lines) + 1:
                self._equipment_screen()
            elif choice == len(lines) + 2:
                self._custom_actions(default_values={"player_id": self.selected_user_id})

    def _inventory_equipment_entry(self) -> None:
        if self.selected_user_id is None:
            query = self._prompt("User lookup")
            self._select_user_by_query(query)
            return
        self._user_detail()

    def _inventory_screen(self) -> None:
        if self.selected_user_id is None:
            return
        while True:
            with self.session_factory() as session:
                summary = self.game.user_summary(session, self.selected_user_id)
                actual_player = session.get(Player, self.selected_user_id)
                entries = self.game.potions.inventory_entries(session, actual_player) if actual_player else ()
                active = self.game.potions.active_effects_at(session, actual_player) if actual_player else ()
            lines = [
                f"User: {summary.display_name} ({summary.player_id})",
                "Active potion effects:",
                *[
                    f"  {effect.activation.id}: {effect.item.name} until {effect.activation.effective_ends_at}"
                    for effect in active
                ],
                "Inventory:",
                *[f"  {entry.item.key} | {entry.item.name} | x{entry.stack.quantity}" for entry in entries],
                "",
            ]
            choice = self._menu(
                "Potion Inventory",
                [*lines, "Set Potion Quantity", "Adjust Potion Quantity", "End Active Potion Effect", "Back"],
                selectable_start=len(lines),
            )
            if choice is None or choice == len(lines) + 3:
                return
            if choice == len(lines):
                self._set_potion_quantity()
            elif choice == len(lines) + 1:
                self._adjust_potion_quantity()
            elif choice == len(lines) + 2:
                self._end_potion_effect()

    def _set_potion_quantity(self) -> None:
        item_key = self._prompt("Potion item key")
        quantity = int(self._prompt("Exact quantity", default="1"))
        reason = self._prompt("Reason")
        if not self._confirm(f"Set {item_key} to {quantity}?", phrase=None):
            return
        with self.session_factory() as session:
            self.game.set_potion_quantity(
                session,
                self.context,
                player_id=self.selected_user_id or 0,
                item_key=item_key,
                quantity=quantity,
                reason=reason,
            )
            session.commit()
        self._message("Potion quantity updated.")

    def _adjust_potion_quantity(self) -> None:
        item_key = self._prompt("Potion item key")
        delta = int(self._prompt("Quantity change, e.g. 3 or -2", default="1"))
        reason = self._prompt("Reason")
        if not self._confirm(f"Apply {delta:+d} to {item_key}?", phrase=None):
            return
        with self.session_factory() as session:
            self.game.adjust_potion_quantity(
                session,
                self.context,
                player_id=self.selected_user_id or 0,
                item_key=item_key,
                delta=delta,
                reason=reason,
            )
            session.commit()
        self._message("Potion quantity adjusted.")

    def _end_potion_effect(self) -> None:
        activation_id = int(self._prompt("Potion activation ID"))
        reason = self._prompt("Reason")
        if not self._confirm(f"End potion activation {activation_id}?", phrase="END"):
            return
        with self.session_factory() as session:
            self.game.end_potion_effect(session, self.context, activation_id=activation_id, reason=reason)
            session.commit()
        self._message("Potion effect ended.")

    def _equipment_screen(self) -> None:
        if self.selected_user_id is None:
            return
        while True:
            with self.session_factory() as session:
                player = session.get(Player, self.selected_user_id)
                lines = [f"{slot}: {getattr(player, slot)}" for slot in self.game.equipment.get_player_equipment(player)]
            choice = self._menu("Equipment", [*lines, "", "Equip Equipment", "Unequip Slot", "Back"], selectable_start=len(lines) + 1)
            if choice is None or choice == len(lines) + 3:
                return
            if choice == len(lines) + 1:
                key = self._prompt("Equipment key")
                reason = self._prompt("Reason")
                if self._confirm(f"Equip {key}?", phrase=None):
                    with self.session_factory() as session:
                        self.game.equip_equipment(
                            session,
                            self.context,
                            player_id=self.selected_user_id,
                            equipment_key=key,
                            reason=reason,
                        )
                        session.commit()
                    self._message("Equipment equipped.")
            elif choice == len(lines) + 2:
                slot = self._prompt("Slot")
                reason = self._prompt("Reason")
                if self._confirm(f"Unequip {slot}?", phrase=None):
                    with self.session_factory() as session:
                        self.game.unequip_slot(session, self.context, player_id=self.selected_user_id, slot=slot, reason=reason)
                        session.commit()
                    self._message("Slot unequipped.")

    def _table_browser(self) -> None:
        with self.session_factory() as session:
            tables = self.tables.list_tables(session, include_counts=True)
        labels = [
            (
                f"{info.table_name} | {info.model_name} | pk={','.join(info.primary_key)} | "
                f"rows={info.record_count} | {'read-only' if info.read_only else 'editable'}"
            )
            for info in tables
        ]
        selected = self._menu("Database Tables", labels)
        if selected is None:
            return
        self._record_list(tables[selected].table_name)

    def _record_list(self, table_name: str) -> None:
        search = ""
        page = 1
        while True:
            with self.session_factory() as session:
                rows = self.tables.list_records(session, table_name, search=search, page=page, page_size=self.config.page_size)
            labels = [json.dumps(row, default=str)[:240] for row in rows]
            choice = self._menu(
                f"{table_name} page {page} search={search or '<none>'}",
                [*labels, "", "Search/Filter", "Create From JSON", "Edit Field", "Delete Record", "Next Page", "Previous Page", "Back"],
                selectable_start=len(labels) + 1,
            )
            if choice is None or choice == len(labels) + 7:
                return
            if choice == len(labels) + 1:
                search = self._prompt("Search")
                page = 1
            elif choice == len(labels) + 2:
                self._create_record(table_name)
            elif choice == len(labels) + 3:
                self._edit_record(table_name)
            elif choice == len(labels) + 4:
                self._delete_record(table_name)
            elif choice == len(labels) + 5:
                page += 1
            elif choice == len(labels) + 6 and page > 1:
                page -= 1

    def _create_record(self, table_name: str) -> None:
        values = json.loads(self._prompt("JSON object of fields"))
        reason = self._prompt("Reason")
        if self._confirm(f"Create record in {table_name}?", phrase=None):
            with self.session_factory() as session:
                self.tables.create_record(session, self.context, table_name, values, reason=reason)
                session.commit()
            self._message("Record created.")

    def _edit_record(self, table_name: str) -> None:
        record_id = self._prompt("Record primary key")
        field = self._prompt("Field")
        value = self._prompt("New value")
        reason = self._prompt("Reason")
        if self._confirm(f"Update {table_name}:{record_id} {field}?", phrase=None):
            with self.session_factory() as session:
                self.tables.update_record(session, self.context, table_name, record_id, {field: value}, reason=reason)
                session.commit()
            self._message("Record updated.")

    def _delete_record(self, table_name: str) -> None:
        record_id = self._prompt("Record primary key")
        reason = self._prompt("Reason")
        if self._confirm(f"Delete {table_name}:{record_id}?", phrase="DELETE"):
            with self.session_factory() as session:
                self.tables.delete_record(session, self.context, table_name, record_id, reason=reason)
                session.commit()
            self._message("Record deleted or soft-deleted.")

    def _custom_actions(self, default_values: dict[str, Any] | None = None) -> None:
        actions = registered_actions()
        selected = self._menu("Custom Administrative Actions", [f"{action.name} | {action.target}" for action in actions])
        if selected is None:
            return
        action = actions[selected]
        values = default_values or {}
        raw = self._prompt("JSON arguments", default=json.dumps(values))
        values = json.loads(raw or "{}")
        confirmed = True
        if action.requires_confirmation:
            confirmed = self._confirm(f"Run {action.name}?", phrase=None)
        if not confirmed:
            return
        with self.session_factory() as session:
            result = execute_action(self.context, session, action.name, values, confirmed=True)
            if result.success:
                session.commit()
            else:
                session.rollback()
        self._message(result.message)

    def _audit_history(self) -> None:
        with self.session_factory() as session:
            entries = recent_audit_entries(session, limit=self.config.page_size)
        labels = [
            (
                f"{entry.created_at} | {entry.administrator_identity} | {entry.action_name} | "
                f"{entry.target_table or entry.target_domain} | user={entry.target_user_id} | {entry.result}"
            )
            for entry in entries
        ]
        self._menu("Recent Audit Entries", labels or ["No audit entries yet."])

    def _system_info(self) -> None:
        lines = [
            f"Environment: {self.config.environment.upper()}",
            f"Read-only: {self.config.read_only}",
            f"Admin: {self.config.admin.identity}",
            f"Role: {self.config.admin.role}",
            f"Database: {self.config.masked_database_url}",
            f"Page size: {self.config.page_size}",
            f"Statement timeout: {self.config.statement_timeout_ms or 'database default'}",
            f"Session: {self.context.session_id}",
        ]
        self._menu("System Information", lines)

    def _guarded(self, handler) -> None:
        try:
            handler()
        except (AdminTableError, ValueError, KeyError, AdminPermissionError) as error:
            self._message(str(error))
        except Exception as error:
            log.exception("Admin console screen failed")
            self._message(f"Operation failed: {error.__class__.__name__}")

    def _remember_user(self, player_id: int) -> None:
        if player_id in self.recent_users:
            self.recent_users.remove(player_id)
        self.recent_users.insert(0, player_id)
        del self.recent_users[10:]

    def _draw_header(self, title: str) -> tuple[int, int]:
        self.stdscr.clear()
        height, width = self.stdscr.getmaxyx()
        if height < MIN_HEIGHT or width < MIN_WIDTH:
            self.stdscr.addstr(0, 0, f"Terminal too small. Minimum {MIN_WIDTH}x{MIN_HEIGHT}.")
            self.stdscr.refresh()
            return height, width
        env = self.config.environment.upper()
        color = curses.color_pair(2 if self.config.is_production else 1) if curses.has_colors() else 0
        banner = f" {env} {'READ ONLY' if self.config.read_only else 'WRITES ENABLED'} | {self.config.admin.identity} "
        self.stdscr.addstr(0, 0, banner[: width - 1].ljust(width - 1), color)
        self.stdscr.addstr(2, 2, title[: width - 4], curses.A_BOLD)
        self.stdscr.addstr(height - 1, 0, FOOTER[: width - 1].ljust(width - 1), curses.color_pair(3) if curses.has_colors() else 0)
        return height, width

    def _menu(self, title: str, options: list[str], *, selectable_start: int = 0) -> int | None:
        index = selectable_start
        top = 0
        while True:
            height, width = self._draw_header(title)
            visible_height = max(1, height - 6)
            index = min(max(selectable_start, index), max(selectable_start, len(options) - 1))
            if index < top:
                top = index
            if index >= top + visible_height:
                top = index - visible_height + 1
            for row, option_index in enumerate(range(top, min(len(options), top + visible_height)), start=4):
                option = options[option_index]
                attr = curses.A_REVERSE if option_index == index and option_index >= selectable_start else curses.A_NORMAL
                self.stdscr.addstr(row, 2, option[: width - 4].ljust(width - 4), attr)
            self.stdscr.refresh()
            key = self.stdscr.getch()
            if key in (ord("q"), 27):
                return None
            if key in (curses.KEY_DOWN, ord("j")):
                index = min(len(options) - 1, index + 1)
            elif key in (curses.KEY_UP, ord("k")):
                index = max(selectable_start, index - 1)
            elif key == curses.KEY_NPAGE:
                index = min(len(options) - 1, index + visible_height)
            elif key == curses.KEY_PPAGE:
                index = max(selectable_start, index - visible_height)
            elif key == curses.KEY_HOME:
                index = selectable_start
            elif key == curses.KEY_END:
                index = len(options) - 1
            elif key in (10, 13):
                return index if index >= selectable_start else None
            elif key == ord("?"):
                self._message(FOOTER)

    def _prompt(self, label: str, *, default: str = "") -> str:
        height, width = self._draw_header(label)
        curses.echo()
        try:
            prompt = f"{label}: "
            self.stdscr.addstr(5, 2, prompt[: width - 4])
            if default:
                self.stdscr.addstr(6, 2, f"default: {default}"[: width - 4])
            self.stdscr.refresh()
            raw = self.stdscr.getstr(7, 2, max(1, width - 4)).decode("utf-8").strip()
            return raw or default
        finally:
            curses.noecho()

    def _confirm(self, message: str, *, phrase: str | None) -> bool:
        if phrase:
            response = self._prompt(f"{message} Type {phrase} to confirm")
            return response == phrase
        response = self._prompt(f"{message} Type yes to confirm")
        return response.lower() == "yes"

    def _message(self, message: str) -> None:
        height, width = self._draw_header("Message")
        for row, line in enumerate(str(message).splitlines()[: height - 7], start=5):
            self.stdscr.addstr(row, 2, line[: width - 4])
        self.stdscr.addstr(height - 3, 2, "Press any key to continue."[: width - 4])
        self.stdscr.refresh()
        self.stdscr.getch()

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from dungeon_steward_admin.config import AdminRuntimeConfig


@dataclass(frozen=True)
class AdminContext:
    config: AdminRuntimeConfig
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    @property
    def admin_identity(self) -> str:
        return self.config.admin.identity

    @property
    def admin_role(self) -> str:
        return self.config.admin.role

    @property
    def environment(self) -> str:
        return self.config.environment

    @property
    def read_only(self) -> bool:
        return self.config.read_only

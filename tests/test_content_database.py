from __future__ import annotations

import json

from sqlalchemy import func, select

from bot.models import (
    ContentEncounter,
    ContentEncounterChoice,
    ContentPotionEffectTarget,
    ContentPotionItem,
    ContentPotionRarityBonus,
    ContentProgressionCurve,
    ContentProgressionDocument,
    Discovery,
)
from bot.services import location_service
from bot.services.content_database import CONTENT_DIR, CONTENT_FILENAMES, dump_content_to_files, load_content_from_files
from bot.services.content_runtime import refresh_runtime_content_from_database
from bot.services.encounter_service import EncounterService


def test_content_json_loads_to_database_and_dumps_round_trip(db, tmp_path):
    load_result = load_content_from_files(db, content_dir=CONTENT_DIR)

    assert load_result.rows["equipment.json"] >= 30
    assert load_result.rows["progression.json"] > 1
    assert load_result.rows["potion_items.json"] > 91
    assert db.get(ContentProgressionDocument, 1).schema_version == 2
    assert db.scalar(select(func.count()).select_from(ContentProgressionCurve)) == 9
    assert db.scalar(select(ContentPotionItem).where(ContentPotionItem.key == "potion_xp_01")) is not None
    assert db.scalar(select(func.count()).select_from(ContentPotionRarityBonus)) == 5
    assert db.scalar(select(func.count()).select_from(ContentPotionEffectTarget)) > 0

    encounter = db.scalar(select(ContentEncounter).where(ContentEncounter.key.is_not(None)))
    assert encounter is not None
    assert (
        db.scalar(
            select(func.count())
            .select_from(ContentEncounterChoice)
            .where(ContentEncounterChoice.encounter_id == encounter.id)
        )
        >= 2
    )

    first_discovery = json.loads((CONTENT_DIR / "discoveries.json").read_text(encoding="utf-8"))[0]
    runtime_discovery = db.scalar(select(Discovery).where(Discovery.key == first_discovery["key"]))
    assert runtime_discovery is not None
    assert runtime_discovery.name == first_discovery["name"]

    dump_result = dump_content_to_files(db, content_dir=tmp_path)
    assert dump_result.rows["encounters.json"] >= 20

    for filename in CONTENT_FILENAMES:
        expected = json.loads((CONTENT_DIR / filename).read_text(encoding="utf-8"))
        actual = json.loads((tmp_path / filename).read_text(encoding="utf-8"))
        assert actual == expected


def test_content_load_replaces_existing_rows(db):
    load_content_from_files(db, content_dir=CONTENT_DIR)
    first_count = db.scalars(select(ContentPotionItem)).all()

    load_content_from_files(db, content_dir=CONTENT_DIR)
    second_count = db.scalars(select(ContentPotionItem)).all()

    assert len(second_count) == len(first_count)


def test_runtime_content_refresh_uses_database_rows(db):
    load_content_from_files(db, content_dir=CONTENT_DIR)
    encounter = db.scalar(select(ContentEncounter).order_by(ContentEncounter.id))
    assert encounter is not None
    encounter.title = "DB-backed encounter title"

    refresh_runtime_content_from_database(db)

    assert EncounterService().get(encounter.key).title == "DB-backed encounter title"
    assert location_service.LOCATION_SERVICE.banner_asset_for("stewards_hall") == "location.stewards_hall"

    load_content_from_files(db, content_dir=CONTENT_DIR)
    refresh_runtime_content_from_database(db)

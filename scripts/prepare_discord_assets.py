from __future__ import annotations

import argparse
from pathlib import Path

from bot.services.discord_asset_service import (
    DEFAULT_CATALOG_PATH,
    AssetDefinition,
    AssetValidationError,
    inspect_image_file,
    load_catalog,
    validate_asset_file,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare and validate Dungeon Steward Discord image assets.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--validate", action="store_true", help="Validate prepared images without modifying files.")
    mode.add_argument("--prepare", action="store_true", help="Resize/crop source images into prepared asset files.")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG_PATH)
    parser.add_argument("--key", help="Prepare or validate one logical asset key.")
    parser.add_argument("--prefix", help="Prepare or validate all keys under a prefix.")
    parser.add_argument("--quality", type=int, default=82, help="WebP quality for prepared photographic artwork.")
    args = parser.parse_args()

    catalog = load_catalog(args.catalog)
    definitions = _filtered_assets(catalog.assets, key=args.key, prefix=args.prefix)
    if not definitions:
        raise SystemExit("No matching assets.")

    failures = 0
    warnings = 0
    for definition in definitions:
        try:
            if args.prepare:
                _prepare(definition, quality=args.quality)
            result = validate_asset_file(definition)
        except Exception as exc:
            failures += 1
            print(f"FAIL {definition.key}: {exc}")
            continue

        warning_text = f" | warnings: {'; '.join(result.warnings)}" if result.warnings else ""
        warnings += len(result.warnings)
        print(
            f"OK {definition.key}: {result.image.width}x{result.image.height}, "
            f"{result.image.size_bytes} bytes, sha256={result.image.sha256[:12]}{warning_text}"
        )

    print(f"Summary: checked={len(definitions)} failures={failures} warnings={warnings}")
    if failures:
        raise SystemExit(1)


def _filtered_assets(
    assets: dict[str, AssetDefinition],
    *,
    key: str | None,
    prefix: str | None,
) -> list[AssetDefinition]:
    if key and prefix:
        raise SystemExit("Use --key or --prefix, not both.")
    if key:
        try:
            return [assets[key]]
        except KeyError as error:
            raise SystemExit(f"Unknown asset key: {key}") from error
    if prefix:
        return [definition for asset_key, definition in sorted(assets.items()) if asset_key.startswith(prefix)]
    return [definition for _, definition in sorted(assets.items())]


def _prepare(definition: AssetDefinition, *, quality: int) -> None:
    if definition.source_path is None:
        if not definition.path.exists():
            raise AssetValidationError(f"{definition.key} has no source_path and no prepared file")
        print(f"SKIP {definition.key}: no source_path; validating existing prepared file")
        return
    if definition.source_path.resolve() == definition.path.resolve():
        raise AssetValidationError(f"{definition.key} source_path must not be the prepared output path")
    if not definition.source_path.exists():
        raise AssetValidationError(f"{definition.key} source image is missing")

    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except Exception as error:
        raise SystemExit("Pillow is required for --prepare. Install project dependencies first.") from error

    try:
        with Image.open(definition.source_path) as image:
            image = ImageOps.exif_transpose(image)
            spec = definition.spec
            if image.width < spec.width or image.height < spec.height:
                print(
                    f"WARN {definition.key}: source is {image.width}x{image.height}; "
                    f"target is {spec.width}x{spec.height}"
                )
            resized = ImageOps.fit(image, (spec.width, spec.height), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
            if resized.mode not in {"RGB", "RGBA"}:
                resized = resized.convert("RGBA" if _has_alpha(resized) and spec.name == "thumbnail" else "RGB")
            elif spec.name != "thumbnail" and resized.mode == "RGBA":
                resized = resized.convert("RGB")

            definition.path.parent.mkdir(parents=True, exist_ok=True)
            before = definition.source_path.stat().st_size
            save_kwargs = _save_kwargs(definition.path.suffix.lower(), quality=quality)
            resized.save(definition.path, **save_kwargs)
            after_info = inspect_image_file(definition.path)
            savings = 100 - ((after_info.size_bytes / before) * 100) if before else 0
            print(
                f"PREP {definition.key}: {image.width}x{image.height} {before} bytes -> "
                f"{after_info.width}x{after_info.height} {after_info.size_bytes} bytes ({savings:.1f}% savings)"
            )
    except UnidentifiedImageError as error:
        raise AssetValidationError(f"{definition.key} source image is invalid") from error


def _has_alpha(image) -> bool:
    if image.mode in {"RGBA", "LA"}:
        return True
    return image.mode == "P" and "transparency" in image.info


def _save_kwargs(suffix: str, *, quality: int) -> dict[str, object]:
    if suffix == ".webp":
        return {"format": "WEBP", "quality": quality, "method": 6}
    if suffix == ".png":
        return {"format": "PNG", "optimize": True}
    if suffix in {".jpg", ".jpeg"}:
        return {"format": "JPEG", "quality": quality, "optimize": True}
    raise AssetValidationError(f"Unsupported output extension: {suffix}")


if __name__ == "__main__":
    main()

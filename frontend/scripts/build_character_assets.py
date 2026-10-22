"""Build browser-sized transparent WebP portraits without touching source PNG files."""

from __future__ import annotations

from pathlib import Path

from PIL import Image


FRONTEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = FRONTEND_DIR.parent
SOURCE_DIR = PROJECT_DIR / "素材" / "红楼梦"
OUTPUT_DIR = FRONTEND_DIR / "public" / "assets" / "characters-webp"
MAX_SIZE = (960, 1200)


def convert(source: Path, destination: Path) -> bool:
    if destination.exists() and destination.stat().st_mtime >= source.stat().st_mtime:
        try:
            with Image.open(destination) as current:
                current.verify()
            return False
        except (OSError, SyntaxError):
            pass

    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        portrait = image.convert("RGBA")
        portrait.thumbnail(MAX_SIZE, Image.Resampling.LANCZOS)
        portrait.save(destination, "WEBP", quality=88, method=4, exact=True)
    return True


def main() -> None:
    if not SOURCE_DIR.is_dir():
        raise SystemExit(f"Portrait source directory does not exist: {SOURCE_DIR}")

    total = 0
    written = 0
    for character_dir in sorted(path for path in SOURCE_DIR.iterdir() if path.is_dir() and path.name != "建筑"):
        for source in sorted(character_dir.glob("*.png")):
            total += 1
            destination = OUTPUT_DIR / character_dir.name / f"{source.stem}.webp"
            if convert(source, destination):
                written += 1

    size_mb = sum(path.stat().st_size for path in OUTPUT_DIR.rglob("*.webp")) / 1024 / 1024
    print(f"Character assets ready: {total} files, {written} rebuilt, {size_mb:.1f} MB")


if __name__ == "__main__":
    main()

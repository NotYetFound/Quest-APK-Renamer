"""Render the canonical SVG into release-platform icon formats."""

from __future__ import annotations

import argparse
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    source = args.project.resolve() / "src/quest_renamer/assets/app-icon.svg"
    _app = QGuiApplication.instance() or QGuiApplication([])
    renderer = QSvgRenderer(str(source))
    if not renderer.isValid():
        raise SystemExit(f"Could not render {source}")
    image = QImage(1024, 1024, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    renderer.render(painter, QRectF(0, 0, 1024, 1024))
    painter.end()
    png = output / "app-icon-1024.png"
    if not image.save(str(png), "PNG"):
        raise SystemExit("Could not save the release PNG icon.")
    windows_icon = image.scaled(
        256,
        256,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    if not windows_icon.save(str(output / "app-icon.ico"), "ICO"):
        raise SystemExit("Could not save the Windows release icon.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

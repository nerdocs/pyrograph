"""The desktop application — Qt Widgets on top of the document model.

Qt lives in this package and nowhere else. Everything below it (``document``, ``job``, ``devices``) stays
importable and testable without a display, which is what keeps the driver chain scriptable.

Three parts, each in its own module:

* :mod:`~pyrograph.gui.canvas` — the work area, drawn in millimetres.
* :mod:`~pyrograph.gui.layers` — the layer stack and its laser parameters.
* :mod:`~pyrograph.gui.device` — connecting and engraving, on a worker thread.

:mod:`~pyrograph.gui.window` ties them together and owns the document.
"""

from __future__ import annotations


def run(path: str | None = None) -> int:
    """Start the application. ``path`` opens a ``.pyg`` document on launch."""
    import sys

    from PySide6.QtWidgets import QApplication

    from .window import MainWindow

    app = QApplication(sys.argv[:1])
    app.setApplicationName("PyroGraph")
    window = MainWindow(path)
    window.show()
    return app.exec()


def main(argv: list[str] | None = None) -> int:
    """The ``pyrograph-gui`` command. The GUI is its own executable, so a desktop launcher points at a
    binary rather than at a subcommand, and starting it never loads the CLI's argument parser."""
    import argparse

    parser = argparse.ArgumentParser(prog="pyrograph-gui", description="Design, position and engrave")
    parser.add_argument("file", nargs="?", help="a .pyg document to open on launch")
    return run(parser.parse_args(argv).file)


__all__ = ["main", "run"]

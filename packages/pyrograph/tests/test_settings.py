"""The galvo settings dialog: what it stores, and what it refuses to store.

These settings are not preferences — without them the machine marks at a guessed size — so the checks
here are about not letting a broken lens configuration through to a job.
"""

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pyrograph.gui import settings as gui_settings  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def stored(tmp_path, monkeypatch):
    """Settings in a file of our own, so a test never reads or writes the real ones."""
    QSettings.setPath(
        QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path)
    )
    monkeypatch.setattr(
        gui_settings,
        "settings",
        lambda: QSettings(
            QSettings.Format.IniFormat,
            QSettings.Scope.UserScope,
            gui_settings.ORGANISATION,
            gui_settings.APPLICATION,
        ),
    )
    return gui_settings.settings()


def grid_file(path):
    from ezcad2 import protocol as p

    lines = []
    for row in range(-2, 3):
        for col in range(-2, 3):
            gx, gy = p.CENTRE + col * 0x1000, p.CENTRE + row * 0x1000
            x_mm, y_mm = (gx - p.CENTRE) / 500, (gy - p.CENTRE) / 500
            lines.append(f"{x_mm:.4f} {y_mm:.4f} {col} {row} {gx:04X} {gy:04X}")
    path.write_text("\n".join(lines) + "\n")
    return path


def test_a_fresh_install_falls_back_to_the_default_lens(app, stored):
    lens, problems = gui_settings.galvo_lens()

    assert lens.galvos_per_mm == gui_settings.DEFAULT_GALVOS_PER_MM
    assert lens.cor_file is None
    assert lens.calibration is None
    assert not problems


def test_a_correction_file_that_moved_is_reported_not_silently_dropped(app, stored):
    """Marking at the wrong size with no explanation is the failure worth preventing here."""
    stored.setValue("galvo/cor_file", "/nowhere/lens.cor")

    lens, problems = gui_settings.galvo_lens()

    assert lens.cor_file is None
    assert any("gone" in problem for problem in problems)


def test_the_dialog_stores_what_was_entered(app, stored, tmp_path):
    dialog = gui_settings.GalvoSettings()
    dialog.source.setCurrentIndex(dialog.source.findData("co2"))
    dialog.scale.setValue(1000.0)
    dialog._accept()

    lens, problems = gui_settings.galvo_lens()
    assert lens.galvos_per_mm == 1000.0
    assert gui_settings.galvo_source() == "co2"
    assert not problems


def test_the_field_size_follows_the_scale(app, stored):
    """The number that matters is the field, and nobody divides 65535 in their head."""
    dialog = gui_settings.GalvoSettings()
    dialog.scale.setValue(500.0)
    assert "131.1" in dialog.field.text()

    dialog.scale.setValue(1000.0)
    assert "65.5" in dialog.field.text()


def test_software_correction_without_a_grid_is_refused(app, stored, monkeypatch):
    """Switching it on and leaving the file empty would silently do nothing at all."""
    warned = []
    monkeypatch.setattr(
        gui_settings.QMessageBox, "warning", lambda *args, **kwargs: warned.append(args[-1])
    )
    dialog = gui_settings.GalvoSettings()
    dialog.host_correction.setChecked(True)
    dialog.calibration_file.setText("")
    dialog._accept()

    assert warned, "the dialog accepted a correction it cannot perform"
    assert dialog.result() != dialog.DialogCode.Accepted


def test_a_broken_grid_is_caught_in_the_dialog(app, stored, tmp_path, monkeypatch):
    """Better here than halfway through a job."""
    broken = tmp_path / "broken.csv"
    broken.write_text("0.0 0.0 0 0\n")
    warned = []
    monkeypatch.setattr(
        gui_settings.QMessageBox, "warning", lambda *args, **kwargs: warned.append(args[-1])
    )
    dialog = gui_settings.GalvoSettings()
    dialog.host_correction.setChecked(True)
    dialog.calibration_file.setText(str(broken))
    dialog._accept()

    assert any("cannot be used" in message for message in warned)


def test_a_stored_grid_reaches_the_lens(app, stored, tmp_path, monkeypatch):
    monkeypatch.setattr(gui_settings.QMessageBox, "information", lambda *a, **k: None)
    path = grid_file(tmp_path / "cal.csv")
    dialog = gui_settings.GalvoSettings()
    dialog.host_correction.setChecked(True)
    dialog.calibration_file.setText(str(path))
    dialog._accept()

    lens, problems = gui_settings.galvo_lens()
    assert lens.calibration is not None
    assert lens.calibration.size == (5, 5)
    assert not problems


def test_a_grid_that_broke_since_it_was_stored_is_reported(app, stored, tmp_path):
    stored.setValue("galvo/host_correction", True)
    stored.setValue("galvo/calibration_file", "/nowhere/cal.csv")

    lens, problems = gui_settings.galvo_lens()

    assert lens.calibration is None
    assert any("not used" in problem for problem in problems)

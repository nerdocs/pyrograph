"""The ``.pyg`` container: lossless round trip, and an SVG that stands on its own."""

import zipfile
from xml.etree import ElementTree as ET

from pyrograph.document import (
    Document,
    LaserParams,
    Layer,
    Path,
    PathObject,
    TextObject,
    Transform,
    load_pyg,
    save_pyg,
)
from pyrograph.document.serialize import SVG_NS


def test_round_trip_keeps_paths_and_images_identical(tmp_path, sample_objects):
    document = Document(
        width_mm=120.0,
        height_mm=80.0,
        layers=[
            Layer(name="cut", params=LaserParams(power=80, dpi=508.0), objects=list(sample_objects)),
            Layer(name="hidden", visible=False),
        ],
    )
    path = tmp_path / "project.pyg"
    save_pyg(document, path)
    assert load_pyg(path) == document


def test_round_trip_keeps_text_editable(tmp_path, font_path):
    text = TextObject(id="otext", text="Hallo", font_path=font_path, size_mm=8.0)
    document = Document(layers=[Layer(objects=[text])])
    path = tmp_path / "text.pyg"
    save_pyg(document, path)

    loaded = load_pyg(path)
    assert loaded == document
    assert loaded.object("otext").text == "Hallo"


def test_document_svg_parses_on_its_own(tmp_path, sample_objects):
    document = Document(layers=[Layer(objects=sample_objects)])
    path = tmp_path / "project.pyg"
    save_pyg(document, path)

    with zipfile.ZipFile(path) as archive:
        assert "images/oimage.png" in archive.namelist()
        root = ET.fromstring(archive.read("document.svg"))

    assert root.tag == f"{{{SVG_NS}}}svg"
    assert root.get("viewBox") == "0 0 100.0 100.0"
    # Nothing of ours leaks into the geometry: no foreign namespace beyond SVG and xlink.
    tags = {element.tag for element in root.iter()}
    assert all(tag.startswith(f"{{{SVG_NS}}}") for tag in tags)


def test_transforms_are_written_only_when_they_do_something(tmp_path):
    document = Document(
        layers=[
            Layer(
                objects=[
                    PathObject(id="oplain", path=Path.rect(0, 0, 1, 1)),
                    PathObject(id="omoved", path=Path.rect(0, 0, 1, 1), transform=Transform.translate(5, 5)),
                ]
            )
        ]
    )
    path = tmp_path / "project.pyg"
    save_pyg(document, path)

    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("document.svg"))
    elements = {e.get("id"): e for e in root.iter() if e.get("id")}
    assert elements["oplain"].get("transform") is None
    assert elements["omoved"].get("transform") == "matrix(1.0 0.0 0.0 1.0 5.0 5.0)"

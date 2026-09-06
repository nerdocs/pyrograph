"""Reading and writing ``.pyg``, pyrograph's native format.

A ``.pyg`` file is a ZIP container::

    project.pyg
    ├── document.svg     geometry — standard SVG, opens in Inkscape
    ├── project.json     layers, laser parameters, object metadata
    └── images/*.png     the original bitmaps, byte for byte

The rule that keeps this useful: **``document.svg`` stays valid SVG on its own.** Nothing laser-specific
goes into it — no custom namespace, no foreign attributes. Everything of ours lives in ``project.json`` and
refers to SVG elements by their ``id``.

That leaves one duplication to be aware of: a ``TextObject`` appears in the SVG as its glyph outline, so
other tools render it correctly, while ``project.json`` keeps the editable text, font and size. On reading,
the JSON wins for text objects and the outline is regenerated.
"""

from __future__ import annotations

import json
import os
import zipfile
from xml.etree import ElementTree as ET

from .document import Document
from .geometry import Path, Transform
from .layer import LaserParams, Layer
from .objects import DocumentObject, ImageObject, PathObject, TextObject

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"

FORMAT = "pyrograph-document"
VERSION = 1

_STROKE = {"fill": "none", "stroke": "#000000", "stroke-width": "0.1"}


def _svg_element(obj: DocumentObject) -> ET.Element:
    """Render one object as the SVG element that represents its geometry."""
    if isinstance(obj, ImageObject):
        element = ET.Element(
            f"{{{SVG_NS}}}image",
            {
                "id": obj.id,
                "x": "0",
                "y": "0",
                "width": repr(obj.width_mm),
                "height": repr(obj.height_mm),
                f"{{{XLINK_NS}}}href": f"images/{obj.id}.png",
            },
        )
    else:
        element = ET.Element(
            f"{{{SVG_NS}}}path", {"id": obj.id, "d": obj.local_path().to_svg_d(), **_STROKE}
        )
    if not obj.transform.is_identity:
        element.set("transform", obj.transform.to_svg())
    return element


def _build_svg(document: Document) -> bytes:
    ET.register_namespace("", SVG_NS)
    ET.register_namespace("xlink", XLINK_NS)
    root = ET.Element(
        f"{{{SVG_NS}}}svg",
        {
            "width": f"{document.width_mm}mm",
            "height": f"{document.height_mm}mm",
            "viewBox": f"0 0 {document.width_mm} {document.height_mm}",
        },
    )
    for index, layer in enumerate(document.layers):
        group = ET.SubElement(root, f"{{{SVG_NS}}}g", {"id": f"layer{index}"})
        if not layer.visible:
            group.set("display", "none")
        for obj in layer.objects:
            group.append(_svg_element(obj))
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _object_json(obj: DocumentObject) -> dict:
    entry = {"id": obj.id, "name": obj.name, "locked": obj.locked}
    if isinstance(obj, ImageObject):
        entry["type"] = "image"
    elif isinstance(obj, TextObject):
        entry.update(type="text", text=obj.text, font=obj.font_path, size_mm=obj.size_mm)
    elif isinstance(obj, PathObject):
        entry["type"] = "path"
    else:
        raise TypeError(f"cannot serialise {type(obj).__name__}")
    return entry


def _build_json(document: Document) -> bytes:
    data = {
        "format": FORMAT,
        "version": VERSION,
        "width_mm": document.width_mm,
        "height_mm": document.height_mm,
        "layers": [
            {
                "name": layer.name,
                "visible": layer.visible,
                "params": vars(layer.params),
                "objects": [_object_json(obj) for obj in layer.objects],
            }
            for layer in document.layers
        ],
    }
    return json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")


def save_pyg(document: Document, path: str | os.PathLike) -> None:
    """Write ``document`` to a ``.pyg`` container."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("document.svg", _build_svg(document))
        archive.writestr("project.json", _build_json(document))
        for obj in document.objects():
            if isinstance(obj, ImageObject):
                archive.writestr(f"images/{obj.id}.png", obj.data)


def _read_object(entry: dict, element: ET.Element, archive: zipfile.ZipFile) -> DocumentObject:
    transform = Transform.from_svg(element.get("transform", "matrix(1 0 0 1 0 0)"))
    common = {
        "id": entry["id"],
        "name": entry.get("name", ""),
        "locked": entry.get("locked", False),
        "transform": transform,
    }
    kind = entry["type"]
    if kind == "image":
        return ImageObject(
            **common,
            data=archive.read(f"images/{entry['id']}.png"),
            width_mm=float(element.get("width", "0")),
            height_mm=float(element.get("height", "0")),
        )
    if kind == "text":
        # The SVG holds the outline for other tools; the editable source comes from the JSON.
        return TextObject(
            **common, text=entry["text"], font_path=entry["font"], size_mm=entry["size_mm"]
        )
    if kind == "path":
        return PathObject(**common, path=Path.from_svg_d(element.get("d", "")))
    raise ValueError(f"unknown object type: {kind!r}")


def load_pyg(path: str | os.PathLike) -> Document:
    """Read a ``.pyg`` container back into a document."""
    with zipfile.ZipFile(path) as archive:
        data = json.loads(archive.read("project.json"))
        if data.get("format") != FORMAT:
            raise ValueError("not a pyrograph document")
        if data.get("version") != VERSION:
            raise ValueError(f"unsupported document version: {data.get('version')}")
        root = ET.fromstring(archive.read("document.svg"))
        elements = {e.get("id"): e for e in root.iter() if e.get("id")}

        layers = [
            Layer(
                name=layer["name"],
                visible=layer["visible"],
                params=LaserParams(**layer["params"]),
                objects=[_read_object(entry, elements[entry["id"]], archive) for entry in layer["objects"]],
            )
            for layer in data["layers"]
        ]
    return Document(width_mm=data["width_mm"], height_mm=data["height_mm"], layers=layers)

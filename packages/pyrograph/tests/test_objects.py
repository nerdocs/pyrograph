"""Objects and layers: bounds per type, layer membership and z-order."""

import math

from pyrograph.document import (
    Document,
    ImageObject,
    Layer,
    MoveObject,
    Path,
    PathObject,
    Rect,
    TextObject,
    Transform,
    UndoStack,
)


def test_image_bounds_follow_the_placement_not_the_pixels(png_bytes):
    # A 4×2 pixel image placed on 20 × 10 mm at (30, 5) — the pixel count never enters the geometry.
    image = ImageObject(data=png_bytes, width_mm=20.0, height_mm=10.0, transform=Transform.translate(30, 5))
    assert image.bounds() == Rect(30.0, 5.0, 20.0, 10.0)


def test_group_bounds_cover_every_transformed_object(sample_objects):
    document = Document(layers=[Layer(objects=sample_objects)])
    # Path 0,0 10×5 and image 30,5 20×10 → 0,0 to 50,15.
    assert document.bounds() == Rect(0.0, 0.0, 50.0, 15.0)


def test_hidden_layers_do_not_contribute_to_the_bounds(sample_objects):
    document = Document(
        layers=[Layer(objects=[sample_objects[0]]), Layer(visible=False, objects=[sample_objects[1]])]
    )
    assert document.bounds() == Rect(0.0, 0.0, 10.0, 5.0)


def test_moving_an_object_between_layers_keeps_its_geometry():
    obj = PathObject(id="omove", path=Path.rect(2, 3, 4, 5), transform=Transform.scale(2))
    document = Document(layers=[Layer(name="a", objects=[obj]), Layer(name="b")])
    before = obj.bounds()

    UndoStack(document).execute(MoveObject("omove", to_layer=1))

    assert document.layers[0].objects == []
    assert document.layers[1].objects[0] is obj
    assert obj.bounds() == before


def test_z_order_within_a_layer_is_the_list_order(sample_objects):
    layer = Layer(objects=sample_objects)
    document = Document(layers=[layer])
    UndoStack(document).execute(MoveObject("oimage", to_layer=0, to_index=0))
    assert [o.id for o in layer.objects] == ["oimage", "opath"]


def test_text_bounds_are_taken_from_the_glyph_outlines(font_path):
    text = TextObject(text="Hy", font_path=font_path, size_mm=10.0)
    box = text.bounds()
    # The baseline sits at y = 0 and the document's y grows downwards, so an ascender has a negative y.
    assert box.y < 0
    assert 0 < box.height <= 10.0
    assert box.width > 0
    # Twice the size means twice the outline.
    doubled = TextObject(text="Hy", font_path=font_path, size_mm=20.0).bounds()
    assert math.isclose(doubled.width, 2 * box.width, rel_tol=1e-9)

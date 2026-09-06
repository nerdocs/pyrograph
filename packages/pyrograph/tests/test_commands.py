"""The command stack: every mutation reversible, undo restores the document exactly."""

import zipfile

from pyrograph.document import (
    AddObject,
    CommandGroup,
    Document,
    LaserParams,
    Layer,
    MoveObject,
    Path,
    PathObject,
    RemoveObject,
    SetLayerParams,
    Transform,
    TransformObject,
    UndoStack,
    save_pyg,
)


def _serialised(document: Document, tmp_path, name: str) -> dict[str, bytes]:
    """The container's contents. Not the raw file — a ZIP stamps every write with the current time."""
    path = tmp_path / name
    save_pyg(document, path)
    with zipfile.ZipFile(path) as archive:
        return {member: archive.read(member) for member in archive.namelist()}


def test_a_sequence_of_commands_undone_restores_the_document(tmp_path, sample_objects):
    document = Document(layers=[Layer(name="a", objects=list(sample_objects)), Layer(name="b")])
    before = _serialised(document, tmp_path, "before.pyg")
    stack = UndoStack(document)

    stack.execute(AddObject(0, PathObject(id="onew", path=Path.rect(1, 1, 2, 2))))
    stack.execute(MoveObject("onew", to_layer=1))
    stack.execute(SetLayerParams(1, LaserParams(power=99, dpi=508.0)))
    stack.execute(RemoveObject("opath"))
    assert _serialised(document, tmp_path, "after.pyg") != before

    while stack.can_undo:
        stack.undo()
    assert _serialised(document, tmp_path, "undone.pyg") == before


def test_redo_replays_what_undo_took_back(sample_objects):
    document = Document(layers=[Layer(objects=list(sample_objects))])
    stack = UndoStack(document)
    stack.execute(RemoveObject("opath"))

    stack.undo()
    assert [o.id for o in document.layers[0].objects] == ["opath", "oimage"]
    stack.redo()
    assert [o.id for o in document.layers[0].objects] == ["oimage"]


def test_a_new_command_drops_the_redo_history(sample_objects):
    document = Document(layers=[Layer(objects=list(sample_objects))])
    stack = UndoStack(document)
    stack.execute(RemoveObject("opath"))
    stack.undo()
    assert stack.can_redo

    stack.execute(RemoveObject("oimage"))
    assert not stack.can_redo


def test_remove_puts_the_object_back_where_it_was(sample_objects):
    document = Document(layers=[Layer(objects=list(sample_objects))])
    stack = UndoStack(document)
    stack.execute(RemoveObject("opath"))
    stack.undo()
    assert document.layers[0].objects[0].id == "opath"


def test_transform_scales_the_stroke_with_the_geometry(sample_objects):
    document = Document(layers=[Layer(objects=list(sample_objects))])
    document.object("opath").stroke_width_mm = 0.4
    stack = UndoStack(document)

    stack.execute(TransformObject("opath", Transform.scale(2.0)))
    assert document.object("opath").bounds().width == 20.0
    assert document.object("opath").stroke_width_mm == 0.8

    stack.undo()
    assert document.object("opath").bounds().width == 10.0
    assert document.object("opath").stroke_width_mm == 0.4


def test_a_stroke_left_to_the_layer_stays_there(sample_objects):
    document = Document(layers=[Layer(objects=list(sample_objects))])
    UndoStack(document).execute(TransformObject("opath", Transform.scale(3.0)))
    assert document.object("opath").stroke_width_mm is None


def test_a_group_undoes_as_one_step(sample_objects):
    document = Document(layers=[Layer(objects=list(sample_objects))])
    stack = UndoStack(document)
    move = Transform.translate(5.0, 0.0)

    stack.execute(CommandGroup([TransformObject("opath", move), TransformObject("oimage", move)]))
    assert document.object("opath").bounds().x == 5.0
    assert document.object("oimage").bounds().x == 35.0

    stack.undo()
    assert document.object("opath").bounds().x == 0.0
    assert document.object("oimage").bounds().x == 30.0
    assert not stack.can_undo


def test_a_clone_is_a_copy_under_a_new_id(sample_objects):
    original = sample_objects[0]
    clone = original.clone()
    assert clone.id != original.id
    assert clone.path.segments == original.path.segments
    clone.path.segments.clear()
    assert original.path.segments  # deep, not shared

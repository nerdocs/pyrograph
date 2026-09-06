"""Image pre-processing and the round trip back to a viewable preview."""

from PIL import Image

from laserpecker.imaging import adjust_levels, image_to_raster, raster_to_image


def test_neutral_settings_change_nothing():
    ramp = list(range(0, 256, 8))
    assert adjust_levels(ramp, 0, 0) == ramp


def test_brightness_shifts_and_clamps():
    assert adjust_levels([100], brightness=10) == [126]  # +10 % of 255
    assert adjust_levels([250], brightness=100) == [255]
    assert adjust_levels([5], brightness=-100) == [0]


def test_contrast_pivots_around_mid_grey():
    assert adjust_levels([128], contrast=50) == [128]
    dark, bright = adjust_levels([64, 192], contrast=50)
    assert dark < 64 and bright > 192


def test_negative_contrast_pulls_towards_mid_grey():
    dark, bright = adjust_levels([64, 192], contrast=-50)
    assert dark > 64 and bright < 192


def test_pre_processing_shifts_how_much_of_the_image_burns():
    # The dither only decides black or white per pixel, so the burnt area is set before it runs.
    flat = Image.new("L", (16, 16), 120)

    def burnt(**settings) -> int:
        return image_to_raster(flat, width_mm=1.6, dpi=254.0, **settings).payload.count(0)

    assert burnt(brightness=40) < burnt() < burnt(brightness=-40)


def test_preview_returns_an_image_of_the_raster_size():
    source = Image.new("L", (20, 10), 128)

    raster = image_to_raster(source, width_mm=2.0, dpi=254.0)
    preview = raster_to_image(raster)

    assert preview.size == (raster.width, raster.height)
    assert preview.mode == "L"


def test_packed_and_plain_previews_agree():
    source = Image.linear_gradient("L").resize((32, 32))

    plain = raster_to_image(image_to_raster(source, width_mm=3.2, dpi=254.0))
    packed = raster_to_image(image_to_raster(source, width_mm=3.2, dpi=254.0, packed=True))

    assert plain.tobytes() == packed.tobytes()

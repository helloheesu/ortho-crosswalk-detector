import unicodedata
import pytest
from ortho import catalog
from ortho.detection import prepare_job


def test_hangul_job_matches_decomposed_disk_name(monkeypatch):
    disk = unicodedata.normalize('NFD', '정사영상.tif')
    image = {'id': 'source', 'relative_path': disk, 'width': 10, 'height': 10, 'georef': None}
    monkeypatch.setattr(catalog, 'scan', lambda root: [image])
    job = {'schema_version': '1.0', 'images': [{'path': '정사영상.tif'}],
           'area': {'space': 'pixel', 'geometry': {'type': 'Polygon',
                    'coordinates': [[[0, 0], [5, 0], [5, 5], [0, 5], [0, 0]]]}}}
    area, images = prepare_job('unused', job)
    assert area['image_id'] == 'source'
    assert images[0]['relative_path'] == disk


def test_ambiguous_names_fail_even_for_exact_match():
    images = [{'relative_path': name} for name in ('정사영상.tif', unicodedata.normalize('NFD', '정사영상.tif'))]
    with pytest.raises(ValueError, match='여러 개'):
        catalog.select_image(images, '정사영상.tif')


def test_reader_error_is_preserved():
    with pytest.raises(ValueError, match='broken TIFF'):
        catalog.select_image([{'relative_path': 'a.tif', 'error': 'broken TIFF'}], 'a.tif')

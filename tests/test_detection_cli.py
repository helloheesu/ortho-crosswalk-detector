"""Stage-1 boundary tests. All imagery/model outputs here are synthetic fixtures."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import rasterio
from affine import Affine
from PIL import Image
from pyproj import Transformer
from shapely.geometry import box, mapping, shape

from ortho import catalog, geo
from ortho.cli import main
from ortho.detection import prepare_job, plan_tiles, execute, DetectionFailed
from ortho.exchange import read_bundle


class SyntheticDetector:
    metadata = {'backend': 'synthetic_test', 'version': 'fixture', 'weights_name': 'NO_REAL_MODEL'}
    def predict(self, rgb):
        return [{'bbox': [20, 30, 65, 80], 'score': .5}]


@pytest.fixture
def inputs(tmp_path):
    root = tmp_path / 'inputs'
    root.mkdir()
    for name, x in [('selected.tif', 530000), ('unused.tif', 540000)]:
        with rasterio.open(root / name, 'w', driver='GTiff', width=300, height=240, count=3,
                           dtype='uint8', crs='EPSG:32652',
                           transform=rasterio.transform.from_origin(x, 3985000, .25, .25)) as ds:
            ds.write(np.full((3, 240, 300), 90, dtype='uint8'))
    return root


def job():
    return {'schema_version': '1.0', 'images': [{'path': 'selected.tif'}],
            'area': {'space': 'pixel', 'name': 'SYNTHETIC TEST', 'geometry': mapping(box(0, 0, 300, 240))},
            'config': {'tile_size': 256, 'overlap': 64, 'margin': 0, 'confidence': .15}}


def test_cli_import_does_not_load_web_database_or_review():
    code = "from ortho.cli import main; import sys; assert not {'flask','sqlite3','ortho.service','ortho.app'} & set(sys.modules)"
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_inspect_and_plan_do_not_read_pixels_or_instantiate_model(inputs, tmp_path, monkeypatch, capsys):
    from ortho import detection
    def forbidden(*a, **kw): raise AssertionError('pixel/model work is forbidden in inspection and planning')
    monkeypatch.setattr(catalog, 'rgb', forbidden)
    monkeypatch.setattr(detection, 'load_detector', forbidden)
    assert main(['inspect', '--input-dir', str(inputs)]) == 0
    assert len(json.loads(capsys.readouterr().out)['images']) == 2
    path = tmp_path / 'job.json'; path.write_text(json.dumps(job()))
    assert main(['plan', '--input-dir', str(inputs), '--job', str(path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['inference_executed'] is False
    assert {t['source_path'] for t in result['tiles']} == {'selected.tif'}
    assert not list(tmp_path.rglob('*.sqlite'))


def test_portable_bundle_survives_without_originals_or_database(inputs, tmp_path):
    data = job(); area, images = prepare_job(inputs, data)
    folder = tmp_path / 'output'; execute(inputs, area, images, data['config'], folder, SyntheticDetector())
    with pytest.raises(ValueError, match='테스트 전용'):
        read_bundle(folder)
    first = read_bundle(folder, allow_test=True)
    assert first['origin'] == 'test_only' and first['candidates']
    assert all(c['location_status'] == 'map_unverified' for c in first['candidates'])
    assert all('review' not in c and 'verdict' not in c and 'osm_id' not in c for c in first['candidates'])
    copied = tmp_path / 'moved'; shutil.copytree(folder, copied); shutil.rmtree(folder); shutil.rmtree(inputs)
    moved = read_bundle(copied, allow_test=True)
    assert moved == first
    assert not list(tmp_path.rglob('*.sqlite'))
    assert (copied / '.gitignore').read_text() == '*\n'


def test_missing_weights_no_fake_completed_bundle(inputs, tmp_path, capsys):
    data = job(); data['config'].update(weights='missing.pt', source='TEST', license='TEST')
    path = tmp_path / 'job.json'; path.write_text(json.dumps(data)); out = tmp_path / 'result'
    assert main(['detect', '--input-dir', str(inputs), '--job', str(path), '--output-dir', str(out)]) == 2
    assert json.loads(capsys.readouterr().err)['status'] == 'failed'
    assert not (out / 'candidates.json').exists()
    assert not list(tmp_path.rglob('*.sqlite'))


def test_unknown_backend_cannot_silently_fall_back(inputs, tmp_path, capsys):
    data = job(); data['config'].update(backend='unsupported', weights='missing', source='TEST', license='TEST')
    path = tmp_path / 'job.json'; path.write_text(json.dumps(data)); out = tmp_path / 'unknown'
    assert main(['detect', '--input-dir', str(inputs), '--job', str(path), '--output-dir', str(out)]) == 2
    assert 'backend' in json.loads(capsys.readouterr().err)['error']
    assert not (out / 'candidates.json').exists()


def test_grounding_missing_local_model_cannot_download_or_fake_results(inputs, tmp_path, capsys):
    data = job(); data['config'].update(backend='grounding_dino', weights='missing', source='TEST', license='TEST', revision='TEST')
    path = tmp_path / 'job.json'; path.write_text(json.dumps(data)); out = tmp_path / 'grounding'
    assert main(['detect', '--input-dir', str(inputs), '--job', str(path), '--output-dir', str(out)]) == 2
    assert '로컬 모델 디렉터리' in json.loads(capsys.readouterr().err)['error']
    assert not (out / 'candidates.json').exists()


def test_explicit_selection_and_output_original_safety(inputs, tmp_path):
    data = job(); area, images = prepare_job(inputs, data)
    unused = next(im for im in images if im['relative_path'] == 'unused.tif')
    before = {p.name: p.read_bytes() for p in inputs.iterdir()}
    with pytest.raises(ValueError, match='서로 포함'):
        execute(inputs, area, images, data['config'], inputs / 'bad', SyntheticDetector())
    assert before == {p.name: p.read_bytes() for p in inputs.iterdir()}
    out = tmp_path / 'out'; execute(inputs, area, images, data['config'], out, SyntheticDetector())
    result = json.loads((out / 'candidates.json').read_text())
    assert unused['id'] not in {s['id'] for s in result['sources']}
    with pytest.raises(ValueError, match='덮어쓰지'):
        execute(inputs, area, images, data['config'], out, SyntheticDetector())
    data['images'].append({'path': 'unused.tif'})
    with pytest.raises(ValueError, match='한 개'):
        prepare_job(inputs, data)


def test_bundle_rejects_modified_assets_and_path_escape(inputs, tmp_path):
    data = job(); area, images = prepare_job(inputs, data)
    out = tmp_path / 'bundle'; execute(inputs, area, images, data['config'], out, SyntheticDetector())
    bpath = out / 'candidates.json'; original = json.loads(bpath.read_text())
    tile = out / original['tiles'][0]['path']; saved = tile.read_bytes(); tile.write_bytes(b'changed')
    with pytest.raises(ValueError, match='해시'):
        read_bundle(out, allow_test=True)
    tile.write_bytes(saved)
    original['tiles'][0]['path'] = '../outside.png'; bpath.write_text(json.dumps(original))
    with pytest.raises(ValueError, match='상대 경로'):
        read_bundle(out, allow_test=True)


def test_failed_inference_exports_audit_but_no_success_package(inputs, tmp_path):
    class Broken(SyntheticDetector):
        def predict(self, rgb): raise RuntimeError('synthetic failure')
    data = job(); area, images = prepare_job(inputs, data); out = tmp_path / 'failed'
    with pytest.raises(DetectionFailed, match='synthetic failure'):
        execute(inputs, area, images, data['config'], out, Broken())
    assert json.loads((out / 'manifest.json').read_text())['status'] == 'failed'
    assert not (out / 'candidates.json').exists()
    assert not (out / 'candidates.geojson').exists()


def test_pixel_only_coverage_and_georef_version(inputs, tmp_path):
    data = job(); data['images'][0]['georef'] = None
    area, images = prepare_job(inputs, data)
    out = tmp_path / 'pixel'; execute(inputs, area, images, data['config'], out, SyntheticDetector())
    bundle = read_bundle(out, allow_test=True)
    assert all(c['geometry'] is None and c['location_status'] == 'pixel_only' for c in bundle['candidates'])
    assert bundle['area']['coverage']['area_m2'] is None


def test_map_plan_reports_missing_and_requires_georef_check(inputs, tmp_path):
    images = catalog.scan(inputs); im = next(i for i in images if i['relative_path'] == 'selected.tif')
    g = im['georef']; region = geo.to_map(box(0, 0, 500, 240), g)
    data = job(); data['area'] = {'space': 'map', 'geometry': mapping(region)}
    area, images = prepare_job(inputs, data)
    assert shape(area['coverage']['missing']).area > 0
    assert shape(area['coverage']['unverified']).area > 0
    with pytest.raises(ValueError, match='중첩 점검'):
        execute(inputs, area, images, data['config'], tmp_path / 'bad', SyntheticDetector())
    data['images'][0]['georef'] = dict(g, verified=True, version='test-v1', verification_note='SYNTHETIC TEST')
    area, images = prepare_job(inputs, data)
    execute(inputs, area, images, data['config'], tmp_path / 'valid', SyntheticDetector())
    assert read_bundle(tmp_path / 'valid', allow_test=True)['sources'][0]['georef']['version'] == 'test-v1'


def test_calibration_json_is_separate_from_source_and_loadable(inputs, tmp_path, capsys):
    transform = Transformer.from_crs(32652, 4326, always_xy=True)
    points = [{'pixel': [x,y], 'map': transform.transform(530000 + x*.25, 3985000-y*.25), 'role': role}
              for x,y,role in [(0,0,'fit'),(300,0,'fit'),(0,240,'fit'),(200,120,'check')]]
    point_path = tmp_path / 'points.json'; point_path.write_text(json.dumps({'reference': 'SYNTHETIC TEST', 'points': points}))
    out = tmp_path / 'calibration' / 'v1.json'
    assert main(['calibrate', '--input-dir', str(inputs), '--image', 'selected.tif',
                 '--points', str(point_path), '--output', str(out)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['verified'] is False and result['absolute_accuracy_m'] is None
    assert json.loads(out.read_text())['fit_rmse_m'] < 1e-5
    assert not list(inputs.glob('*.json'))


def test_cross_source_duplicate_suggestions_keep_distinct_crossings(inputs, tmp_path):
    class FixedPositions(SyntheticDetector):
        def predict(self, rgb):
            # Adjacent but separate crossings must remain separate candidate observations.
            return [{'bbox': [20, 30, 65, 80], 'score': .5}, {'bbox': [95, 30, 140, 80], 'score': .5}]
    images = catalog.scan(inputs)
    g = dict(images[0]['georef'], verified=True, verification_note='SYNTHETIC aligned fixture')
    # Use the same coordinate transform for two synthetic originals.
    data = job()
    data['area'] = {'space': 'map', 'geometry': mapping(geo.to_map(box(0, 0, 200, 200), g))}
    data['images'] = [{'path': n, 'georef': g} for n in ('selected.tif', 'unused.tif')]
    area, images = prepare_job(inputs, data)
    execute(inputs, area, images, data['config'], tmp_path / 'duplicates', FixedPositions())
    bundle = read_bundle(tmp_path / 'duplicates', allow_test=True)
    cs = bundle['candidates']
    assert len(cs) == 4
    assert all(len(c['possible_duplicates']) == 1 for c in cs)
    by_id = {c['id']: c for c in cs}
    assert all(by_id[c['possible_duplicates'][0]]['bbox_pixels'] == c['bbox_pixels'] for c in cs)
    assert all(by_id[c['possible_duplicates'][0]]['source_id'] != c['source_id'] for c in cs)


def test_all_nodata_is_unknown_and_not_facility_absence(inputs, tmp_path):
    path = inputs / 'selected.tif'
    with rasterio.open(path, 'r+') as ds:
        ds.nodata = 0
        ds.write(np.zeros((3, ds.height, ds.width), dtype='uint8'))
    class MustNotRun(SyntheticDetector):
        def predict(self, rgb): raise AssertionError('cannot infer on nodata-only windows')
    data = job(); area, images = prepare_job(inputs, data)
    execute(inputs, area, images, data['config'], tmp_path / 'nodata', MustNotRun())
    bundle = read_bundle(tmp_path / 'nodata', allow_test=True)
    assert not bundle['candidates']
    assert bundle['counts']['unobservable_tiles'] == len(bundle['tiles'])
    assert all(t['status'] == 'unobservable_nodata' for t in bundle['tiles'])
    assert not bundle.get('confirmed_absence')

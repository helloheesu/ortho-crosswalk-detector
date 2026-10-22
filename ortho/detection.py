"""Stage 1: selected imagery -> raw observations. No Flask, review logic or DB."""
import copy
import importlib.metadata
import importlib.util
import math
import platform
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from affine import Affine
from pyproj import CRS
from rasterio.windows import Window
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

from . import catalog, geo
from .models import load_detector, configure_runtime
from .records import digest, now, uid, write_json, output_outside_inputs
from .settings import DEFAULT_CONFIDENCE, DEFAULT_TILE_SIZE, DEFAULT_OVERLAP, resolve_model

JOB_VERSION = '1.0'


class DetectionFailed(RuntimeError):
    def __init__(self, error, manifest):
        super().__init__(str(error))
        self.manifest = manifest


def validate_config(config):
    out = dict(config)
    for key, default in [('tile_size', DEFAULT_TILE_SIZE), ('overlap', DEFAULT_OVERLAP), ('margin', 128), ('max_tiles', 2000)]:
        value = out.get(key, default)
        if isinstance(value, bool) or int(value) != float(value):
            raise ValueError(f'{key}는 정수여야 합니다')
        out[key] = int(value)
    out['confidence'] = float(out.get('confidence', DEFAULT_CONFIDENCE))
    out['iou'] = float(out.get('iou', .7))
    out.setdefault('device', 'cpu')
    size = out['tile_size']
    if not (128 <= size <= 2048 and size % 32 == 0 and 0 <= out['overlap'] < size
            and 0 <= out['margin'] <= 2048 and 0 < out['confidence'] < 1
            and 0 < out['iou'] <= 1 and 1 <= out['max_tiles'] <= 100000):
        raise ValueError('타일 128~2048 (32배수), 0≤겹침<타일, 여유 0~2048, 점수/IoU 범위와 타일 한도를 확인하세요')
    return out


def validate_georef(value):
    if value is None:
        return None
    result = copy.deepcopy(value)
    CRS.from_user_input(result['crs'])
    values = result['transform']
    if len(values) != 6 or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                                   and math.isfinite(v) for v in values):
        raise ValueError('좌표 변환에는 유한한 숫자 6개가 필요합니다')
    if abs(Affine(*values).determinant) < 1e-15:
        raise ValueError('역변환할 수 없는 좌표 변환입니다')
    if type(result.get('verified', False)) is not bool:
        raise ValueError('verified는 true/false여야 합니다')
    if result.get('verified') and not str(result.get('verification_note', '')).strip():
        raise ValueError('중첩 점검 근거 verification_note를 기록하세요')
    return result


def pixel_region(area, source):
    region = geo.polygon(area['geometry'])
    return geo.to_pixel(region, source['georef']) if area['space'] == 'map' else region


def prepare_job(input_dir, description):
    """Read headers; select only explicitly named images. No pixel reads or inference."""
    if description.get('schema_version') != JOB_VERSION:
        raise ValueError('지원하는 작업 정의 schema_version은 1.0입니다')
    area = copy.deepcopy(description['area'])
    if area.get('space') not in ('pixel', 'map'):
        raise ValueError('작업 영역 space는 pixel 또는 map입니다')
    region = geo.polygon(area['geometry'])
    if area['space'] == 'map' and not (-180 <= region.bounds[0] < region.bounds[2] <= 180
                                     and -80 <= region.bounds[1] < region.bounds[3] <= 84):
        raise ValueError('지도 영역은 WGS84 경위도, 위도 -80~84 범위여야 합니다')
    selections = description.get('images', [])
    if not selections or (area['space'] == 'pixel' and len(selections) != 1):
        raise ValueError('사용 영상을 명시하세요. 픽셀 작업은 영상 한 개를 선택합니다')
    images = catalog.scan(input_dir)
    selected = []
    seen = set()
    for entry in selections:
        relative = entry['path']
        im = catalog.select_image(images, relative)
        if im['id'] in seen:
            raise ValueError('같은 영상을 중복 선택할 수 없습니다: ' + str(relative))
        seen.add(im['id'])
        g = validate_georef(entry.get('georef', im.get('georef')))
        source = {'image_id': im['id'], 'georef': g}
        if area['space'] == 'map' and g is None:
            raise ValueError('지도 영역에는 선택 영상의 지리참조가 필요합니다')
        pixels = pixel_region(area, source)
        bounds = geo.pixel_polygon([0, 0, im['width'], im['height']])
        if area['space'] == 'pixel' and not bounds.covers(pixels):
            raise ValueError('픽셀 작업 영역이 영상 밖입니다')
        if pixels.intersection(bounds).area <= 0:
            raise ValueError('선택한 영상이 분석 영역과 겹치지 않습니다: ' + relative)
        selected.append(source)
    area.update(id=uid('area'), name=str(area.get('name', '분석 영역')), images=selected)
    if area['space'] == 'pixel':
        area['image_id'] = selected[0]['image_id']
    area['coverage'] = coverage(area, images)
    return area, images


def coverage(area, images):
    region = geo.polygon(area['geometry'])
    if area['space'] == 'pixel':
        return {'space': 'pixel', 'missing': mapping(region.difference(region)),
                'unverified': None, 'area_m2': None,
                'note': '영상 내부 픽셀 영역. 지도 위치·내부 가림·nodata는 별도 확인.'}
    by_id = {im['id']: im for im in images}
    covered = []
    checked = []
    for source in area['images']:
        im = by_id[source['image_id']]
        footprint = geo.to_map(geo.pixel_polygon([0, 0, im['width'], im['height']]), source['georef'])
        cut = region.intersection(footprint)
        covered.append(cut)
        if source['georef'].get('verified'):
            checked.append(cut)
    missing = region.difference(unary_union(covered))
    pending = region.difference(unary_union(checked)).difference(missing)
    return {'space': 'map', 'missing': mapping(missing), 'unverified': mapping(pending),
            'note': '선택한 영상 외곽 기준. 내부 nodata·가림은 유효 관측으로 확정하지 않음.'}


def plan_tiles(area, images, config):
    config = validate_config(config)
    by_id = {im['id']: im for im in images}
    plan = []
    for source in area['images']:
        if source['image_id'] not in by_id:
            raise ValueError('선택한 입력 영상을 찾을 수 없습니다')
        im = by_id[source['image_id']]
        region = pixel_region(area, source)
        expanded = region.buffer(config['margin'], join_style=2).intersection(
            geo.pixel_polygon([0, 0, im['width'], im['height']]))
        if expanded.is_empty:
            continue
        l, t, r, b = expanded.bounds
        for y in range(max(0, math.floor(t)), math.ceil(b), config['tile_size'] - config['overlap']):
            for x in range(max(0, math.floor(l)), math.ceil(r), config['tile_size'] - config['overlap']):
                tile = [x, y, min(x + config['tile_size'], im['width']), min(y + config['tile_size'], im['height'])]
                if expanded.intersection(geo.pixel_polygon(tile)).area > 0:
                    plan.append((source, im, region, tile))
                    if len(plan) > config['max_tiles']:
                        raise ValueError('타일 한도를 초과했습니다. 분석 영역을 줄이세요')
    if not plan:
        raise ValueError('읽을 타일이 없습니다')
    return plan


def execute(input_dir, area, images, config, output_dir, detector=None, progress=None, run_id=None):
    """Run the same engine from CLI or the legacy app; publish no review records."""
    folder = output_outside_inputs(input_dir, output_dir)
    if folder.exists():
        raise ValueError('새 출력 폴더를 지정하세요. 이전 실행을 덮어쓰지 않습니다')
    config = validate_config(config)
    if area.get('legacy_multitile_review_only'):
        raise ValueError('기존 근거 타일은 검수 재사용용입니다. 원본에서 새 작업 영역을 지정하세요')
    if area['space'] == 'map' and any(not (s.get('georef') or {}).get('verified') for s in area['images']):
        raise ValueError('지도 분석 전 선택 영상의 중첩 점검 완료를 기록하세요')
    plan = plan_tiles(area, images, config)
    fingerprints = {}
    for source, im, _, _ in plan:
        if im['id'] not in fingerprints:
            fingerprints[im['id']] = dict(catalog.fingerprint(input_dir, im), width=im['width'], height=im['height'],
                                             bands=im['bands'], resolution=im['resolution'], resolution_units=im['resolution_units'])
            saved = (source.get('georef') or {}).get('source_fingerprint')
            if saved and (saved['sha256'] != fingerprints[im['id']]['sha256']
                          or sorted(saved.get('sidecars', []), key=lambda x: x['relative_path'])
                          != sorted(fingerprints[im['id']]['sidecars'], key=lambda x: x['relative_path'])):
                raise ValueError('보정 기준의 원본 해시가 현재 입력과 다릅니다')
    if detector is None:
        config = validate_config(resolve_model(config))
        configure_runtime(folder.parent / 'runtime')
        detector = load_detector(config)
    folder.mkdir(parents=True)
    (folder / '.gitignore').write_text('*\n')
    ident = run_id or uid('run')
    manifest = {'id': ident, 'area_id': area['id'], 'status': 'running', 'started_at': now(),
                'config': config, 'model': detector.metadata,
                'origin': 'model' if detector.metadata.get('backend') in ('ultralytics', 'grounding_dino') else 'test_only',
                'sources': fingerprints, 'area_snapshot': area, 'tile_count': len(plan),
                'pixel_policy': 'RGB; dtype range to uint8; nodata=0; nearest; no native-pixel downsampling',
                'environment': {'python': platform.python_version(), 'platform': platform.platform(),
                    'packages': {p: importlib.metadata.version(p) for p in ('rasterio', 'numpy', 'shapely', 'pyproj', 'Pillow')},
                    'inference_packages': {p: importlib.metadata.version(p) for p in ('ultralytics', 'torch', 'torchvision', 'transformers', 'safetensors', 'tokenizers', 'huggingface_hub')
                                           if importlib.util.find_spec(p) is not None}},
                'code_sha256': {p.name: digest(p) for p in Path(__file__).parent.glob('*.py')}}
    write_json(folder / 'started.json', manifest)
    observations = []
    tiles = []
    try:
        for index, (source, im, region, b) in enumerate(plan):
            with rasterio.open(catalog.image_path(input_dir, im)) as ds:
                arr, nodata = catalog.rgb(ds, Window(b[0], b[1], b[2] - b[0], b[3] - b[1]))
            size = config['tile_size']
            padded = np.zeros((size, size, 3), dtype='uint8')
            padded[:arr.shape[0], :arr.shape[1]] = arr
            tile_id = f'{index:06d}'
            path = folder / (tile_id + '.png')
            Image.fromarray(padded).save(path)
            tiles.append({'id': tile_id, 'image_id': im['id'], 'bbox': b, 'path': path.name,
                          'nodata_fraction': nodata, 'sha256': digest(path),
                          'status': 'unobservable_nodata' if nodata == 1 else 'inferred'})
            if progress:
                progress({'run_id': ident, 'status': 'running', 'done': index, 'total': len(plan)})
            if nodata == 1:
                continue
            for raw in detector.predict(padded):
                local = raw['bbox']
                score = raw['score']
                if (len(local) != 4 or not all(isinstance(v, (float, int)) and math.isfinite(v) for v in local)
                        or not local[0] < local[2] or not local[1] < local[3]
                        or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1):
                    raise ValueError('모델의 박스·점수 형식이 잘못되었습니다')
                box = [max(b[0], local[0] + b[0]), max(b[1], local[1] + b[1]),
                       min(b[2], local[2] + b[0]), min(b[3], local[3] + b[1])]
                if not (box[0] < box[2] and box[1] < box[3]):
                    continue
                catalog.validate_box(box, im)
                obj = geo.pixel_polygon(box)
                relation = ('inside' if region.covers(obj) else
                            'boundary' if region.intersection(obj).area > 0 else 'context_only')
                observations.append({'id': uid('observation'), 'image_id': im['id'], 'bbox': box,
                    'raw_tile_output': raw, 'score': score, 'tile_id': tile_id, 'tile_bbox': b,
                    'area_relation': relation, 'tile_clipped': local[0] <= 1 or local[1] <= 1
                        or local[2] >= arr.shape[1] - 1 or local[3] >= arr.shape[0] - 1,
                    'source_clipped': box[0] <= 1 or box[1] <= 1 or box[2] >= im['width'] - 1 or box[3] >= im['height'] - 1,
                    'nodata_fraction': nodata, 'georef': source['georef']})
        for source, im, _, _ in plan:
            catalog.image_path(input_dir, im)
        manifest.update(status='complete', completed_at=now(), tiles=tiles, observations=observations)
        from .exchange import write_bundle
        write_bundle(folder, manifest)
    except Exception as exc:
        manifest.update(status='failed', error=str(exc), completed_at=now(), tiles=tiles, observations=observations)
        # An interrupted/failed run must not look like a completed exchange package.
        (folder / 'candidates.json').unlink(missing_ok=True)
        (folder / 'candidates.geojson').unlink(missing_ok=True)
        write_json(folder / 'manifest.json', manifest)
        raise DetectionFailed(exc, manifest) from exc
    write_json(folder / 'manifest.json', manifest)
    if progress:
        progress({'run_id': ident, 'status': 'complete', 'done': len(tiles), 'total': len(plan)})
    return manifest

"""Versioned stage-1 exchange package; portable evidence and no review/OSM state."""
import copy
import json
import math
from pathlib import Path

from shapely.geometry import mapping
from . import geo
from .records import digest, write_json

BUNDLE_VERSION = '1.0'
KIND = 'ortho-crosswalk-candidates'


def _map_geometry(candidate):
    if candidate.get('georef'):
        return geo.to_map(geo.pixel_polygon(candidate['bbox']), candidate['georef'])
    return None


def write_bundle(folder, manifest):
    if manifest['status'] != 'complete':
        raise ValueError('완료된 실행만 후보 교환 데이터로 만들 수 있습니다')
    folder = Path(folder)
    sources = []
    for source in manifest['area_snapshot']['images']:
        fingerprint = manifest['sources'].get(source['image_id'])
        if fingerprint:
            sources.append(dict(fingerprint, id=source['image_id'], georef=source['georef']))
    tiles = {t['id']: t for t in manifest['tiles']}
    candidates = []
    geometries = {}
    for ob in manifest['observations']:
        if ob['area_relation'] == 'context_only':
            continue
        t = tiles[ob['tile_id']]
        g = ob['georef']
        geometry = _map_geometry(ob)
        geometries[ob['id']] = geometry
        candidates.append({'id': ob['id'], 'source_id': ob['image_id'], 'bbox_pixels': ob['bbox'],
            'score': ob['score'], 'origin': manifest['origin'], 'area_relation': ob['area_relation'],
            'location_status': 'map_estimated' if g and g.get('verified') else 'map_unverified' if g else 'pixel_only',
            'geometry': mapping(geometry) if geometry is not None else None,
            'observation_id': ob['id'], 'tile_id': ob['tile_id'],
            'oriented_corners_tile': ob['raw_tile_output'].get('oriented_corners'),
            'evidence': {'path': t.get('path', t['id'] + '.png'), 'sha256': t['sha256'],
                         'source_pixel_window': t['bbox']},
            'limitations': {'tile_clipped': ob['tile_clipped'], 'source_clipped': ob['source_clipped'],
                            'nodata_fraction': ob['nodata_fraction']},
            'possible_duplicates': []})
    # Strong overlap suggests observations to compare; no physical facilities are merged.
    from shapely import STRtree
    grouped = {}
    checked_map = []
    for c in candidates:
        grouped.setdefault(c['source_id'], []).append(c)
        if (next(s['georef'] for s in sources if s['id'] == c['source_id']) or {}).get('verified'):
            checked_map.append(c)
    def suggest(group, geoms, different_sources=False):
        if not group: return
        tree = STRtree(geoms)
        for i, a in enumerate(geoms):
            for index in tree.query(a):
                j = int(index)
                if j <= i or (different_sources and group[i]['source_id'] == group[j]['source_id']):
                    continue
                b = geoms[j]
                union = a.union(b).area
                if union and a.intersection(b).area / union >= .65:
                    group[i]['possible_duplicates'].append(group[j]['id'])
                    group[j]['possible_duplicates'].append(group[i]['id'])
    for group in grouped.values():
        suggest(group, [geo.pixel_polygon(c['bbox_pixels']) for c in group])
    suggest(checked_map, [geometries[c['id']] for c in checked_map], True)
    model = copy.deepcopy(manifest['model'])
    if model.get('config', {}).get('weights'):
        model['config']['weights'] = Path(model['config']['weights']).name
    bundle = {'schema_version': BUNDLE_VERSION, 'kind': KIND, 'status': 'complete',
              'bundle_id': 'bundle-' + manifest['id'], 'run_id': manifest['id'], 'origin': manifest['origin'],
              'coordinate_convention': {'pixels': 'top-left outer corner; x right, y down; [left, top, right, bottom]',
                                        'map': 'GeoJSON WGS84 [longitude, latitude]'},
              'area': {k: manifest['area_snapshot'].get(k) for k in ('space', 'geometry', 'name', 'coverage')},
              'model': model, 'sources': sources, 'tiles': manifest['tiles'], 'candidates': candidates,
              'counts': {'candidates': len(candidates), 'raw_observations': len(manifest['observations']),
                         'context_only_observations': sum(o['area_relation'] == 'context_only' for o in manifest['observations']),
                         'unobservable_tiles': sum(t.get('status') == 'unobservable_nodata' for t in manifest['tiles'])},
              'limits': ['Candidates are unconfirmed observations, not OSM edit objects.',
                         'Model scores are not calibrated probabilities.',
                         'Empty results do not establish absence in masked/occluded areas.']}
    features = [{'type': 'Feature', 'id': c['id'], 'geometry': c['geometry'],
                 'properties': {k: v for k, v in c.items() if k != 'geometry'}} for c in candidates]
    write_json(folder / 'candidates.geojson', {'type': 'FeatureCollection', 'features': features,
                                             'schema_version': BUNDLE_VERSION, 'origin': manifest['origin']})
    write_json(folder / 'candidates.json', bundle)
    return bundle


def read_bundle(path, verify_evidence=True, allow_test=False):
    """Consumer entrypoint. Resolve assets only inside the bundle, independent of originals/DB."""
    path = Path(path).resolve()
    if path.is_dir():
        path = path / 'candidates.json'
    data = json.loads(path.read_text())
    if (data.get('schema_version') != BUNDLE_VERSION or data.get('kind') != KIND or data.get('status') != 'complete'
            or not isinstance(data.get('run_id'), str) or not data['run_id']
            or data.get('bundle_id') != 'bundle-' + data['run_id']):
        raise ValueError('지원하는 완료 후보 교환 데이터가 아닙니다')
    if data.get('origin') not in ('model', 'test_only') or (data['origin'] == 'test_only' and not allow_test):
        raise ValueError('테스트 전용 결과는 실제 탐지 데이터로 읽을 수 없습니다')
    sources = {s['id']: s for s in data['sources']}
    if len(sources) != len(data['sources']):
        raise ValueError('원본 ID가 중복됐습니다')
    tiles = {t['id']: t for t in data['tiles']}
    if len(tiles) != len(data['tiles']):
        raise ValueError('타일 ID가 중복됐습니다')
    checked = set()
    for tile in data['tiles']:
        relative = Path(tile['path'])
        resolved = (path.parent / relative).resolve()
        if relative.is_absolute() or not resolved.is_relative_to(path.parent):
            raise ValueError('근거 이미지는 교환 데이터 폴더 안의 상대 경로여야 합니다')
        if tile['image_id'] not in sources:
            raise ValueError('타일의 원본 참조가 잘못됐습니다')
        if verify_evidence and (not resolved.is_file() or digest(resolved) != tile['sha256']):
            raise ValueError('근거 이미지가 없거나 해시가 일치하지 않습니다')
        checked.add((tile['path'], tile['sha256']))
    ids = {c['id'] for c in data['candidates']}
    if len(ids) != len(data['candidates']):
        raise ValueError('후보 ID가 중복됐습니다')
    for c in data['candidates']:
        b = c['bbox_pixels']
        if (c['source_id'] not in sources or c['tile_id'] not in tiles or c['origin'] != data['origin']
                or len(b) != 4 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in b)
                or not 0 <= b[0] < b[2] or not 0 <= b[1] < b[3]
                or not isinstance(c['score'], (int, float)) or not math.isfinite(c['score']) or not 0 <= c['score'] <= 1
                or c['area_relation'] not in ('inside', 'boundary')
                or c['location_status'] not in ('pixel_only', 'map_unverified', 'map_estimated')):
            raise ValueError('후보의 참조·좌표·점수 형식이 잘못됐습니다')
        tile = tiles[c['tile_id']]
        source = sources[c['source_id']]
        window = tile['bbox']
        if not (0 <= b[0] < b[2] <= source['width'] and 0 <= b[1] < b[3] <= source['height']
                and window[0] <= b[0] < b[2] <= window[2] and window[1] <= b[1] < b[3] <= window[3]):
            raise ValueError('후보 박스가 원본 또는 근거 타일 밖입니다')
        if (tile['image_id'] != c['source_id'] or (c['evidence']['path'], c['evidence']['sha256']) not in checked
                or c['evidence']['path'] != tile['path'] or c['evidence']['sha256'] != tile['sha256']
                or c['evidence']['source_pixel_window'] != tile['bbox']):
            raise ValueError('후보의 근거 이미지 연결이 잘못됐습니다')
        if not all(ident in ids and ident != c['id'] for ident in c['possible_duplicates']):
            raise ValueError('중복 가능 후보 참조가 잘못됐습니다')
        if (c['geometry'] is None) != (c['location_status'] == 'pixel_only'):
            raise ValueError('지도 형상과 좌표 상태가 일치하지 않습니다')
    return data

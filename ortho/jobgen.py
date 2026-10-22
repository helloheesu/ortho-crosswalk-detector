"""Generate portable pixel-area jobs; no team, assignment, or inference policy."""
import argparse
import json
from pathlib import Path
import re

from . import catalog


def generate(folder, image, name, columns=1, rows=1):
    root = Path(folder).expanduser().resolve()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', name):
        raise ValueError('작업 이름은 영문·숫자·밑줄·하이픈으로 지정하세요')
    if columns < 1 or rows < 1 or columns * rows > 10000:
        raise ValueError('행·열은 양수이고 총 작업 수는 10,000 이하여야 합니다')
    source = catalog.select_image(catalog.scan(root), image)
    width, height = source['width'], source['height']
    if columns > width or rows > height:
        raise ValueError('픽셀 수보다 많이 분할할 수 없습니다')
    entries = []
    for row in range(rows):
        for col in range(columns):
            # Integer boundaries cover every pixel once, including remainder pixels.
            x0, x1 = col * width // columns, (col + 1) * width // columns
            y0, y1 = row * height // rows, (row + 1) * height // rows
            ident = name if columns == rows == 1 else f'{name}-R{row+1}C{col+1}'
            job = {'schema_version': '1.0', 'images': [{'path': source['relative_path']}],
                   'area': {'name': ident, 'space': 'pixel', 'geometry': {
                       'type': 'Polygon', 'coordinates': [[[x0,y0],[x1,y0],[x1,y1],[x0,y1],[x0,y0]]]}},
                   'config': {}}
            entries.append((root / f'{ident}.json', job))
    manifest = root / f'{name}.jobs.json'
    records = entries + [(manifest, {'schema_version': '1.0', 'kind': 'ortho-job-set',
        'image': source['relative_path'], 'width': width, 'height': height,
        'columns': columns, 'rows': rows, 'coordinate_space': 'pixel',
        'coverage': 'full_image', 'jobs': [p.name for p, _ in entries],
        'inference_executed': False})]
    if any(p.exists() for p, _ in records):
        raise ValueError('같은 이름의 JSON 또는 작업 목록이 이미 있습니다. 다른 --name을 지정하세요')
    created = []
    try:
        for path, data in records:
            with path.open('x', encoding='utf-8') as stream:
                created.append(path)
                stream.write(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    except Exception:
        for path in created: path.unlink()
        raise
    return {'jobs': [p.stem for p, _ in entries], 'manifest': str(manifest),
            'columns': columns, 'rows': rows, 'inference_executed': False}


def main():
    p = argparse.ArgumentParser(description='영상 전체 또는 격자 영역의 작업 JSON 생성')
    p.add_argument('folder'); p.add_argument('--image', required=True)
    p.add_argument('--name', required=True)
    p.add_argument('--columns', type=int, default=1); p.add_argument('--rows', type=int, default=1)
    a = p.parse_args()
    try:
        result = generate(a.folder, a.image, a.name, a.columns, a.rows)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError) as exc:
        print(f'실패: {exc}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

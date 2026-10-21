"""Independent stage-1 commands. No review application or database dependency."""
import argparse
import json
import sys
from pathlib import Path

from . import catalog, geo
from .detection import prepare_job, plan_tiles, validate_config, execute
from .exchange import read_bundle
from .records import output_outside_inputs, write_json, uid, now


def read_json(path):
    return json.loads(Path(path).expanduser().read_text())


def load_job(path):
    path = Path(path).expanduser().resolve()
    description = read_json(path)
    for image in description.get('images', []):
        if image.get('georef_file'):
            if 'georef' in image:
                raise ValueError('georef와 georef_file은 하나만 지정하세요')
            gpath = Path(image['georef_file']).expanduser()
            image['georef'] = read_json(gpath if gpath.is_absolute() else path.parent / gpath)
    config = dict(description.get('config', {}))
    if config.get('weights'):
        weights = Path(config['weights']).expanduser()
        config['weights'] = str(weights if weights.is_absolute() else path.parent / weights)
    config.setdefault('class_id', 0)
    return description, config


def selected_image(root, relative):
    images = catalog.scan(root)
    im = next((i for i in images if i['relative_path'] == relative and not i.get('error')), None)
    if im is None:
        raise ValueError('입력 목록에서 사용할 영상의 상대 경로를 선택하세요')
    return im


def output_file(input_dir, path):
    target = output_outside_inputs(input_dir, path)
    if target.exists():
        raise ValueError('새 출력 파일을 지정하세요. 이전 결과를 덮어쓰지 않습니다')
    target.parent.mkdir(parents=True, exist_ok=True)
    # Exclude just this result, without hiding unrelated source files in the parent.
    ignore = target.parent / '.gitignore'
    line = '/' + ''.join('\\' + c if c in '\\!#[]*?' else c for c in target.name)
    old = ignore.read_text() if ignore.exists() else ''
    if line not in old.splitlines():
        ignore.write_text(old + ('\n' if old and not old.endswith('\n') else '') + line + '\n')
    return target


def parser():
    p = argparse.ArgumentParser(description='정사영상 기반 횡단보도 후보 탐지 (검수 DB 없이 실행)')
    sub = p.add_subparsers(dest='command', required=True)
    inspect = sub.add_parser('inspect', help='영상 목록·메타데이터 확인, 픽셀 읽기/추론 없음')
    inspect.add_argument('--input-dir', default='./data/inputs')
    preview = sub.add_parser('preview', help='선택 영상 또는 window의 축소 미리보기')
    preview.add_argument('--input-dir', default='./data/inputs')
    preview.add_argument('--image', required=True, help='입력 폴더 기준 상대 경로')
    preview.add_argument('--bbox', nargs=4, type=float)
    preview.add_argument('--size', type=int, default=1400)
    preview.add_argument('--output', required=True)
    calibrate = sub.add_parser('calibrate', help='기준점 JSON으로 지리참조 버전 작성')
    calibrate.add_argument('--input-dir', default='./data/inputs')
    calibrate.add_argument('--image', required=True)
    calibrate.add_argument('--points', required=True, help='points/reference/verification_note JSON')
    calibrate.add_argument('--output', required=True)
    for name, help_text in [('plan', '선택 영역·영상·읽을 타일 계획 확인, 추론 없음'),
                            ('detect', '실제 로컬 가중치로 추론하고 후보 교환 데이터 생성')]:
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument('--input-dir', default='./data/inputs')
        cmd.add_argument('--job', required=True)
        if name == 'detect':
            cmd.add_argument('--output-dir', required=True)
    validate = sub.add_parser('validate-bundle', help='다른 프로그램에서 후보·근거 해시 확인')
    validate.add_argument('path')
    validate.add_argument('--allow-test', action='store_true', help='합성 테스트 결과임을 명시하고 읽기')
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == 'inspect':
            result = {'images': catalog.scan(args.input_dir), 'inference_executed': False}
        elif args.command == 'preview':
            if not 100 <= args.size <= 1800:
                raise ValueError('미리보기 크기는 100~1800px입니다')
            im = selected_image(args.input_dir, args.image)
            payload = catalog.preview(args.input_dir, im, args.bbox, args.size)
            path = output_file(args.input_dir, args.output)
            path.write_bytes(payload)
            result = {'preview': str(path), 'image_id': im['id'], 'inference_executed': False}
        elif args.command == 'calibrate':
            im = selected_image(args.input_dir, args.image)
            data = read_json(args.points)
            if not str(data.get('reference', '')).strip():
                raise ValueError('기준 지도의 출처 reference를 기록하세요')
            g = geo.fit(data['points'], im['width'], im['height'])
            verified = data.get('verified', False)
            if type(verified) is not bool or (verified and not str(data.get('verification_note', '')).strip()):
                raise ValueError('verified와 중첩 점검 근거 verification_note를 확인하세요')
            g.update(version=uid('georef'), created_at=now(), image_path=im['relative_path'], source_fingerprint=catalog.fingerprint(args.input_dir, im),
                     reference=data['reference'], verified=verified,
                     verification_note=data.get('verification_note', ''))
            path = output_file(args.input_dir, args.output)
            write_json(path, g)
            result = {'georef': str(path), 'verified': verified, 'fit_rmse_m': g['fit_rmse_m'],
                      'check_rmse_m': g['check_rmse_m'], 'absolute_accuracy_m': None}
        elif args.command in ('plan', 'detect'):
            description, config = load_job(args.job)
            area, images = prepare_job(args.input_dir, description)
            config = validate_config(config)
            if args.command == 'plan':
                planned = plan_tiles(area, images, config)
                result = {'area': area, 'tile_count': len(planned),
                          'tiles': [{'source_id': im['id'], 'source_path': im['relative_path'], 'bbox_pixels': b}
                                    for _, im, _, b in planned], 'inference_executed': False}
            else:
                if not config.get('weights'):
                    raise ValueError('작업 config에 실제 횡단보도 weights 경로가 필요합니다')
                result_run = execute(args.input_dir, area, images, config, args.output_dir)
                result = {'run_id': result_run['id'], 'status': result_run['status'],
                          'bundle': str(Path(args.output_dir).expanduser().resolve() / 'candidates.json'),
                          'origin': result_run['origin'], 'tile_count': result_run['tile_count']}
        elif args.command == 'validate-bundle':
            data = read_bundle(args.path, allow_test=args.allow_test)
            result = {'schema_version': data['schema_version'], 'origin': data['origin'],
                      'candidates': len(data['candidates']), 'evidence_integrity': 'verified'}
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (ValueError, TypeError, KeyError, OSError, RuntimeError) as exc:
        print(json.dumps({'status': 'failed', 'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

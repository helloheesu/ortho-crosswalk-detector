#!/usr/bin/env python3
"""Small, standard-library entry point for setup and assigned local jobs."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parent
REVISION = '99634dbb4c3628353a4225df51a266c622891807'
MODEL_SHA = '4bd13c1def936232ca3ca041be0756039150e916e420dc6da3d067f879e83904'
BASE = f'https://raw.githubusercontent.com/UCL-SightLinks/SightLinks-Main/{REVISION}/'


def python():
    return ROOT / '.venv' / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')


def compatible_python():
    """Prefer the existing environment; do not change the system Python."""
    candidates = [str(python())]
    candidates.extend(filter(None, (shutil.which(name) for name in
                      ('python3.12', 'python3.13', 'python3.14', 'python3.11', 'python3'))))
    for candidate in dict.fromkeys(candidates):
        try:
            probe = subprocess.run([candidate, '-c',
                                    'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'],
                                   capture_output=True, timeout=10)
            if probe.returncode == 0:
                return candidate
        except (OSError, subprocess.TimeoutExpired):
            continue
    return None


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def setup():
    if not python().exists():
        subprocess.run([sys.executable, '-m', 'venv', str(ROOT / '.venv')], check=True)
    for lock in ('requirements.lock.txt', 'requirements-yolo.lock.txt'):
        subprocess.run([str(python()), '-m', 'pip', 'install', '-r', lock], cwd=ROOT, check=True)
    target = ROOT / 'models/sightlinks/yolo-n.pt'
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if sha(target) != MODEL_SHA:
            raise ValueError(f'모델 해시 불일치: {target}. 기존 파일을 확인한 뒤 옮기고 setup을 다시 실행하세요.')
    else:
        temporary = target.with_suffix('.download')
        try:
            urllib.request.urlretrieve(BASE + 'models/yolo-n.pt', temporary)
            if sha(temporary) != MODEL_SHA:
                raise ValueError('다운로드한 nano 모델의 SHA256이 일치하지 않습니다')
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    urllib.request.urlretrieve(BASE + 'LICENSE', target.parent / 'LICENSE')
    print('준비 완료. python3 run.py run "자료 폴더" 작업ID 로 실행하세요.', flush=True)


def jobs(folder, ids):
    folder = Path(folder).expanduser().resolve()
    if not folder.is_dir():
        raise ValueError(f'자료 폴더가 없습니다: {folder}')
    selected = []
    for value in ids:
        for name in value.split(','):
            name = name.strip()
            if not re.fullmatch(r'[A-Za-z0-9_-]+', name):
                raise ValueError(f'파일명 확장자 없이 작업 ID를 입력하세요: {name!r}')
            if name in [x[0] for x in selected]:
                continue
            path = folder / f'{name}.json'
            if not path.is_file():
                raise ValueError(f'작업 JSON이 없습니다: {path}. TIFF와 JSON이 있는 폴더를 지정하세요.')
            job = json.loads(path.read_text(encoding='utf-8'))
            if job.get('area', {}).get('name') != name:
                raise ValueError(f'작업 ID와 JSON area.name이 다릅니다: {name}')
            for image in job.get('images', []):
                if not (folder / image['path']).is_file():
                    raise ValueError(f"입력 영상이 없습니다: {image['path']}")
            selected.append((name, path))
    return folder, selected


def cli(args, log):
    command = [str(python()), '-m', 'ortho.cli', *map(str, args)]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    log.write('$ ' + json.dumps(command, ensure_ascii=False) + '\n' + result.stdout + result.stderr + '\n')
    log.flush()
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f'종료 코드 {result.returncode}')
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError('명령은 종료됐지만 JSON 응답을 읽지 못했습니다. '
                           'commands.log와 생성된 bundle을 확인하세요. 탐지 실패와는 별개일 수 있습니다.') from exc


def git(*args):
    try:
        return subprocess.check_output(['git', *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return 'unavailable'


def run(folder, ids, plan_only=False):
    folder, selected = jobs(folder, ids)
    if not python().exists():
        raise ValueError('먼저 python3 run.py setup 을 실행하세요.')
    output = (ROOT / 'work/assigned').resolve()
    if output == folder or folder in output.parents:
        raise ValueError('자료 폴더 안에 결과를 저장할 수 없습니다. 자료 폴더를 저장소 밖에 두세요.')
    commit, dirty = git('rev-parse', 'HEAD'), git('status', '--porcelain')
    for name, job in selected:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
        destination = output / name / stamp
        destination.mkdir(parents=True, exist_ok=False)
        shutil.copy2(job, destination / job.name)
        started = time.monotonic()
        report = {'job_id': name, 'code_commit': commit, 'working_tree_status': dirty,
                  'status': 'running', 'input_dir': str(folder), 'human_review': 'not_performed'}
        print(f'[{name}] 시작 → {destination}', flush=True)
        try:
            with (destination / 'commands.log').open('w', encoding='utf-8') as log:
                plan = cli(['plan', '--input-dir', folder, '--job', job], log)
                (destination / 'plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
                report['tile_count'] = plan['tile_count']
                print(f"[{name}] 계획: {plan['tile_count']}타일", flush=True)
                if plan_only:
                    report['status'] = 'planned_only'
                else:
                    print(f'[{name}] 탐지 중. 상세 로그: {destination / "commands.log"}', flush=True)
                    report['detection'] = cli(['detect', '--input-dir', folder, '--job', job,
                                               '--output-dir', destination / 'bundle'], log)
                    report['validation'] = cli(['validate-bundle', destination / 'bundle'], log)
                    report['status'] = 'validated'
        except (Exception, KeyboardInterrupt) as exc:
            report.update(status='interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed',
                          error=str(exc) or '사용자 중단')
            raise
        finally:
            report['elapsed_seconds'] = round(time.monotonic() - started, 2)
            (destination / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        if not plan_only:
            archive_base = destination.parent / f'{name}__{stamp}'
            archive = shutil.make_archive(str(archive_base), 'zip', root_dir=destination.parent, base_dir=destination.name)
            print(f'[{name}] 검증 완료. 반환 ZIP: {archive}', flush=True)
        else:
            print(f'[{name}] 계획만 확인했습니다. 탐지는 실행하지 않았습니다.', flush=True)


def main(argv=None):
    p = argparse.ArgumentParser(description='설치 한 번, 폴더 경로 + 작업 ID로 로컬 탐지 실행')
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('setup', help='전용 가상환경·의존성·nano 모델 준비 (인터넷 필요)')
    c = sub.add_parser('make-jobs', help='영상 전체(기본) 또는 격자 분할 작업 JSON 생성; 추론 없음')
    c.add_argument('folder', help='영상이 있는 폴더; 생성 JSON도 이곳에 저장')
    c.add_argument('--image', required=True, help='폴더 기준 영상 상대 경로')
    c.add_argument('--name', required=True, help='작업 이름 또는 분할 작업 이름 접두사')
    c.add_argument('--columns', type=int, default=1)
    c.add_argument('--rows', type=int, default=1)
    for name in ('plan', 'run'):
        c = sub.add_parser(name, help='계획만 확인' if name == 'plan' else '계획 → 탐지 → 검증 → 반환 ZIP')
        c.add_argument('folder', help='TIFF와 작업 JSON이 함께 있는 폴더')
        c.add_argument('ids', nargs='+', help='작업 ID; 여러 개는 공백 또는 쉼표로 구분')
    args = p.parse_args(argv)
    try:
        if sys.version_info < (3, 11):
            interpreter = compatible_python()
            if interpreter:
                print(f'Python {sys.version_info.major}.{sys.version_info.minor} 대신 {interpreter} 사용', flush=True)
                return subprocess.run([interpreter, str(Path(__file__).resolve()),
                                       *(sys.argv[1:] if argv is None else argv)]).returncode
            raise ValueError(
                'Python 3.11 이상을 찾지 못했습니다. macOS(Homebrew): '
                'brew install python@3.12 실행 후 python3.12 run.py setup 을 실행하세요. '
                'Windows: Python 3.12 설치 후 py -3.12 run.py setup 을 실행하세요. '
                'Linux: 배포판에서 Python 3.11 이상과 venv 패키지를 설치하세요.')
        if args.command == 'setup':
            setup()
        elif args.command == 'make-jobs':
            if not python().exists():
                raise ValueError('먼저 python3 run.py setup 을 실행하세요.')
            subprocess.run([str(python()), '-m', 'ortho.jobgen', str(Path(args.folder).expanduser().resolve()),
                            '--image', args.image, '--name', args.name,
                            '--columns', str(args.columns), '--rows', str(args.rows)], cwd=ROOT, check=True)
        else:
            run(args.folder, args.ids, plan_only=args.command == 'plan')
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f'실패: {exc}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('사용자가 실행을 중단했습니다. 완료로 처리하지 않습니다.', file=sys.stderr)
        return 130


if __name__ == '__main__':
    raise SystemExit(main())

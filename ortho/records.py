"""Small provenance helpers shared by detection and review, without a database."""
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


def uid(prefix):
    return prefix + '-' + uuid.uuid4().hex


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def write_json(path, data):
    """Atomic single-file publication; never leaves a partial JSON document."""
    path = Path(path)
    temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def output_outside_inputs(input_dir, output):
    source = Path(input_dir).expanduser().resolve()
    target = Path(output).expanduser().resolve()
    if target.is_relative_to(source) or source.is_relative_to(target):
        raise ValueError('출력 경로와 입력 폴더는 서로 포함할 수 없습니다')
    return target

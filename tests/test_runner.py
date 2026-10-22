import importlib.util
import json
from pathlib import Path
import zipfile

import pytest

spec = importlib.util.spec_from_file_location('runner', Path(__file__).parents[1] / 'run.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def prepare(tmp_path, monkeypatch):
    root = tmp_path / 'checkout'
    root.mkdir()
    monkeypatch.setattr(runner, 'ROOT', root)
    monkeypatch.setattr(runner, 'python', lambda: Path(__file__))
    monkeypatch.setattr(runner, 'git', lambda *args: 'test-commit')
    folder = tmp_path / 'input with spaces'
    folder.mkdir()
    (folder / 'source.tif').write_bytes(b'original image')
    for name in ['A', 'B']:
        (folder / f'{name}.json').write_text(json.dumps({'area': {'name': name}, 'images': [{'path': 'source.tif'}]}))
    return root, folder


def test_multiple_jobs_return_only_results(tmp_path, monkeypatch):
    root, folder = prepare(tmp_path, monkeypatch)
    calls = []
    def cli(args, log):
        calls.append(args[0])
        if args[0] == 'plan':
            return {'tile_count': 2}
        if args[0] == 'detect':
            bundle = Path(args[-1]); bundle.mkdir()
            (bundle / 'candidates.json').write_text('{}')
        return {'ok': True}
    monkeypatch.setattr(runner, 'cli', cli)
    runner.run(folder, ['A,B', 'A'])
    assert calls == ['plan', 'detect', 'validate-bundle'] * 2
    archives = list(root.rglob('*.zip'))
    assert len(archives) == 2
    for archive in archives:
        with zipfile.ZipFile(archive) as z:
            assert not any(n.endswith('.tif') for n in z.namelist())
            report = json.loads(z.read(next(n for n in z.namelist() if n.endswith('report.json'))))
            assert report['status'] == 'validated'
            assert report['code_commit'] == 'test-commit'


def test_failed_validation_leaves_report_without_success_zip(tmp_path, monkeypatch):
    root, folder = prepare(tmp_path, monkeypatch)
    def cli(args, log):
        if args[0] == 'validate-bundle':
            raise RuntimeError('bad evidence hash')
        return {'tile_count': 2}
    monkeypatch.setattr(runner, 'cli', cli)
    with pytest.raises(RuntimeError):
        runner.run(folder, ['A'])
    assert not list(root.rglob('*.zip'))
    report = json.loads(next(root.rglob('report.json')).read_text())
    assert report['status'] == 'failed'
    assert 'bad evidence hash' in report['error']


def test_plan_never_detects_and_checks_all_ids_first(tmp_path, monkeypatch):
    root, folder = prepare(tmp_path, monkeypatch)
    calls = []
    def cli(args, log):
        calls.append(args[0]); return {'tile_count': 2}
    monkeypatch.setattr(runner, 'cli', cli)
    with pytest.raises(ValueError):
        runner.run(folder, ['A', 'missing'])
    assert calls == []
    runner.run(folder, ['A'], plan_only=True)
    assert calls == ['plan']
    assert not list(root.rglob('*.zip'))


def test_rejects_wrong_id_and_output_inside_inputs(tmp_path, monkeypatch):
    root, folder = prepare(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        runner.jobs(folder, ['../A'])
    shutil = __import__('shutil')
    shutil.copy2(folder / 'A.json', root / 'A.json')
    shutil.copy2(folder / 'source.tif', root / 'source.tif')
    with pytest.raises(ValueError, match='자료 폴더 안'):
        runner.run(root, ['A'])

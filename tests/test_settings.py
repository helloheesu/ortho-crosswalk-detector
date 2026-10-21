"""Configuration boundaries: no silent provenance changes or model work in plan."""
import json
from pathlib import Path

import pytest

from ortho.cli import main
from ortho.detection import execute, prepare_job
from ortho.models import YoloDetector
from test_detection_cli import SyntheticDetector, inputs, job


def job_file(tmp_path, config):
    data = job(); data['config'] = config
    path = tmp_path / 'job.json'; path.write_text(json.dumps(data))
    return path


def test_bare_job_plans_nano_low_threshold_without_model_work(inputs, tmp_path, monkeypatch, capsys):
    from ortho import detection
    def forbidden(*a, **kw): raise AssertionError('plan must not instantiate a model')
    monkeypatch.setattr(detection, 'load_detector', forbidden)
    path = job_file(tmp_path, {})
    assert main(['plan', '--input-dir', str(inputs), '--job', str(path)]) == 0
    result = json.loads(capsys.readouterr().out); config = result['config']
    assert config['confidence'] == .01 and config['preset'] == 'sightlinks-nano'
    assert config['tile_size'] == 768 and config['overlap'] == 128
    assert Path(config['weights']) == Path.cwd() / 'models/sightlinks/yolo-n.pt'
    assert '/yolo-n.pt' in config['source'] and config['expected_weights_sha256']
    assert result['inference_executed'] is False


def test_cli_model_and_threshold_overrides_are_saved_in_execution(inputs, tmp_path, monkeypatch, capsys):
    from ortho import detection
    received = []
    def fixture(config): received.append(dict(config)); return SyntheticDetector()
    monkeypatch.setattr(detection, 'load_detector', fixture)
    path = job_file(tmp_path, dict(job()['config'], model='nano', confidence=.2))
    out = tmp_path / 'result'
    assert main(['detect', '--input-dir', str(inputs), '--job', str(path), '--output-dir', str(out),
                 '--model', 'medium', '--confidence', '.03']) == 0
    json.loads(capsys.readouterr().out)
    manifest = json.loads((out / 'manifest.json').read_text())
    assert manifest['config'] == received[0]
    assert manifest['config']['preset'] == 'sightlinks-medium'
    assert manifest['config']['confidence'] == .03
    assert manifest['config']['tile_size'] == 256  # Explicit job tiling survives a model switch.
    assert '/yolo-m.pt' in manifest['config']['source']
    assert manifest['origin'] == 'test_only'


def test_explicit_old_custom_job_keeps_its_settings(inputs, tmp_path, capsys):
    config = dict(job()['config'], confidence=.23, weights='custom.pt', source='CUSTOM', license='CUSTOM')
    path = job_file(tmp_path, config)
    assert main(['plan', '--input-dir', str(inputs), '--job', str(path)]) == 0
    saved = json.loads(capsys.readouterr().out)['config']
    assert saved['confidence'] == .23 and saved['tile_size'] == 256
    assert saved['source'] == 'CUSTOM' and saved['license'] == 'CUSTOM'
    assert Path(saved['weights']) == tmp_path / 'custom.pt'
    assert 'preset' not in saved and 'expected_weights_sha256' not in saved


def test_custom_cli_weights_require_provenance_and_clear_preset(inputs, tmp_path, capsys):
    path = job_file(tmp_path, {})
    args = ['plan', '--input-dir', str(inputs), '--job', str(path), '--weights', 'my.pt']
    assert main(args) == 2
    assert '--weight-source' in json.loads(capsys.readouterr().err)['error']
    assert main(args + ['--weight-source', 'CUSTOM', '--weight-license', 'CUSTOM', '--class-id', '4']) == 0
    saved = json.loads(capsys.readouterr().out)['config']
    assert saved['source'] == 'CUSTOM' and saved['class_id'] == 4
    assert Path(saved['weights']) == Path.cwd() / 'my.pt'
    assert not {'preset', 'expected_weights_sha256', 'revision'} & saved.keys()


@pytest.mark.parametrize('threshold', ['0', '1', '-.1', 'nan'])
def test_invalid_cli_threshold_is_rejected_before_inference(inputs, tmp_path, capsys, threshold):
    path = job_file(tmp_path, {}); out = tmp_path / 'bad'
    assert main(['detect', '--input-dir', str(inputs), '--job', str(path), '--output-dir', str(out),
                 f'--confidence={threshold}']) == 2
    assert json.loads(capsys.readouterr().err)['status'] == 'failed'
    assert not out.exists()


def test_python_engine_uses_same_default_model_without_cli(inputs, tmp_path, monkeypatch):
    from ortho import detection
    received = []
    def fixture(config): received.append(dict(config)); return SyntheticDetector()
    monkeypatch.setattr(detection, 'load_detector', fixture)
    data = job(); area, images = prepare_job(inputs, data)
    execute(inputs, area, images, {}, tmp_path / 'api')
    assert received[0]['confidence'] == .01 and received[0]['preset'] == 'sightlinks-nano'


def test_wrong_named_weights_hash_rejected_before_deserialization(tmp_path):
    weights = tmp_path / 'wrong.pt'; weights.write_bytes(b'not a checkpoint')
    with pytest.raises(ValueError, match='해시'):
        YoloDetector({'weights': str(weights), 'source': 'TEST', 'license': 'TEST',
                      'expected_weights_sha256': '0' * 64})

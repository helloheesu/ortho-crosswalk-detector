import json
from ortho import cli


def test_third_party_stdout_does_not_pollute_json(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, 'load_job', lambda path: ({}, {}))
    monkeypatch.setattr(cli, 'execution_config', lambda config, args: {'weights': 'local.pt'})
    monkeypatch.setattr(cli, 'prepare_job', lambda root, job: ({}, []))
    def noisy_execute(*args):
        print('Creating new Ultralytics Settings file')
        print('Settings details {not JSON}')
        return {'id': 'run-1', 'status': 'complete', 'origin': 'model', 'tile_count': 60, 'config': {}}
    monkeypatch.setattr(cli, 'execute', noisy_execute)
    assert cli.main(['detect', '--job', 'job.json', '--output-dir', str(tmp_path/'bundle')]) == 0
    output = capsys.readouterr()
    assert json.loads(output.out)['status'] == 'complete'
    assert 'Ultralytics' in output.err
    assert 'Ultralytics' not in output.out

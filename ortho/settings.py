"""Pinned model presets and shared defaults; no model imports or downloads."""
from pathlib import Path

DEFAULT_MODEL = 'nano'
DEFAULT_CONFIDENCE = .01
DEFAULT_TILE_SIZE = 768
DEFAULT_OVERLAP = 128
SIGHTLINKS_REVISION = '99634dbb4c3628353a4225df51a266c622891807'
MODEL_FIELDS = ('backend', 'weights', 'source', 'license', 'revision', 'class_id',
                'preset', 'expected_weights_sha256')
_VARIANTS = {
    'nano': ('n', '4bd13c1def936232ca3ca041be0756039150e916e420dc6da3d067f879e83904'),
    'medium': ('m', '1bf31821522294e0199d149e20cf7372aa8803cbe8d6c5255901673b7db531ed'),
}


def model_preset(name):
    if name not in _VARIANTS:
        raise ValueError('model은 nano 또는 medium이어야 합니다. 다른 가중치는 weights와 출처·라이선스로 지정하세요')
    variant, sha = _VARIANTS[name]
    filename = f'yolo-{variant}.pt'
    return {'backend': 'ultralytics', 'weights': str((Path.cwd() / 'models' / 'sightlinks' / filename).resolve()),
            'source': f'https://github.com/UCL-SightLinks/SightLinks-Main/blob/{SIGHTLINKS_REVISION}/models/{filename}',
            'license': 'Upstream repository: MIT; checkpoint and Ultralytics runtime: AGPL-3.0',
            'revision': SIGHTLINKS_REVISION, 'class_id': 0, 'preset': 'sightlinks-' + name,
            'expected_weights_sha256': sha}


def resolve_model(config, model=None):
    """Presets own identity fields; explicit custom weights keep their own provenance.

    Preset paths use the working directory. Caller-resolved custom paths retain
    their own base directory. Resolving an already resolved configuration is safe.
    """
    out = dict(config)
    selected = out.pop('model', None)
    if model is not None:
        selected = model
    if selected is not None:
        out.update(model_preset(selected))
    elif not out.get('weights') and out.get('backend', 'ultralytics') == 'ultralytics':
        out.update(model_preset(DEFAULT_MODEL))
    return out

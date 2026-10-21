"""Replaceable detector interface. No automatic weight downloads or fake fallback."""
from pathlib import Path
import os
from typing import Protocol
from .records import digest


class Detector(Protocol):
    metadata: dict
    def predict(self, rgb): ...


def configure_runtime(folder):
    folder=Path(folder).resolve();folder.mkdir(parents=True,exist_ok=True)
    if not (folder/'.gitignore').exists(): (folder/'.gitignore').write_text('*\n')
    os.environ.setdefault('YOLO_CONFIG_DIR',str(folder/'ultralytics'))
    os.environ.setdefault('MPLCONFIGDIR',str(folder/'matplotlib'))
    os.environ['YOLO_OFFLINE']='true'
    os.environ['YOLO_AUTOINSTALL']='false'


class YoloDetector:
    def __init__(self, config):
        p=Path(config['weights']).expanduser().resolve()
        if not p.is_file():
            raise ValueError('횡단보도 가중치 파일이 없습니다. docs/models.md의 다운로드 안내 또는 --weights 설정을 확인하세요')
        if not config.get('source') or not config.get('license'):
            raise ValueError('가중치 출처와 라이선스를 기록해야 합니다')
        weights_sha256 = digest(p)
        if config.get('expected_weights_sha256') and weights_sha256 != config['expected_weights_sha256']:
            raise ValueError('선택 모델의 가중치 해시가 다릅니다. 올바른 공개 가중치를 준비하거나 사용자 가중치로 명시하세요')
        try:
            import ultralytics
        except ImportError:
            raise ValueError('선택 의존성 미설치: pip install -e ".[yolo]"') from None
        ultralytics.settings.update({'sync':False})
        from ultralytics import YOLO
        self.model=YOLO(str(p))
        self.config=config
        self.class_id=int(config['class_id'])
        names=self.model.names
        name=names.get(self.class_id,'') if isinstance(names,dict) else names[self.class_id]
        if name.strip().lower() not in ('crosswalk','crosswalks','zebra_cross','zebra crossing','zebra_crossing','pedestrian_crossing','횡단보도'):
            raise ValueError(f'선택 클래스 {name!r}는 횡단보도 클래스가 아닙니다. 일반 COCO 가중치는 지원하지 않습니다')
        if self.model.task not in ('detect','obb'):
            raise ValueError('객체 탐지 또는 OBB 모델이 필요합니다')
        self.metadata={'backend':'ultralytics','version':ultralytics.__version__,'weights_sha256':weights_sha256,
                       'weights_name':p.name,'source':config['source'],'license':config['license'],
                       'task':self.model.task,'class_id':self.class_id,'class_name':name,'config':dict(config,weights=str(p)),
                       'score_semantics':'model score, not calibrated probability or field accuracy'}

    def predict(self, rgb):
        # Ultralytics ndarray input is BGR. Explicit conversion preserves RGB.
        import numpy as np
        result=self.model.predict(source=np.ascontiguousarray(rgb[:,:,::-1]),
            imgsz=self.config['tile_size'],conf=self.config['confidence'],iou=self.config.get('iou',.7),
            classes=[self.class_id],device=self.config.get('device','cpu'),verbose=False)[0]
        if result.obb is not None:
            for box,score,obb in zip(result.obb.xyxy.cpu().tolist(),result.obb.conf.cpu().tolist(),result.obb.xyxyxyxy.cpu().tolist()):
                yield {'bbox':box,'score':score,'oriented_corners':obb}
        elif result.boxes is not None:
            for box,score in zip(result.boxes.xyxy.cpu().tolist(),result.boxes.conf.cpu().tolist()):
                yield {'bbox':box,'score':score}


class GroundingDinoDetector:
    """Optional local, open-vocabulary baseline; never downloads at inference time."""
    def __init__(self, config):
        folder = Path(config['weights']).expanduser().resolve()
        required = ('model.safetensors', 'config.json', 'preprocessor_config.json',
                    'tokenizer.json', 'tokenizer_config.json', 'special_tokens_map.json', 'vocab.txt')
        if not folder.is_dir() or any(not (folder / f).is_file() for f in required):
            raise ValueError('Grounding DINO 로컬 모델 디렉터리와 safetensors·설정·토크나이저 파일이 필요합니다')
        if not config.get('source') or not config.get('license') or not config.get('revision'):
            raise ValueError('모델 출처·라이선스·고정 revision을 기록해야 합니다')
        prompt = config.get('text_prompt', 'a crosswalk. a zebra crossing.')
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError('text_prompt는 비어 있지 않은 문자열이어야 합니다')
        text_threshold = float(config.get('text_threshold', .2))
        threads = int(config.get('threads', 4))
        if not 0 < text_threshold < 1 or not 1 <= threads <= 64:
            raise ValueError('text_threshold는 0~1, threads는 1~64 범위입니다')
        try:
            import torch
            import transformers
            from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection
        except ImportError:
            raise ValueError('선택 의존성 미설치: pip install -e ".[grounding]"') from None
        torch.set_num_threads(threads)
        self.torch = torch
        self.config = config
        self.prompt = prompt
        self.text_threshold = text_threshold
        self.device = config.get('device', 'cpu')
        self.processor = AutoProcessor.from_pretrained(folder, local_files_only=True, use_fast=False)
        self.model = AutoModelForZeroShotObjectDetection.from_pretrained(
            folder, local_files_only=True, use_safetensors=True).to(self.device).eval()
        files = {p.name: digest(p) for p in folder.iterdir() if p.is_file() and p.suffix in ('.json', '.txt', '.safetensors')}
        self.metadata = {'backend': 'grounding_dino', 'version': transformers.__version__,
            'weights_name': folder.name, 'weights_sha256': files['model.safetensors'],
            'model_files_sha256': files, 'source': config['source'], 'license': config['license'],
            'revision': config['revision'], 'task': 'zero-shot-object-detection',
            'class_name': 'crosswalk (text-conditioned, no local fine-tuning)',
            'text_prompt': prompt, 'text_threshold': text_threshold,
            'image_processor': self.processor.image_processor.to_dict(),
            'config': dict(config, weights=str(folder)),
            'postprocessing': 'threshold filtering; raw boxes preserved, no NMS',
            'score_semantics': 'model score, not calibrated probability or field accuracy'}

    def predict(self, rgb):
        inputs = self.processor(images=rgb, text=self.prompt, return_tensors='pt').to(self.device)
        with self.torch.inference_mode():
            outputs = self.model(**inputs)
        result = self.processor.post_process_grounded_object_detection(
            outputs, inputs.input_ids, threshold=self.config['confidence'],
            text_threshold=self.text_threshold, target_sizes=[rgb.shape[:2]])[0]
        labels = result['text_labels'] if 'text_labels' in result else result['labels']
        for box, score, label in zip(result['boxes'].cpu().tolist(), result['scores'].cpu().tolist(), labels):
            yield {'bbox': box, 'score': score, 'text_label': label,
                   'model_input_size': list(inputs.pixel_values.shape[-2:])}


def load_detector(config):
    backend = config.get('backend', 'ultralytics')
    if backend == 'ultralytics':
        return YoloDetector(config)
    if backend == 'grounding_dino':
        return GroundingDinoDetector(config)
    raise ValueError('지원하지 않는 모델 backend: ' + str(backend))

# 항공 횡단보도 모델 가중치 · 확인일 2026-10-21

## 바로 실행한 공개 가중치

[UCL-SightLinks/SightLinks-Main](https://github.com/UCL-SightLinks/SightLinks-Main)은 항공영상에서 횡단보도를 검출하는 개발팀 공식 저장소다. 같은 팀의 Hugging Face 모델은 접근 동의가 필요하지만, 공식 GitHub 저장소의 `models/yolo-n.pt`, `yolo-s.pt`, `yolo-m.pt`는 인증 없이 공개 다운로드된다. 이 프로젝트에서는 nano와 medium을 실제로 내려받아 기존 Ultralytics 어댑터에서 로컬 CPU 추론·후보 교환 데이터 생성을 확인했다. 별도 학습이나 외부 비전 API가 필요하지 않았다.

[공식 알고리즘 설명](https://students.cs.ucl.ac.uk/2024/group15/algorithms.html)은 YOLO11 OBB를 사용한다고 설명한다. 받은 두 체크포인트의 실제 task는 `obb`, 클래스는 `{0: 'zebra_crossing'}`, 저장 버전은 Ultralytics 8.3.57, 학습 이미지 크기는 1024다. 현재 선택 의존성 Ultralytics 8.4.183에서 실행했다. 회전 코너는 원래 관측에 보존하고, 일반 후보 박스는 축정렬 외접 사각형으로 출력한다.

소스 고정 commit: `99634dbb4c3628353a4225df51a266c622891807`.

| 파일 | 크기(bytes) | SHA256 |
| --- | ---: | --- |
| `yolo-n.pt` | 5,778,620 | `4bd13c1def936232ca3ca041be0756039150e916e420dc6da3d067f879e83904` |
| `yolo-m.pt` | 42,375,886 | `1bf31821522294e0199d149e20cf7372aa8803cbe8d6c5255901673b7db531ed` |

### 출처와 라이선스 기록

[배포 저장소 LICENSE](https://github.com/UCL-SightLinks/SightLinks-Main/blob/99634dbb4c3628353a4225df51a266c622891807/LICENSE)는 MIT를 선언한다. 한편 받은 두 `.pt` 체크포인트의 `license` 필드는 모두 `AGPL-3.0 (https://ultralytics.com/license)`이고, 선택 실행 라이브러리 Ultralytics에도 해당 이용 조건이 적용된다. **가중치에 MIT만 적용된다고 단정하지 않는다.** 공개 모델 파일·저장소 코드·실행 라이브러리·학습 영상의 이용 조건은 같은 항목이 아니다. 모델을 자동 재배포하지 않고 선언과 해시를 실행 기록에 남긴다.

[SightLinks 공개 학습 자료](https://huggingface.co/datasets/SightLinks/YOLO-OBB-Zebra-Crossings-Dataset)의 dataset 페이지에는 license가 `unknown`으로 표시된다. 공개 접근 가능성과 재학습·영상 재배포 권한이 모두 확인됐다는 주장은 구분한다. 이번 로컬 추론에는 그 데이터셋을 다운로드하거나 학습하지 않았다.

## 명시적 다운로드와 실행

저장소 루트에서 실행한다. 아래 코드는 공식 고정 commit의 선택 파일과 LICENSE만 받고 해시를 검사한다. 프로그램의 추론 명령은 자동으로 모델을 다운로드하지 않는다.

```sh
.venv/bin/python -m pip install -r requirements-yolo.lock.txt
.venv/bin/python - <<'PY'
from pathlib import Path
import hashlib
import urllib.request

commit = '99634dbb4c3628353a4225df51a266c622891807'
base = f'https://raw.githubusercontent.com/UCL-SightLinks/SightLinks-Main/{commit}/'
folder = Path('models/sightlinks')
folder.mkdir(parents=True, exist_ok=True)
expected = {
    'yolo-n.pt': '4bd13c1def936232ca3ca041be0756039150e916e420dc6da3d067f879e83904',
    'yolo-m.pt': '1bf31821522294e0199d149e20cf7372aa8803cbe8d6c5255901673b7db531ed',
}
for name, sha in expected.items():
    target = folder / name
    if not target.exists():
        urllib.request.urlretrieve(base + 'models/' + name, target)
    if hashlib.file_digest(target.open('rb'), 'sha256').hexdigest() != sha:
        raise ValueError(f'Unexpected weights hash: {name}')
license_path = folder / 'LICENSE'
if not license_path.exists():
    urllib.request.urlretrieve(base + 'LICENSE', license_path)
PY
```

[SightLinks 작업 정의 예시](../examples/sightlinks-pixel-job.json)의 영상명·영역·가중치 경로를 사용자 입력에 맞춘다. nano 대신 medium을 쓰려면 weights와 source의 파일명을 함께 바꾼다. 출력은 새 폴더를 지정한다.

```sh
.venv/bin/python -m ortho.cli plan --input-dir /path/to/orthophotos \
  --job /path/to/job.json
.venv/bin/python -m ortho.cli detect --input-dir /path/to/orthophotos \
  --job /path/to/job.json --output-dir work/sightlinks-run-001
.venv/bin/python -m ortho.cli validate-bundle work/sightlinks-run-001
```

첫 비교에는 원본 window 768px, 겹침 128px, 여유 128px, 점수 하한 0.20, 타일 내 NMS IoU 0.70을 고정했다. 학습 이미지 크기 1024와 다르며, 모든 해상도·지역에 대한 최적 설정이라는 의미는 아니다. 다른 모델의 같은 숫자 점수도 같은 확률이나 동일한 후보 부담을 뜻하지 않는다. 이 설정을 바꾸어 고를 때는 개발/검증 영역을 사용하고 독립 평가 영역을 별도로 유지한다.

### 현재 nano 예제: 누락을 줄이는 후보 수집

사용자가 누락을 더 큰 비용으로 판단해, 후속 개발 비교에서 nano의 하한 0.20·0.10·0.05·0.02·0.01을 확인했다. 현재 예제는 `confidence: 0.01`로 낮은 점수 관측도 남긴다. 타일·겹침·주변 여유·NMS 설정은 그대로다. `confidence`는 후보를 남기는 모델 점수 하한이며 실제 확률이 아니다. [Ultralytics 추론 설정](https://docs.ultralytics.com/modes/predict/) 참고.

하한을 낮추면 검수 후보와 배경 혼동도 늘어난다. 현재 개발 자료에서는 0.02와 0.01의 느슨한 박스 대응 수가 같았지만, 알려진 후보에 없는 실제 횡단보도의 추가 가능성을 제외하지 않고 누락 우선의 0.01을 선택했다. 후보 부담을 줄이는 비교 설정으로 0.02를 사용할 수 있다. 이 값이 전국 최적값이거나 모든 누락을 해결했다는 뜻은 아니다. 낮은 점수 후보를 후속 검수 단계에서 일괄 삭제하면 수집한 근거를 잃을 수 있으므로 원래 출력·점수를 보존한다.

예제 JSON은 새 작업을 위한 명시적 설정이며 기존 실행 manifest나 다른 모델의 하한을 소급 변경하지 않는다. 하한을 생략한 일반 작업은 실행부의 기존 기본값 0.15를 사용하므로, 이 후보 수집 방침을 적용할 때는 예제처럼 0.01을 명시한다.

## 그 밖의 조사 결과

| 후보 | 확인한 내용 | 바로 비교 가능한가 |
| --- | --- | --- |
| [SightLinks HF 모델](https://huggingface.co/SightLinks/YOLO-OBB-Zebra-Crossings-Satellite) | 항공 횡단보도 YOLO OBB. 모델 카드·가중치 파일에 접근 동의 필요 | HF 경로 대신 공식 GitHub 공개 파일을 사용함. 동의 절차 우회나 개인정보 제공 없음 |
| [CrosswalkNet 공식 저자 저장소](https://github.com/z00bean/CrosswalkNet) | 항공 횡단보도 연구 소개와 결과 이미지. 확인한 기본 브랜치·release 목록에 실행 코드/체크포인트 없음 | 이번 조사에서 가중치 확보 못함. 논문 자체 성능을 이 입력의 성능으로 사용하지 않음 |
| [Dagim1992-Haile 자료](https://github.com/Dagim1992-Haile/crosswalk-detection-satellite-imagery) | 위성영상 50장과 YOLO 형식 라벨. 실행 모델 가중치 없음 | 학습 자료 후보이며 즉시 추론 모델이 아님. 영상 권리 확인 필요 |
| 일반 COCO/DOTA YOLO | 일반 항공 객체 또는 일반 영상 객체의 기본 가중치. 횡단보도 클래스가 있다는 보장이 없음 | 횡단보도 클래스 확인 없이 사용하지 않음 |

## 추가 학습을 준비할 때

공개 모델로 후보를 만들 수 있어도 지역별 누락·배경 혼동은 독립적으로 확인해야 한다. 기존 검수 후보가 있다면 새 모델의 입력이나 자동 확정 정답으로 섞지 않고 명시적인 라벨 자료로 내보낸다.

1. 선택한 학습 구역 전체에서 누락된 횡단보도를 추가하고, 가림·판단 불가 영역을 표시한다. 후보에 없는 영역을 전부 음성으로 두지 않는다.
2. 횡단 줄무늬 전체를 감싸는 박스의 기준을 통일한다. 주차선·도로 빗금·감속 띠·지붕 같은 혼동 배경도 주변 맥락과 함께 전수 라벨 구역에 포함한다.
3. AABB 탐지 모델을 학습할 때는 타이트한 축정렬 박스를 사용할 수 있다. SightLinks OBB를 추가 학습하려면 회전 사각형 네 모서리 라벨이 필요하다. 기존 AABB를 단순히 네 점으로 바꾼 것을 정밀한 회전 정답으로 간주하지 않는다. [공식 OBB 형식](https://docs.ultralytics.com/datasets/obb/) 참고.
4. 타일 생성 전에 train/val/test 구역을 공간적으로 분리한다. 원본·인접 도엽·타일이 달라도 같은 시설은 동일 분할에 속해야 한다. 픽셀 라벨 자체에는 지도 좌표가 필수는 아니지만 여러 원본 간 공간 누수 점검에는 검증된 위치나 명시적인 동일 시설/그룹 대응이 필요하다.
5. 원본/라벨/분할 해시, 모델 출처·라이선스, seed·환경·학습 설정과 실제 best weights를 기록한다. 외부 검수 DB가 아닌 버전 있는 라벨 입력을 사용한다. 현재 독립 탐지 저장소에는 학습 CLI가 없으며, 이전 통합 프로토타입의 검수 DB 기반 학습 코드를 독립 학습 완료로 보지 않는다.

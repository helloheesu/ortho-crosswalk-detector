# 기본값과 실행 설정

2026-10-21부터 실제 실행 기본값은 **SightLinks YOLO11 OBB nano / 점수 하한 0.01**이다. 작업 파일에 모델·점수를 생략해도 적용된다. 입력 폴더는 `./data/inputs/`가 기본이며 계속 `--input-dir`로 변경할 수 있다. 영상·분석 영역은 작업 JSON에 사람이 명시한다. 폴더 등록만으로 전체 영상을 추론하지 않는다.

## 기본 실행

```sh
ortho-crosswalk detect \
  --input-dir /path/to/orthophotos \
  --job /path/to/area.json \
  --output-dir work/run-001
```

`area.json`에는 최소한 `schema_version`, `images`, `area`가 필요하다. `config`는 생략할 수 있다. [기본 작업 예제](../examples/pixel-job.json)는 선택 영역과 새 기본값을 보여 준다.

| 설정 | 생략 시 기본값 | 변경 방법 |
| --- | --- | --- |
| 입력 영상 폴더 | `./data/inputs/` | `--input-dir` |
| 모델 | SightLinks `nano` | `--model nano` 또는 `--model medium`, JSON `config.model` |
| 후보 점수 하한 | `0.01` | `--confidence`, JSON `config.confidence` |
| 기본 모델 파일 | 현재 작업 디렉터리의 `models/sightlinks/yolo-n.pt` | 다른 파일은 `--weights` 또는 JSON `config.weights` |
| 원본 해상도 타일 | 768px | JSON `config.tile_size` |
| 타일 겹침 / 주변 여유 | 128 / 128px | JSON `config.overlap` / `config.margin` |
| 타일 내부 NMS IoU | 0.70 | JSON `config.iou` |
| 실행 장치 | CPU | JSON `config.device` |

가중치는 자동 다운로드하지 않는다. 처음에는 [고정 출처·해시·다운로드 안내](models.md)에 따라 로컬 파일을 준비한다. 기본 nano/medium은 고정된 공개 가중치의 SHA256도 검사한다. 이름이 같아도 다른 파일이면 기본 모델로 실행하지 않는다.

## 실행 시 변경

```sh
# 같은 영역에서 모델과 점수 하한만 변경
ortho-crosswalk detect --input-dir /path/to/orthophotos \
  --job /path/to/area.json --output-dir work/medium-001 \
  --model medium --confidence 0.02

# 추론 전에 실제 적용할 값과 읽을 타일을 확인
ortho-crosswalk plan --input-dir /path/to/orthophotos \
  --job /path/to/area.json --model nano --confidence 0.01
```

`plan`과 `detect`의 응답 `config`는 기본값·작업 설정·실행 옵션을 적용한 값이다. `plan`은 모델을 로드하거나 픽셀을 읽지 않는다. 실제 가중치 파일·클래스·해시는 `detect`에서 검사한다. 완료된 실행 manifest와 교환 데이터의 모델 설정에도 최종 적용값을 남긴다.

일반 설정의 우선순위는 **기본값 → 작업 JSON → 명시적 CLI 옵션**이다. 기존 JSON이 `confidence: 0.20`을 명시했다면 그 값을 유지한다. `--confidence 0.01`을 추가하거나 새 기본값을 사용하려면 해당 키를 생략한다. `--model`은 모델·가중치·출처·라이선스·버전·클래스를 한 묶음으로 바꾸며, 작업 JSON의 타일·점수 설정은 유지한다.

지속적으로 바꿔 쓸 값은 작업 JSON에 저장한다.

```json
{
  "config": {
    "model": "nano",
    "confidence": 0.01,
    "tile_size": 768,
    "overlap": 128,
    "margin": 128
  }
}
```

위 조각은 설정 부분이며 전체 작업 파일에는 선택 영상과 영역도 필요하다. `config.model`을 선택하면 기본 모델의 식별 필드가 적용된다. 사용자 가중치를 직접 지정할 때는 이 키를 빼고 아래 형식을 사용한다.

## 사용자 가중치

현재 Ultralytics 어댑터와 호환되는 다른 횡단보도 `.pt`를 지정할 수 있다. 일반 COCO의 zebra(동물)를 횡단보도로 취급하지 않으며 선택 클래스 이름을 검사한다.

```sh
ortho-crosswalk detect --input-dir /path/to/orthophotos \
  --job /path/to/area.json --output-dir work/custom-001 \
  --weights /path/to/trusted-crosswalk.pt \
  --weight-source '가중치의 확인한 출처 URL' \
  --weight-license '확인한 라이선스' \
  --class-id 0 --confidence 0.03
```

`--weights`로 파일을 바꾸면 `--weight-source`와 `--weight-license`도 함께 지정해야 한다. 기본 모델의 출처·버전·예상 해시를 새 파일에 잘못 붙이지 않는다. 고정 버전은 `--weight-revision`으로 기록할 수 있다. JSON으로 지정하면 기존 형식인 `weights`, `source`, `license`, `class_id`, 필요 시 `backend`·`revision`을 사용한다. Grounding DINO는 `backend: grounding_dino`인 작업 JSON을 사용하며 로컬 모델 폴더와 revision이 필요하다.

경로 기준은 다음과 같다.

- 기본 모델 파일·`--weights`·`--input-dir`: 실행한 현재 작업 디렉터리 기준. 절대 경로도 가능.
- JSON의 직접 `config.weights`: 작업 JSON 파일의 디렉터리 기준.
- `images[].path`: 입력 폴더 기준.

## 모델을 더 비교할 때의 우선순위

현재 개발 자료에서는 nano와 medium의 기존 기록 대응 수가 유사했고 nano의 추론이 더 가벼웠다. 기본값을 nano로 두되 모델을 교체하고 비교하는 경로는 유지한다. 새 모델을 광범위하게 찾는 작업을 현재 진행의 필수 조건으로 두지 않는다.

1. 먼저 공간적으로 분리된 새 평가 구역에서 모델 후보를 보지 않고 전수 라벨과 관측 불가 영역을 만든다. 현재의 97/100은 개발 기록 재대응 수이므로 실제 전체 발견률을 대신하지 못한다.
2. 같은 nano에서 768px/1024px 타일·시작 위치·겹침을 비교한다. 부분 박스와 경계 문제를 모델 교체 없이 얼마나 줄이는지 확인한다. [원 모델 설명](https://students.cs.ucl.ac.uk/2024/group15/algorithms.html)은 1024px 맥락 창을 사용한다. 효과는 실제 비교 후 판단한다.
3. 남는 누락에 medium의 관측이 보완적으로 도움이 되는지 확인한다. 서로 다른 모델·타일의 원래 관측을 보존하고 같은 시설을 무조건 병합하거나 자동 확인하지 않는다.
4. 특정 해상도·도색·그림자에서 누락이 반복되면 현지 라벨 보완·추가 학습 또는 다른 전용 모델을 검토한다. SAM 정밀 분할 등은 전체 횡단보도 후보 박스라는 현재 목적에서 필요성이 확인된 뒤 추가한다.

이 우선순위는 다음 실험 제안이다. 새 독립 평가, 타일 배치 비교, medium 보조 탐지, 추가 학습을 수행했다고 표시하지 않는다. 모델 점수 하한의 뜻은 [Ultralytics 추론 설정](https://docs.ultralytics.com/modes/predict/)을 참고한다.

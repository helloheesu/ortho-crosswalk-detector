# ortho-crosswalk-detector

정사영상의 선택 영역에서 횡단보도 **후보와 시각적 근거**를 추출하는 로컬 도구입니다. 원본·좌표 상태·모델·실행 이력을 보존하고, 후속 검수 도구가 읽을 수 있는 후보 교환 데이터 v1.0을 만듭니다.

## 범위

영상 메타데이터와 미리보기, 픽셀/지도 영역, 기준점 보정, 겹침 타일 추론, 중복 가능 관측, 이동 가능한 후보·근거 묶음을 다룹니다. 사람의 시설 확정, 검수 DB, OSM 편집과 서비스 연결은 포함하지 않습니다. 원본을 수정하지 않으며 위치 미확정·가림·실패 실행을 구분합니다.

## AI 코딩 도구에 맡겨 시작하기

로컬 파일과 터미널을 사용할 수 있는 AI 코딩 도구에 **이 저장소 URL과 정사영상의 로컬 경로**를 전달하면 됩니다. 영상은 저장소에 포함되어 있지 않습니다. 인터넷 연결은 코드·의존성·공개 모델 준비에 필요하며, 탐지는 로컬에서 수행합니다. AI 도구의 실행 권한과 운영체제에 따라 환경 설치에 사용자 조작이 필요할 수 있습니다.

아래 요청문을 복사해서 사용하세요. 작업 담당자가 전달한 작업 ID·영역이 있다면 함께 붙여 주세요.

```text
https://github.com/helloheesu/ortho-crosswalk-detector 를 별도 폴더에 받아
README.md, docs/configuration.md, docs/models.md, docs/detection-cli.md를 읽고
내가 전달한 정사영상으로 실제 탐지를 실행해 줘.

1. Python 3.11 이상을 확인하고 프로젝트 전용 가상환경에
   requirements.lock.txt와 requirements-yolo.lock.txt를 설치해 줘.
   전역 환경을 변경하지 말고 운영체제에 맞는 가상환경 Python 경로를 사용해 줘.
2. docs/models.md의 고정 출처에서 nano 가중치를 준비하고 SHA256을 확인해 줘.
   모델 기본 경로는 저장소 루트 기준 models/sightlinks/yolo-n.pt야.
   저장소 루트에서 명령을 실행하고 nano / confidence 0.01 / CPU로 시작해 줘.
3. inspect와 preview로 영상 크기·좌표정보·미리보기를 확인해 줘.
   배정된 작업 영역이 있으면 그대로 사용해 줘. 없으면 미리보기를 보여 주고
   내가 시험할 작은 영역을 선택하게 해 줘. 전체 영상을 임의로 처리하지 마.
4. examples/pixel-job.json을 참고해 실제 영상 경로와 원본 픽셀 영역으로
   work/<작업ID>/job.json을 작성해 줘. 좌표가 미확정이어도 픽셀 작업은 가능해.
   지도 중첩을 확인하지 않고 verified=true로 만들거나 기준점을 추측하지 마.
5. plan으로 적용 설정과 타일 수를 확인한 뒤 detect를 실행해 줘.
   출력은 work/<작업ID>/<실행ID>/ 아래 새 폴더에 저장하고 validate-bundle로 검사해 줘.
   원본과 기존 결과는 수정하지 마.
6. 근거 이미지를 열어 내가 볼 수 있게 하고, 코드 커밋·환경·작업 JSON·
   실행 명령·설치 문제와 해결 방법·실행 시간·후보 수·bundle_id를 기록해 줘.
   AI 관찰과 사람 검수는 구분하고, 미검수 결과를 정답으로 표시하지 마.
7. 원본·가중치·후보 및 근거 이미지 묶음은 로컬에 보관해 줘.
   공유는 지정된 전달 경로를 사용하고 GitHub에 자동 업로드하지 마.
```

현재 배포에는 검수 웹 UI가 없습니다. AI가 근거 타일을 열어 줄 수 있으며, 탐지 박스 위치는 `candidates.json`에 있습니다. 타일 자체에 박스가 그려져 있다고 가정하지 마세요. 첫 실행 성공 후 범위를 확대하고, 여러 사람의 분담은 [공동 테스트 안내](docs/collaborative-testing.md)를 따릅니다.

## 설치와 실행

Python 3.11 이상이 필요합니다. 먼저 저장소를 clone하고 그 루트에서 실행합니다. 아래는 macOS/Linux 명령이며 Windows에서는 `.venv/bin/python` 대신 `.venv\Scripts\python.exe`를 사용합니다. 운영체제별 새 환경 설치는 아직 모두 검증하지 않았습니다.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
.venv/bin/python -m ortho.cli inspect --input-dir /path/to/orthophotos
.venv/bin/python -m ortho.cli plan --input-dir /path/to/orthophotos --job examples/pixel-job.json
```

예제의 영상·영역·가중치 경로는 실제 입력으로 수정해야 합니다. 실제 추론은 로컬 가중치와 해당 선택 의존성을 준비한 뒤 실행합니다.

실행 기본값은 **SightLinks nano / 후보 점수 하한 0.01**입니다. 작업 파일에 모델·점수를 생략해도 적용됩니다. 기본 가중치는 실행 위치의 `models/sightlinks/yolo-n.pt`에서 읽으며 자동 다운로드하지 않습니다. `--input-dir`처럼 `--model`, `--confidence`, `--weights`로 변경할 수 있습니다. [기본값·우선순위·경로 기준](docs/configuration.md)을 참고하세요.

```sh
.venv/bin/python -m pip install -r requirements-yolo.lock.txt
.venv/bin/python -m ortho.cli detect --input-dir /path/to/orthophotos --job /path/to/job.json --output-dir work/run-001
.venv/bin/python -m ortho.cli validate-bundle work/run-001

# 모델·점수 변경 (기존 작업 JSON의 명시적 값보다 우선)
.venv/bin/python -m ortho.cli plan --input-dir /path/to/orthophotos \
  --job /path/to/job.json --model medium --confidence 0.02
```

Grounding DINO는 선택 실험 어댑터입니다. `requirements-grounding.lock.txt`와 `examples/grounding-pixel-job.json`을 참고하세요. 일반 모델의 텍스트 프롬프트 탐지를 횡단보도 전용 모델의 정확도로 해석하지 않습니다.

항공 횡단보도용 공개 SightLinks YOLO11 OBB 가중치도 실행할 수 있습니다. 개발팀 공식 GitHub의 nano·medium 체크포인트를 기존 어댑터에서 실제 실행했습니다. [고정 출처·해시·라이선스 선언·다운로드 방법](docs/models.md)과 [작업 정의 예시](examples/sightlinks-pixel-job.json)를 제공합니다. 모델 가중치는 이 저장소에 포함하지 않습니다.

현재 SightLinks 실행 예제는 **nano·점수 하한 0.01**로 누락을 줄이는 후보 수집을 우선합니다. 낮은 점수 관측도 보존하므로 사람이 검수할 후보는 늘어납니다. 점수는 실제 확률이 아니며, 이 설정의 선택에는 개발 구역 비교를 사용했습니다. 검증 구역에서 점수 하한·후보 수·누락을 함께 확인해야 합니다.

- [명령과 출력 형식](docs/detection-cli.md)
- [기본값과 설정 변경·추가 모델 검토 순서](docs/configuration.md)
- [구조와 책임 경계](docs/architecture.md)
- [검증 범위](docs/verification.md)
- [실제 모델 비교와 설정 선택 이력](docs/experiments/README.md)
- [항공 횡단보도 모델과 추가 학습 준비](docs/models.md)
- [외부 의존성과 공개 상태](docs/third-party.md)

## 검증

```sh
.venv/bin/python -m pytest -q
```

합성 영상·테스트 대역은 입력·좌표·실행·교환 형식 검증에 사용하며 실제 탐지 성능을 입증하지 않습니다. 가중치·원본 영상·실제 후보·검수 이력은 이 저장소에 포함하지 않습니다.

## 공개 상태

프로젝트 코드의 라이선스는 **GNU AGPL v3.0 only (`AGPL-3.0-only`)**입니다. [LICENSE](LICENSE)와 [외부 의존성·데이터의 경계](docs/third-party.md)를 참고하세요. Copyright (C) 2026 ortho-crosswalk-detector contributors. 이 프로그램은 라이선스에 명시된 범위에서 무보증으로 제공됩니다. 원본 영상·라벨·외부 가중치에 이 라이선스를 새로 부여하지 않습니다. GitHub 게시 여부는 코드 라이선스 선택과 별개입니다.

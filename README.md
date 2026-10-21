# ortho-crosswalk-detector

정사영상의 선택 영역에서 횡단보도 **후보와 시각적 근거**를 추출하는 로컬 도구입니다. 원본·좌표 상태·모델·실행 이력을 보존하고, 후속 검수 도구가 읽을 수 있는 후보 교환 데이터 v1.0을 만듭니다.

## 범위

영상 메타데이터와 미리보기, 픽셀/지도 영역, 기준점 보정, 겹침 타일 추론, 중복 가능 관측, 이동 가능한 후보·근거 묶음을 다룹니다. 사람의 시설 확정, 검수 DB, OSM 편집과 서비스 연결은 포함하지 않습니다. 원본을 수정하지 않으며 위치 미확정·가림·실패 실행을 구분합니다.

## 설치와 실행

Python 3.11 이상이 필요합니다.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
.venv/bin/python -m ortho.cli inspect --input-dir /path/to/orthophotos
.venv/bin/python -m ortho.cli plan --input-dir /path/to/orthophotos --job examples/pixel-job.json
```

예제의 영상·영역·가중치 경로는 실제 입력으로 수정해야 합니다. 실제 추론은 로컬 가중치와 해당 선택 의존성을 준비한 뒤 실행합니다.

```sh
.venv/bin/python -m pip install -r requirements-yolo.lock.txt
.venv/bin/python -m ortho.cli detect --input-dir /path/to/orthophotos --job /path/to/job.json --output-dir work/run-001
.venv/bin/python -m ortho.cli validate-bundle work/run-001
```

Grounding DINO는 선택 실험 어댑터입니다. `requirements-grounding.lock.txt`와 `examples/grounding-pixel-job.json`을 참고하세요. 일반 모델의 텍스트 프롬프트 탐지를 횡단보도 전용 모델의 정확도로 해석하지 않습니다.

항공 횡단보도용 공개 SightLinks YOLO11 OBB 가중치도 실행할 수 있습니다. 개발팀 공식 GitHub의 nano·medium 체크포인트를 기존 어댑터에서 실제 실행했습니다. [고정 출처·해시·라이선스 선언·다운로드 방법](docs/models.md)과 [작업 정의 예시](examples/sightlinks-pixel-job.json)를 제공합니다. 모델 가중치는 이 저장소에 포함하지 않습니다.

현재 SightLinks 실행 예제는 **nano·점수 하한 0.01**로 누락을 줄이는 후보 수집을 우선합니다. 낮은 점수 관측도 보존하므로 사람이 검수할 후보는 늘어납니다. 점수는 실제 확률이 아니며, 이 설정의 선택에는 개발 구역 비교를 사용했습니다. 검증 구역에서 점수 하한·후보 수·누락을 함께 확인해야 합니다.

- [명령과 출력 형식](docs/detection-cli.md)
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

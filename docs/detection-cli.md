# 1번 우선 구현: 독립 탐지 명령과 후보 교환 데이터

독립 탐지 실행과 후보 교환 형식을 제공한다. 실제 모델 성능은 사용 영상과 가중치별로 별도 평가한다.

## 독립 실행

검수 웹 앱, Flask, SQLite DB 없이 `ortho.cli`를 실행할 수 있다. 모델은 `detect` 명령에서만 로드한다. 기본 입력은 `./data/inputs/`이며 모든 명령에서 `--input-dir`로 변경할 수 있다. 후속 검수 앱은 이 저장소에 포함하지 않는다.

```sh
# 파일 목록·크기·해상도·좌표정보·연결 메타데이터만 확인
.venv/bin/python -m ortho.cli inspect --input-dir /path/to/orthophotos

# 선택한 영상의 축소 미리보기. 원본은 수정하지 않음
.venv/bin/python -m ortho.cli preview \
  --input-dir /path/to/orthophotos --image survey-a/sheet-01.tif \
  --output work/previews/sheet-01.png

# 사람이 지정한 영역과 사용 영상으로 타일 계획·영상 없는 부분 확인. 추론 없음
.venv/bin/python -m ortho.cli plan \
  --input-dir /path/to/orthophotos --job /path/to/job.json

# 실제 횡단보도용 로컬 가중치를 준비한 경우에만 추론
.venv/bin/python -m ortho.cli detect \
  --input-dir /path/to/orthophotos --job /path/to/job.json \
  --output-dir work/detection/run-001

# 다른 프로그램에서 원본·검수 DB 없이 교환 데이터의 참조·근거 해시 확인
.venv/bin/python -m ortho.cli validate-bundle work/detection/run-001
```


입력 등록은 분석 실행이 아니다. `inspect`, `plan`은 전체 픽셀 디코딩·추론을 하지 않으며 `preview`는 선택 영상/window를 제한 크기로 읽는다. `detect`도 job에 명시한 영상과 영역에 필요한 타일만 읽는다. 출력은 입력 폴더 바깥의 새 경로에 저장하고 기존 결과를 덮어쓰지 않는다. 결과 폴더/파일에는 Git 제외 규칙을 생성한다. 명령 실패는 stderr JSON과 종료 코드 2로 알린다.

## 작업 정의 job.json

[예시 작업 정의](../examples/pixel-job.json)는 파일 형식 설명용이다. 영상·모델·탐지 결과가 포함된 샘플이 아니다. 사용자는 실제 파일명·분석 영역·가중치 출처와 라이선스로 수정해야 한다.

- `schema_version`: 현재 `1.0`.
- `images`: 사용할 영상만 명시. `path`는 입력 폴더 기준 상대 경로다. 목록에 넣지 않은 영상은 추론하지 않는다.
- `area.space`: `pixel` 또는 `map`. 픽셀 영역은 선택 영상 한 장의 원본 좌표를 사용한다. 지도 영역은 WGS84 경위도 Polygon으로 선택한 여러 영상을 함께 지정할 수 있다.
- `area.geometry`: GeoJSON Polygon. 픽셀 좌표는 좌상단 바깥 모서리 기준 x 오른쪽/y 아래, 지도 좌표는 [경도, 위도]다.
- `images[].georef`: 영상의 내장/부속 좌표정보 대신 사용할 명시적 보정 스냅샷. 생략하면 입력 메타데이터를 사용한다.
- `images[].georef_file`: 보정 스냅샷 JSON을 파일로 참조할 수 있다. 상대 경로는 job.json 기준이다. `georef`와 동시에 지정하지 않는다.
- `config`: 타일 크기·겹침·여유·점수 하한·장치·가중치·클래스·가중치 출처와 라이선스. 상대 가중치 경로도 job.json 기준이다.

`config.backend` 기본은 `ultralytics`이며 로컬 `.pt`의 횡단보도 클래스를 검사한다. 선택값 `grounding_dino`는 로컬 safetensors 모델 디렉터리·출처·라이선스·고정 revision·텍스트 조건으로 실행한다. 전용 모델 학습을 대신하는 성능 보장은 아니다. [설정 예시](../examples/grounding-pixel-job.json)와 [선택 의존성](../requirements-grounding.lock.txt)을 참고한다.

내장 좌표정보는 점검 대기 상태로 읽는다. 지도 영역의 `plan`은 미검증 부분과 선택 영상으로 덮이지 않는 부분을 보여 준다. 지도에서 실제 탐지를 실행하려면 각 보정 스냅샷의 중첩 점검 상태가 `verified: true`여야 한다. 픽셀 작업은 좌표 미확정 상태에서도 가능하다. 다른 CRS는 자동 변환하며, CRS가 다르다는 이유로 기준점을 다시 요구하지 않는다.

지리참조가 있는 경우 작업 정의에서 해당 좌표정보·점검 근거를 명시하거나, 기존 입력·보정 화면에서 저장한 보정 스냅샷을 사용할 수 있다. CLI가 지도 중첩을 스스로 검증해 주지는 않는다.

## 기준점 보정

```sh
.venv/bin/python -m ortho.cli calibrate \
  --input-dir /path/to/orthophotos --image survey-a/sheet-01.tif \
  --points /path/to/control-points.json \
  --output work/calibration/sheet-01-v1.json
```

기준점 JSON에는 `reference`와 `points`를 넣는다. 각 점은 `pixel: [x,y]`, `map: [longitude,latitude]`, `role: fit|check`를 가진다. 사용자가 지정한 실제 점만 사용하며 기준점을 자동 작성하지 않는다. `fit` 3쌍 이상이 필요하고 `check`는 맞춤에 쓰지 않는 검증점이다. 사람이 중첩 점검까지 했다면 `verified: true`와 `verification_note`를 기록한다. 기본은 false다.

출력에는 보정 버전 ID, 기준점·변환 방식·잔차·출처·원본 및 부속파일 해시를 저장한다. 실제 위치 정확도는 `null`이며 잔차와 동일시하지 않는다. 입력 파일을 변경하지 않고 새 보정 파일만 만든다. 다른 입력/부속파일의 보정 스냅샷을 연결하면 탐지 전에 해시 불일치로 중단한다.

## 후보 교환 데이터 v1.0

```text
run-001/                    # Git 제외, 통째로 다른 위치로 복사 가능
  candidates.json           # 버전이 있는 후보 교환 데이터
  candidates.geojson        # 지도 중첩용 후보 영역. OSM 편집 파일이 아님
  000000.png                # 원본 픽셀 크기의 근거 타일
  000001.png
  started.json              # 실행 시작 설정
  manifest.json             # 환경·설정·코드/원본/타일 해시·원래 모델 관측
```

JSON Schema: [candidates-v1.schema.json](../ortho/schemas/candidates-v1.schema.json). 소비자는 `ortho.exchange.read_bundle(path)`로 읽을 수 있다. 이 함수는 원본 영상·검수 DB 없이 버전·참조·후보 좌표·점수·근거 상대 경로와 해시를 검사한다. 전체 패키지를 옮긴 뒤에도 근거 타일을 확인할 수 있다. 임의 고해상도 확대나 범위 밖 원본까지 다시 읽으려면 원본 영상에 별도로 접근해야 한다.

| 데이터 | 내용 |
| --- | --- |
| `bundle_id` / `run_id` | 실행마다 새 ID를 발급하고 묶음을 복사해도 유지. 같은 실행의 교환 묶음은 `bundle-` + run_id로 식별 |
| `sources` | 원본 상대 경로·해시·크기·해상도·부속파일 해시·좌표/보정 버전 |
| `tiles` | 원본 픽셀 window, PNG 상대 경로·해시, nodata 비율과 관측 상태 |
| `candidates` | 후보 ID, 원본 픽셀 bbox, 모델 점수, 근거 타일, 지도 형상·좌표 상태, 경계 잘림, 중복 가능 관측 |
| `model` | 모델 실행부·버전·가중치 식별값·출처·라이선스·설정 |
| `area` | 분석 영역과 선택 영상 기준의 coverage |
| `origin` | 실제 Ultralytics/Grounding DINO 실행은 `model`, 테스트 대역은 `test_only` |

`id`는 후보 관측 ID이며 물리 시설 ID가 아니다. `sources[].id`는 묶음 안의 참조 ID이고, 실행 간 원본 일치는 경로명 대신 SHA256으로 확인한다. 같은 묶음을 다시 가져올 때 `(bundle_id, candidate.id)`를 기준으로 기존 판정을 보존하는 importer는 2단계에서 구현한다.

`inside`는 분석 영역 내부, `boundary`는 영역 경계에 걸친 후보다. `context_only` 원래 관측은 manifest에 보존하고 교환 후보에서는 제외한다. 원본 경계에서 패딩한 타일은 source window 밖에 실제 영상이 존재한다고 보지 않는다. nodata만 있는 타일은 `unobservable_nodata`로 기록한다.

`possible_duplicates`는 강한 형상 겹침의 비교 제안이다. 인접하지만 다른 횡단보도를 합치지 않도록 물리 시설을 자동 병합하지 않는다. 한 시설의 원본별 관측과 서로 다른 시점·해상도는 보존한다. 인접 원본 픽셀은 평균/모자이크하지 않고 원본별 추론을 유지한다.

좌표 상태는 `pixel_only`, `map_unverified`, `map_estimated`로 구분한다. 지도 형상도 영상 후보 bbox를 변환한 추정 영역이다. 모델 점수는 확률/현장 정확도가 아니고, 빈 결과나 가림/nodata를 시설 부재로 간주하지 않는다. 사람 판정·수정 박스·OSM 객체 ID·편집 상태는 교환 데이터의 책임에 포함하지 않는다.

실패 실행은 진단용 manifest만 남기고 완료 후보 교환 데이터를 발행하지 않는다. `read_bundle`은 테스트 결과를 기본 거부한다. 합성 검증에 한해 `allow_test=True` 또는 `validate-bundle --allow-test`로 출처를 확인하며 읽을 수 있다.

## 현재 범위

독립 실행·후보 교환 형식은 구현되어 있다. 실제 모델의 성능은 사용 영상·가중치·설정에 따라 별도로 검증해야 한다. 검수 UI·운영 DB·OSM 편집·서비스 연동은 이 배포에 포함하지 않는다.

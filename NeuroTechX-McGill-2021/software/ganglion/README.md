## 내장 Bluetooth 단계별 SSVEP (GUI 없이)

```bash
bash software/ganglion/start_native.sh
# http://127.0.0.1:8004
```

기존 `.venv-brainflow-validation` 사용. Ganglion firmware 3 대상입니다.
GUI와 capture_brainflow.py를 종료하고 보드를 켭니다. 연결 준비 → 연결 후
수신 중을 확인하고 실제 배치를 입력하여 새 세션을 만듭니다.
단위/필터는 서버에서 µV / raw로 설정합니다. SW1–4는 공통 REF용 DOWN.

- 1단계: 15 Hz 정지 화면 10초 / 깜빡임 10초, 3쌍.
- 2단계: 12/15 Hz, 주파수별 5회 + 시선 이탈 5회, 각 6초.
- 3단계: 10/12/15 Hz, 주파수별 5회 + 시선 이탈 5회, 각 6초.
- 각 구간 전 안내/준비 5초. 단계를 바꿀 때 새 세션을 권장합니다.
- 화면 검사 → 자극 확인란 → 선택한 실험 시작. Esc/탭 숨김은 중단 및 부분 저장.
- 잡음 경고에도 기록하려면 탐색 기록 계속을 명시적으로 체크합니다.
  시간축/화면 오류는 여전히 중단하며 품질 미통과 결과는 분류 성공으로 인정하지 않습니다.
- 하단 탐색용 OFF/ON 표는 품질 실패 구간도 경고와 함께 보여줍니다.
  정식 비교 요약은 유효 구간만 포함합니다. 2개 후보에 1/3 우연 수준 p값을 적용하지 않습니다.
- 원시 EEG, 원본 BrainFlow Unix timestamp, monotonic 변환 시각, 수신 시각,
  자극 후보/정답, 프레임 시각을 `native_recordings/<session>/`에 저장합니다.
- HTTP 구간 제어이며 실제 광출력과 정밀 동기화되지 않습니다. CCA는 확률이 아닙니다.
- 4채널이라는 이유로 자극 4개가 보장되는 것은 아닙니다. 현재 1→2→3 단계를 수동 선택합니다.

# Ganglion SSVEP 로컬 실행 안내

## EEG가 실제로 잡히는지부터 확인하려면

단계별 검증 환경을 먼저 사용하세요. 원시 품질 → 눈 뜸/감음 알파 → 화면 타이밍 →
단일 SSVEP → 3지선다를 분리해 기록합니다. GUI 녹화 파일도 LSL 없이 읽을 수 있습니다.

```bash
bash software/ganglion/start_validation.sh
# http://127.0.0.1:8002
```

- [아침 실험 안내서](docs/MORNING_GUIDE.html): 전극/REF/D_G, GUI 녹화법, 단계별 실행·실패 분기, 논문과 공식 자료
- [기존 파일에서 확인한 문제](docs/EXISTING_RECORDINGS_FINDINGS.md): LSL 역전, 약 83 Hz 기록, 큰 신호 진폭
- [검증 도구의 설계·검사·제한](docs/VALIDATION_TECHNICAL.md)
- [공개 EEG 참고 그림과 해설](validation_reports/reference/index.html): 실제 눈 뜸/감음·SSVEP 예제 (사용자의 기록과 별도)
- `validation_recordings/`: 새 실험 원시 NPZ·세션 JSON·오프라인 HTML 보고서 (Git 제외)
- `validation_reports/audit/index.html`: 기존 GUI/SSVEP 파일 감사 보고서 (로컬 생성물, Git 제외)

아래 안내는 기존 5초 SSVEP 앱에 해당합니다. 새 검증 앱의 실행 경로와 포트가 다릅니다.

이 폴더는 OpenBCI Ganglion 4채널용 초기 SSVEP 실험 앱입니다.
기존 Cyton speller와 별도의 실행 경로이며, DB·AWS·Node.js·언어 모델 없이 실행합니다.
화면과 API를 Python 서버 하나가 제공합니다. 기존 React/Flask 실행 스크립트는 사용하지 않습니다.

```text
Ganglion → OpenBCI GUI → LSL EEG TimeSeries → Python 수집/CCA
                                                   ↕
                                    브라우저 10 / 12 / 15 Hz 자극
```

## 1. 설치 (처음 한 번)

macOS의 Python 3.11 또는 3.12를 사용하세요. 이 작업에서는 Apple Silicon / Python 3.12로 검증했습니다.
터미널에서 저장소 루트로 이동합니다.

```bash
cd /Users/philovepark/Documents/Open_BCI_decoder/NeuroTechX-McGill-2021
python3 -m venv .venv
.venv/bin/python -m pip install -r software/ganglion/requirements-lock.txt
.venv/bin/python software/ganglion/install_macos_lsl.py
```

이 작업이 수행된 현재 노트북에는 `.venv`와 필요한 패키지, liblsl이 준비되어 있습니다.
재설치할 필요 없이 2번부터 진행할 수 있습니다.

설치 스크립트는 공식 liblsl 1.17.7 universal macOS 패키지를 내려받아 SHA-256을 확인하고,
서명된 프레임워크 전체를 `.venv/lsl.framework`에 배치합니다. 시스템 설치나 sudo는 필요하지 않습니다.
프레임워크에서 실행 파일만 꺼내 이름을 바꾸면 macOS 서명 검증이 실패할 수 있으므로 전체 구조를 보존합니다.
앱이 이 위치를 자동으로 인식합니다. 별도의 liblsl을 쓰려면 `PYLSL_LIB`로 직접 지정할 수 있습니다.

## 2. OpenBCI GUI에서 Ganglion 데이터 보내기

1. 이미 연결한 **Ganglion 실제 보드 세션**을 사용합니다. 실험에는 Synthetic 모드를 선택하지 않습니다.
2. Time Series에서 사용할 채널에 신호가 들어오는지 확인합니다.
3. 위젯 선택 메뉴에서 **Networking**을 엽니다.
4. Protocol을 **LSL**로 설정합니다.
5. Stream 1의 Data Type을 **TimeSeries**, Type을 **EEG**로 지정합니다.
6. Name은 `ganglion_eeg`처럼 알아보기 쉬운 이름을 사용합니다. 채널 수는 **4**인지 확인합니다.
7. 가능하면 LSL 출력의 Filters를 **Off**로 두어 앱에서 전처리를 담당하게 합니다. GUI 버전에 따라 항목이 다를 수 있습니다.
8. **Start LSL Stream**과 보드의 **Start Data Stream**이 모두 켜져 있어야 합니다.

FFT / BandPower / Accelerometer 출력은 이 앱의 입력으로 사용하지 않습니다.
GUI의 화면 표시 필터와 LSL 출력 필터가 별개일 수 있으므로 출력 설정을 확인하세요.
현재 경로에서는 GUI가 보드 연결을 담당합니다. 별도로 Python에서 보드 Bluetooth 연결을 열 필요가 없습니다.

공식 설명: [OpenBCI LSL](https://docs.openbci.com/Software/CompatibleThirdPartySoftware/LSL/),
[Networking 위젯](https://docs.openbci.com/Software/OpenBCISoftware/GUIWidgets/).

## 3. 서버 실행

저장소 루트에서:

```bash
bash software/ganglion/start.sh
```

브라우저 주소창에서 **http://127.0.0.1:8000** 을 엽니다.
서버 터미널은 켜 둡니다. 서버 종료는 터미널에서 `Ctrl+C`입니다.
포트가 사용 중이면 `bash software/ganglion/start.sh --port 8001`로 실행하고 같은 포트로 접속합니다.

## 4. 연결 확인과 첫 측정

1. **LSL 스트림 검색**을 누릅니다.
2. Ganglion의 **4ch / 200 Hz** 스트림을 고른 뒤 **연결**을 누릅니다.
3. 화면에 **수신 중**, 수신률이 대략 **200 Hz**로 표시되는지 확인합니다. 값이 안정될 때까지 2~3초 기다립니다.
4. 실제 전극을 연결한 채널만 선택합니다. 기본값은 CH1 하나입니다.
5. `바라볼 자극`에서 A, B, C 중 하나를 선택합니다. 이는 평가용 정답이며 분류기에 정답을 입력하는 것은 아닙니다.
6. **5초 측정 시작**을 누른 뒤 지정한 자극을 바라봅니다.
7. 결과에서 예측, 후보별 CCA 점수, 수신률, 화면 FPS, 저장 파일을 확인합니다.
8. A/B/C를 번갈아 각 10회 이상 측정해 혼동되는 자극과 판정 보류 비율을 확인합니다.

화면: **A=10 Hz, B=12 Hz, C=15 Hz**. 기본 CCA는 기본파와 2차 고조파를 사용합니다.
전극은 후두부 O1/Oz/O2/POz 등이 배치 후보이며, 실제 채널 번호와 위치를 별도로 기록해야 합니다.
미사용·평탄한 채널까지 선택하면 판정을 보류합니다. 좋은 채널 하나부터 확인하고 채널을 추가하세요.

모니터는 우선 고정 60 Hz 이상으로 설정하고 측정 탭을 앞에 둡니다. 화면 주사율을 EEG의 200 Hz와 혼동하지 마세요.
자극은 `requestAnimationFrame`과 시간 기반 사인 밝기로 생성됩니다. 큰 프레임 지연 또는 50 fps 미만이면 판정을 보류합니다.
**즉시 중단** 또는 **Esc**는 깜빡임을 바로 멈춥니다. 다른 탭으로 이동해도 중단됩니다.
중단한 측정은 저장하지 않습니다. 완료된 측정은 판정 보류 결과도 저장합니다.

## 5. 기록과 설정

측정 파일은 `software/ganglion/recordings/*.npz`에 저장되고 Git에는 포함되지 않습니다.

| 항목 | 내용 |
|---|---|
| `samples` | 필터 전 4채널 수신값, `(샘플 수, 4)` |
| `timestamps` | 시간 보정을 적용한 LSL 타임스탬프 |
| `frame_times_ms` | 브라우저의 첫 자극 프레임 기준 프레임 시각 |
| `metadata` | JSON 문자열: 정답, 선택 채널(0부터 시작), 스트림 XML, 샘플링 주파수, 설정, 결과 |

```python
import json
import numpy as np

with np.load("software/ganglion/recordings/파일명.npz", allow_pickle=False) as recording:
    eeg = recording["samples"]
    timestamps = recording["timestamps"]
    metadata = json.loads(str(recording["metadata"]))
    print(eeg.shape, metadata["result"])
```

`config.json`이 화면 주파수와 분류기 후보를 함께 결정합니다. 수정 후 서버를 재시작하고 페이지를 새로고침합니다.
기본 필터는 7~35 Hz, 자극은 5초, 분석에서 시작 0.3초를 제외합니다.
`min_score=0.35`, `min_margin=0.08`은 **검증되지 않은 초기 실험 임계값**입니다.
CCA 점수는 확률이 아니며, 눈을 감거나 자극을 보지 않은 상태에서도 잘못된 선택이 생길 수 있습니다.
후보 주파수나 고조파 수를 바꿀 때 필터 범위와 모니터 주사율도 함께 검토해야 합니다.

이 버전은 HTTP 요청으로 측정 구간을 제어합니다. LSL 시각과 브라우저 상대 프레임 시각은 저장하지만
실제 화면 광출력과 EEG가 정밀 동기화되었다는 의미는 아닙니다. 위상 기반 분류나 정밀 잠복기 실험에는
별도의 마커/포토다이오드 검증이 필요합니다. 현재 목표는 소수 주파수의 초기 CCA 검증입니다.

## 6. 문제 해결

| 증상 | 확인할 사항 |
|---|---|
| 스트림 없음 | GUI의 두 Start 버튼, Type=`EEG`, Data Type=`TimeSeries`, 같은 컴퓨터인지 확인 |
| 스트림이 여러 개 | 이름과 채널 수를 보고 선택. 이 앱은 UID로 연결하므로 자동으로 첫 스트림을 고르지 않음 |
| 8채널로 표시 | Synthetic/Cyton 또는 다른 스트림인지 확인. Ganglion의 4채널 스트림을 선택 |
| 연결됐지만 수신 없음 | 보드 Data Stream 켜기, GUI/보드 연결 상태 확인, 연결 해제 후 다시 연결 |
| liblsl 로딩 실패 | 위 설치 스크립트를 `.venv/bin/python`으로 실행. `PYLSL_LIB`가 오래된 경로를 가리키는지 확인 |
| 판정 보류 | 전극 접촉, 선택 채널, 실제 수신률, 브라우저 프레임 지연, 후보별 점수 확인 |
| 데이터 공백/타임스탬프 오류 | GUI 전송 상태와 패킷 누락 확인. 끊긴 데이터를 정상 EEG처럼 보간해 분류하지 않음 |
| 페이지 연결 실패 | 서버 터미널의 에러와 포트 확인. 주소는 `127.0.0.1:8000` |

화면 없이 LSL 검색만 하려면:

```bash
.venv/bin/python software/ganglion/check_lsl.py
# 출력한 uid로 5초 수신 확인 (데이터 저장/자극 없음)
.venv/bin/python software/ganglion/check_lsl.py --uid '출력된-uid'
```

## 7. 검증 명령과 코드 위치

```bash
.venv/bin/python -m unittest discover -s software/ganglion -v
# 실제 로컬 LSL 소켓으로 합성 EEG를 보내는 선택적 통합 테스트
GANGLION_LSL_TEST=1 .venv/bin/python -m unittest discover -s software/ganglion -v
```

- `app.py`: 로컬 서버, 측정 수명주기, 기록 저장
- `acquisition.py`: 스트림 선택, 연속 수신, LSL 타임스탬프 보존
- `decoder.py`: 일반 CCA, 필터, 데이터 품질 및 점수 검사
- `static/`: 자극 화면과 중단/결과 표시
- `test_ganglion.py`: 합성 신호 분류, 불량 데이터, 저장/API 회귀 테스트
- `test_lsl_integration.py`: 실제 LSL 루프백 통합 테스트 (물리 보드 검증과 구분)

일반 CCA의 최대 정준상관은 중심화한 EEG와 기준 신호의 직교기저 사이 최대 특이값으로 계산합니다.
원본 speller와 같은 분류 원리를 사용하며, NumPy/SciPy로 구현하여 sklearn 및 원본 DB 앱 초기화 의존성을 제거했습니다.
기존 `software/backend/dcp`, `software/frontend`, `signal/`의 Cyton 실행 경로에는 이 변경이 적용되지 않습니다.

## 추가 맞춤 선택 실험
서버 실행 후 `http://127.0.0.1:8004/?mode=custom`에서 후보 2~20개(8~17.5 Hz), 목표 또는 무작위 목표, 횟수(기본 10), 시간을 설정합니다. 새 세션을 만들고 화면 검사·자극 확인 후 시작합니다. 20개 예시는 0.5 Hz 간격의 탐색 구성으로 성능을 보장하지 않습니다. 완료 회차의 보류·품질 실패를 오답으로 포함한 정확도와 회차별 예측을 표시합니다. 상세 결과는 native_recordings 세션 보고서에 저장됩니다. 이번 실행 표는 페이지를 새로 열면 초기화됩니다.

## FBCCA 녹화본 재분석

`fbcca.py`는 200 Hz에 맞춘 오프라인 FBCCA입니다. 실시간 Native 앱은 기존 CCA를 유지합니다.
5개 중첩 Chebyshev-I 대역(하한 6/14/22/30/38, 상한 90 Hz), 5개 고조파,
가중치 `m**(-1.25)+0.25`와 CCA 상관 제곱합을 사용합니다. 상단 저지대역은
200 Hz의 Nyquist를 피하도록 원 참고 구현의 100 Hz에서 95 Hz로 조정했습니다.
원 기록을 수정하지 않고 두 알고리즘에 같은 구간·채널·60 Hz 노치를 적용합니다.
보류 없는 최고 점수 선택 비교이며 FBCCA에는 기존 CCA 문턱을 적용하지 않습니다.
단일 자극 결과는 다중 선택 정확도가 아니고, 시선 이탈에는 별도 거절 기준이 필요합니다.

```bash
.venv-brainflow-validation/bin/python software/ganglion/compare_fbcca.py \
  software/ganglion/native_recordings/20261126T112331Z_7530b4be641c \
  software/ganglion/native_recordings/20261126T115655Z_311b029f6a04 \
  --out software/ganglion/validation_reports/fbcca_comparison
open software/ganglion/validation_reports/fbcca_comparison/index.html
```

출력: HTML 보고서, 회차별 CSV, 설정·대역별 상관·원본 SHA256을 포함한 JSON.

## 개인 보정 → 고정 모델 → 독립 평가

`bash software/ganglion/start_native.sh` 실행 후
`http://127.0.0.1:8004/?mode=personal`을 엽니다. 실제 REF/D_G와 채널 위치를
입력하여 새 세션을 만들고, 정지된 150 CSS px 사각형의 한 변(cm)과 시청 거리,
조명 조건을 기록합니다. 기존 전극/화면 조건을 보정·평가 동안 유지하세요.

1. 실험 준비 → 화면 타이밍 검사 → 자극 확인란 선택.
2. 보정 시작: 12 Hz/15 Hz/시선 이탈 각 15회(총 45회), 블록마다 무작위 순서.
   한 번에 최대 15회 후 멈추므로 쉬고 같은 버튼으로 이어서 진행합니다.
3. 학습·모델 고정: 보정 데이터만으로 15개 블록을 하나씩 제외한 교차검증,
   목표당 3/5/10/14회 학습 곡선, 필터뱅크 eTRCA 및 4항 eCCA 비교.
   교차검증 점수로 거절 문턱을 보정합니다. 문턱 최적화 결과는 독립 성능이 아닙니다.
4. 독립 평가: 새 45회. 두 모델과 문턱을 고정하고, 다시 학습할 수 없습니다.
   평가의 중단/품질 실패는 시도 분모에 남고 재시도하지 않습니다.
   보정 실패는 원 기록을 보존한 채 같은 슬롯을 다시 수집합니다.
5. 서버 재시작 후 같은 조건이라면 세션 ID로 복구합니다. 배치가 바뀌면 새 세션입니다.

자극 6초, 준비 5초. 분석은 자극 첫 rAF 프레임 후 1~5초의 4초입니다.
5회 왕복 시계 측정 중 최소 RTT의 중간점을 사용하고 추정 오차 >10 ms이면 차단합니다.
BLE producer timestamp와 샘플 인덱스의 선형회귀로 균등 시계를 재구성한 다음
200 Hz로 보간합니다. 추정 196~204 Hz, 회귀 RMS <=25 ms, 최대 공백 <=150 ms를
작업 기준으로 사용하며 외삽은 허용하지 않습니다. 원시 시각/데이터는 그대로 보존합니다.
이 기준은 연구용 시작 기준으로 검증된 동기화 정확도가 아닙니다. 광출력 시각,
ADC 시계 및 패킷 누락을 직접 검증한 것으로 해석하면 안 됩니다.
화면 크기/DPR/자극 CSS 크기가 바뀌면 시작 마커를 거절합니다.

학습 모델: 60 Hz Q30 노치, 6/14/22~90 Hz 3개 Chebyshev-I 대역,
가중치 m^-1.25+0.25. eTRCA는 채널 공분산에 trace-scaled 1e-6 ridge를 적용하고
목표별 공간필터를 결합합니다. eCCA는 X-Y, X-template(공동 CCA), X-template(X-Y
필터), X-template(template-Y 필터)의 네 상관을 부호 보존 제곱합으로 결합합니다.
템플릿이나 문턱에 평가 데이터를 넣지 않습니다. 시선 이탈은 주파수 클래스가 아니라
거절 보정 자료입니다. 보정 OOF 시선 이탈 오선택 <=1/15인 문턱 후보 중
목표의 정답 채택 수 - 오답 채택 수가 가장 큰 조합을 선택합니다.

`native_recordings/<session>/`에 원시 NPZ, `session.json`, `personal_model.json`,
`personal_results.json`, `personal_report.html`을 저장합니다. 모델 SHA256과 학습
시행 ID를 기록하며 평가 시 모델 무결성을 확인합니다. 기존 일반 보고서의 CCA 통계와
개인 실험 통계를 섞지 않습니다. 브라우저 표는 전체 정확도, 보류, 오선택, 품질 실패,
유효 시선 이탈의 오선택 수를 따로 표시합니다.

검증 명령:
```bash
.venv-brainflow-validation/bin/python -m unittest discover -s software/ganglion -p 'test_personal.py'
```

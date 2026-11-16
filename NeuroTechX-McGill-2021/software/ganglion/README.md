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

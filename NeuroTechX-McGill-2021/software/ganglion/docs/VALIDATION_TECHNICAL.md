# Ganglion 검증 도구 — 설계와 검증 범위

실험 절차는 [아침 안내서](MORNING_GUIDE.html), 실제 과거 자료의 관찰은
[기존 녹화 감사](EXISTING_RECORDINGS_FINDINGS.md)에 있다. 이 문서는 계산과 저장의 의미를 설명한다.

## 실행 경로

```text
GUI의 Ganglion RAW 저장 ────────────────→ GUI 파일 검사 / EO·EC 비교
       └─ LSL 4ch EEG → Receiver → 단계별 실험 → NPZ + JSON + HTML
선택 비교: GUI 종료 → 별도 BrainFlow 5.24.0 → 직접 수집 NPZ + HTML
소프트웨어 점검: 명시적으로 SYNTHETIC인 신호 → 같은 수집·분석 경로
```

`bash software/ganglion/start_validation.sh`는 `127.0.0.1:8002`만 연다.
외부 서비스나 CDN 없이 동작하며 EEG를 업로드하지 않는다.
기존 `app.py`/`decoder.py`의 5초 실험과 분리했다. 공용 `acquisition.py`에는
진단용 수신 기록을 추가했고 기존 `window()`의 동작은 유지했다.

## 원시 저장과 시간축

완료·중단·타임아웃 구간을 `validation_recordings/UTC시각_ID/`에 저장한다.
세션마다 전극 위치, REF/D_G, 선택 채널, 단위, 출력 필터 상태, 모니터 설정, 메모를 기록한다.
전극이나 설정을 바꾸면 새 세션을 만든다. 서버 재시작 후에는 이전 보고서를 읽을 수 있지만
이전 세션에 이어 기록하지 않는다.

| NPZ 배열 | 의미 |
|---|---|
| `samples` | 수신 순서의 4채널 값. 저장 시 필터·단위 변환하지 않음 |
| `timestamps` | 연결 시 계산한 LSL time correction을 적용한 생산자 시각 |
| `producer_timestamps` | 수신한 원래 LSL 시각 |
| `arrival_timestamps` | Python이 chunk를 읽은 컴퓨터 LSL clock 시각. 같은 chunk는 같은 시각 |
| `sequence` | 연결 이후 수신 순서를 나타내는 증가 번호. 장치 패킷 번호가 아님 |
| `frame_times_ms` | 첫 브라우저 프레임으로부터 상대 시각. 물리적 화면 onset이 아님 |
| `metadata` | 조건·주파수·쌍 번호·설정·분석·중단 이유를 담은 JSON 문자열 |

구간 선택은 수신 순서를 사용한다. 타임스탬프 역전이 있어도 행을 정렬·제거하거나
시각을 보간하지 않는다. 품질 계산은 휴식/알파/아티팩트의 처음 2초, 자극의 처음 1초를 제외하며,
이 부분도 원시 NPZ에는 남긴다. 시작은 HTTP 요청 기준이므로 정밀 위상 분석에 사용할 수 없다.

수신률은 생산자 시각, 컴퓨터 도착 시각, 실제 구간 길이 대비 샘플 수로 각각 계산한다.
GUI/BrainFlow 파일의 두 샘플에 같은 패킷 시각이 붙는 패턴은 LSL 역전과 구분한다.
패킷 번호의 차이 분포는 진단 정보로 남기지만 펌웨어 규약을 확인하지 않고 손실률로 바꾸지 않는다.

세션 manifest와 HTML은 임시 파일을 쓴 후 교체한다. 브라우저 응답이 없으면 예정 구간 길이
+12초에 부분 저장한다. Esc·탭 숨김·연결 해제·정상 서버 종료도 부분 저장을 시도한다.
강제 종료, 전원 꺼짐, 디스크 쓰기 실패 때는 현재 미완료 구간 저장을 보장하지 못한다.
완료된 구간 파일은 별도로 남는다.

## 계산 규약과 작업 기준

- PSD: 원시 값에 Hann 창, 최대 4초, 50% 겹침, 창별 평균 제거, Welch density.
  200 Hz/4초 창이면 주파수 간격 0.25 Hz. notch와 ICA는 적용하지 않는다.
- 알파: 8–13 Hz 양 끝 빈을 포함한 PSD 합 × 빈 간격(µV²).
  EO·EC 각각 분석 데이터 10초 이상이고 품질이 유효한 완성 쌍만 비교한다.
  `10 log10(Pclosed/Popen)`을 쌍별로 구한다. 최소 3쌍 중 2/3 이상에서 +3 dB는 작업용 반복성 기준이다.
- SNR: 목표 빈의 파워를 양옆 ±2, ±3, ±4 빈의 평균 파워로 나눈 뒤 10 log10.
  인접 ±1 빈은 제외한다. 창 길이에 따라 비교하는 물리적 주파수 폭이 달라진다.
- AC RMS: 4차 Butterworth 1–40 Hz의 양방향 필터 후 표준편차.
  눈/근육 아티팩트 구간의 큰 값 자체는 예상 가능한 양성 대조다.
- CCA: 7–35 Hz 양방향 필터, 10/12/15 Hz의 sin/cos와 2차 고조파.
  최대 정준상관을 사용한다. 정답 주파수는 분류 입력에 전달하지 않는다.
  점수는 확률이 아니다. 초기 점수 0.35, 1·2위 차이 0.08은 검증된 보편 임계값이 아니다.
- 시간축 오차 >5%, 역전, 큰 공백, 선택 채널의 평탄/비유한 값/큰 진폭/입력 범위 근처 값/
  50·60 Hz 우세는 비교를 보류한다. 정확한 수치는 각 보고서의 `thresholds`에 보존한다.
- 시간축 불량 시에도 진단 PSD는 설정된 sample rate를 가정해 보여 주지만 `spectral_valid=false`다.
  그 피크를 실제 알파·상용전원 주파수·SSVEP로 확정하지 않는다.
- µV/V/mV 변환은 분석 시 한 번만 한다. 단위를 모르면 진폭 기반 판정을 보류한다.
  GUI RAW는 공식 EXG µV 형식을 가정하며 일반 CSV의 열 순서는 추측하지 않는다.
- 화면: 중앙 fps ≥50, 큰 공백 <100 ms, 누락 추정 ≤1%, 프레임 기록 길이 ≥예정 길이의 95%.
  입력한 모니터 Hz와의 차이도 확인한다. 광출력 검증은 별도다.

모든 기준은 장비 commissioning을 위한 작업용 경고다. 정상 EEG, 질환 또는 신경성 기원의 판정이 아니다.
채널을 늘리거나 임계값을 바꾼 뒤 같은 데이터에서 가장 좋은 결과를 골라 성능으로 보고하지 않는다.

## 분석과 실패 기록

3지선다는 주파수별 5회, 총 15회와 시선 이탈 대조 5회를 사용한다.
전체 시도 정확도에는 보류/품질 실패도 오답으로 포함한다. 채택된 시도의 정확도와 채택률,
품질 실패 수, 혼동행렬, 시선 이탈 오탐을 함께 남긴다. 중단 구간은 별도 표기하고 정확도에서 제외한다.
1/3 우연 수준의 단측 이항 검정은 독립 시행을 가정한 탐색적 보조값이다.

GUI-only 비교는 파일 전체가 한 조건일 때만 사용한다. 앱은 오래된 파일의 눈 상태를 추측하지 않는다.
같은 파일 중복 추가와 같은 쌍의 같은 눈 상태 중복 추가를 막는다. 원본은 이동하거나 변경하지 않는다.
불완전한 숫자 행은 위치를 표시하고, 해당 파일의 생리 비교를 보류한다.

## 재현 명령

저장소 루트에서:

```bash
.venv/bin/python -m unittest discover -s software/ganglion -v
GANGLION_LSL_TEST=1 .venv/bin/python -m unittest discover -s software/ganglion -v
.venv/bin/python software/ganglion/validate_eeg.py demo
.venv/bin/python software/ganglion/validate_eeg.py audit \
  "$HOME/Documents/OpenBCI_GUI/Recordings" software/ganglion/recordings \
  --channels 1 2 3 4
```

`test_validation.py`는 알려진 정현파/단위, 잘못된 시간축, flat/line/saturation, 조건 쌍,
프레임 누락, 보류 포함 정확도, 파일 파싱, 원시 보존, 부분 저장과 API를 검사한다.
`test_validation_lsl.py`는 실제 로컬 LSL 소켓에 합성 신호를 보내 정상 주파수 판정과 역전 시각 보존을 확인한다.
기존 앱 테스트도 함께 실행된다. 합성 시험 성공이 물리 보드/전극 성공을 뜻하지 않는다.

`test_validation_frontend.mjs`는 가짜 DOM/시계로 JavaScript 수명주기를 검사한다.
정상 종료, Esc, 탭 숨김, 전체 화면 종료, 미완료 구간의 제어 잠금을 확인하며 실제 브라우저
화면·음성·광출력을 검사한 것으로 세지 않는다. Node가 있는 환경에서는
`node software/ganglion/test_validation_frontend.mjs`로 실행할 수 있다.

장시간 선택 검사:

```bash
.venv/bin/python software/ganglion/soak_validation.py
# 30초 × 22구간. 합성 LSL만 사용하며 사람/보드/깜빡임 없음.
# validation_reports/soak/latest.json 및 captures/ 아래 원시 기록과 보고서
```

이 검사는 120,000샘플 수신 버퍼가 한 바퀴 돈 뒤에도 새 구간의 수신 순서·샘플 수·품질 계산과
반복 저장이 유지되는지 확인한다. 물리 BLE의 장시간 안정성을 대신하지 않는다.

선택 직접 경로는 별도 `.venv-brainflow-validation`에 BrainFlow 5.24.0을 설치했다.
`--transport synthetic --seconds 5`로 저장·리포트 경로를 실행 확인했다.
이 합성 보드는 250 Hz이며 Ganglion의 200 Hz 확인을 대신하지 않는다.
실제 장비 실행 전 GUI를 종료해야 한다. 자세한 명령은 아침 안내서를 따른다.

`plot_audit.py`는 감사 JSON에서 정적 근거 그림을 만드는 선택 도구다.
실험 앱 실행에는 matplotlib이 필요 없다. 그림 생성에만 선택 환경의 matplotlib을 사용한다.

## 공개 EEG 참고 자료

`reference_examples.py`는 PhysioNet S001의 눈 뜸/감음 한 쌍과 Nakanishi 연구진의 공개
SSVEP s1(180회)을 분석한다. 파일 해시, 출처, 사용한 구간과 모든 분류 결과를 저장한다.
첫 참가자와 네 후두부 채널을 고정했고 결과를 보고 가장 좋은 참가자를 고르지 않았다.
분석은 원래 160/256 Hz를 유지한다. Ganglion 200 Hz 수집 검사를 통과한 데이터로 표시하지 않는다.

```bash
.venv-brainflow-validation/bin/python -m pip install -r software/ganglion/requirements-reference.txt
.venv-brainflow-validation/bin/python software/ganglion/reference_examples.py --download
```

현재 컴퓨터에는 다운로드와 계산을 완료했다. 앱 상단에서 참고 보고서를 열 수 있다.
알파는 같은 설정의 MNE `psd_array_welch`와 SciPy Welch 수치가 일치하는지도 검사했다.
SSVEP에는 데이터셋의 12후보를 사용하고 원래 MAT의 수치 단위로 Ganglion 포화를 추정하지 않는다.
공개 자료를 이용한 분석 예시는 임계값의 임상 검증이나 실제 장치 성능 평가가 아니다.

## 아직 확인되지 않은 부분

실물 보드의 현재 전송, 전극/REF/D_G 접촉, 사용자 알파/SSVEP, 실제 디스플레이 광출력은
이 작업 중 측정하지 않았다. 웹 화면의 실제 브라우저 시각 검사는 컴퓨터 제어 연결이 응답하지 않아
완료하지 못했다. API·분석·저장·LSL 및 JavaScript 검사는 이 제한과 구분한다.
아침 첫 측정은 자극 없이 GUI 30초 RAW부터 시작한다.

## 2026-11-14에 실제 완료한 소프트웨어 검사

| 검사 | 결과 |
|---|---|
| 전체 Python 검사 (`GANGLION_LSL_TEST=1`) | 26개 모두 통과, 약 25.7초. 기존 앱 회귀와 실제 LSL 소켓 포함 |
| JavaScript 수명주기 | 5개 시나리오 통과. 가짜 DOM/시계이며 실제 브라우저 시각 검사는 아님 |
| 연속 합성 LSL 수집 | 670.5초, 수신 sequence 133,555. 120,000개 버퍼가 한 바퀴 돈 뒤까지 검사 |
| 반복 기록 | 30초 × 22구간 모두 품질·수신 순서·원시 저장 통과 |
| 실제 과거 파일 읽기 | GUI RAW 21개 + 기존 SSVEP NPZ 3개 검사. 빈 파일·불완전 행을 별도 표시 |
| 실제 HTTP 경로 | 앱/안내서/예제/개별 보고서, GUI 파일 목록 및 11월 8일 파일 분석 응답 확인 |
| 공개 EEG 계산 | 원본 해시 확인. 설정을 맞춘 SciPy/MNE Welch의 최대 절대 차이 0 |
| 직접 BrainFlow 소프트웨어 경로 | 합성 보드로 5초 수집·NPZ·HTML 생성 확인. 실제 Ganglion은 미연결 |
| 정적 검사 | Python compileall, git diff --check, HTML ID·로컬 링크 검사 통과 |

검사 로그: `validation_reports/final_checks.log`, 장시간 결과: `validation_reports/soak/latest.json`.
위 결과는 전극·실제 BLE·사용자의 EEG·디스플레이 광출력 검증과 구분한다.

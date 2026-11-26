"""Local-only commissioning workstation for Ganglion, separate from the speller."""
import argparse
import atexit
from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
import re
import threading
import time
from uuid import uuid4

from flask import Flask, jsonify, request, send_from_directory
import numpy as np
from scipy.stats import binomtest

from acquisition import Receiver, lsl
from validation import analyze, clean_json, compare_trials, display_metrics, dumps, TARGETS, THRESHOLDS
from validation_io import write_report, analyze_recording

ROOT = Path(__file__).resolve().parent
CONDITIONS = {"rest", "blink", "jaw", "eyes_open", "eyes_closed", "baseline", "single", "choice", "no_control"}


def protocol(name, seed=20261114):
    if name == "quality":
        return [{"condition": "rest", "duration": 30, "cue": "편하게 눈을 뜨고 정지된 십자표를 보세요. 움직이지 마세요."}]
    if name == "artifact":
        return [{"condition": condition, "duration": 15, "cue": cue} for condition, cue in [
            ("rest", "평소처럼 눈을 뜨고 턱과 얼굴을 편하게 두세요."),
            ("blink", "3초에 한 번 정도 천천히 눈을 깜빡이세요. 뇌파가 아닌 눈 움직임의 모양을 확인합니다."),
            ("rest", "얼굴을 편하게 두고 쉬세요."),
            ("jaw", "통증 없이 턱에 아주 잠깐 힘을 주었다 풀기를 3번 합니다. 근육 잡음 확인용입니다."),
            ("rest", "턱을 풀고 평소처럼 쉬세요.")]]
    if name == "alpha":
        return [{"condition": c, "duration": 20, "pair": pair,
                 "cue": "눈을 감고 턱에 힘을 빼세요. 다음 음성 안내 때 눈을 뜨세요." if c == "eyes_closed" else "눈을 뜨고 정지된 십자표를 편하게 보세요."}
                for pair in range(3) for c in (("eyes_closed", "eyes_open") if pair == 1 else ("eyes_open", "eyes_closed"))]
    if name in {"single", "single15"}:
        rng = np.random.default_rng(seed)
        result = []
        for pair in range(3):
            for f in ([15.] if name == "single15" else rng.permutation(TARGETS)):
                for condition in ("baseline", "single"):
                    result.append({"condition": condition, "duration": 10, "frequency": float(f), "pair": pair,
                                   "cue": "정지된 사각형 중앙을 보세요." if condition == "baseline" else f"{f:g} Hz 사각형 중앙을 보세요. 불편하면 즉시 Esc를 누르세요."})
        return result
    if name in {"choice", "choice2"}:
        rng = np.random.default_rng(seed)
        result = []
        for block in range(5):
            candidates = [12., 15.] if name == "choice2" else TARGETS
            order = rng.permutation(candidates).tolist() + [None]
            for f in order:
                result.append({"condition": "choice" if f else "no_control", "duration": 6, "frequency": f,
                               "candidates": candidates, "pair": block, "cue": f"{f:g} Hz 표시를 바라보세요." if f else "깜빡이는 화면에서 시선을 떼고 옆의 정지된 물체를 보세요. 눈은 뜬 상태입니다."})
        return result
    raise ValueError("지원하지 않는 프로토콜입니다.")


def summarize(session):
    records = session["trials"]
    choices = [r for r in records if r["condition"] == "choice" and not r.get("aborted")]
    controls = [r for r in records if r["condition"] == "no_control" and not r.get("aborted")]
    accepted = [r for r in choices if r.get("prediction") is not None]
    correct = sum(r.get("prediction") == r.get("frequency") for r in choices)
    confusion = {str(f): {str(p): 0 for p in TARGETS + [None]} for f in TARGETS}
    for r in choices:
        confusion[str(r["frequency"])][str(r.get("prediction"))] += 1
    return {"alpha": compare_trials(records, "alpha", session["setup"]["channels"]),
            "single": compare_trials(records, "single", session["setup"]["channels"]),
            "choice": {"attempted": len(choices), "accepted": len(accepted), "correct": correct,
                       "invalid": sum(not r.get("valid_for_decision", False) for r in choices),
                       "accuracy_all_attempts": correct / len(choices) if choices else None,
                       "accuracy_accepted": correct / len(accepted) if accepted else None,
                       "coverage": len(accepted) / len(choices) if choices else None,
                       "binomial_p_one_sided": float(binomtest(correct, len(choices), 1 / 3, alternative="greater").pvalue) if choices and all(len(r.get("candidates", TARGETS)) == 3 for r in choices) else None,
                       "confusion": confusion, "no_control_attempts": len(controls),
                       "no_control_false_positives": sum(r.get("prediction") is not None for r in controls),
                       "note": "전체 시도 정확도에는 보류/품질 실패를 오답으로 포함합니다. 시선 이탈 대조는 선택한 자극들을 켠 채 시선을 떼는 조건입니다. 소표본 p값은 탐색용이며 독립 시행을 가정합니다."}}


def create_app(receiver=None, output_dir=None, clock=None, gui_dir=None, native=False):
    app = Flask(__name__, static_folder=str(ROOT / ("native_static" if native else "validation_static")), static_url_path="/static")
    app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
    receiver = receiver or Receiver()
    folder = Path(output_dir or ROOT / "validation_recordings")
    gui_folder = Path(gui_dir or Path.home()/"Documents/OpenBCI_GUI/Recordings").resolve()
    now = clock or (lambda: lsl().local_clock())
    lock = threading.RLock()
    state = {"session": None, "trial": None, "timer": None}
    atexit.register(receiver.disconnect)

    def persist():
        session = state["session"]
        if not session:
            return
        session["summary"] = summarize(session)
        dest = folder / session["id"]
        dest.mkdir(parents=True, exist_ok=True)
        # Atomic replacement protects the previous completed session manifest.
        tmp = dest / "session.tmp"
        tmp.write_text(dumps(session), encoding="utf-8")
        tmp.replace(dest / "session.json")
        write_report(dest / "report.tmp", session)
        (dest / "report.tmp").replace(dest / "report.html")

    def finish(frames=None, aborted=False, reason=""):
        trial = state["trial"]
        if not trial:
            raise ValueError("진행 중인 구간이 없습니다.")
        end = now()
        rows = receiver.snapshot(after=trial["cursor"])
        # Arrival timestamps are chunk receipts, not ADC sample times. They
        # select a capture without deleting reversed producer timestamps.
        rows = [r for r in rows if r[2] <= end]
        samples = np.asarray([r[4] for r in rows], float).reshape(-1, 4)
        ts = np.asarray([r[1] for r in rows], float)
        arrivals = np.asarray([r[2] for r in rows], float)
        setup = state["session"]["setup"]
        fs = trial["stream"]["sampling_rate"]
        elapsed = end - trial["start_lsl"]
        # Discard settling samples for spectra, preserve ALL raw samples on disk.
        settle = 2.0 if trial["condition"] in {"eyes_open", "eyes_closed", "rest", "blink", "jaw"} else 1.0
        mask = arrivals >= trial["start_lsl"] + settle
        report = analyze(samples[mask], ts[mask], fs, setup["channels"], arrivals[mask],
                         elapsed=max(0, elapsed - settle), units=setup["units"], targets=trial.get("candidates", TARGETS), notch_hz=60 if native else None)
        if elapsed < trial["duration"] - .25 or elapsed > trial["duration"] + 2.5:
            report["eligible"] = False
            report["warnings"].append("구간 실제 시간이 예정과 다릅니다.")
        if setup.get("lsl_filters") != "off":
            report["eligible"] = False
            report["warnings"].append("GUI LSL 출력 필터 Off가 확인되지 않았습니다. 원시 품질 판정은 보류합니다.")
        if not receiver.status()["receiving"]:
            report["eligible"] = False
            report["warnings"].append("구간 종료 시 수신이 중단되어 있습니다.")
        display = display_metrics(frames or [], trial["duration"], setup.get("monitor_hz"))
        flicker = trial["condition"] in {"single", "choice", "no_control"}
        valid = report["eligible"] and not aborted and (display["ok"] if flicker else True)
        scores = report.get("cca_scores_exploratory", {})
        candidates = trial.get("candidates", TARGETS)
        scores = {k: v for k, v in scores.items() if float(k) in candidates}
        ranked = sorted(scores, key=scores.get, reverse=True)
        prediction = None
        if valid and flicker and len(ranked) > 1:
            if scores[ranked[0]] >= THRESHOLDS["cca_score"] and scores[ranked[0]] - scores[ranked[1]] >= THRESHOLDS["cca_margin"]:
                prediction = float(ranked[0])
        completed = {**trial, "end_lsl": end, "elapsed_seconds": elapsed, "settle_seconds": settle,
                     "analysis": report, "display": display, "aborted": aborted, "abort_reason": reason,
                     "valid_for_decision": bool(valid), "prediction": prediction,
                     "setup": setup, "stimulus": "rAF elapsed-time sinusoidal CSS RGB: round(125 + 65*sin(2*pi*f*t)); not gamma-linearized",
                     "synchronization": "HTTP cue + chunk receipt; physical display onset unmeasured"}
        dest = folder / state["session"]["id"]
        dest.mkdir(parents=True, exist_ok=True)
        name = f"{len(state['session']['trials']) + 1:03d}_{trial['condition']}_{trial['id']}.npz"
        completed["recording"] = name
        # Saving is part of completion; do not clear state before a successful write.
        np.savez_compressed(dest / name, samples=samples, timestamps=ts,
                            arrival_timestamps=arrivals,
                            producer_timestamps=np.asarray([r[3] for r in rows]),
                            sequence=np.asarray([r[0] for r in rows], dtype=np.int64),
                            frame_times_ms=np.asarray(frames or [], float), metadata=dumps(completed))
        state["session"]["trials"].append(completed)
        state["trial"] = None
        if state["timer"]:
            state["timer"].cancel()
            state["timer"] = None
        persist()
        return completed

    def shutdown_capture():
        with lock:
            if state["trial"]:
                try:
                    finish(aborted=True, reason="서버 정상 종료 중 부분 저장")
                except Exception:
                    app.logger.exception("Shutdown partial save failed")
    # Runs before receiver.disconnect (atexit callbacks are LIFO). SIGKILL or
    # power loss cannot guarantee this callback; completed blocks are durable.
    atexit.register(shutdown_capture)

    @app.errorhandler(ValueError)
    def invalid(exc):
        return jsonify(error=str(exc)), 400

    @app.errorhandler(Exception)
    def failed(exc):
        from werkzeug.exceptions import HTTPException
        if isinstance(exc, HTTPException):
            return jsonify(error=exc.description), exc.code
        app.logger.exception("Validation request failed")
        return jsonify(error=f"작업 실패: {exc}"), 500

    @app.before_request
    def protect_local():
        if request.host.split(":")[0] not in {"localhost", "127.0.0.1"}:
            return jsonify(error="로컬 주소로 접속하세요."), 403
        if request.method == "POST":
            if request.headers.get("Origin") not in (None, request.host_url.rstrip("/")):
                return jsonify(error="다른 출처의 요청은 허용하지 않습니다."), 403
            if not request.is_json or not isinstance(request.get_json(), dict):
                return jsonify(error="JSON 객체가 필요합니다."), 415

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    @app.get("/api/status")
    def status():
        return jsonify(clean_json({**receiver.status(), "active_trial": state["trial"],
                                   "session_id": state["session"]["id"] if state["session"] else None}))

    @app.get("/api/streams")
    def streams():
        return jsonify(streams=receiver.discover())

    @app.post("/api/connect")
    def connect():
        with lock:
            if state["trial"]:
                raise ValueError("진행 중인 구간을 먼저 중단하세요.")
            uid = request.get_json().get("uid")
            if not isinstance(uid, str) or not uid:
                raise ValueError("스트림을 선택하세요.")
            return jsonify(receiver.connect(uid))

    @app.post("/api/disconnect")
    def disconnect():
        with lock:
            if state["trial"]:
                finish(aborted=True, reason="연결 해제")
            receiver.disconnect()
            return jsonify(ok=True)

    @app.get("/api/live")
    def live():
        rows = receiver.snapshot(seconds=10)
        fs = (receiver.info or {}).get("sampling_rate", 200)
        if len(rows) < fs * 2:
            return jsonify(waiting=True, count=len(rows))
        setup = state["session"]["setup"] if state["session"] else {"channels": [0], "units": "uV"}
        return jsonify(analyze([r[4] for r in rows], [r[1] for r in rows], fs,
                               setup["channels"], [r[2] for r in rows], units=setup["units"], notch_hz=60 if native else None))

    @app.post("/api/session")
    def new_session():
        with lock:
            if state["trial"]:
                raise ValueError("진행 중인 구간을 먼저 중단하세요.")
            setup = request.get_json().get("setup", {})
            if not isinstance(setup, dict):
                raise ValueError("설정 객체가 필요합니다.")
            if native:
                setup.update(units="uV", lsl_filters="off", acquisition="brainflow-native")
            channels = setup.get("channels")
            if not isinstance(channels, list) or not channels or any(type(c) is not int or c not in range(4) for c in channels) or len(set(channels)) != len(channels):
                raise ValueError("실제 연결한 CH1~CH4를 선택하세요.")
            if setup.get("units") not in {"uV", "mV", "V", "unknown"}:
                raise ValueError("신호 단위를 선택하세요.")
            monitor = setup.get("monitor_hz")
            if monitor is not None and (type(monitor) not in (float, int) or not np.isfinite(monitor) or not 50 <= monitor <= 360):
                raise ValueError("모니터 주사율은 비워 두거나 50~360 Hz로 입력하세요.")
            for key in ("reference", "ground", "positions", "electrode", "switches", "notes"):
                if not isinstance(setup.get(key, ""), str) or len(setup.get(key, "")) > 2000:
                    raise ValueError("설정 텍스트는 2000자 이내여야 합니다.")
            session_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ_") + uuid4().hex[:12]
            state["session"] = {"id": session_id, "created_utc": datetime.now(timezone.utc).isoformat(),
                                "setup": setup, "trials": [], "version": "1.0"}
            persist()
            return jsonify(id=session_id, report=f"/files/{session_id}/report.html")

    @app.get("/api/protocol/<name>")
    def get_protocol(name):
        return jsonify(blocks=protocol(name), seed=20261114, inter_block_rest_seconds=5)

    @app.post("/api/block/start")
    def start():
        with lock:
            if state["trial"]:
                raise ValueError("구간이 이미 진행 중입니다.")
            if not state["session"]:
                raise ValueError("먼저 실험 설정을 저장하세요.")
            if not receiver.status()["receiving"]:
                raise ValueError("실시간 수신이 없습니다. GUI의 두 Start 버튼을 확인하세요.")
            b = request.get_json()
            condition = b.get("condition")
            duration = b.get("duration")
            frequency = b.get("frequency")
            pair = b.get("pair")
            if condition not in CONDITIONS or type(duration) not in (int, float) or not np.isfinite(duration) or not 5 <= duration <= 60:
                raise ValueError("조건 또는 구간 길이(5~60초)가 잘못되었습니다.")
            if condition in {"baseline", "single", "choice"} and (type(frequency) not in (int, float) or not np.isfinite(frequency) or not 8 <= frequency <= 17.5 or (not native and frequency not in TARGETS)):
                raise ValueError("지원 주파수는 8~17.5 Hz입니다.")
            if pair is not None and (type(pair) is not int or not 0 <= pair <= 999):
                raise ValueError("pair는 0~999 정수입니다.")
            candidates = b.get("candidates", TARGETS)
            if not isinstance(candidates, list) or not 1 <= len(candidates) <= 20 or any(type(f) not in (int, float) or not np.isfinite(f) or not 8 <= f <= 17.5 or (not native and f not in TARGETS) for f in candidates) or len(set(candidates)) != len(candidates):
                raise ValueError("잘못된 자극 후보입니다.")
            if condition == "choice" and frequency not in candidates:
                raise ValueError("정답이 자극 후보에 없습니다.")
            trial = {"id": uuid4().hex, "candidates": candidates, "condition": condition, "duration": duration,
                     "frequency": float(frequency) if frequency else None, "pair": pair,
                     "cursor": receiver.cursor(), "start_lsl": now(), "stream": receiver.info}
            state["trial"] = trial

            def timeout():
                with lock:
                    if state["trial"] and state["trial"]["id"] == trial["id"]:
                        try:
                            finish(aborted=True, reason="브라우저 응답 없음/제한 시간 초과")
                        except Exception:
                            app.logger.exception("Automatic partial save failed")
            timer = threading.Timer(duration + 12, timeout)
            timer.daemon = True
            state["timer"] = timer
            timer.start()
            return jsonify(trial)

    @app.post("/api/block/finish")
    def stop():
        with lock:
            body = request.get_json()
            if not state["trial"] or body.get("id") != state["trial"]["id"]:
                raise ValueError("측정 ID가 일치하지 않습니다. 이미 자동 저장되었으면 세션 보고서를 여세요.")
            frames = body.get("frame_times_ms", [])
            if not isinstance(frames, list) or len(frames) > 25000 or any(type(v) not in (float, int) or not np.isfinite(v) for v in frames):
                raise ValueError("프레임 기록이 잘못되었습니다.")
            return jsonify(finish(frames, aborted=body.get("aborted") is True, reason=str(body.get("reason", ""))[:300]))

    @app.get("/api/session")
    def current_session():
        with lock:
            return jsonify(state["session"])

    @app.get("/api/sessions")
    def sessions():
        return jsonify(sessions=[p.parent.name for p in sorted(folder.glob("*/session.json"), reverse=True)][:100])

    def gui_files():
        # Restrict read access to the GUI recordings directory; never expose a
        # general-purpose filesystem endpoint through a local web server.
        return {hashlib.sha256(str(p).encode()).hexdigest()[:20]: p
                for p in gui_folder.glob("*/OpenBCI-RAW*.txt")
                if p.is_file() and p.resolve().is_relative_to(gui_folder)}

    @app.get("/api/gui-files")
    def list_gui_files():
        return jsonify(files=[{"key": key, "name": p.name, "session": p.parent.name, "bytes": p.stat().st_size}
                              for key, p in sorted(gui_files().items(), key=lambda kv: kv[1].name, reverse=True)])

    @app.post("/api/gui-analyze")
    def inspect_gui_file():
        with lock:
            if state["trial"]:
                raise ValueError("실시간 구간을 먼저 종료하세요.")
            b = request.get_json()
            path = gui_files().get(b.get("key"))
            if not path:
                raise ValueError("목록에 있는 GUI 녹화 파일을 선택하세요.")
            channels = state["session"]["setup"]["channels"] if state["session"] else [0]
            result = analyze_recording(path, channels)
            # Imported files can be labelled for a paired EO/EC experiment even
            # if LSL is broken. Stimulus timing cannot be invented from a file.
            condition = b.get("condition", "unlabelled")
            if condition not in {"unlabelled", "eyes_open", "eyes_closed", "rest"}:
                raise ValueError("GUI 파일 비교는 휴식/눈 뜸/눈 감음만 지원합니다.")
            if b.get("add_to_session"):
                if not state["session"]:
                    raise ValueError("비교하려면 먼저 현재 배치의 새 세션을 만드세요.")
                pair = b.get("pair")
                if type(pair) is not int or not 0 <= pair <= 999:
                    raise ValueError("쌍 번호는 1~1000 범위로 입력하세요.")
                if any(t.get("source_file") == str(path) for t in state["session"]["trials"]):
                    raise ValueError("이 파일은 이미 이 세션에 추가했습니다.")
                if condition in {"eyes_open", "eyes_closed"} and any(
                        t.get("condition") == condition and t.get("pair") == pair for t in state["session"]["trials"]):
                    raise ValueError("이 쌍 번호에 같은 눈 상태 기록이 이미 있습니다. 다른 쌍 번호 또는 새 세션을 사용하세요.")
                if condition == "unlabelled":
                    raise ValueError("실험 중 실제로 기록한 눈 뜸/감음/휴식 조건을 선택하세요.")
                imported = {"id": uuid4().hex, "condition": condition, "pair": pair, "frequency": None,
                            "source_file": str(path), "recording": path.name, "analysis": result["analysis"],
                            "elapsed_seconds": result["analysis"]["timing"].get("timestamp_span_s"),
                            "valid_for_decision": False, "prediction": None, "aborted": False,
                            "display": {"ok": False, "reason": "GUI 파일: 화면 타이밍 기록 없음"},
                            "import_note": "파일 전체를 조건으로 사용. 전환/움직임이 포함되면 비교에 쓰지 마세요. 원본 파일은 이동/수정하지 않았습니다."}
                state["session"]["trials"].append(imported)
                persist()
                result["added_to_session"] = True
            return jsonify(result)

    @app.get("/files/<session_id>/<filename>")
    def file(session_id, filename):
        if not re.fullmatch(r"\d{8}T\d{6}Z_[a-f0-9]{12}", session_id) or not re.fullmatch(r"[a-zA-Z0-9_.-]+", filename):
            raise ValueError("잘못된 파일 이름입니다.")
        if filename not in {"session.json", "report.html"} and not filename.endswith(".npz"):
            raise ValueError("지원하지 않는 파일입니다.")
        return send_from_directory(folder / session_id, filename, as_attachment=filename.endswith(".npz"))

    @app.get("/guide")
    def guide():
        return send_from_directory(ROOT / "docs", "MORNING_GUIDE.html")

    @app.get("/reports/<category>/<filename>")
    def prepared_report(category, filename):
        if category not in {"audit", "demo", "reference"} or not re.fullmatch(r"[a-zA-Z0-9_.-]+\.(html|png|json)", filename):
            raise ValueError("지원하지 않는 보고서 경로입니다.")
        return send_from_directory(ROOT / "validation_reports" / category, filename)

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8002)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    create_app(output_dir=args.output_dir).run(host="127.0.0.1", port=args.port, threaded=True, debug=False)

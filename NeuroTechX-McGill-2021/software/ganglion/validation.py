"""Transparent EEG commissioning metrics. No metric here proves neural origin.

Samples stay in acquisition order. Spectra use the advertised sample rate and
are explicitly provisional when timing QC fails. No interpolation, timestamp
sorting, hidden notch, artifact removal, or automated re-referencing is used.
"""
import json
import math

import numpy as np
from scipy.signal import butter, sosfiltfilt, welch, iirnotch, filtfilt

from decoder import basis

VERSION = "1.0"
TARGETS = [10.0, 12.0, 15.0]
THRESHOLDS = {
    "rate_error_fraction": 0.05,
    "max_gap_seconds": 0.15,
    "flat_seconds": 0.5,
    "large_ac_rms_uv": 100.0,
    "near_rail_uv": 15500.0,
    "near_rail_fraction": 0.001,
    "line_power_fraction": 0.35,
    "alpha_increase_db": 3.0,
    "ssvep_snr_db": 3.0,
    "cca_score": 0.35,
    "cca_margin": 0.08,
}


def clean_json(value):
    """Strict JSON; absent/undefined numerical evidence is null, never NaN."""
    if isinstance(value, np.ndarray):
        return clean_json(value.tolist())
    if isinstance(value, dict):
        return {str(k): clean_json(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [clean_json(v) for v in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def dumps(value):
    return json.dumps(clean_json(value), ensure_ascii=False, allow_nan=False)


def longest_run(mask):
    padded = np.r_[False, np.asarray(mask, bool), False].astype(int)
    edges = np.flatnonzero(np.diff(padded))
    return int(np.max(edges[1::2] - edges[::2])) if len(edges) else 0


def timing_metrics(timestamps, fs, arrivals=None, elapsed=None, source="lsl"):
    ts = np.asarray(timestamps, float)
    n = len(ts)
    issues, notes = [], []
    out = {"count": n, "nominal_hz": fs, "source": source}
    if n < 2 or not np.isfinite(ts).all():
        return {**out, "ok": False, "issues": ["유효한 시간 정보가 부족합니다."], "notes": []}
    dt = np.diff(ts)
    span = ts[-1] - ts[0]
    rate = (n - 1) / span if span > 0 else None
    out.update(timestamp_span_s=span, timestamp_rate_hz=rate,
               backwards=int(np.sum(dt < 0)), duplicates=int(np.sum(dt == 0)),
               max_gap_s=float(dt.max()), min_step_s=float(dt.min()),
               median_positive_step_s=float(np.median(dt[dt > 0])) if np.any(dt > 0) else None)
    if source == "gui":
        notes.append("Ganglion GUI는 한 BLE 패킷의 두 샘플에 같은 시각을 쓸 수 있습니다. 중복 시각을 샘플 누락으로 세지 않습니다.")
    elif np.any(dt == 0):
        issues.append("LSL 타임스탬프 중복: 생산자 시간 설정을 확인하세요.")
    if np.any(dt < 0):
        issues.append("타임스탬프 역전: 수신 순서는 보존했지만 시간축을 검증하지 못했습니다.")
    if dt.max() > THRESHOLDS["max_gap_seconds"]:
        issues.append("150 ms 초과 시간 공백이 있습니다.")
    if rate is None or abs(rate / fs - 1) > THRESHOLDS["rate_error_fraction"]:
        issues.append("파일/LSL 시각으로 계산한 수신률이 설정값과 5% 넘게 다릅니다.")
    if arrivals is not None and len(arrivals) == n:
        arrival = np.asarray(arrivals, float)
        a_span = arrival[-1] - arrival[0]
        a_rate = (n - 1) / a_span if a_span > 0 else None
        out["receipt_rate_hz"] = a_rate
        out["max_receipt_gap_s"] = float(np.max(np.diff(arrival)))
        if a_rate is None or abs(a_rate / fs - 1) > 0.05:
            issues.append("컴퓨터 도착률도 설정값과 5% 넘게 다릅니다. GUI/BLE 수집 경로를 확인하세요.")
        if out["max_receipt_gap_s"] > 0.5:
            issues.append("컴퓨터 수신에 0.5초 초과 정지가 있습니다.")
    if elapsed is not None and elapsed > 0:
        out["capture_rate_hz"] = n / elapsed
        out["expected_count"] = elapsed * fs
        out["count_fraction"] = n / (elapsed * fs)
        if abs(out["count_fraction"] - 1) > 0.05:
            issues.append("측정 실제 시간 대비 샘플 수가 5% 넘게 다릅니다. 이것만으로 패킷 손실률은 확정할 수 없습니다.")
    out.update(ok=not issues, issues=issues, notes=notes)
    return clean_json(out)


def band_power(freqs, psd, low, high):
    # Sum density * bin-width (includes both band endpoints); convention saved.
    sel = (freqs >= low) & (freqs <= high)
    return np.sum(psd[sel], axis=0) * (freqs[1] - freqs[0])


def local_snr(freqs, psd, frequency):
    i = int(np.argmin(np.abs(freqs - frequency)))
    # Three neighboring bins per side, skip the immediately adjacent bin.
    offsets = [-4, -3, -2, 2, 3, 4]
    neighbors = [i + j for j in offsets if 0 <= i + j < len(freqs)]
    if len(neighbors) != 6 or abs(freqs[i] - frequency) > (freqs[1] - freqs[0]) / 2 + 1e-8:
        return {"requested_hz": frequency, "bin_hz": float(freqs[i]), "snr_db": None}
    noise = np.mean(psd[neighbors], axis=0)
    snr = 10 * np.log10(np.maximum(psd[i], 1e-30) / np.maximum(noise, 1e-30))
    return {"requested_hz": frequency, "bin_hz": float(freqs[i]), "snr_db": clean_json(snr)}


def cca_scores(x, fs, targets=TARGETS):
    if len(x) < fs * 2:
        return {}
    filtered = sosfiltfilt(butter(4, [7, 35], btype="bandpass", fs=fs, output="sos"), x, axis=0)
    qx = basis(filtered)
    t = np.arange(len(x)) / fs
    scores = {}
    for f in targets:
        ref = np.column_stack([fun(2 * np.pi * f * h * t) for h in (1, 2) for fun in (np.sin, np.cos)])
        singular = np.linalg.svd(qx.T @ basis(ref), compute_uv=False)
        scores[str(f)] = float(np.clip(singular[0], 0, 1)) if len(singular) else 0.0
    return scores


def analyze(samples, timestamps, fs=200.0, channels=None, arrivals=None,
            elapsed=None, source="lsl", units="uV", include_plot=True, targets=TARGETS, notch_hz=None):
    if notch_hz is not None and (not np.isfinite(notch_hz) or not 0 < notch_hz < fs / 2):
        raise ValueError("노치 주파수는 0과 Nyquist 사이여야 합니다.")
    x = np.asarray(samples, float)
    if not np.isfinite(fs) or not 80 <= fs <= 1000:
        raise ValueError("샘플링 주파수는 80~1000 Hz 범위여야 합니다.")
    if x.ndim != 2 or x.shape[1] != 4 or len(timestamps) != len(x):
        raise ValueError("4채널 samples와 같은 길이의 timestamps가 필요합니다.")
    channels = list(range(4)) if channels is None else channels
    if not channels or len(set(channels)) != len(channels) or any(type(c) is not int or c not in range(4) for c in channels):
        raise ValueError("선택 채널은 중복 없이 0~3이어야 합니다.")
    if units not in ("uV", "mV", "V", "unknown"):
        raise ValueError("단위는 uV/mV/V/unknown 중 하나여야 합니다.")
    scale = {"uV": 1, "mV": 1000, "V": 1e6, "unknown": 1}[units]
    x = x * scale
    timing = timing_metrics(timestamps, fs, arrivals, elapsed, source)
    out = {"version": VERSION, "thresholds": THRESHOLDS, "timing": timing,
           "methods": {"psd": "Welch, Hann, up to 4 s, 50% overlap, constant detrend, density; no notch",
                       "alpha": "8–13 Hz inclusive bins; sum PSD × bin width",
                       "snr": "10 log10(target PSD / mean PSD of offsets −4,−3,−2,+2,+3,+4 bins)",
                       "amplitude": "1–40 Hz Butterworth order 4, forward/backward; standard deviation",
                       "cca": "7–35 Hz, candidate-frequency sine/cosine references, harmonics 1 and 2"},
           "channels": [], "selected_channels": channels, "input_units": units,
           "display_units": "uV" if units != "unknown" else "입력 단위",
           "spectral_axis": "nominal_sample_index", "spectral_valid": timing["ok"],
           "signal_ok": False, "eligible": False, "warnings": [],
           "method": "Welch Hann 4 s, 50% overlap, constant detrend, mean density; no notch. Bandpower = sum(PSD bins) × df. SNR = 10 log10(power / mean of ±2,3,4 bins)."}
    if fs != 200:
        out["warnings"].append("Ganglion BLE 기본값 200 Hz와 다릅니다. 장비/스트림 종류를 확인하세요.")
        out["spectral_valid"] = False
    if units == "unknown":
        out["warnings"].append("단위가 확인되지 않아 진폭/포화 판정을 하지 않습니다.")
    if len(x) < 2 * fs:
        out["warnings"].append("2초 이상 데이터가 필요합니다.")
        return clean_json(out)
    valid_columns = np.isfinite(x).all(axis=0)
    # Invalid channels are marked, not silently repaired; NaN placeholders stay
    # out of all selected-channel statistics and CCA.
    work = x.copy()
    work[:, ~valid_columns] = 0
    f, p = welch(work, fs=fs, nperseg=min(int(4 * fs), len(work)), axis=0, detrend="constant", scaling="density")
    filtered = sosfiltfilt(butter(4, [1, min(40, fs / 2 - 1)], btype="bandpass", fs=fs, output="sos"), work, axis=0)
    processed = work
    post_p = p
    if notch_hz is not None:
        b, a = iirnotch(notch_hz, 30, fs=fs)
        processed = filtfilt(b, a, work, axis=0)
        _, post_p = welch(processed, fs=fs, nperseg=min(int(4 * fs), len(work)), axis=0, detrend="constant", scaling="density")
        filtered = sosfiltfilt(butter(4, [1, min(40, fs / 2 - 1)], btype="bandpass", fs=fs, output="sos"), processed, axis=0)
    out["methods"]["notch"] = {"frequency_hz": notch_hz, "Q": 30 if notch_hz else None, "phase": "forward/backward", "scope": "display and CCA; raw storage and PSD unchanged"}
    post_line = np.maximum(band_power(f, post_p, 49, 51), band_power(f, post_p, 59, 61)) / np.maximum(band_power(f, post_p, 1, min(90, fs / 2 - 1)), 1e-30)
    alpha = band_power(f, p, 8, 13)
    broad = band_power(f, p, 1, min(90, fs / 2 - 1))
    line50 = band_power(f, p, 49, 51)
    line60 = band_power(f, p, 59, 61)
    spectrum_targets = {str(v): local_snr(f, p, v) for v in (10., 12., 15., 20., 24., 30., 50., 60.) if v < fs / 2}
    for ch in range(4):
        v = work[:, ch]
        flags = []
        if not valid_columns[ch]:
            flags.append("NaN/무한대")
        flat = (longest_run(np.diff(v) == 0) + 1) / fs
        rms = float(np.std(filtered[:, ch]))
        rail = float(np.mean(np.abs(v) >= THRESHOLDS["near_rail_uv"])) if units != "unknown" else None
        line_fraction = float(max(line50[ch], line60[ch]) / max(broad[ch], 1e-30))
        if flat >= THRESHOLDS["flat_seconds"] or np.std(v) < 1e-10:
            flags.append("평탄/같은 값 반복")
        if units != "unknown" and rms > THRESHOLDS["large_ac_rms_uv"]:
            flags.append("1–40 Hz 진폭 큼")
        if rail is not None and rail > THRESHOLDS["near_rail_fraction"]:
            flags.append("입력 범위 근처 값: 포화 의심")
        if line_fraction > THRESHOLDS["line_power_fraction"]:
            if notch_hz is None or post_line[ch] > THRESHOLDS["line_power_fraction"]:
                flags.append("50/60 Hz 성분 우세")
            else:
                out["warnings"].append(f"CH{ch+1}: 원시 전원 잡음 우세, 노치 후 감소. 원시 신호 품질 개선을 뜻하지 않습니다.")
        peak_sel = (f >= 1) & (f <= min(90, fs / 2 - 1))
        out["channels"].append({"channel": ch, "selected": ch in channels, "flags": flags,
            "finite": bool(valid_columns[ch]), "mean_uv": float(np.mean(v)),
            "raw_std_uv": float(np.std(v)), "raw_ptp_uv": float(np.ptp(v)),
            "ac_rms_uv": rms, "flat_seconds": flat, "near_rail_fraction": rail,
            "line_fraction": line_fraction, "line_fraction_after_notch": float(post_line[ch]),
            "line60_power_before": float(line60[ch]), "line60_power_after": float(band_power(f, post_p, 59, 61)[ch]), "alpha_power": float(alpha[ch]),
            "alpha_relative": float(alpha[ch] / max(band_power(f, p, 1, 40)[ch], 1e-30)),
            "peak_hz": float(f[peak_sel][np.argmax(p[peak_sel, ch])]),
            "snr_db": {k: val["snr_db"][ch] if val["snr_db"] is not None else None for k, val in spectrum_targets.items()}})
    selected_ok = all(not out["channels"][c]["flags"] for c in channels)
    out["signal_ok"] = selected_ok and units != "unknown"
    out["eligible"] = out["signal_ok"] and out["spectral_valid"]
    if len(channels) > 1 and np.all(np.std(work[:, channels], axis=0) > 0):
        corr = np.corrcoef(work[:, channels].T)
        out["correlation"] = clean_json(corr)
        if np.max(np.abs(corr - np.eye(len(channels)))) > .98:
            out["warnings"].append("채널 상관 >0.98: 공통 잡음/REF/전극 연결을 확인하세요. 상관만으로 원인을 확정하지 않습니다.")
    out["cca_scores_exploratory"] = cca_scores(processed[:, channels], fs, targets) if valid_columns[channels].all() else {}
    out["frequency_resolution_hz"] = float(f[1] - f[0])
    if not out["spectral_valid"]:
        out["warnings"].append("시간축 미검증: 표시 주파수와 CCA는 설정 주파수를 가정한 참고값이며 생리 반응 판정에 사용하지 않습니다.")
    if include_plot:
        view = min(len(x), int(5 * fs))
        step = max(1, int(np.ceil(view / 1200)))
        tail = work[-view:]
        # Bin minima/maxima preserve spikes, unlike naive trace decimation.
        bins = [tail[i:i + step] for i in range(0, view, step)]
        out["plot"] = {"freqs": f, "psd_db": 10 * np.log10(np.maximum(p, 1e-30)),
                       "trace_t": np.arange(len(bins)) * step / fs,
                       "raw_min": np.array([b.min(0) for b in bins]) - tail.mean(0),
                       "raw_max": np.array([b.max(0) for b in bins]) - tail.mean(0),
                       "filtered": filtered[-view::step], "alpha_band": [8, 13]}
    return clean_json(out)


def display_metrics(frame_times, duration, expected_fps=None):
    t = np.asarray(frame_times, float)
    if t.ndim != 1 or len(t) < 3 or not np.isfinite(t).all() or np.any(np.diff(t) <= 0):
        return {"ok": False, "reason": "유효한 브라우저 프레임 기록이 없습니다."}
    dt = np.diff(t)
    median = float(np.median(dt))
    fps = 1000 / median
    missed = int(np.sum(np.maximum(np.rint(dt / median).astype(int) - 1, 0)))
    dropped_fraction = missed / (len(dt) + missed)
    ok = fps >= 50 and dt.max() < 100 and dropped_fraction <= .01 and t[-1] - t[0] >= .95 * duration * 1000
    if expected_fps and abs(fps / expected_fps - 1) > .05:
        ok = False
    return {"ok": bool(ok), "median_fps": fps, "max_gap_ms": float(dt.max()),
            "estimated_dropped_frames": missed, "dropped_fraction": dropped_fraction,
            "duration_s": float((t[-1] - t[0]) / 1000),
            "reason": "소프트웨어 프레임 검사 통과; 실제 광출력 검증은 별도입니다." if ok else "프레임 지연/누락/길이/주사율을 확인하세요.",
            "physical_onset_verified": False}


def compare_trials(reports, kind="alpha", channels=None):
    """Descriptive within-session comparison, never population inference.

    Trial-level observations are independent units here, not overlapping Welch
    windows. Incomplete/mismatched pairs are excluded and explicitly counted.
    """
    selected = channels if channels is not None else [0]
    good = [r for r in reports if r.get("analysis", {}).get("eligible") and not r.get("aborted")]
    if kind == "alpha":
        good = [r for r in good if r["analysis"]["timing"].get("count", 0) >=
                10 * r["analysis"]["timing"].get("nominal_hz", 200)]
    out = {"kind": kind, "total_trials": len(reports), "eligible_trials": len(good), "channels": []}
    if kind == "alpha":
        opens = {r["pair"]: r for r in good if r.get("condition") == "eyes_open" and r.get("pair") is not None}
        closes = {r["pair"]: r for r in good if r.get("condition") == "eyes_closed" and r.get("pair") is not None}
        pairs = sorted(set(opens) & set(closes))
        out["complete_pairs"] = len(pairs)
        for ch in selected:
            changes = [10 * np.log10(max(closes[k]["analysis"]["channels"][ch]["alpha_power"], 1e-30) /
                                    max(opens[k]["analysis"]["channels"][ch]["alpha_power"], 1e-30)) for k in pairs]
            out["channels"].append({"channel": ch, "pair_change_db": changes,
                "median_change_db": float(np.median(changes)) if changes else None,
                "supporting_pairs": sum(v >= THRESHOLDS["alpha_increase_db"] for v in changes),
                "repeatable_increase": len(changes) >= 3 and sum(v >= 3 for v in changes) >= math.ceil(2 * len(changes) / 3)})
        out["interpretation"] = "8–13 Hz 파워의 감음/뜸 변화. 유효 데이터 10초 이상인 쌍만 사용합니다. 3 dB·3쌍 기준은 작업용 기준입니다. 반응 없음은 장비 고장/비정상 EEG를 뜻하지 않습니다. 눈 움직임·졸음·광원 잡음을 함께 검토하세요."
    else:
        out["interpretation"] = "단일 자극마다 같은 pair의 정지 화면 기준선과 비교합니다. SNR 상승만으로 신경성 반응을 확정할 수 없습니다."
        baselines = {(r.get("pair"), r.get("frequency")): r for r in good if r.get("condition") == "baseline"}
        for ch in selected:
            rows = []
            for r in good:
                if r.get("condition") != "single" or not r.get("display", {}).get("ok"):
                    continue
                b = baselines.get((r.get("pair"), r.get("frequency")))
                if not b:
                    continue
                key = str(float(r["frequency"]))
                on = r["analysis"]["channels"][ch]["snr_db"].get(key)
                off = b["analysis"]["channels"][ch]["snr_db"].get(key)
                if on is not None and off is not None:
                    rows.append({"frequency": r["frequency"], "pair": r["pair"], "on_snr_db": on,
                                 "off_snr_db": off, "change_db": on - off})
            out["channels"].append({"channel": ch, "trials": rows})
    return clean_json(out)

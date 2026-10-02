"""Standard CCA using orthonormal bases; samples are rows, EEG channels columns."""
import numpy as np
from scipy.signal import butter, sosfiltfilt


def basis(matrix):
    centered = matrix - matrix.mean(axis=0)
    u, s, _ = np.linalg.svd(centered, full_matrices=False)
    if not len(s) or s[0] < 1e-12:
        return u[:, :0]
    return u[:, s > s[0] * 1e-10]


def decode(samples, timestamps, sampling_rate, channels, config, expected_seconds):
    result = {"prediction": None, "scores": {}, "reason": "", "sample_count": len(samples)}

    def reject(reason):
        result["reason"] = reason
        return result

    x = np.asarray(samples, dtype=float)
    ts = np.asarray(timestamps, dtype=float)
    if x.ndim != 2 or len(x) < 2 or ts.shape != (len(x),):
        return reject("수신 데이터가 부족합니다.")
    if not channels or any(type(c) is not int or c < 0 or c >= x.shape[1] for c in channels):
        return reject("사용할 EEG 채널을 확인하세요.")
    if not np.isfinite(x[:, channels]).all() or not np.isfinite(ts).all():
        return reject("선택 채널에 NaN/무한대 값이 있습니다.")
    dt = np.diff(ts)
    result["max_gap_seconds"] = float(dt.max())
    if np.any(dt <= 0) or dt.max() > 0.15:
        return reject("타임스탬프 역전 또는 150 ms 이상의 데이터 공백이 있습니다.")
    measured = (len(ts) - 1) / (ts[-1] - ts[0])
    result["measured_rate_hz"] = float(measured)
    if abs(measured / sampling_rate - 1) > 0.15:
        return reject("실제 수신률과 LSL 샘플링 주파수가 다릅니다.")
    if len(x) < max(2 * sampling_rate, 0.85 * expected_seconds * sampling_rate):
        return reject("샘플 수가 예상보다 적습니다. GUI 데이터 전송을 확인하세요.")
    high = config["bandpass_hz"][1]
    if high >= sampling_rate / 2:
        return reject("필터 상한이 Nyquist 주파수보다 높습니다.")
    # A zero/constant electrode should not silently enter multichannel CCA.
    if np.any(np.std(x[:, channels], axis=0) < 1e-6):
        return reject("선택 채널에 평탄한 신호가 있습니다. 미사용 채널을 해제하세요.")
    x = x[:, channels] - x[:, channels].mean(axis=0)
    filt = butter(4, config["bandpass_hz"], btype="bandpass", fs=sampling_rate, output="sos")
    qx = basis(sosfiltfilt(filt, x, axis=0))
    t = np.arange(len(x)) / sampling_rate
    for target in config["targets"]:
        reference = np.column_stack([
            wave(2 * np.pi * target["frequency"] * harmonic * t)
            for harmonic in range(1, config["harmonics"] + 1)
            for wave in (np.sin, np.cos)
        ])
        qy = basis(reference)
        singular = np.linalg.svd(qx.T @ qy, compute_uv=False)
        result["scores"][target["id"]] = float(np.clip(singular[0], 0, 1)) if len(singular) else 0.0
    ranked = sorted(result["scores"], key=result["scores"].get, reverse=True)
    best, runner_up = (result["scores"][key] for key in ranked[:2])
    result["margin"] = best - runner_up
    if best < config["min_score"] or result["margin"] < config["min_margin"]:
        return reject("상관 점수 또는 후보 간 차이가 작아 판정을 보류했습니다.")
    result["prediction"] = ranked[0]
    return result

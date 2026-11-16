"""Public EEG teaching examples. These are NOT the user's Ganglion recordings.

Uses native 160/256 Hz files; no resampling or fabricated acquisition validation.
Shares band-power, local-SNR and CCA mathematics with the commissioning tool.
"""
import argparse
import base64
import hashlib
import html
from pathlib import Path

import numpy as np
from scipy.io import loadmat
from scipy.signal import welch

from validation import band_power, cca_scores, dumps, local_snr, THRESHOLDS

ROOT = Path(__file__).resolve().parent
CHANNELS = ['O1', 'O2', 'Oz', 'POz']
FREQUENCIES = [9.25, 11.25, 13.25, 9.75, 11.75, 13.75,
               10.25, 12.25, 14.25, 10.75, 12.75, 14.75]
SOURCES = [
    ('physionet/S001R01.edf', 'https://physionet.org/files/eegmmidb/1.0.0/S001/S001R01.edf',
     '4743b736131a7e147c150e8b37711029b6cda5e356c4b3e8261a03cdcaaf8b0c'),
    ('physionet/S001R02.edf', 'https://physionet.org/files/eegmmidb/1.0.0/S001/S001R02.edf',
     '31a95e0a880e6c3d89960d9d62c144f24cc4e9f5d7e93c7f864ef61cd49e847e'),
    ('nakanishi/s1.mat', 'https://raw.githubusercontent.com/mnakanishi/12JFPM_SSVEP/master/data/s1.mat', None),
]
MAT_BLOB_SHA1 = '207bfed4cffea53d851e3892ce58b3c075350765'


def verified_sources(folder, download=False):
    import requests
    manifest = []
    for name, url, expected in SOURCES:
        dest = folder/name
        if not dest.exists():
            if not download:
                raise ValueError(f'{dest} 없음. --download로 공개 예제만 내려받을 수 있습니다.')
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            content = response.content
        else:
            content = dest.read_bytes()
        actual = hashlib.sha256(content).hexdigest()
        if expected and actual != expected:
            raise ValueError(f'{name} SHA-256 불일치')
        if name.endswith('.mat'):
            blob = hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()
            if blob != MAT_BLOB_SHA1:
                raise ValueError('저자 저장소의 검증된 s1.mat Git blob과 다릅니다.')
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
        manifest.append({'file':name, 'url':url, 'sha256':actual, 'bytes':len(content)})
    return manifest


def make_examples(data_folder, dest, download=False):
    import mne
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    manifest = verified_sources(data_folder, download)
    dest.mkdir(parents=True, exist_ok=True)
    alpha = []
    for run, condition in [(1, 'eyes_open'), (2, 'eyes_closed')]:
        raw = mne.io.read_raw_edf(data_folder/f'physionet/S001R{run:02d}.edf', preload=True, verbose=False)
        mne.datasets.eegbci.standardize(raw)
        fs = raw.info['sfreq']
        # Fixed, preselected 5..60 s region. One EO/EC pair, not three independent pairs.
        x = raw.get_data(picks=CHANNELS, start=int(5*fs), stop=int(60*fs)).T*1e6
        f, p = welch(x, fs=fs, nperseg=int(4*fs), axis=0)
        power = band_power(f, p, 8, 13)
        alpha.append({'condition':condition, 'fs':fs, 'x':x, 'f':f, 'psd':p, 'power':power})
    alpha_change = 10*np.log10(alpha[1]['power']/alpha[0]['power'])
    # Independent public API with exactly matched settings, not an attempt to
    # reproduce the MNE tutorial's different 19-second/boxcar estimator.
    check_psd, check_freq = mne.time_frequency.psd_array_welch(
        alpha[0]['x'].T, 160, n_fft=640, n_per_seg=640, n_overlap=320,
        window='hann', verbose=False)
    np.testing.assert_allclose(check_freq, alpha[0]['f'])
    np.testing.assert_allclose(check_psd.T, alpha[0]['psd'], rtol=1e-10, atol=1e-12)

    eeg = loadmat(data_folder/'nakanishi/s1.mat')['eeg']
    if eeg.shape != (12,8,1114,15):
        raise ValueError('예상한 저자 데이터 shape와 다릅니다.')
    # Native 256 Hz, onset = MATLAB sample 39 (Python 38). Use a fixed 0.25 s
    # settling delay then 3.5 s. This is not the paper's optimized latency.
    start = 38+64
    end = start+896
    picks = [5,7,6,2]  # O1, O2, Oz, POz; original 8-channel montage.
    classifications, psds = [], []
    for label, target in enumerate(FREQUENCIES):
        class_psd = []
        for trial in range(15):
            x = eeg[label,picks,start:end,trial].T
            f, p = welch(x, fs=256, nperseg=len(x), axis=0)
            class_psd.append(p)
            scores = cca_scores(x, 256, targets=FREQUENCIES)
            ranked = sorted(scores, key=scores.get, reverse=True)
            chosen = float(ranked[0])
            accepted = (scores[ranked[0]] >= THRESHOLDS['cca_score'] and
                        scores[ranked[0]]-scores[ranked[1]] >= THRESHOLDS['cca_margin'])
            classifications.append({'target_hz':target, 'trial':trial+1, 'top1_hz':chosen,
                                    'accepted':accepted, 'prediction_hz':chosen if accepted else None,
                                    'scores':scores})
        psds.append(np.stack(class_psd))
    n = len(classifications)
    forced_correct = sum(r['top1_hz']==r['target_hz'] for r in classifications)
    accepted = sum(r['accepted'] for r in classifications)
    accepted_correct = sum(r['prediction_hz']==r['target_hz'] for r in classifications)
    snr_grid = np.array([[np.median(local_snr(f, p.transpose(1,0,2), target)['snr_db'],axis=0)[2]
                         for target in FREQUENCIES] for p in psds])
    metrics = {'public_reference_only':True, 'user_hardware_validated':False, 'mne_version':mne.__version__,
               'channels':CHANNELS, 'sources':manifest,
               'matched_MNE_Welch_max_abs_error':float(np.max(np.abs(check_psd.T-alpha[0]['psd']))),
               'alpha':{'subject':'S001', 'fs':160, 'region_seconds':[5,60], 'independent_pairs':1,
                        'power_open':alpha[0]['power'], 'power_closed':alpha[1]['power'], 'change_db':alpha_change},
               'ssvep':{'subject':'s1', 'fs':256, 'region_samples_python':[start,end], 'trials':n,
                        'targets_hz':FREQUENCIES, 'top1_correct':forced_correct, 'accepted':accepted,
                        'accepted_correct':accepted_correct, 'all_attempt_accuracy':accepted_correct/n,
                        'no_control_recordings':0, 'trial_results':classifications,
                        'snr_median_db_Oz':snr_grid,
                        'note':'Source numerical units are not used for amplitude/rail judgments. No Ganglion transport QC; no hardware timestamps. No tuning of channel subset, window or thresholds on this subject.'}}
    (dest/'metrics.json').write_text(dumps(metrics),encoding='utf-8')

    fig,axes=plt.subplots(2,2,figsize=(13,8.5),layout='constrained')
    colors=['#246e83','#c37135']
    for k,a in enumerate(alpha):
        ax=axes[0,0]
        keep=(a['f']>=2)&(a['f']<=35)
        ax.plot(a['f'][keep],10*np.log10(a['psd'][keep,2]),label=['Eyes open','Eyes closed'][k],color=colors[k])
    ax.set(xlim=(2,35),xlabel='Frequency [Hz]',ylabel='Oz PSD [dB uV²/Hz]',title='A. Public resting EEG: eyes closed vs open')
    ax.axvspan(8,13,color='#b6d2b6',alpha=.25);ax.legend()
    ax=axes[0,1]
    ax.bar(CHANNELS,alpha_change,color='#246e83');ax.axhline(0,color='gray',lw=1)
    ax.set(ylabel='Closed / open alpha power [dB]',title='B. One public EO/EC pair; not 3 repeat trials')
    for i,v in enumerate(alpha_change):ax.text(i,v+.15,f'{v:.1f}',ha='center')
    ax=axes[1,0]
    for k,target in enumerate([12.25,14.75]):
        p=psds[FREQUENCIES.index(target)].mean(axis=0)[:,2]
        # Normalized density avoids assuming this MAT's raw numerical units.
        norm=p/np.sum(p[(f>=5)&(f<=35)])/(f[1]-f[0])
        keep=(f>=5)&(f<=32)
        ax.plot(f[keep],10*np.log10(norm[keep]),label=f'Attend {target} Hz',color=colors[k])
    ax.set(xlim=(5,32),xlabel='Frequency [Hz]',ylabel='Oz normalized PSD [dB/Hz]',title='C. Public SSVEP: mean of 15 trials per target')
    ax.legend();ax.axvline(12.25,color=colors[0],ls=':',alpha=.5);ax.axvline(14.75,color=colors[1],ls=':',alpha=.5)
    ax=axes[1,1]
    im=ax.imshow(snr_grid,vmin=-5,vmax=15,cmap='viridis',aspect='auto')
    ax.set(xticks=range(12),yticks=range(12),xticklabels=[str(v) for v in FREQUENCIES],yticklabels=[str(v) for v in FREQUENCIES],
           xlabel='Measured frequency [Hz]',ylabel='Attended target [Hz]',title='D. All targets: median single-trial Oz SNR')
    ax.tick_params(axis='x',labelrotation=65,labelsize=8);ax.tick_params(axis='y',labelsize=8)
    fig.colorbar(im,ax=ax,label='SNR [dB]')
    fig.suptitle('Public EEG teaching examples — not Ganglion, not your EEG',fontsize=17,weight='bold')
    fig.savefig(dest/'public_eeg_examples.png',dpi=160);plt.close(fig)
    image_data=base64.b64encode((dest/'public_eeg_examples.png').read_bytes()).decode()
    rows=''.join(f'<tr><td>{ch}</td><td>{a:.2f}</td><td>{b:.2f}</td><td>{d:.2f}</td></tr>' for ch,a,b,d in zip(CHANNELS,alpha[0]['power'],alpha[1]['power'],alpha_change))
    page=f'''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>공개 EEG 참고 예제</title><style>body{{max-width:1100px;margin:30px auto;padding:20px;font:17px/1.8 system-ui;color:#17313b}}img{{max-width:100%}}td,th{{border:1px solid #ccd;padding:8px}}table{{border-collapse:collapse}}.note{{background:#fff1da;padding:18px}}pre{{white-space:pre-wrap;font-size:13px}}</style>
    <h1>실제 공개 EEG에서 무엇을 찾아보는가</h1><p class="note">사용자의 기록도, Ganglion의 성능 시험도 아닙니다. 공개 자료의 첫 번째 참가자를 미리 정해 분석한 교육용 예제입니다. 피크가 약한 trial도 모두 포함했습니다.</p>
    <img alt="공개 EEG의 알파 조건 차이와 SSVEP 주파수별 비교" src="data:image/png;base64,{image_data}">
    <h2>눈 뜸/감음: 같은 사람·같은 채널의 변화</h2><p>PhysioNet EEGMMIDB S001의 R01(눈 뜸)과 R02(눈 감음), 각각 5–60초를 사용했습니다. 160 Hz를 그대로 유지했고 O1/O2/Oz/POz만 골랐습니다. 재참조·ICA·notch 없이 4초 Hann Welch PSD를 계산했습니다. 한 쌍의 기록이며 여러 조각으로 잘라 독립 3쌍이라고 세지 않았습니다.</p>
    <table><tr><th>채널</th><th>뜸 알파 µV²</th><th>감음 알파 µV²</th><th>변화 dB</th></tr>{rows}</table>
    <p>후두부 8–13 Hz가 조건에 따라 변하는 모양을 참고하세요. 이 참가자의 진폭이나 변화량을 사용자의 필수 합격 기준으로 사용하지 않습니다.</p>
    <h2>SSVEP: 조건을 바꾸면 목표 빈도의 근거도 바뀌는가</h2><p>Nakanishi 연구진의 공개 s1 자료에서 원래 256 Hz와 12개 주파수를 유지했습니다. O1/O2/Oz/POz 네 채널, onset 후 0.25초부터 3.5초를 고정해 사용했습니다. 위의 두 선은 12.25/14.75 Hz 조건 각 15회 평균입니다. 오른쪽은 모든 12조건의 단일 trial SNR 중앙값입니다. 평균 그림에서 보이는 차이가 매번 큰 단일 피크를 뜻하지는 않습니다.</p>
    <p>같은 CCA 연산(7–35 Hz, 고조파 2개)을 12개 후보에 적용하면 최대 점수 강제 선택은 {forced_correct}/{n}입니다. 초기 점수·차이 기준을 적용하면 {accepted}/{n}회만 채택되고 그중 {accepted_correct}회가 맞습니다. 보류를 포함한 전체 정확도는 {accepted_correct/n*100:.1f}%입니다. 이 작은 예제는 논문 전체 성능 재현, 사용자 정확도 예측 또는 임계값 검증이 아닙니다. 시선 이탈 대조가 없어서 오탐률도 계산할 수 없습니다.</p>
    <p>이 MAT 자료의 큰 DC 값으로 Ganglion 포화를 판정하지 않았습니다. SSVEP 그림은 정규화한 파워, SNR과 CCA는 척도에 불변인 값을 사용합니다. 주파수 계산은 알려진 256 Hz를 쓰지만 파일에 실시간 수집 시각이 없으므로 전송 품질 검사와는 무관합니다.</p>
    <h2>출처와 재현</h2><p><a href="https://physionet.org/content/eegmmidb/1.0.0/">Schalk, EEG Motor Movement/Imagery Dataset (2009), DOI 10.13026/C28G6P</a>, <a href="https://pubmed.ncbi.nlm.nih.gov/15188875/">Schalk et al., BCI2000 (2004)</a>. PhysioNet 자료는 Open Data Commons Attribution License v1.0에 따릅니다. 플랫폼 인용: <a href="https://doi.org/10.1038/s44360-026-00096-z">Pollard et al., PhysioNet (2026)</a>.</p>
    <p><a href="https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0140703">Nakanishi et al. (2015), PLOS ONE, DOI 10.1371/journal.pone.0140703</a>; <a href="https://github.com/mnakanishi/12JFPM_SSVEP">저자의 원본 데이터 저장소</a>. 논문은 CC BY이며 원자료를 이 코드 저장소에 재배포하지 않습니다. 내려받은 원본은 로컬 validation_reports/reference_data에 보존했습니다.</p>
    <pre>.venv-brainflow-validation/bin/python software/ganglion/reference_examples.py
# 파일이 없는 다른 컴퓨터: requirements-reference.txt 설치 후 --download</pre>
    <details><summary>파일 해시와 다운로드 출처</summary><pre>{html.escape(dumps(manifest))}</pre></details>
    <p>그림은 이번 코드로 생성했습니다. 분석 수치와 180회 결과는 같은 폴더의 metrics.json에 있습니다. MNE의 별도 12/15 Hz 예제는 저장 서버 DNS 오류로 내려받지 못해 분석하지 않았습니다.</p></html>'''
    (dest/'index.html').write_text(page,encoding='utf-8')
    print(dumps({'alpha_change_db':alpha_change, 'ssvep_top1_correct':forced_correct,
                 'ssvep_accepted':accepted, 'ssvep_accepted_correct':accepted_correct,
                 'trials':n,'report':str((dest/'index.html').resolve())}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,default=ROOT/'validation_reports/reference_data')
    parser.add_argument('--out',type=Path,default=ROOT/'validation_reports/reference')
    parser.add_argument('--download',action='store_true')
    args=parser.parse_args()
    make_examples(args.data,args.out,args.download)

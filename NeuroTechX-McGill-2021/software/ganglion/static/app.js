const $ = id => document.getElementById(id);
let config, active = false, busy = false, receiving = false, frame = 0, generation = 0, count = 0;
const targetElements = [];
async function api(path, body) {
  const response = await fetch(`/api/${path}`, body === undefined ? {} : {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}
function controls() {
  $('start').disabled = active || busy || !receiving || !config;
  $('stop').disabled = !active;
  $('scan').disabled = active || busy;
  $('connect').disabled = active || busy || !$('streams').value;
  $('disconnect').disabled = active || busy;
  document.querySelectorAll('#settings input, #settings select, #streams').forEach(e => e.disabled = active || busy);
}
function darken() { cancelAnimationFrame(frame); targetElements.forEach(e => e.style.backgroundColor = 'rgb(60,60,60)'); }
async function refresh() {
  try {
    const s = await api('status');
    receiving = s.receiving;
    $('status').textContent = s.connected ? `${s.stream.name} · ${s.stream.channels}채널 · 설정 ${s.stream.sampling_rate} Hz · 수신 ${s.measured_rate_hz?.toFixed(1) ?? '—'} Hz · ${s.receiving ? '수신 중' : '데이터 대기 / 중단'}` : '연결되지 않았습니다. GUI의 LSL 스트림을 검색하세요.';
    if (s.error) $('status').textContent += ` · ${s.error}`;
  } catch (e) { receiving = false; $('status').textContent = `서버 연결 실패: ${e.message}`; }
  controls();
}
$('streams').onchange = controls;
$('scan').onclick = async () => {
  busy = true; controls(); $('message').textContent = 'EEG 스트림 검색 중…';
  try {
    const data = await api('streams'); $('streams').replaceChildren();
    data.streams.forEach(s => $('streams').add(new Option(`${s.name} · ${s.channels}ch · ${s.sampling_rate} Hz`, s.uid)));
    $('message').textContent = data.streams.length ? 'Ganglion 4채널 TimeSeries 스트림을 선택하고 연결하세요.' : 'EEG 스트림이 없습니다. GUI의 Start LSL Stream과 Start Data Stream을 확인하세요.';
  } catch (e) { $('message').textContent = e.message; }
  finally { busy = false; controls(); }
};
$('connect').onclick = async () => {
  busy = true; controls();
  try { await api('connect', {uid: $('streams').value}); $('message').textContent = '연결했습니다. 수신 중 표시를 기다리세요.'; }
  catch (e) { $('message').textContent = e.message; }
  finally { busy = false; await refresh(); }
};
$('disconnect').onclick = async () => {
  busy = true; controls();
  try { await api('disconnect', {}); } catch (e) { $('message').textContent = e.message; }
  finally { busy = false; await refresh(); }
};
async function abort() {
  if (!active) return;
  generation++; darken(); active = false; busy = true; controls();
  $('progress').textContent = '중단됨'; $('message').textContent = '측정을 중단했습니다. 이번 구간은 저장하지 않습니다.';
  try { await api('trial/abort', {}); } catch (e) { $('message').textContent = e.message; }
  finally { busy = false; controls(); }
}
$('stop').onclick = abort;
document.addEventListener('keydown', e => { if (e.key === 'Escape') abort(); });
document.addEventListener('visibilitychange', () => { if (document.hidden) abort(); });
window.addEventListener('pagehide', () => {
  darken();
  if (active) fetch('/api/trial/abort', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}', keepalive: true});
});
$('start').onclick = async () => {
  active = true; controls(); const token = ++generation;
  const target = $('target').value || null;
  const channels = [...document.querySelectorAll('input[name=channel]:checked')].map(e => Number(e.value));
  targetElements.forEach((e, i) => e.classList.toggle('chosen', config.targets[i].id === target));
  $('message').textContent = target ? `${target} 자극을 바라보세요.` : '선택한 자극 하나를 바라보세요.';
  try {
    const trial = await api('trial/start', {target, channels});
    if (token !== generation) { await api('trial/abort', {}); return; }
    const times = []; let first;
    const animate = time => {
      if (token !== generation) return;
      if (first === undefined) first = time;
      const elapsed = time - first; times.push(elapsed);
      if (elapsed >= trial.duration_seconds * 1000) { darken(); finish(trial.id, times, token); return; }
      targetElements.forEach((e, i) => {
        const light = Math.round(125 + 95 * Math.sin(2 * Math.PI * config.targets[i].frequency * elapsed / 1000));
        e.style.backgroundColor = `rgb(${light},${light},${light})`;
      });
      $('progress').textContent = `${Math.ceil(trial.duration_seconds - elapsed / 1000)}초`;
      frame = requestAnimationFrame(animate);
    };
    frame = requestAnimationFrame(animate);
  } catch (e) {
    if (token === generation) { darken(); active = false; controls(); $('message').textContent = e.message; }
  }
};
async function finish(id, frameTimes, token) {
  active = false; busy = true; controls(); $('progress').textContent = '분석 중';
  try {
    const r = await api('trial/stop', {id, frame_times_ms: frameTimes});
    if (token !== generation) return;
    $('message').textContent = r.prediction ? `예측: ${r.prediction}${r.target ? (r.correct ? ' · 정답' : ' · 오답') : ''}` : `판정 보류: ${r.reason}`;
    $('scores').replaceChildren();
    Object.entries(r.scores).forEach(([key, value]) => { const s = document.createElement('span'); s.textContent = `${key}: ${value.toFixed(3)}`; $('scores').append(s); });
    $('details').textContent = `분석 샘플 ${r.sample_count} · 수신 ${r.measured_rate_hz?.toFixed(1) ?? '—'} Hz · 화면 ${r.display_fps?.toFixed(1) ?? '—'} fps · 최대 프레임 간격 ${r.max_frame_gap_ms?.toFixed(1) ?? '—'} ms`;
    $('saved').textContent = `저장: software/ganglion/recordings/${r.recording}`;
    const row = document.createElement('tr');
    [++count, r.target || '—', r.prediction || '보류', r.target ? (r.correct ? '정답' : '오답 / 보류') : '—'].forEach(v => { const cell = document.createElement('td'); cell.textContent = v; row.append(cell); });
    $('history').prepend(row); $('progress').textContent = '완료';
  } catch (e) { $('message').textContent = e.message; $('progress').textContent = '오류'; }
  finally { busy = false; controls(); }
}
(async () => {
  try {
    config = await api('config');
    config.targets.forEach(t => {
      const box = document.createElement('div'); box.className = 'target';
      const title = document.createElement('strong'); title.textContent = t.id;
      const frequency = document.createElement('span'); frequency.textContent = `${t.frequency} Hz`;
      box.append(title, frequency); $('targets').append(box); targetElements.push(box);
      $('target').add(new Option(`${t.id} (${t.frequency} Hz)`, t.id));
    });
  } catch (e) { $('message').textContent = e.message; }
  await refresh(); setInterval(refresh, 1500);
})();

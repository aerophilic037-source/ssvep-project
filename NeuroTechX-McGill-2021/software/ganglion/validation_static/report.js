/* Shared by live UI and fully offline reports. No libraries or network access. */
function node(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;}
function fmt(v,d=2){return typeof v==='number'&&Number.isFinite(v)?v.toFixed(d):'—';}
function table(headers,rows){const wrap=node('div',undefined,'table-wrap'),t=node('table'),head=node('tr');headers.forEach(h=>head.append(node('th',h)));t.append(head);for(const row of rows){const tr=node('tr');for(const v of row)tr.append(node('td',v??'—'));t.append(tr);}wrap.append(t);return wrap;}
const chartColors=['#7bd2c4','#f3cb88','#a9baff','#eea5cd'];
function chart(canvas,x,series,{labels=[],xmin=null,xmax=null,ymin=null,ymax=null,band=null,xlabel='',ylabel=''}={}){
  const w=1000,h=270;canvas.width=w;canvas.height=h;const c=canvas.getContext('2d');c.fillStyle='#111a20';c.fillRect(0,0,w,h);
  const l=70,r=20,top=28,bottom=43,pw=w-l-r,ph=h-top-bottom;
  const finite=series.flat().filter(Number.isFinite);if(!finite.length||!x.length)return;
  xmin=xmin??Math.min(...x);xmax=xmax??Math.max(...x);ymin=ymin??Math.min(...finite);ymax=ymax??Math.max(...finite);
  if(ymax-ymin<1e-10){ymin-=1;ymax+=1;}const pad=(ymax-ymin)*.07;ymin-=pad;ymax+=pad;
  const xx=v=>l+(v-xmin)/(xmax-xmin||1)*pw,yy=v=>top+ph-(v-ymin)/(ymax-ymin)*ph;
  if(band){c.fillStyle='#29483c';c.fillRect(xx(band[0]),top,xx(band[1])-xx(band[0]),ph);}
  c.font='12px system-ui';c.strokeStyle='#34434c';c.fillStyle='#9eb1bb';
  for(let i=0;i<=5;i++){const y=ymin+(ymax-ymin)*i/5;c.beginPath();c.moveTo(l,yy(y));c.lineTo(w-r,yy(y));c.stroke();c.fillText(y.toFixed(1),6,yy(y)+4);const xv=xmin+(xmax-xmin)*i/5;c.fillText(xv.toFixed(1),xx(xv)-12,h-23);}
  c.save();c.beginPath();c.rect(l,top,pw,ph);c.clip();
  series.forEach((values,k)=>{c.strokeStyle=chartColors[k%4];c.lineWidth=1.3;c.beginPath();let started=false;values.forEach((v,i)=>{if(!Number.isFinite(v)||x[i]<xmin||x[i]>xmax){started=false;return;}if(!started)c.moveTo(xx(x[i]),yy(v));else c.lineTo(xx(x[i]),yy(v));started=true;});c.stroke();});c.restore();
  c.fillStyle='#c6d5dc';c.fillText(ylabel,l,17);c.fillText(xlabel,w-160,h-5);labels.forEach((v,i)=>{c.fillStyle=chartColors[i%4];c.fillText(v,l+260+i*140,17);});
}
function renderAnalysis(parent,a,{plots=true}={}){
  if(!a){parent.append(node('p','분석 정보가 없습니다.'));return;}
  const timing=a.timing||{};
  parent.append(node('p',`수집 시간축: ${a.spectral_valid?'작업 기준 통과':'확인 필요'} · 선택 채널 품질: ${a.signal_ok?'작업 기준 통과':'확인 필요'} · ${a.eligible?'다음 단계 비교 가능':'생리 반응 판정 보류'}`,a.eligible?'good':'warn'));
  parent.append(node('p',`샘플 ${timing.count??0}개 · 설정 ${fmt(timing.nominal_hz,1)} Hz · 소스 시각 ${fmt(timing.timestamp_rate_hz,1)} Hz · 컴퓨터 도착 ${fmt(timing.receipt_rate_hz,1)} Hz · 전체 측정 ${fmt(timing.capture_rate_hz,1)} Hz`));
  parent.append(node('p',`역전 ${timing.backwards??0} · 중복 시각 ${timing.duplicates??0} · 최대 공백 ${fmt(timing.max_gap_s?timing.max_gap_s*1000:timing.max_gap_s,1)} ms`, 'muted'));
  const messages=[...(timing.issues||[]),...(a.warnings||[])];if(messages.length){const ul=node('ul');messages.forEach(m=>ul.append(node('li',m)));parent.append(ul);}
  for(const note of(timing.notes||[]))parent.append(node('p',note,'muted'));
  parent.append(table(['채널','상태','AC RMS (µV)','Raw 평균 / p-p (µV)','입력 범위 근처','50/60 Hz 비중','알파 파워','주요 피크'],(a.channels||[]).map(ch=>[
    `CH${ch.channel+1}${ch.selected?' ✓':''}`,ch.flags.join(' · ')||'작업 기준 통과',fmt(ch.ac_rms_uv),`${fmt(ch.mean_uv,1)} / ${fmt(ch.raw_ptp_uv,1)}`,ch.near_rail_fraction===null?'단위 미확인':`${fmt(ch.near_rail_fraction*100)}%`,`${fmt(ch.line_fraction*100,1)}%`,fmt(ch.alpha_power),`${fmt(ch.peak_hz)} Hz`])));
  if(a.input_units==='unknown')parent.append(node('p','단위 미확인: 표의 µV 표기는 적용되지 않으며 값은 입력 단위입니다.','warn'));
  const selected=a.selected_channels||[0];
  if(plots&&a.plot){const p=a.plot,labels=selected.map(ch=>`CH${ch+1}`);parent.append(node('p',a.spectral_valid?'원시 신호 PSD · 알파 대역 8–13 Hz':'주파수축 미검증 — 설정 Hz를 가정한 참고 PSD','legend'));const psd=node('canvas');parent.append(psd);chart(psd,p.freqs,selected.map(ch=>p.psd_db.map(row=>row[ch])),{labels,xmin:0,xmax:90,band:[8,13],xlabel:'Hz (설정값 기준)',ylabel:'PSD dB (µV²/Hz)'});
    const c=node('canvas');parent.append(node('p','마지막 5초 · 1–40 Hz 표시 필터 (저장 파일은 필터 전 값)','legend'),c);chart(c,p.trace_t,selected.map(ch=>p.filtered.map(row=>row[ch])),{labels,xlabel:'초 (샘플 순서)',ylabel:'µV'});
    const d=node('details'),s=node('summary','원시 파형 범위 보기 (평균만 제거, 필터 없음)');d.append(s);const raw=node('canvas');d.append(raw);parent.append(d);const ch=selected[0];chart(raw,p.trace_t,[p.raw_min.map(row=>row[ch]),p.raw_max.map(row=>row[ch])],{labels:[`CH${ch+1} min`,`CH${ch+1} max`],xlabel:'초 (샘플 순서)',ylabel:'µV'});
  }
  if(a.channels?.length){parent.append(node('p','목표/고조파 주변 SNR (dB). 0 dB는 주변 빈 평균과 같은 파워입니다.','legend'));parent.append(table(['채널','10 Hz','12 Hz','15 Hz','20 Hz','24 Hz','30 Hz'],selected.map(ch=>[`CH${ch+1}`,...['10.0','12.0','15.0','20.0','24.0','30.0'].map(f=>fmt(a.channels[ch].snr_db[f]))])));}
  if(a.cca_scores_exploratory)parent.append(node('p','참고 CCA: '+Object.entries(a.cca_scores_exploratory).map(([f,v])=>`${f} Hz ${fmt(v,3)}`).join(' · ')+' (확률 아님)','muted'));
  if(a.methods||a.thresholds){const d=node('details');d.append(node('summary','분석 방법과 작업용 기준'),node('pre',JSON.stringify({methods:a.methods,thresholds:a.thresholds},null,2)));parent.append(d);}
}
function renderSummary(parent,summary){
  if(!summary)return;
  const a=summary.alpha;parent.append(node('h3',`알파 비교 · 유효한 완성 쌍 ${a.complete_pairs??0}`));
  parent.append(table(['채널','감음−뜸 중앙값 (dB)','각 쌍 변화','≥3 dB 쌍 수','반복 증가 근거'],a.channels.map(c=>[`CH${c.channel+1}`,fmt(c.median_change_db),c.pair_change_db.map(v=>fmt(v)).join(', '),c.supporting_pairs,c.repeatable_increase?'관찰됨':'미확인'])));parent.append(node('p',a.interpretation,'muted'));
  parent.append(node('h3','단일 자극 · 정지 화면 대조'));for(const c of summary.single.channels){if(!c.trials?.length)continue;parent.append(node('p',`CH${c.channel+1}`),table(['Hz','쌍','ON SNR','OFF SNR','차이 (dB)'],c.trials.map(t=>[t.frequency,t.pair+1,fmt(t.on_snr_db),fmt(t.off_snr_db),fmt(t.change_db)])));}
  parent.append(node('p',summary.single.interpretation,'muted'));
  const q=summary.choice;parent.append(node('h3','3지선다 · 보류와 대조 조건 포함'));
  parent.append(node('p',`정답 ${q.correct}/${q.attempted} · 전체 정확도 ${q.accuracy_all_attempts===null?'—':fmt(q.accuracy_all_attempts*100,1)+'%'} · 채택 ${q.accepted}/${q.attempted} · 품질/시간 실패 ${q.invalid} · 채택된 시도 정확도 ${q.accuracy_accepted===null?'—':fmt(q.accuracy_accepted*100,1)+'%'} · 시선 이탈 오탐 ${q.no_control_false_positives}/${q.no_control_attempts}`));
  parent.append(table(['정답 → 예측','10 Hz','12 Hz','15 Hz','보류'],Object.entries(q.confusion).map(([f,row])=>[f,...['10.0','12.0','15.0','None'].map(p=>row[p])])));
  parent.append(node('p',`우연 수준 1/3 대비 단측 이항 p=${fmt(q.binomial_p_one_sided,4)}. ${q.note}`,'muted'));
}
function renderReport(parent,payload){
  parent.replaceChildren();
  if(payload.files){parent.append(node('p',`파일 ${payload.files.length}개 · ${payload.created_local||''}`));for(const file of payload.files){const d=node('details',undefined,'block');d.append(node('summary',file.file||file.error));if(file.report_file){const a=node('a','파형·PSD가 포함된 개별 보고서');a.href='./'+encodeURIComponent(file.report_file);d.append(a);}if(file.analysis)renderAnalysis(d,file.analysis);else d.append(node('p',file.error,'bad'));parent.append(d);}return;}
  if(payload.analysis&&!payload.trials){parent.append(node('p',payload.file||payload.condition||'','report-file'));if(payload.metadata){const d=node('details');d.append(node('summary','원본 기록 메타데이터'),node('pre',JSON.stringify(payload.metadata,null,2)));parent.append(d);}renderAnalysis(parent,payload.analysis);return;}
  parent.append(node('p',`세션 ${payload.id} · ${payload.created_utc}`));
  const setup=node('details'),s=node('summary','측정 설정 / 전극 / 기준값');setup.append(s,node('pre',JSON.stringify(payload.setup,null,2)));parent.append(setup);
  renderSummary(parent,payload.summary);
  parent.append(node('h2',`구간 기록 ${payload.trials?.length||0}개`));
  for(const [i,t]of(payload.trials||[]).entries()){const d=node('details',undefined,'block');d.append(node('summary',`${i+1}. ${t.condition} ${t.frequency?`${t.frequency} Hz`:''} · ${t.aborted?'중단 기록':t.valid_for_decision?'비교 가능':'확인 필요'} · ${fmt(t.elapsed_seconds,1)}초`));d.append(node('p',t.recording,'report-file'));if(t.aborted)d.append(node('p',`중단 사유: ${t.abort_reason}`,'warn'));if(t.display?.median_fps)d.append(node('p',`표시 ${fmt(t.display.median_fps,1)} fps · 누락 추정 ${fmt(t.display.dropped_fraction*100,2)}% · ${t.display.reason}`));renderAnalysis(d,t.analysis);parent.append(d);}
}

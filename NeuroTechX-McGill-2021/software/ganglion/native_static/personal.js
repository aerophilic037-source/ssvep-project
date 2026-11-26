/* Personal calibration and frozen-model evaluation. Uses shared capture/stop UI. */
let personalMode=new URLSearchParams(location.search).get('mode')==='personal';
let personalState=null, onsetPromise=null, onsetClock=null, personalBlock=null;
function personalControls(){
 const locked=running||busy||!!current;
 document.querySelectorAll('#personal-panel input,#personal-panel button,#personal-panel select').forEach(e=>e.disabled=locked);
 if(!personalMode)return;
 for(const id of ['personal-distance','personal-size','personal-light'])$(id).disabled=locked||!!personalState;
 $('run').disabled=true;
 $('personal-prepare').disabled=locked||!sessionId||!!personalState;
 $('personal-calibrate').disabled=locked||!receiving||!personalState||personalState.calibration_completed>=45||!!personalState.model_id;
 $('personal-train').disabled=locked||!personalState||personalState.calibration_completed!==45||!!personalState.model_id;
 $('personal-evaluate').disabled=locked||!receiving||!personalState?.model_id||personalState.evaluation_completed>=45;
}
async function personalRefresh(){
 if(!personalMode)return;
 try{personalState=await api('personal/status');renderPersonal();}catch(e){tell(e.message,true);}personalControls();
}
function renderPersonal(){
 const out=$('personal-results');out.replaceChildren();
 if(!personalState){out.append(node('p','새 세션을 만든 후 실험 준비를 누르세요.'));return;}
 const s=personalState;out.append(node('p',`유효 보정 ${s.calibration_completed}/45 · 평가 시도 ${s.evaluation_completed}/45 · ${s.model_id?'모델 고정됨':'미학습'}`));
 if(s.cv){out.append(node('p','보정 교차검증 최고점 선택 결과 (독립 평가가 아님)'));out.append(table(['알고리즘','정답 / 30'],Object.entries(s.cv).map(([k,v])=>[k,v.forced_choice_correct])));out.append(table(['모델','목표당 학습 횟수','검증 정답 / 30'],Object.entries(s.cv).flatMap(([k,v])=>(v.learning_curve||[]).map(p=>[k,p.training_trials_per_target,`${p.correct}/${p.n}`]))));out.append(node('p','거절 문턱은 보정 교차검증 점수에 맞췄습니다. 이 단계의 문턱 성능은 독립 평가가 아닙니다.'));}
 out.append(table(['모델','전체 정답률','정답 / 시도','보류','오선택','무효 목표','시선 이탈 오선택 / 유효','무효 시선 이탈'],Object.entries(s.algorithms).map(([k,v])=>[k,v.accuracy_all===null?'—':`${(v.accuracy_all*100).toFixed(1)}%`,`${v.correct}/${v.target_attempts}`,v.rejected,v.wrong_accepted,v.invalid_targets,`${v.control_false_positives}/${v.valid_controls}`,v.invalid_controls])));
 const a=node('a','개인 실험 전체 보고서');a.href=`/files/${sessionId}/personal_report.html`;a.target='_blank';a.rel='noopener';out.append(a);
}
async function syncPersonalClock(){
 const samples=[];
 for(let i=0;i<5;i++){const before=performance.now()/1000;const r=await api('personal/clock');const after=performance.now()/1000;samples.push({offset:r.server_time-(before+after)/2,uncertainty_ms:(after-before)*500});}
 const best=samples.sort((a,b)=>a.uncertainty_ms-b.uncertainty_ms)[0];
 if(best.uncertainty_ms>10)throw Error('브라우저–서버 시계 오차 >10 ms. 다른 작업을 줄이고 다시 시도하세요.');return best;
}
function personalOnFirstFrame(time){
 if(!personalBlock||!current||!onsetClock)return;
 onsetPromise=api('personal/onset',{id:current.id,server_time:time/1000+onsetClock.offset,uncertainty_ms:onsetClock.uncertainty_ms,geometry:{width:innerWidth,height:innerHeight,dpr:devicePixelRatio,target_px:$('stimuli').querySelector('.stimulus')?.getBoundingClientRect().width}})
 .then(()=>({ok:true})).catch(e=>({ok:false,error:e.message}));
}
async function runPersonal(phase){
 if(!$('flicker-ready').checked){tell('자극 주의사항과 중단 방법 확인란을 선택하세요.',true);return;}
 if(!receiving||!sessionId)return;
 const token=++generation;running=true;controls();let completed=0;
 try{
  const p=await api(`personal/plan/${phase}`);
  // One chunk is at most 15 trials (5 balanced blocks), then explicit rest.
  const blocks=p.blocks.slice(0,15);
  for(const block of blocks){
   if(token!==generation)break;
   neutral();$('cue').textContent=`${phase==='calibration'?'보정':'독립 평가'} ${block.slot+1}/45 · ${block.cue}`;
   $('stimulus-overlay').textContent=$('cue').textContent;$('progress').textContent='준비 5초';$('stage-progress').textContent='준비 5초';speak(block.cue);
   onsetClock=await syncPersonalClock();if(!await delay(5000,token))break;
   const trial=await api('block/start',block);
   if(token!==generation){await saveBlock(trial.id,[],true,'시작 요청 중 중단');break;}
   current=trial;personalBlock=block;onsetPromise=null;
   const frames=await animate(block,token);personalBlock=null;
   if(token!==generation)break;
   const marker=onsetPromise?await onsetPromise:{ok:false,error:'첫 프레임 마커 누락'};
   if(token!==generation)break;
   const result=await saveBlock(trial.id,frames.times,!marker.ok,marker.error||'');current=null;completed++;
   await personalRefresh();
   if(!result.personal?.eligible){tell(`진행을 멈췄습니다: ${result.personal?.error||marker.error}. ${phase==='calibration'?'수정 후 같은 보정 슬롯을 재시도합니다.':'평가 무효 시행은 분모에 남고 다음 슬롯부터 재개합니다.'}`,true);break;}
  }
  if(token===generation){$('cue').textContent=`${completed}회 저장. 1분 이상 쉬고 같은 단계 버튼으로 이어서 진행하세요.`;$('stimulus-overlay').textContent=$('cue').textContent;speak('기록을 저장했습니다. 편하게 쉬세요.');}
 }catch(e){tell(e.message,true);if(current){const t=current;try{await saveBlock(t.id,[],true,'개인 실험 오류');current=null;}catch(err){tell(`부분 저장 확인 필요: ${err.message}`,true);}}}
 finally{personalBlock=null;if(token===generation){running=false;neutral();controls();}await personalRefresh();}
}
$('personal-prepare').onclick=async()=>{busy=true;controls();try{
 const environment={distance_cm:Number($('personal-distance').value),target_cm:Number($('personal-size').value),lighting:$('personal-light').value};
 await api('personal/prepare',{environment});tell('12/15 Hz 보정 실험을 준비했습니다. 화면 검사 후 보정 시작을 누르세요.');
}catch(e){tell(e.message,true);}finally{busy=false;await personalRefresh();controls();}};
$('personal-calibrate').onclick=()=>runPersonal('calibration');
$('personal-evaluate').onclick=()=>runPersonal('evaluation');
$('personal-train').onclick=async()=>{busy=true;controls();tell('보정 기록만으로 블록 교차검증 및 eTRCA/eCCA 학습 중…');try{personalState=await api('personal/train',{});tell('두 모델과 거절 기준을 고정했습니다. 독립 평가를 시작할 수 있습니다.');renderPersonal();}catch(e){tell(e.message,true);}finally{busy=false;controls();}};
$('personal-resume').onclick=async()=>{busy=true;controls();try{const id=$('personal-session-id').value.trim();if(!/^\d{8}T\d{6}Z_[a-f0-9]{12}$/.test(id))throw Error('복구에는 저장된 전체 세션 ID가 필요합니다. 처음 시작하면 복구 대신 새 세션 생성 → 실험 준비를 사용하세요.');const r=await api('personal/resume',{id});sessionId=r.id;$('session-label').textContent=sessionId;setReportLinks();const s=await api('session');fillSetup(s.setup);tell('저장된 실험을 복구했습니다. 전극·화면·거리 조건이 동일할 때 이어서 진행하세요.');}catch(e){tell(e.message,true);}finally{busy=false;await personalRefresh();controls();}};
if(personalMode){document.body.classList.add('personal-mode');$('personal-panel').hidden=false;$('protocol').closest('section').querySelector('h2').textContent='화면 검사와 자극 영역';$('protocol').hidden=true;personalRefresh();setInterval(()=>{if(!running&&!busy)personalRefresh();},3000);}

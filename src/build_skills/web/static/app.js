const $ = id => document.getElementById(id);
let options, material, job, current, step = 0;
const stages = ['导入材料', '配置流程', '材料与草案', '测评与交付'];
const labels = {parsing:'解析材料',awaiting_material_approval:'等待核对材料',awaiting_approval:'等待审阅',approved:'已确认',delivered:'已交付',failed:'调用失败',unmet:'未达到标准',interrupted:'执行中断',new:'准备中',verified:'验证通过'};
function show(n) {
  step = n;
  stages.forEach((_,i) => $(`step${i}`).hidden = i !== n);
  document.querySelectorAll('nav button').forEach((b,i) => {b.classList.toggle('active',i===n);b.disabled = i===1 ? !material || !!job : i>1 && !job;});
}
function error(e) {$('error').textContent=e.message || String(e);$('error').hidden=false;}
async function api(path, init={}) {
  const response = await fetch(`/api/${path}`,{...init,headers:{'X-Build-Skills':'local',...(init.body instanceof FormData ? {} : {'Content-Type':'application/json'}),...init.headers}});
  const value = await response.json();
  if (!response.ok) throw Error(typeof value.detail==='string' ? value.detail : JSON.stringify(value.detail));
  return value;
}
function text(tag, value) {const el=document.createElement(tag);el.textContent=value;return el;}
async function upload(files) {
  if(!files.length)return;
  $('error').hidden=true; $('upload-state').textContent='正在保存原件…';$('configure').disabled=true;
  const data=new FormData();for(const file of files)data.append('files',file);
  try {
    material=await api('materials',{method:'POST',body:data});
    $('materials').replaceChildren();
    for(const file of material.files){const d=document.createElement('details');d.append(text('summary',`${file.name} · ${file.text === null ? "等待 Agent 解析" : file.text.length.toLocaleString()+" 字符"}`),text('pre',file.text ?? '原件已保存。配置模型后，Agent 将读取此文件并返回文本。'));$('materials').append(d);}
    $('upload-state').textContent=`已导入 ${material.files.length} 个文件。复杂文件将在下一步配置模型后解析。`;
    $('configure').disabled=false; show(0);
  }catch(e){material=null;error(e);$('upload-state').textContent='导入失败，请调整文件后重试。';}
}
$('files').onchange=e=>upload(e.target.files);
$('drop').ondragover=e=>{e.preventDefault();$('drop').classList.add('drag');};
$('drop').ondragleave=()=>$('drop').classList.remove('drag');
$('drop').ondrop=e=>{e.preventDefault();$('drop').classList.remove('drag');upload(e.dataTransfer.files);};
document.querySelectorAll('[data-step]').forEach(b=>b.onclick=()=>show(Number(b.dataset.step)));
$('configure').onclick=()=>show(1);
$('new').onclick=async()=>{try{options=await api('options');renderOptions();}catch(e){error(e);return;}job=null;current=null;material=null;$('materials').replaceChildren();$('configure').disabled=true;$('files').value='';$('error').hidden=true;$('history').value='';$('upload-state').textContent='文本可直接预览；复杂文件配置模型后解析。';history.replaceState(null,'',location.pathname);show(0);};
function readChoice(row) {
  return {provider:row.querySelector('[data-connection]').value,model:row.querySelector('[data-model]').value,reasoning_effort:row.querySelector('[data-effort]').value||null};
}
function modelRow(selected, execution=false) {
  const row=document.createElement('div');row.className='model-choice';
  const label=text('label',execution?'执行模型':'统一模型');
  const select=document.createElement('select');select.setAttribute('aria-label',execution?'选择执行模型':'选择构建、评估和重构模型');
  options.catalog.forEach((p,i)=>{const o=text('option',p.label);o.value=String(i);select.append(o);});
  const custom=text('option','自定义模型');custom.value='custom';select.append(custom);label.append(select);row.append(label);
  const details=document.createElement('details');details.append(text('summary','修改模型或思考等级'));
  const fields=document.createElement('div');fields.className='model-fields';
  const connectionLabel=text('label','Agent 连接');const connection=document.createElement('select');connection.dataset.connection='';
  for(const [name,p] of Object.entries(options.connections)){const option=text('option',`${name} (${p.kind})`);option.value=name;connection.append(option);}connectionLabel.append(connection);
  const modelLabel=text('label','模型名称');const model=document.createElement('input');model.dataset.model='';model.setAttribute('list','model-names');modelLabel.append(model);
  const effortLabel=text('label','思考等级');const effort=document.createElement('input');effort.dataset.effort='';effort.setAttribute('list','reasoning-levels');effort.placeholder='使用 Agent 默认值';effort.pattern='[a-z][a-z0-9_-]*';effortLabel.append(effort);
  fields.append(connectionLabel,modelLabel,effortLabel);details.append(fields);row.append(details);
  function assign(value){connection.value=value.provider;model.value=value.model;effort.value=value.reasoning_effort||'';model.required=options.connections[value.provider].kind!=='command';}
  assign(selected);
  const index=options.catalog.findIndex(p=>p.provider===selected.provider&&p.model===selected.model&&(p.reasoning_effort||null)===(selected.reasoning_effort||null));select.value=index<0?'custom':String(index);
  select.onchange=()=>{if(select.value==='custom'){details.open=true;}else assign(options.catalog[Number(select.value)]);};
  for(const field of [connection,model,effort])field.oninput=()=>{select.value='custom';model.required=options.connections[connection.value].kind!=='command';};
  if(execution){const actions=document.createElement('div');actions.className='model-actions';const copy=text('button','重复此模型');copy.type='button';copy.className='secondary';copy.onclick=()=>addExecutor(readChoice(row));const remove=text('button','移除');remove.type='button';remove.className='secondary';remove.onclick=()=>{row.remove();};actions.append(copy,remove);row.append(actions);}
  return row;
}
function addExecutor(selected){if($('executor-models').children.length>=20){error(Error('最多选择 20 项执行模型'));return;}$('executor-models').append(modelRow(selected,true));}
function renderOptions() {
  $('name').value=options.name;$('goal').value=options.goal;$('rounds').value=options.max_rounds;$('repetitions').value=options.repetitions;$('score').value=options.minimum_score;$('parsing-timeout').value=options.parsing_timeout_seconds;
  $('model-names').replaceChildren(...[...new Set(options.catalog.map(p=>p.model).filter(Boolean))].map(value=>{const o=document.createElement('option');o.value=value;return o;}));
  $('builder-model').replaceChildren(modelRow(options.builder));$('executor-models').replaceChildren();options.executors.forEach(addExecutor);
}
function modelDefaults(){
  const executors=[...$('executor-models').children].map(readChoice);if(!executors.length)throw Error('至少添加一个执行模型');
  return {builder:readChoice($('builder-model').firstChild),executors,max_rounds:Number($('rounds').value),repetitions:Number($('repetitions').value),minimum_score:Number($('score').value),parsing_timeout_seconds:Number($('parsing-timeout').value)};
}
$('add-executor').onclick=()=>addExecutor(options.executors[0]);
$('save-defaults').onclick=async()=>{
  if(!$('settings').reportValidity())return;
  $('save-defaults').disabled=true;$('error').hidden=true;
  try{const name=$('name').value,goal=$('goal').value;options=await api('defaults',{method:'PUT',body:JSON.stringify(modelDefaults())});renderOptions();$('name').value=name;$('goal').value=goal;$('defaults-status').textContent=`默认配置已保存到本机：${options.defaults_path}`;}
  catch(e){error(e);}finally{$('save-defaults').disabled=false;}
};
$('settings').onsubmit=async e=>{
  e.preventDefault();$('prepare').disabled=true;$('error').hidden=true;
  try{
    const result=await api('jobs',{method:'POST',body:JSON.stringify({...modelDefaults(),material:material.id,name:$('name').value,goal:$('goal').value})});
    job=result.id;current=null;$('review').hidden=true;$('material-review').hidden=true;$('review-status').textContent='正在解析材料…';history.replaceState(null,'',`?job=${job}`);show(2);await refresh();await listJobs();
  }catch(e){error(e);}finally{$('prepare').disabled=false;}
};
$('materials-accepted').onchange=()=>{$('accept-materials').disabled=!$('materials-accepted').checked;};
$('accept-materials').onclick=async()=>{
  $('accept-materials').disabled=true;$('error').hidden=true;
  try {await api(`jobs/${job}/accept-materials`,{method:'POST',body:JSON.stringify({digest:current.parsing_digest})});await refresh();}
  catch(e){error(e);$('accept-materials').disabled=!$('materials-accepted').checked;}
};
function renderBrief(brief) {
  $('questions').replaceChildren();$('questions-panel').hidden=!brief.questions.length;
  $('questions-title').textContent=`需要你回答 ${brief.questions.length} 个问题`;
  brief.questions.forEach((question,index)=>{const label=text('label',`${index+1}. ${question}`);const answer=document.createElement('textarea');answer.dataset.answer=String(index);answer.rows=3;answer.required=true;answer.maxLength=10000;answer.placeholder='填写你的决定、适用范围或具体规则';label.append(answer);$('questions').append(label);});
  const content=$('brief-content');content.replaceChildren();
  function panel(title){const p=document.createElement('div');p.className='panel';p.append(text('h2',title));content.append(p);return p;}
  panel('构建范围').append(text('p',brief.scope));
  const criteria=document.createElement('ol');brief.criteria.forEach(item=>criteria.append(text('li',item)));panel('评估标准').append(criteria);
  for(const [key,title] of [['development','开发场景'],['holdout','保留场景 · 仅用于最终验证']]){
    const p=panel(title);
    for(const scenario of brief[key]){const d=document.createElement('details');d.append(text('summary',scenario.id),text('p',scenario.task));
      for(const [name,body] of Object.entries(scenario.files)){d.append(text('h3',`输入文件：${name}`),text('pre',body));}
      const checks=document.createElement('ul');for(const check of scenario.checks){checks.append(text('li',check.equals!==null&&check.equals!==undefined?`${check.path} 的内容应完全等于：${check.equals}`:check.contains!==null&&check.contains!==undefined?`${check.path} 应包含：${check.contains}`:`应生成文件：${check.path}`));}d.append(checks);p.append(d);
    }
  }
  const sources=panel('材料来源与依据');for(const source of brief.sources){const d=document.createElement('details');d.append(text('summary',source.reference),text('p',source.finding),text('p',`依据：${source.evidence}`),text('p',`状态：${({provided:'用户提供',supported:'已有证据',uncertain:'仍有不确定性'})[source.status]||source.status}`));sources.append(d);}
  $('review-feedback').value='';$('accepted').checked=false;
}
function reviewControls(){
  const pending=!!current?.brief?.questions.length,busy=!!current?.busy;
  $('accepted').disabled=pending||busy;$('approve').disabled=pending||busy||!$('accepted').checked;
  $('approval-hint').textContent=pending?'请先回答上方问题并更新草案。':'确认后开始构建与测评。';
  $('revise').disabled=busy;$('revise').textContent=pending?'提交回答并更新草案':'根据修改意见更新草案';
}
$('review-form').onsubmit=async e=>{
  e.preventDefault();$('error').hidden=true;
  const answers=[...document.querySelectorAll('[data-answer]')].map(el=>el.value.trim());
  const feedback=$('review-feedback').value.trim();
  if(!answers.length&&!feedback){$('review-feedback').focus();error(Error('请填写希望调整的内容'));return;}
  $('revise').disabled=true;
  try{await api(`jobs/${job}/review`,{method:'POST',body:JSON.stringify({digest:current.brief_digest,answers,feedback})});await refresh();}
  catch(e){error(e);reviewControls();}
};
$('accepted').onchange=reviewControls;
$('approve').onclick=async()=>{
  $('approve').disabled=true;$('error').hidden=true;
  try{await api(`jobs/${job}/approve`,{method:'POST',body:JSON.stringify({digest:current.brief_digest})});show(3);await refresh();}
  catch(e){error(e);reviewControls();}
};
$('resume').onclick=async()=>{try{await api(`jobs/${job}/resume`,{method:'POST',body:'{}'});await refresh();}catch(e){error(e);}};
$('copy').onclick=async()=>{try{await navigator.clipboard.writeText($('delivery-path').value);$('copy').textContent='已复制';}catch(e){$('delivery-path').select();error(Error('请复制已选中的本地地址'));}};
async function listJobs(){const list=await api('jobs');$('history').replaceChildren(text('option','选择已有任务'));$('history').firstChild.value='';for(const item of list){const o=text('option',`${item.name} · ${item.id.slice(0,8)}`);o.value=item.id;$('history').append(o);}$('history').value=job||'';}
$('history').onchange=async()=>{if(!$('history').value)return;job=$('history').value;current=null;$('error').hidden=true;history.replaceState(null,'',`?job=${job}`);await refresh();show(!current.approval?2:3);};
async function refresh(){
  if(!job)return;const requested=job;const state=await api(`jobs/${job}`);if(requested!==job)return;
  if(state.brief && (!current || current.brief_digest!==state.brief_digest)){renderBrief(state.brief);}
  if(state.parsing && (!current || current.parsing_digest!==state.parsing_digest)){
    $('parsed-files').replaceChildren();
    for(const file of state.parsing.files){
      const d=document.createElement('details');d.open=true;d.append(text('summary',`${file.name} · ${file.status==='partial'?'部分解析，请检查遗漏':'已读取'}`));
      for(const warning of file.warnings){const p=text('p',warning);p.className='fail';d.append(p);}
      d.append(text('pre',file.text));$('parsed-files').append(d);
    }
    $('materials-accepted').checked=false;$('accept-materials').disabled=true;
    $('parsing-usage').textContent=`解析调用 ${state.parsing.calls} 次 · 耗时 ${state.parsing.elapsed_seconds.toFixed(1)} 秒 · 后续 Loop 复用此结果`;
  }
  $('material-review').hidden=!state.parsing||state.materials_approved||state.busy;
  current=state;reviewControls();$('review').hidden=!state.brief||state.busy||!!state.approval;
  $('review-status').textContent=state.busy?'正在调用模型，请稍候…':state.error||(state.brief?(state.brief.questions.length?'请回答下方问题，模型将据此更新草案。':'草案已就绪。可审阅确认，也可填写修改意见让模型调整。'):'材料已就绪。请核对解析文本与警告。');
  $('status').textContent=state.busy?'执行中':labels[state.status]||state.status||'准备中';$('round').textContent=state.round||0;$('calls').textContent=state.calls||0;
  $('result-title').textContent=state.status==='delivered'?'Skill 已完成验证':'构建与测评';$('result-status').textContent=state.error|| (state.busy?'任务正在本机运行，可以离开此页面后重新打开。':'任务状态与测评结果已保存在本机。');
  $('reports').replaceChildren();
  for(const [name,report] of Object.entries(state.reports||{})){const d=document.createElement('details');const s=text('summary',`${name} · ${report.passed?'通过':'未通过'}`);s.className=report.passed?'pass':'fail';d.append(s,text('pre',JSON.stringify(report,null,2)));$('reports').append(d);}
  if(!$('reports').children.length)$('reports').textContent='尚无测评结果。开发场景通过后会进行保留场景验证。';
  $('delivery').hidden=state.status!=='delivered';$('delivery-path').value=state.delivery||'';$('download').href=`/api/jobs/${job}/download`;
  $('report-download').hidden=!Object.keys(state.reports||{}).length;$('report-download').href=`/api/jobs/${job}/report`;
  $('resume').hidden=state.busy||state.status==='delivered'||!state.approval;
  $('details').textContent=JSON.stringify({run:state.run,path:state.path,status:state.status,error:state.error,previous_error:state.previous_error,usage:state.usage,parsing_attempt:state.parsing_attempt,models:state.settings?{builder:state.settings.builder,executors:state.settings.executors,repetitions:state.settings.repetitions}:null},null,2);
}
(async()=>{try{options=await api('options');$('connection').textContent='本地连接已就绪';renderOptions();job=new URLSearchParams(location.search).get('job');await listJobs();if(job){await refresh();show(!current.approval?2:3);}else show(0);}catch(e){error(e);$('connection').textContent='连接失败';}})();
setInterval(()=>refresh().catch(error),2000);

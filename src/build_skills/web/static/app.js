const $ = id => document.getElementById(id);
let options, material, job, current, step = 0;
const stages = ['导入材料', '配置流程', '审阅与确认', '测评与交付'];
const labels = {awaiting_approval:'等待审阅',approved:'已确认',delivered:'已交付',failed:'调用失败',unmet:'未达到标准',interrupted:'执行中断',new:'准备中',verified:'验证通过'};
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
  $('error').hidden=true; $('upload-state').textContent='正在上传并提取文字…';$('configure').disabled=true;
  const data=new FormData();for(const file of files)data.append('files',file);
  try {
    material=await api('materials',{method:'POST',body:data});
    $('materials').replaceChildren();
    for(const file of material.files){const d=document.createElement('details');d.append(text('summary',`${file.name} · ${file.text.length.toLocaleString()} 字符`),text('pre',file.text));$('materials').append(d);}
    $('upload-state').textContent=`已导入 ${material.files.length} 个文件。请核对提取内容，图片仅提取文字。`;
    $('configure').disabled=false; show(0);
  }catch(e){material=null;error(e);$('upload-state').textContent='导入失败，请调整文件后重试。';}
}
$('files').onchange=e=>upload(e.target.files);
$('drop').ondragover=e=>{e.preventDefault();$('drop').classList.add('drag');};
$('drop').ondragleave=()=>$('drop').classList.remove('drag');
$('drop').ondrop=e=>{e.preventDefault();$('drop').classList.remove('drag');upload(e.dataTransfer.files);};
document.querySelectorAll('[data-step]').forEach(b=>b.onclick=()=>show(Number(b.dataset.step)));
$('configure').onclick=()=>show(1);
$('new').onclick=()=>{job=null;current=null;material=null;$('materials').replaceChildren();$('configure').disabled=true;$('files').value='';$('error').hidden=true;$('history').value='';$('upload-state').textContent='提取后的文字会在这里显示，供你核对。';history.replaceState(null,'',location.pathname);show(0);};
function renderOptions() {
  $('name').value=options.name;$('goal').value=options.goal;$('rounds').value=options.max_rounds;$('repetitions').value=options.repetitions;$('score').value=options.minimum_score;
  for(const [name,p] of Object.entries(options.providers)){
    const panel=document.createElement('div');panel.className='panel provider';
    const title=text('div',name);title.append(text('small',p.kind==='command'?'演示替身 / 非真实模型':p.kind));
    const modelLabel=text('label','LLM 模型');const input=document.createElement('input');input.value=p.model;input.dataset.model=name;input.required=p.kind!=='command';input.disabled=p.kind==='command';modelLabel.append(input);
    const effortLabel=text('label','思考等级');const effort=document.createElement('input');effort.value=p.reasoning_effort||'';effort.placeholder='默认 / 如 high';effort.dataset.effort=name;effort.pattern='[a-z][a-z0-9_-]*';effort.disabled=p.kind==='command';effortLabel.append(effort);
    panel.append(title,modelLabel,effortLabel);$('providers').append(panel);
  }
  for(const [role,label] of Object.entries({prepare:'准备',build:'构建',evaluate:'评估',improve:'改进'})){
    const l=text('label',label);const select=document.createElement('select');select.dataset.role=role;
    for(const name of Object.keys(options.providers)){const o=text('option',name);o.value=name;select.append(o);}select.value=options.roles[role];l.append(select);$('roles').append(l);
  }
  const group=document.createElement('div');group.append(text('label','执行测评的模型（至少一个）'));
  for(const name of Object.keys(options.providers)){const l=text('label',name);l.className='check';const c=document.createElement('input');c.type='checkbox';c.dataset.execution=name;c.checked=options.models.includes(name);l.prepend(c);group.append(l);}$('roles').append(group);
}
$('settings').onsubmit=async e=>{
  e.preventDefault();$('prepare').disabled=true;$('error').hidden=true;
  try{
    const providers={};document.querySelectorAll('[data-model]').forEach(el=>providers[el.dataset.model]={model:el.value});document.querySelectorAll('[data-effort]').forEach(el=>providers[el.dataset.effort].reasoning_effort=el.value||null);
    const roles={};document.querySelectorAll('[data-role]').forEach(el=>roles[el.dataset.role]=el.value);
    const models=[...document.querySelectorAll('[data-execution]:checked')].map(el=>el.dataset.execution);if(!models.length)throw Error('至少选择一个执行模型');
    const result=await api('jobs',{method:'POST',body:JSON.stringify({material:material.id,name:$('name').value,goal:$('goal').value,providers,roles,models,max_rounds:Number($('rounds').value),repetitions:Number($('repetitions').value),minimum_score:Number($('score').value)})});
    job=result.id;current=null;$('review').hidden=true;$('review-status').textContent='正在准备目标与测评场景…';history.replaceState(null,'',`?job=${job}`);show(2);await refresh();await listJobs();
  }catch(e){error(e);}finally{$('prepare').disabled=false;}
};
$('accepted').onchange=()=>{$('approve').disabled=!$('accepted').checked;};
$('approve').onclick=async()=>{
  $('approve').disabled=true;$('error').hidden=true;
  try{await api(`jobs/${job}/approve`,{method:'POST',body:JSON.stringify({brief:JSON.parse($('brief').value),digest:current.brief_digest})});show(3);await refresh();}
  catch(e){error(e);$('approve').disabled=!$('accepted').checked;}
};
$('resume').onclick=async()=>{try{await api(`jobs/${job}/resume`,{method:'POST',body:'{}'});await refresh();}catch(e){error(e);}};
$('copy').onclick=async()=>{try{await navigator.clipboard.writeText($('delivery-path').value);$('copy').textContent='已复制';}catch(e){$('delivery-path').select();error(Error('请复制已选中的本地地址'));}};
async function listJobs(){const list=await api('jobs');$('history').replaceChildren(text('option','选择已有任务'));$('history').firstChild.value='';for(const item of list){const o=text('option',`${item.name} · ${item.id.slice(0,8)}`);o.value=item.id;$('history').append(o);}$('history').value=job||'';}
$('history').onchange=async()=>{if(!$('history').value)return;job=$('history').value;current=null;$('error').hidden=true;history.replaceState(null,'',`?job=${job}`);await refresh();show(current.brief&&!current.approval?2:3);};
async function refresh(){
  if(!job)return;const requested=job;const state=await api(`jobs/${job}`);if(requested!==job)return;
  if(state.brief && (!current || current.brief_digest!==state.brief_digest)){$('brief').value=JSON.stringify(state.brief,null,2);$('accepted').checked=false;$('approve').disabled=true;}
  current=state;$('review').hidden=!state.brief||state.busy||!!state.approval;
  $('review-status').textContent=state.busy?'正在调用模型，请稍候…':state.error||'草案已就绪。核对内容后确认，或直接编辑。';
  $('status').textContent=state.busy?'执行中':labels[state.status]||state.status||'准备中';$('round').textContent=state.round||0;$('calls').textContent=state.calls||0;
  $('result-title').textContent=state.status==='delivered'?'Skill 已完成验证':'构建与测评';$('result-status').textContent=state.error|| (state.busy?'任务正在本机运行，可以离开此页面后重新打开。':'任务状态与测评结果已保存在本机。');
  $('reports').replaceChildren();
  for(const [name,report] of Object.entries(state.reports||{})){const d=document.createElement('details');const s=text('summary',`${name} · ${report.passed?'通过':'未通过'}`);s.className=report.passed?'pass':'fail';d.append(s,text('pre',JSON.stringify(report,null,2)));$('reports').append(d);}
  if(!$('reports').children.length)$('reports').textContent='尚无测评结果。开发场景通过后会进行保留场景验证。';
  $('delivery').hidden=state.status!=='delivered';$('delivery-path').value=state.delivery||'';$('download').href=`/api/jobs/${job}/download`;
  $('report-download').hidden=!Object.keys(state.reports||{}).length;$('report-download').href=`/api/jobs/${job}/report`;
  $('resume').hidden=state.busy||state.status==='delivered'||!state.approval;
  $('details').textContent=JSON.stringify({run:state.run,path:state.path,status:state.status,error:state.error,usage:state.usage},null,2);
}
(async()=>{try{options=await api('options');$('connection').textContent='本地连接已就绪';renderOptions();job=new URLSearchParams(location.search).get('job');await listJobs();if(job){await refresh();show(current.brief&&!current.approval?2:3);}else show(0);}catch(e){error(e);$('connection').textContent='连接失败';}})();
setInterval(()=>refresh().catch(error),2000);

const $=s=>document.querySelector(s),esc=v=>String(v==null?"":v).replace(/[&<>"']/g,x=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[x]));
const pretty=v=>JSON.stringify(v,null,2),statusNames={success:"成功",failure:"失败",not_executed:"未执行",unknown:"未知",unverified:"待验证",verified:"已验证",unverifiable:"无法验证"};
const tag=s=>'<span class="tag '+esc(s)+'">'+esc(statusNames[s]||s)+'</span>';
const json=v=>'<pre class="json">'+esc(pretty(v))+'</pre>';
const title=(a,b,c="")=>'<div class="page-title"><div><div class="eyebrow">VIDEO KNOWLEDGE / POSTGRESQL</div><h1>'+a+'</h1><p>'+b+'</p></div>'+c+'</div>';
let state={page:"overview",cases:[],skills:[],selectedCase:"01",selectedSkill:null,caseTab:"video",skillTab:"tuple",table:"cases"},ticket=0;
async function api(path){const r=await fetch(path);const x=await r.json();if(r.status===401){location.replace("/login");throw Error("登录已失效")}if(!r.ok)throw Error(x.error||"读取失败");return x}
function error(e){$("#content").innerHTML='<div class="error">读取未完成：'+esc(e.message)+'。请刷新重试。</div>'}
function go(page){state.page=page;ticket++;document.querySelectorAll("nav button").forEach(x=>x.classList.toggle("active",x.dataset.page===page));$("#crumb").textContent={overview:"总览",cases:"视频与操作图",skills:"技能知识",proposal:"表结构审阅",database:"数据库浏览"}[page];$("#content").innerHTML='<div class="empty">正在读取数据库…</div>';({overview,cases:casePage,skills:skillPage,proposal,database}[page])().catch(error)}
function caseRows(items){return items.map(c=>'<div class="list-row"><span class="case-num">'+esc(c.id)+'</span><div class="row-body"><b>'+esc(c.title)+'</b><small>'+esc(c.method)+' · '+c.node_count+' 个操作节点</small></div>'+tag(c.outcome)+'<button class="text-btn" data-open-case="'+esc(c.id)+'">查看 →</button></div>').join("")}
function attachCaseOpen(){document.querySelectorAll("[data-open-case]").forEach(x=>x.onclick=()=>{state.selectedCase=x.dataset.openCase;go("cases")})}
async function overview(){
 const my=ticket,[o,cases]=await Promise.all([api("/api/overview"),api("/api/cases")]);if(my!==ticket)return;
 state.cases=cases;
 const stats=[["视频案例",o.cases,"16 段完整案例已导入"],["技能类别",o.skills,"目的与实现方式分开"],["知识版本",o.versions,"全部保留原验证状态"],["展示产物",o.artifacts,"另有 "+o.original_videos+" 个原始 MP4"]];
 $("#content").innerHTML=title("让视频经验成为可追溯的知识","查看案例、检查知识与证据，然后决定正式的数据结构。")+
 '<div class="stats">'+stats.map(s=>'<div class="stat"><small>'+s[0]+'</small><strong>'+s[1]+'</strong><span>'+s[2]+'</span></div>').join("")+'</div>'+
 '<div class="grid2"><div><section class="panel"><h2>从观察到知识</h2><div class="flow"><div>视频案例<small>动作 · 状态 · 证据</small></div><b>→</b><div>语义操作图<small>结构 · 条件 · 时序</small></div><b>→</b><div>技能知识<small>七元组 · 实现候选</small></div></div><p>操作图结构存入 JSONB，展示产物原始字节存入 BYTEA。它们已实际写入 PostgreSQL 预览库，可在页面中直接读取。</p></section><section class="panel"><div class="section-head"><h2>视频案例</h2><button class="text-btn" id="all-cases">全部 16 段 →</button></div>'+caseRows(cases.slice(0,5))+'</section></div>'+
 '<div><section class="panel"><h2>当前预览环境</h2>'+[["数据库","videostudy_preview"],["Schema","preview · 视频结构已落实"],["数据库版本",o.postgres_version],["产物原始大小",(o.stored_bytes/1048576).toFixed(1)+" MiB"],["界面权限","只读浏览"],["结构审阅","8 项保留 · 技能侧暂缓"]].map(x=>'<div class="summary-line"><span>'+x[0]+'</span><b>'+esc(x[1])+'</b></div>').join("")+'</section><section class="panel"><h2>需要一起确认的事</h2><p>① 操作图节点和边是否独立建表？</p><p>② 条件、谓词和证据如何关联？</p><p>③ 技能如何审核、发布和选用版本？</p><button class="primary" id="review-schema">审阅表结构草案 →</button></section><section class="panel"><h2>保留真实的不确定性</h2><span class="tag warn">18 个知识版本仍为待验证</span><p>结构检查通过不代表语义、因果或机器人执行已验证。导入时没有升级任何结论状态。</p></section></div></div>';
 $("#all-cases").onclick=()=>go("cases");$("#review-schema").onclick=()=>go("proposal");attachCaseOpen();
}
async function casePage(){
 const my=ticket;state.cases=await api("/api/cases");if(my!==ticket)return;
 $("#content").innerHTML=title("视频与操作图","原视频、操作图、工作台与结构数据关联到同一条数据库记录。")+'<div class="split"><div class="list-panel"><div class="search"><input id="case-search" placeholder="搜索视频、对象或方法" aria-label="搜索案例"></div><div id="case-list"></div></div><div id="case-detail"></div></div>';
 const paint=(q="")=>{$("#case-list").innerHTML=state.cases.filter(c=>pretty(c).toLowerCase().includes(q.toLowerCase())).map(c=>'<button class="pick '+(c.id===state.selectedCase?"active":"")+'" data-case="'+c.id+'"><small>CASE '+c.id+' · '+c.node_count+' 个节点</small><b>'+esc(c.title)+'</b>'+tag(c.outcome)+'</button>').join("")||'<div class="empty">没有匹配案例</div>';document.querySelectorAll("[data-case]").forEach(x=>x.onclick=()=>{state.selectedCase=x.dataset.case;paint($("#case-search").value);loadCase().catch(error)})};
 $("#case-search").oninput=e=>paint(e.target.value);paint();await loadCase();
}
async function loadCase(){
 const cid=state.selectedCase,my=ticket,b=await api("/api/cases/"+cid);if(my!==ticket||cid!==state.selectedCase)return;
 const dest=$("#case-detail");if(!dest)return;
 dest.innerHTML='<section class="panel"><h2 class="detail-title">'+esc(b.title)+'</h2><div class="meta">'+tag(b.outcome)+'<span class="tag">'+b.node_count+' 个操作节点</span><span class="tag info">来自 PostgreSQL</span></div><div class="tabs">'+[["video","视频 MP4"],["svg","操作图 SVG"],["html","交互工作台"],["graph","图结构 JSON"],["nodes","节点七元组"],["result","完整分析"],["files","产物原件"]].map(([id,name])=>'<button data-ctab="'+id+'" class="'+(state.caseTab===id?"active":"")+'">'+name+'</button>').join("")+'</div><div id="case-view"></div></section><section class="panel"><h2>参考标注与任务观察</h2><p>参考标注和模型观察分别显示；任务结果与局部子任务分开。</p><details><summary>已有参考标注</summary>'+json(b.metadata)+'</details><details><summary>当前任务观察</summary>'+json(b.result.task_observation)+'</details></section>';
 document.querySelectorAll("[data-ctab]").forEach(x=>x.onclick=()=>{state.caseTab=x.dataset.ctab;loadCase().catch(error)});
 const area=$("#case-view"),tab=state.caseTab;
 if(tab==="svg"||tab==="html"){const name=tab==="svg"?"operations.svg":"workbench.html";area.innerHTML='<p class="muted">图面可在下方滚动查看。<a class="artifact-link" target="_blank" rel="noopener" href="/case-assets/'+cid+'/'+name+'">单独打开 ↗</a></p><iframe title="'+(tab==="svg"?"操作图":"交互工作台")+'" sandbox="allow-scripts" src="/case-assets/'+cid+'/'+name+'"></iframe>'}
 if(tab==="video"){
 const video=b.video;
 area.innerHTML=video?'<p class="muted">从 PostgreSQL 读取视频。播放器使用 H.264 兼容副本；下载原件保留原始 MP4 字节。</p><video id="case-video" class="case-video" controls playsinline preload="metadata" aria-label="'+esc(b.title)+'的视频"><source src="/api/cases/'+cid+'/video/playback" type="video/mp4">当前浏览器不支持视频播放。</video><p id="video-message" class="muted" role="status"></p><div class="video-links"><a href="/api/cases/'+cid+'/video/original?download=1">下载原始 MP4 ↓</a><a href="/api/cases/'+cid+'/video/playback?download=1">下载 H.264 播放副本 ↓</a></div><div class="video-meta"><span>原件：'+esc(video.filename)+'</span><span>原件大小：'+(video.bytes/1048576).toFixed(2)+' MiB</span><span>播放格式：H.264 / MP4</span><span class="video-hash">原件 SHA256：'+esc(video.sha256)+'</span></div>':'<div class="empty">该案例暂无数据库视频</div>';
 const player=document.getElementById("case-video");if(player)player.addEventListener("error",()=>{document.getElementById("video-message").textContent="视频未能载入，请确认登录状态或下载播放副本查看。"});
 }
 if(tab==="graph")area.innerHTML=json(b.graph);
 if(tab==="result")area.innerHTML=json(b.result);
 if(tab==="nodes"){
 const nodes=b.result.task_nodes.task_nodes;
 area.innerHTML='<p class="muted">选择操作节点，查看执行主体、对象、条件、评价与实现方式。</p><div class="node-buttons">'+nodes.map((n,i)=>'<button data-node="'+i+'">'+esc(n.name)+'</button>').join("")+'</div><div id="node-tuple"></div>';
 const show=i=>{$("#node-tuple").innerHTML=json(nodes[i].tuple)};document.querySelectorAll("[data-node]").forEach(x=>x.onclick=()=>show(Number(x.dataset.node)));if(nodes.length)show(0);
 }
 if(tab==="files")area.innerHTML='<div class="table-wrap"><table><thead><tr><th>文件</th><th>类型</th><th>大小</th><th>SHA256</th></tr></thead><tbody>'+b.artifacts.map(a=>'<tr><td><a href="/case-assets/'+cid+'/'+encodeURIComponent(a.filename)+'" target="_blank" rel="noopener">'+esc(a.filename)+'</a></td><td>'+esc(a.mime_type)+'</td><td>'+(a.byte_size/1024).toFixed(1)+' KB</td><td><code>'+esc(a.sha256)+'</code></td></tr>').join("")+'</tbody></table></div>';
}
async function skillPage(){
 const my=ticket;state.skills=await api("/api/skills");if(my!==ticket)return;if(!state.selectedSkill)state.selectedSkill=state.skills[0].skill_id;
 $("#content").innerHTML=title("技能知识","浏览七元组、实现分支和来源记录。所有版本均保持原来的待验证状态。")+'<div class="split"><div class="list-panel"><div class="search"><input id="skill-search" placeholder="搜索技能名称或ID" aria-label="搜索技能"></div><div id="skill-list"></div></div><div id="skill-detail"></div></div>';
 const paint=(q="")=>{$("#skill-list").innerHTML=state.skills.filter(s=>(s.name+s.skill_id).includes(q)).map(s=>'<button class="pick '+(s.skill_id===state.selectedSkill?"active":"")+'" data-skill="'+s.skill_id+'"><small>'+esc(s.skill_id)+'</small><b>'+esc(s.name)+'</b><span class="tag">'+s.versions+' 个版本</span> '+tag("unverified")+'</button>').join("");document.querySelectorAll("[data-skill]").forEach(x=>x.onclick=()=>{state.selectedSkill=x.dataset.skill;state.version=null;paint($("#skill-search").value);loadSkill().catch(error)})};
 $("#skill-search").oninput=e=>paint(e.target.value);paint();await loadSkill();
}
async function loadSkill(){
 const sid=state.selectedSkill,item=state.skills.find(x=>x.skill_id===sid),version=state.version&&item.history.some(x=>x.version===state.version)?state.version:item.history[0].version,my=ticket;
 state.version=version;const data=await api("/api/skills/"+sid+"?version="+version);if(my!==ticket||sid!==state.selectedSkill)return;
 const s=data.skill,area=$("#skill-detail");if(!area)return;
 area.innerHTML='<section class="panel"><h2 class="detail-title">'+esc(s.name)+'</h2><p>'+esc(s.purpose)+'</p><div class="meta">'+tag(s.verification_status)+'<span class="tag">'+s.R.length+' 个实现候选</span><span class="tag">'+s.provenance.length+' 条来源记录</span><span class="tag info">执行接口待绑定</span></div><label class="muted" for="version">版本（按哈希排列，不代表审核顺序）</label><select id="version" style="width:100%;margin:8px 0 20px">'+item.history.map(v=>'<option value="'+v.version+'" '+(v.version===version?"selected":"")+'>'+v.version.slice(0,24)+'… · '+v.realizations+' 实现 / '+v.instances+' 来源</option>').join("")+'</select><div class="tabs">'+[["tuple","七元组"],["realizations","实现方式"],["provenance","来源证据"],["raw","完整 JSON"]].map(([id,name])=>'<button data-stab="'+id+'" class="'+(state.skillTab===id?"active":"")+'">'+name+'</button>').join("")+'</div><div id="skill-view"></div></section>';
 $("#version").onchange=e=>{state.version=e.target.value;loadSkill().catch(error)};document.querySelectorAll("[data-stab]").forEach(x=>x.onclick=()=>{state.skillTab=x.dataset.stab;loadSkill().catch(error)});
 const view=$("#skill-view");
 if(state.skillTab==="tuple"){const labels={X:"执行主体",O:"对象角色",C_pre:"公共前置条件",C_const:"公共持续约束",E:"评价规则",C_post:"目标效果"};view.innerHTML='<p class="muted">公共条件为空表示证据尚不足；各实现分支中的候选条件仍保留。谓词ID可在“完整 JSON”中查询。</p><div class="tuples">'+Object.entries(labels).map(([key,label])=>'<div class="tuple"><b>'+key+' · '+label+'</b><pre>'+esc(pretty(s[key]))+'</pre></div>').join("")+'</div>'}
 if(state.skillTab==="realizations")view.innerHTML=s.R.map((x,i)=>'<details class="panel"><summary>R'+(i+1)+' · '+esc(x.name)+' '+tag(x.verification_status)+'</summary>'+json(x)+'</details>').join("");
 if(state.skillTab==="provenance")view.innerHTML=json(s.provenance);
 if(state.skillTab==="raw")view.innerHTML=json(data);
}
async function proposal(){
 const my=ticket,[data,review]=await Promise.all([api("/schema-proposal.json"),api("/schema-review.json")]);if(my!==ticket)return;
 $("#content").innerHTML=title("表结构审阅记录","你的 JSON 意见已导入：8 项均保留。视频、运行、图版本、产物和审核记录已落实；技能侧保持原状。",'<button class="primary" id="export-notes">导出我的意见 ↓</button>')+'<p class="notes">可在每张表下记录调整意见。意见仅保存在当前浏览器，不会修改数据库；导出后可交给我继续调整。</p><div class="proposals">'+data.map((x,i)=>'<article class="proposal"><div class="section-head"><h3>'+String(i+1).padStart(2,"0")+' · '+esc(x.name)+'</h3><span class="tag info">保留 · '+esc(x.implementation)+'</span></div><code>'+x.id+'</code><p>'+esc(x.purpose)+'</p><div class="fields">'+x.fields.map(f=>'<span>'+esc(f)+'</span>').join("")+'</div><p><b>关系：</b>'+esc(x.relations)+'</p><p>'+esc(x.question)+'</p><textarea data-note="'+x.id+'" aria-label="'+esc(x.name)+'的调整意见" placeholder="你的意见：保留、合并、拆分或增加字段…"></textarea></article>').join("")+'</div>';
 let notes=Object.assign({},review.notes);try{Object.assign(notes,JSON.parse(localStorage.getItem("v2o-schema-notes")||"{}"))}catch{}
 document.querySelectorAll("[data-note]").forEach(x=>{x.value=notes[x.dataset.note]||"";x.oninput=()=>{notes[x.dataset.note]=x.value;try{localStorage.setItem("v2o-schema-notes",JSON.stringify(notes))}catch{}}});
 $("#export-notes").onclick=()=>{const blob=new Blob([pretty({status:"reviewed_keep_all_with_skill_freeze",tables:data,notes})],{type:"application/json"}),url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download="知识库表结构审阅意见.json";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
}
async function database(){
 const my=ticket,columns=await api("/api/schema");if(my!==ticket)return;
 const names={imports:"导入记录",videos:"视频原件",cases:"案例与操作图",analysis_runs:"分析运行",operation_graph_versions:"操作图版本",skill_versions:"知识版本",artifacts:"产物原件",reviews:"审核记录"};
 $("#content").innerHTML=title("数据库浏览","直接读取 PostgreSQL 系统目录和预览表；不会执行修改、删除或任意 SQL。")+'<div class="database-grid">'+Object.entries(names).map(([id,n])=>'<button data-table="'+id+'" class="'+(state.table===id?"active":"")+'"><b>'+n+'</b><small>preview.'+id+'</small></button>').join("")+'</div><section class="panel"><h2>字段定义 <span class="tag info">实际数据库</span></h2><div class="table-wrap"><table><thead><tr><th>字段</th><th>PostgreSQL 类型</th><th>允许空值</th></tr></thead><tbody>'+columns.filter(c=>c.table_name===state.table).map(c=>'<tr><td><code>'+c.column_name+'</code></td><td>'+c.data_type+'</td><td>'+c.is_nullable+'</td></tr>').join("")+'</tbody></table></div></section><section class="panel"><h2>数据样本 <span class="muted">最多 100 行，大产物只显示元数据</span></h2><div id="db-rows">读取中…</div></section>';
 document.querySelectorAll("[data-table]").forEach(x=>x.onclick=()=>{state.table=x.dataset.table;database().catch(error)});
 const selected=state.table,data=await api("/api/tables/"+selected);if(my!==ticket||state.table!==selected)return;
 if(!data.length){$("#db-rows").innerHTML='<p>暂无数据</p>';return}
 const keys=Object.keys(data[0]);$("#db-rows").innerHTML='<div class="table-wrap"><table><thead><tr>'+keys.map(k=>'<th>'+esc(k)+'</th>').join("")+'</tr></thead><tbody>'+data.map(row=>'<tr>'+keys.map(k=>'<td>'+(typeof row[k]==="object"?'<details><summary>JSON</summary><pre>'+esc(pretty(row[k]))+'</pre></details>':'<code>'+esc(row[k])+'</code>')+'</td>').join("")+'</tr>').join("")+'</tbody></table></div>';
}
document.querySelectorAll("nav button").forEach(x=>x.onclick=()=>go(x.dataset.page));$("#go-proposal").onclick=()=>go("proposal");
api("/api/health").then(x=>{$("#pgversion").textContent=x.postgres_version;$("#connection").innerHTML='<span class="dot"></span> 数据库已连接'}).catch(()=>{$("#connection").textContent="数据库连接失败"});
go("overview");

document.getElementById("logout").onclick=async()=>{await fetch("/api/logout",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"});location.replace("/login")};

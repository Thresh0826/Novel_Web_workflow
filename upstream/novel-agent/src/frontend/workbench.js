/* Manual handoff UI. All source manuscript access is read-only. */
let books = [], book, chapter, selectedTask = null, tasks = [], tab = 'draft';
let revision = 0, selectionRevision = 0, taskLoadRevision = 0, materialFiles = [], selectedMaterials = new Set();
const reportDrafts = new Map();
let activeRunId = null;
let displayedRun = null;
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const stamp = value => new Date(value).toLocaleString('zh-CN', {timeZone: 'Asia/Shanghai', month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});
const verdictNames = {pass: '通过', revise: '需修改', blocked: '待作者裁定', submitted: '创作结果'};

const style = document.createElement('style');
style.textContent = `
.top{align-items:center}.top-actions{display:flex;gap:12px;align-items:center}.tabs{gap:16px;flex-wrap:wrap}.controls{display:flex;gap:10px;align-items:center;justify-content:space-between}.controls .primary{float:none}.history-select{width:calc(100% - 44px);margin:12px 22px;border:1px solid var(--line);padding:9px;background:#fafbf8;border-radius:6px;color:var(--ink)}.task-banner{margin:0 22px 14px;padding:10px 12px;background:#edf4ed;border-radius:6px;font-size:12px}.task-banner.warn{background:#fff2dc;color:#8a622d}.task-pane{padding:20px 22px;min-height:405px;max-height:640px;overflow:auto}.task-pane input,.task-pane select,.task-pane textarea{font:inherit;display:block;width:100%;border:1px solid var(--line);border-radius:6px;padding:9px;background:#fcfcf9;color:var(--ink)}.task-pane label{font-size:12px;color:var(--muted);display:block;margin-bottom:7px}.report-fields{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:15px 0}.task-pane textarea{height:155px;resize:vertical;line-height:1.8}.task-buttons{display:flex;gap:10px;flex-wrap:wrap;margin:15px 0}.task-buttons .primary{float:none}.secondary:disabled,.primary:disabled{opacity:.45;cursor:not-allowed}.report-card{margin-top:14px;padding:14px;border:1px solid var(--line);border-radius:7px}.report-card summary{cursor:pointer;font-size:12px;line-height:1.8}.report-card pre{height:auto;max-height:300px;padding:14px 0 0;font-size:12px}.empty{padding:30px 8px;color:var(--muted);line-height:2}.version-confirm{padding:10px 22px;font-size:12px;background:#fff7e9;color:#876232}.version-confirm input,.materials input{width:auto;margin-right:7px;accent-color:var(--green)}.materials{border:1px solid var(--line);border-radius:9px;background:#fff;margin-top:18px;padding:17px 20px}.materials summary{cursor:pointer;font-size:13px}.materials-list{display:grid;grid-template-columns:1fr 1fr;max-height:270px;overflow:auto;gap:7px;padding-top:15px}.materials label{font-size:12px;display:flex;align-items:flex-start;overflow-wrap:anywhere}.materials-note{font-size:12px;color:var(--muted);margin:10px 0 0}.skill-tags{font-size:12px;color:var(--green);margin-top:12px}.manifest{font-size:12px;line-height:1.8}.manifest summary{cursor:pointer}.manifest ul{padding-left:18px}.status-badge{display:inline-block;padding:2px 8px;border-radius:12px;font-size:11px;background:#edf4ed;color:var(--green)}.save-hint{font-size:12px;color:var(--green);min-height:20px}.file-upload{margin-top:10px}.file-upload input{font-size:12px;padding:7px}.chapter-list{height:580px}.diff-view{font-family:Consolas,'Microsoft YaHei',monospace}.notice{line-height:1.9}@media(max-width:1100px){.chapter-list{height:250px}}@media(max-width:650px){.materials-list,.report-fields{grid-template-columns:1fr}.controls{flex-wrap:wrap}.top-actions .pill{display:none}.tabs{gap:12px}}
.automation-card{display:grid;grid-template-columns:1fr auto;gap:6px 20px;align-items:center;background:#edf4ed;border:1px solid #dae6da;border-radius:10px;margin:-9px 0 26px;padding:17px 20px}.automation-card strong{font-size:14px}.automation-card span{display:block;font-size:12px;color:var(--muted);margin-top:3px}.automation-card .primary{float:none}.automation-card details{grid-column:1/-1;font-size:12px;color:var(--muted)}.automation-card summary{cursor:pointer}.readiness-details{padding-top:8px;white-space:pre-wrap;line-height:1.8;color:#785f40}
`;
document.head.append(style);
document.querySelector('.top').innerHTML = '<span>工作空间 / 章节协作</span><div class="top-actions"><button class="secondary" id="refresh">刷新目录与版本</button><span class="pill">本地工作台 · 原稿只读</span></div>';
document.querySelector('.aside-foot').innerHTML = '书稿保存在本机<br>Gemini 创作 · Codex 审阅';
$('generate').textContent = '创建任务并保存材料 ↗';
$('generate').classList.remove('primary'); $('generate').classList.add('secondary');
document.querySelector('.controls').insertAdjacentHTML('afterend', '<div id="version-confirm" class="version-confirm" hidden><label><input type="checkbox" id="confirm-versions">我已核对本章及前文中入口未收录的正文版本</label></div><select id="task-history" class="history-select" aria-label="历史任务"><option>本章暂无任务</option></select><div id="task-banner" class="task-banner" hidden></div>');
document.querySelector('.flow').insertAdjacentHTML('afterend', '<div class="automation-card"><div><strong>Gemini 写作 · Codex 审纲/审稿 · 新会话独立终审</strong><span id="provider-status">正在连接本机模型 CLI…</span></div><button id="automatic-run" class="primary" disabled>一键运行本章</button><details><summary>查看运行情况</summary><div id="readiness-details" class="readiness-details">正在检查 CLI 登录与本章状态。</div><div id="automatic-result" class="readiness-details"></div></details></div>');
document.querySelector('.tabs').insertAdjacentHTML('beforeend', '<button data-tab="reports">审查记录</button><button data-tab="changes">文件变化</button>');
$('content').insertAdjacentHTML('afterend', '<div id="task-pane" class="task-pane" hidden></div>');
$('focus').insertAdjacentHTML('afterend', '<details class="materials"><summary>本章补充材料 <span class="muted">· 核心设定自动附入，可勾选人物与卷纲</span></summary><p class="materials-note">文风、验收规则、最近三章正文和对应审查技能会自动整理。勾选的补充文件将保存到本次任务快照。</p><div id="skill-tags" class="skill-tags"></div><div id="materials-list" class="materials-list"></div></details>');
document.querySelector('.notice').textContent = '选中章节后点“一键运行本章”。Gemini 负责生成/返修细纲和正文，Codex 审纲、审稿，再以全新会话终审。终审通过后由作者确认定稿；若追踪状态异常，候选稿会留在本地，不会覆盖原稿。';

async function api(url, options) {
    const response = await fetch(url, options);
    if (!response.ok) {
        let message = '请求失败';
        try { const data = await response.json(); message = typeof data.detail === 'string' ? data.detail : '输入格式不正确，请检查内容'; } catch {}
        throw Error(message);
    }
    return response.json();
}
function post(url, data) { return api(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)}); }
let toastTimer;
function toast(message) { clearTimeout(toastTimer); $('toast').textContent = message; $('toast').style.display = 'block'; toastTimer = setTimeout(() => $('toast').style.display = 'none', 5200); }
function renderBooks() {
    $('books').innerHTML = books.map(b => `<button class="book ${book?.id === b.id ? 'active' : ''}" data-book="${b.id}" aria-pressed="${book?.id === b.id}">${esc(b.title)}<small>${esc(b.genre)}</small></button>`).join('');
    document.querySelectorAll('[data-book]').forEach(el => el.onclick = () => selectBook(el.dataset.book));
}
function renderHeader() {
    renderBooks();
    $('title').textContent = book.title;
    $('root').textContent = '先选章节，再点启动。运行后在下方查看进度和结果。';
    $('project-path').textContent = book.root;
    $('focus').textContent = '本书审查尺度：' + book.focus;
    $('stats').innerHTML = `<span>${book.chapters.filter(c => c.draft?.length).length} 章已有正文</span><span>${book.approved_count} 章已确认定稿</span>`;
}
async function selectBook(id) {
    book = books.find(b => b.id === id);
    if(!book)return;
    document.body.classList.add('has-book');
    setNavigationCollapsed(true);
    $('book-pending').hidden=true;
    $('workspace').hidden=false;
    document.querySelector('.chapter-browser').hidden=false;
    $('book-shelf').open=false;
    $('book-shelf-label').textContent=book.title;
    $('book-shelf-label').title=book.title;
    $('process-details').open=false;
    $('search').value = '';
    selectedMaterials = new Set();
    materialFiles = [];
    renderMaterials();
    $('skill-tags').textContent = '正在读取本书材料与审查规则…';
    renderHeader();
    const currentId = book.id;
    selectChapter(book.chapters.find(c => c.draft?.length && !c.source_warning)?.number ?? book.chapters[0]?.number);
    pollChapterRuns();
    try {
        const data = await api(`/api/local/books/${currentId}/materials`);
        if (book.id !== currentId) return;
        materialFiles = data.files;
        selectedMaterials = new Set(materialFiles.filter(f => f.default).map(f => f.path));
        $('skill-tags').textContent = '细纲审查：' + (data.skills.outline || '未配置') + '　正文审查与终审：' + (data.skills.review || '未配置');
        renderMaterials();
    } catch (error) { toast(error.message); }
}
async function loadReadiness(id, number=chapter?.number) {
    const status=$('provider-status'), button=$('automatic-run'), details=$('readiness-details');
    status.textContent='正在检查本机模型登录与本章资料…'; button.disabled=true;
    try {
        const data=await api(`/api/local/books/${id}/readiness${number?`?chapter=${number}`:''}`);
        if(book?.id!==id || chapter?.number!==number)return;
        if(activeRunId)return;
        const gemini=data.agents.gemini?'Gemini CLI 已安装':'缺少 Gemini CLI';
        const codex=data.agents.codex?'Codex 已登录':'Codex 未登录';
        status.textContent=data.can_start ? (data.has_draft?'将审查已有正文，并在需要时生成修改稿。':'将按细纲生成正文，再自动审阅。') : '暂时无法启动，请展开下方检查详情。';
        button.textContent=workflowMode()==='outline'?'开始审阅细纲':'开始全面写作';
        details.textContent=[gemini,codex,data.tracking.message,...data.blockers,data.can_write_back?'通过终审后可安全写回正文。':'修改稿保存在工作台，目前不会自动覆盖原稿。'].filter(Boolean).join('\n');
        button.disabled=!data.can_start || !data.has_outline || (data.source_warning && !$('confirm-versions').checked);
    } catch(error) { if(book?.id===id){status.textContent='自动流程尚不可用';details.textContent=error.message;} }
}
function renderMaterials() {
    $('materials-list').innerHTML = materialFiles.map(f => `<label><input type="checkbox" data-material="${esc(f.path)}" ${selectedMaterials.has(f.path) ? 'checked' : ''} ${f.default ? 'disabled' : ''}>${esc(f.path)}${f.default ? '（自动附入）' : ''}</label>`).join('');
    document.querySelectorAll('[data-material]').forEach(el => el.onchange = () => el.checked ? selectedMaterials.add(el.dataset.material) : selectedMaterials.delete(el.dataset.material));
}
function renderChapters() {
    if(!book)return;
    const term = $('search').value.trim();
    $('chapters').innerHTML = book.chapters.filter(c => (c.draft?.[0] || c.outline?.[0] || '').includes(term) || String(c.number).includes(term)).map(c => {
        const title=(c.draft?.[0] || c.outline?.[0] || '').split('/').pop().replace(/\.md$/,'').replace(/^细纲[_：:]?/, '').replace(/^第[0-9一二三四五六七八九十百零〇两]+章[_：:\s]*/, '') || '细纲已准备';
        const current=chapter?.number===c.number;
        return `<div class="chapter-item ${current?'current':''}" data-chapter-row="${c.number}"><div class="chapter-row-head"><button class="chapter ${current?'selected':''}" data-chapter="${c.number}" aria-pressed="${current}" title="第${c.number}章 · ${esc(title)}"><span class="chapter-basic"><span>第 ${c.number} 章</span><span class="chapter-kind">${c.draft?.length?'正文':'细纲'}</span><span class="chapter-state"></span></span><span class="chapter-detail"><strong>${esc(title)}</strong><span class="chapter-status">${esc(c.status)}${c.stage?' · '+esc(c.stage):''}</span>${c.source_warning?'<span class="chapter-warning">阅读入口尚未确认此版本</span>':''}${[...(c.draft||[]),...(c.outline||[])].map(p=>`<span class="chapter-file">${esc(p)}</span>`).join('')}</span></button></div></div>`;
    }).join('');
    if(!$('chapters').children.length)$('chapters').innerHTML='<p class="chapter-empty">没有匹配的章节</p>';
    document.querySelectorAll('[data-chapter]').forEach(el => el.onclick = () => selectChapter(Number(el.dataset.chapter)));
    updateChapterRunBadges();
}
function rememberDraft() {
    if (selectedTask && $('report-content') && $('task-pane').dataset.taskId === selectedTask.id) reportDrafts.set(selectedTask.id, {content:$('report-content').value, reviewer:$('reviewer').value, verdict:$('verdict').value});
}
async function selectChapter(number) {
    rememberDraft();
    const token = ++selectionRevision;
    activeRunId = null;
    displayedRun = null;
    revision++;
    chapter = book.chapters.find(c => c.number === number);
    tasks = []; selectedTask = null; tab = 'draft';
    $('chapter-title').textContent = chapter ? `第 ${number} 章` : '暂无章节';
    $('run-title').textContent = chapter ? `处理第 ${number} 章` : '先选择章节';
    $('automatic-run').textContent = workflowMode()==='outline'?'开始审阅细纲':'开始全面写作';
    renderPhases();
    $('automatic-result').textContent = '尚未启动本章任务。';
    $('process-details').open=false;
    $('process-detail-count').textContent='报告、修改建议与运行日志';
    $('stage').value = chapter?.draft?.length ? 'final' : 'outline';
    $('confirm-versions').checked = false;
    $('version-confirm').hidden = !book.chapters.some(c => c.source_warning && c.number <= number && c.number >= number - 3);
    renderChapters(); renderHistory(); renderContent();
    const selected=document.querySelector('.chapter-item.current');
    if(selected){const list=$('chapters'),top=selected.getBoundingClientRect().top-list.getBoundingClientRect().top+list.scrollTop;if(top<list.scrollTop||top+selected.offsetHeight>list.scrollTop+list.clientHeight)list.scrollTop=Math.max(0,top-list.clientHeight/2);}
    if (!chapter) return;
    loadReadiness(book.id, number);
    restoreRun(book.id, number, token);
    const currentBook = book.id;
    try {
        const data = await api(`/api/local/books/${currentBook}/tasks?chapter=${number}`);
        if (token !== selectionRevision) return;
        tasks = data; renderHistory();
        if (tasks.length) await loadTask(tasks[0].id, false);
    } catch (error) { if (token === selectionRevision) toast(error.message); }
}
function renderHistory() {
    $('task-history').innerHTML = tasks.length ? tasks.map(t => `<option value="${t.id}" ${selectedTask?.id === t.id ? 'selected' : ''}>${esc(stamp(t.created_at))} · ${esc(t.stage_label)} · ${esc(t.status)}</option>`).join('') : '<option value="">本章暂无任务 · 请先选择阶段创建任务</option>';
    $('task-banner').hidden = !selectedTask;
    if (selectedTask) {
        $('task-banner').classList.toggle('warn', selectedTask.stale);
        $('task-banner').textContent = `${selectedTask.stage_label} · ${selectedTask.status}　｜　${selectedTask.file_count} 份文件 · ${selectedTask.report_count} 份回填报告`;
    }
}
async function loadTask(id, showReports = true) {
    rememberDraft();
    const token = selectionRevision;
    const loadToken = ++taskLoadRevision;
    const detail = await api(`/api/local/tasks/${id}`);
    if (token !== selectionRevision || loadToken !== taskLoadRevision || detail.book_id !== book.id || detail.chapter !== chapter?.number) return;
    selectedTask = detail;
    $('stage').value = detail.stage;
    if (showReports) tab = 'reports';
    renderHistory(); renderContent();
}
async function refresh() {
    if(!book){books=await api('/api/local/books');renderBooks();return;}
    rememberDraft();
    const token = selectionRevision, id = book?.id, number = chapter?.number, taskId = selectedTask?.id;
    const data = await api('/api/local/books');
    if (token !== selectionRevision) return;
    books = data; book = books.find(b => b.id === id) || books[0];
    chapter = book.chapters.find(c => c.number === number);
    renderHeader(); renderChapters();
    if (chapter) {
        tasks = await api(`/api/local/books/${book.id}/tasks?chapter=${chapter.number}`);
        if (token !== selectionRevision) return;
        selectedTask = taskId ? await api(`/api/local/tasks/${taskId}`) : null;
        if (token !== selectionRevision) return;
        renderHistory(); renderContent();
    } else selectChapter(book.chapters[0]?.number);
}
async function renderContent() {
    const version = ++revision;
    document.querySelectorAll('[data-tab]').forEach(el => el.classList.toggle('on', el.dataset.tab === tab));
    $('content').hidden = tab === 'reports'; $('task-pane').hidden = tab !== 'reports';
    $('content').classList.toggle('diff-view', tab === 'changes');
    $('content').classList.toggle('source-view', ['packet','changes'].includes(tab));
    $('meta').textContent = selectedTask ? `任务 ${selectedTask.id.slice(0,8)} · ${stamp(selectedTask.created_at)} · 原稿只读` : '尚未创建任务 · 原稿只读';
    $('download').disabled = !selectedTask;
    if (tab === 'reports') { renderReports(); return; }
    if (tab === 'packet') { $('content').textContent = selectedTask?.packet.text || '先选择任务阶段，点击“创建任务并保存材料”。\n\n工作台会保存这一版本的材料；你可以下载后交给 Gemini 或 Codex 执行，再将报告回填到本任务。'; return; }
    if (tab === 'changes') {
        $('content').textContent = selectedTask ? '正在对比送审版本与当前文件…' : '创建任务后，可在这里检查材料是否变化。';
        if (!selectedTask) return;
        try {
            const data = await api(`/api/local/tasks/${selectedTask.id}/changes`);
            if (version !== revision) return;
            $('content').textContent = data.changes.length ? data.changes.map(f => `${f.path}：${f.reason}`).join('\n') + '\n\n' + data.diffs.map(f => f.diff).join('\n\n') : '本次任务包含的文件与送审快照一致。\n\n这仅表示文件版本未变，不代表内容已经通过审查。';
        } catch (error) { if (version === revision) $('content').textContent = error.message; }
        return;
    }
    const path = tab === 'rules' ? '写作规范/文风规则.md' : chapter?.draft?.[0] || chapter?.outline?.[0];
    if (!path) { $('content').textContent = '暂无可预览内容'; return; }
    $('content').textContent = '正在读取…';
    try {
        const data = await api(`/api/local/books/${book.id}/document?path=${encodeURIComponent(path)}`);
        if (version !== revision) return;
        $('content').innerHTML = data.html;
        $('meta').textContent = data.path + ' · ' + data.content.length.toLocaleString() + ' 字符';
    } catch (error) { if (version === revision) $('content').textContent = error.message; }
}
function renderReports() {
    $('task-pane').dataset.taskId = selectedTask?.id || '';
    if (!selectedTask && displayedRun) { $('task-pane').innerHTML = $('automatic-result').innerHTML.replace('id="run-reviews"',''); return; }
    if (!selectedTask) { $('task-pane').innerHTML = '<div class="empty">本章还没有审阅报告。<br>选择任务后点击开始，每一轮报告都会保存在这里。</div>'; return; }
    const task = selectedTask;
    const saved = reportDrafts.get(task.id) || {reviewer:'', content:'', verdict:task.stage === 'draft' ? 'submitted' : 'revise'};
    const options = task.stage === 'draft' ? ['submitted'] : ['revise','blocked','pass'];
    $('task-pane').innerHTML = `
        <details class="manual-report"><summary>手动导入报告</summary><p class="muted" style="font-size:12px">适用于已在其他窗口完成的审阅。</p>
        ${task.stale ? '<p class="focus">送审材料已经变化。此处回填将保留为旧版本记录；请用当前文件创建新任务复审。</p>' : ''}
        <div class="report-fields"><div><label for="reviewer">执行人 / 模型</label><input id="reviewer" maxlength="100" placeholder="例如：Codex、DeepSeek 或作者" value="${esc(saved.reviewer)}"></div><div><label for="verdict">报告结论</label><select id="verdict">${options.map(v => `<option value="${v}" ${saved.verdict === v ? 'selected' : ''}>${verdictNames[v]}</option>`).join('')}</select></div></div>
        <label for="report-content">完整报告 / 结果（至少 10 字）</label><textarea id="report-content" placeholder="粘贴实际审查意见、原文证据和修改建议；不要用测试文字标记真实章节通过。">${esc(saved.content)}</textarea>
        <label class="file-upload">也可导入本地报告（.md / .txt）<input id="report-file" type="file" accept=".md,.txt,text/plain,text/markdown"></label>
        <div class="task-buttons"><button id="save-report" class="primary">保存本次报告</button></div></details><div class="task-buttons"><button id="previous-reports" class="secondary" ${task.stage === 'final' && !task.report_count ? 'disabled' : ''}>查看前轮意见</button><button id="approve" class="secondary" ${task.can_approve ? '' : 'disabled'}>${task.approved ? '作者已定稿' : '作者确认定稿'}</button></div>
        <div id="save-hint" class="save-hint">${task.approval ? '已有作者确认记录：' + esc(stamp(task.approval.created_at)) + (task.approved ? '' : '（当前已失效）') : '定稿仅记录在工作台，不修改正文或平台发布状态。'}</div>
        <div id="previous-list"></div>
        <details class="manifest"><summary>送审材料清单 · ${task.file_count} 份</summary><ul>${task.packet.files.map(f => `<li>${esc(f.path)} · ${f.chars.toLocaleString()} 字符</li>`).join('')}</ul></details>
        <h3 style="font-size:13px;margin-top:20px">报告历史 · ${task.reports.length}</h3>
        ${task.reports.map((r,i) => `<details class="report-card" ${i === 0 ? 'open' : ''}><summary><span class="status-badge">${verdictNames[r.verdict]}</span> ${esc(r.reviewer)} · ${esc(stamp(r.created_at))}</summary><pre>${esc(r.content)}</pre></details>`).join('') || '<p class="muted">尚未回填报告</p>'}`;
    ['reviewer','verdict','report-content'].forEach(id => $(id).oninput = rememberDraft);
    $('report-file').onchange = async event => {
        const file = event.target.files[0];
        if (!file) return;
        if (file.size > 1500000) { toast('报告文件过大，请控制在 1.5 MB 内'); return; }
        const content = await file.text();
        if (selectedTask?.id !== task.id || !$('report-content')) return;
        $('report-content').value = content; rememberDraft();
    };
    $('save-report').onclick = () => saveReport(task.id);
    $('previous-reports').onclick = () => previousReports(task.id);
    $('approve').onclick = () => approve(task.id, task.latest_report.id);
}
async function saveReport(taskId) {
    rememberDraft();
    const draft = reportDrafts.get(taskId);
    if (!draft?.reviewer.trim() || draft.content.trim().length < 10) { toast('请填写执行人和至少 10 字的实际报告'); return; }
    const button = $('save-report'); button.disabled = true;
    try {
        const result = await post(`/api/local/tasks/${taskId}/reports`, draft);
        reportDrafts.delete(taskId);
        if (selectedTask?.id !== taskId) return;
        $('report-content').value = '';
        selectedTask = result;
        await refresh();
        toast('报告已保存在本地');
    } catch (error) { toast(error.message); } finally { if (button.isConnected) button.disabled = false; }
}
async function previousReports(taskId) {
    try {
        const data = await api(`/api/local/tasks/${taskId}/previous-reports`);
        if (selectedTask?.id !== taskId || !$('previous-list')) return;
        $('previous-list').innerHTML = '<h3 style="font-size:13px">前轮审查意见</h3>' + (data.length ? data.map(t => `<details class="report-card"><summary>${esc(t.stage_label)}${t.stale ? ' · 对应材料已变化' : ''}</summary>${t.reports.map(r => `<p class="muted">${esc(r.reviewer)} · ${verdictNames[r.verdict]}</p><pre>${esc(r.content)}</pre>`).join('')}</details>`).join('') : '<p class="muted" style="font-size:12px">本章没有更早的回填报告。</p>');
    } catch (error) { toast(error.message); }
}
async function approve(taskId, reportId) {
    const button = $('approve'); button.disabled = true;
    try {
        await post(`/api/local/tasks/${taskId}/approve`, {report_id: reportId});
        if (selectedTask?.id === taskId) await refresh();
        toast('作者定稿记录已保存');
    } catch (error) { toast(error.message); } finally { if (button.isConnected) button.disabled = false; }
}

document.querySelectorAll('[data-tab]').forEach(el => el.onclick = () => { rememberDraft(); tab = el.dataset.tab; renderContent(); });
$('confirm-versions').onchange = () => { if (book && chapter) loadReadiness(book.id, chapter.number); };
$('search').oninput = renderChapters;
$('task-history').onchange = () => { if ($('task-history').value) loadTask($('task-history').value).catch(error => toast(error.message)); };
$('refresh').onclick = async () => { $('refresh').disabled = true; try { await refresh(); toast('目录与材料版本已检查'); } catch(error) { toast(error.message); } finally { $('refresh').disabled = false; } };
$('automatic-run').onclick = async () => {
    if (!book || !chapter) return;
    const button=$('automatic-run'); button.disabled=true; $('automatic-result').textContent='正在将本章交给 Gemini 与 Codex 依次处理…';
    try {
        const run=await post(`/api/local/books/${book.id}/run`,{chapter:chapter.number,confirm_versions:$('confirm-versions').checked,mode:workflowMode(),max_revisions:Number($('max-revisions').value),codex_model:$('codex-model').value.trim()||null,gemini_model:$('gemini-model').value||null});
        await watchRun(run.id);
    } catch(error) { $('automatic-result').textContent=error.message; toast(error.message); }
    finally { if(book && chapter) loadReadiness(book.id, chapter.number); }
};
async function restoreRun(id, number, token) {
    try {
        const runs=await api(`/api/local/books/${id}/runs?chapter=${number}`);
        if(token!==selectionRevision)return;
        if(runs.length) {
            const chosen=runs[0].result?.options?.mode;
            if(chosen) document.querySelector(`[name="workflow-mode"][value="${chosen==='outline'?'outline':'full'}"]`).checked=true;
            await watchRun(runs[0].id, true);
        }
    } catch(error) { if(token===selectionRevision) $('automatic-result').textContent=error.message; }
}
async function watchRun(runId, restoring=false) {
    const token=selectionRevision;
    activeRunId=runId;
    const status=$('provider-status'), details=$('automatic-result');
    let lastRendered=null;
    while (true) {
        const run=await api(`/api/local/runs/${runId}`);
        if(token!==selectionRevision)return;
        const states={queued:'等待运行',running:'正在处理',completed:'已完成',needs_author:'需要你确认',blocked:'已暂停',failed:'未完成'};
        status.textContent=`第${run.chapter}章 · ${states[run.status] || run.status} · ${run.step}`;
        $('automatic-run').disabled=['queued','running'].includes(run.status);
        if(lastRendered!==run.updated_at){await paintRun(run,token);lastRendered=run.updated_at;}
        if (run.status === 'completed' || run.status === 'needs_author' || run.status === 'blocked' || run.status === 'failed') {
            activeRunId=null;
            if (!run.artifacts?.length && run.result?.draft_file) {
                const draftName=run.result.draft_file.split(/[\\/]/).pop();
                const outlineName=run.result.outline_file?.split(/[\\/]/).pop();
                details.insertAdjacentHTML('beforeend', `<p><a href="/api/local/runs/${encodeURIComponent(run.id)}/artifacts/${encodeURIComponent(draftName)}">下载候选正文</a>${outlineName?`　<a href="/api/local/runs/${encodeURIComponent(run.id)}/artifacts/${encodeURIComponent(outlineName)}">下载候选细纲</a>`:''}</p>`);
            }
            if (run.result?.final_task_id && !restoring) {
                await refresh();
                await loadTask(run.result.final_task_id);
            }
            if(!restoring) toast(run.status === 'completed' ? '本章自动审阅流程已完成' : '流程停在需要处理的位置，书稿没有被自动覆盖');
            return;
        }
        await new Promise(resolve=>setTimeout(resolve,1800));
    }
}
$('generate').onclick = async () => {
    if (!chapter) return;
    rememberDraft();
    const id = book.id, number = chapter.number, token = selectionRevision;
    $('generate').disabled = true;
    try {
        const result = await post(`/api/local/books/${id}/tasks`, {chapter:number, stage:$('stage').value, extra_paths:[...selectedMaterials], confirm_versions:$('confirm-versions').checked});
        if (token !== selectionRevision) return;
        selectedTask = result; tab = 'packet';
        await refresh();
        toast('任务与材料快照已保存，可下载交给模型执行');
    } catch (error) { toast(error.message); } finally { $('generate').disabled = false; }
};
$('download').onclick = () => {
    if (!selectedTask) { toast('请先创建任务'); return; }
    const url = URL.createObjectURL(new Blob([selectedTask.packet.text], {type:'text/markdown;charset=utf-8'}));
    const anchor = document.createElement('a'); anchor.href = url;
    anchor.download = `${book.id}_第${chapter.number}章_${selectedTask.stage_label}_${selectedTask.id.slice(0,8)}.md`;
    anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
};
document.querySelector('.flow').insertAdjacentHTML('beforebegin', '<section class="sync-card"><div><strong>书籍记忆</strong><span id="sync-summary">正在检查同步进度…</span></div><button id="tracking-sync" class="secondary">同步两本书</button><details><summary>查看每本书的进度</summary><div id="tracking-sync-status" class="readiness-details" role="status">正在检查…</div><p class="muted">同步会更新上下文、人物、伏笔与时间线。缺失记录由 Codex 补记，会使用账号额度；原追踪自动备份。</p></details></section>');
let syncWatching = false;
async function loadTrackingSync(watch = false) {
    if (syncWatching) return;
    syncWatching = true;
    try {
        do {
            const items = await api('/api/local/tracking-sync');
            const active = items.some(i => ['queued','running'].includes(i.latest_run?.status));
            $('tracking-sync').disabled = active;
            $('tracking-sync').textContent = active ? '正在同步…' : '同步两本书';
            $('sync-summary').textContent = active ? '正在核对正文并补记，完成前不会覆盖原追踪。' : items.some(i => i.error || i.validation_error || i.pending?.length) ? '有书籍的记忆需要更新，可一键同步。' : '两本书的追踪均已通过校验。';
            $('tracking-sync-status').textContent = items.map(i => {
                const heading = `${i.title}：${i.error || `已追踪 ${i.tracked} / 有效正文 ${i.confirmed} 章，待补记 ${i.pending.length} 章`}`;
                return heading + (i.validation_error ? `\n追踪校验：${i.validation_error}` : '') +
                    (i.excluded?.length ? `\n未纳入：${i.excluded.length} 份未登记正文` : '') +
                    (i.latest_run ? `\n${i.latest_run.step}：${i.latest_run.message}` : '');
            }).join('\n\n');
            if (!active || !watch) break;
            await new Promise(resolve => setTimeout(resolve, 2500));
        } while (true);
    } catch (error) { $('tracking-sync-status').textContent = error.message; }
    finally { syncWatching = false; }
}
$('tracking-sync').onclick = async () => {
    $('tracking-sync').disabled = true;
    try { await post('/api/local/tracking-sync', {}); await loadTrackingSync(true); }
    catch (error) { toast(error.message); }
    finally { $('tracking-sync').disabled = false; if (book && chapter) loadReadiness(book.id, chapter.number); }
};
// Keep the daily flow visible and move manual handoff tools behind one disclosure.
const runCard = document.querySelector('.automation-card');
runCard.classList.add('run-card');
runCard.querySelector('strong').id = 'run-title';
runCard.querySelector('strong').textContent = '选择章节后启动';
runCard.querySelector('summary').textContent = '连接与校验详情';
runCard.append($('automatic-result'));
$('automatic-result').setAttribute('role','status');
const reader = document.querySelector('.layout > section:last-child');
document.querySelector('.layout').before(runCard);
document.querySelector('.layout').after(document.querySelector('.sync-card'));
const advanced = document.createElement('details');
advanced.className = 'advanced-tools';
advanced.innerHTML = '<summary>高级工具 <span>手动任务、补充材料与项目设置</span></summary><p id="project-path" class="muted"></p>';
document.querySelector('main').append(advanced);
for (const element of [document.querySelector('.flow'), document.querySelector('.controls'), $('task-history'), $('focus'), document.querySelector('.materials')]) advanced.append(element);
runCard.append($('version-confirm'));
reader.querySelector('.panel-head').after($('task-banner'));
for (const name of ['packet','changes']) document.querySelector(`[data-tab="${name}"]`).classList.add('advanced-tab');
advanced.addEventListener('toggle', () => document.body.classList.toggle('show-advanced', advanced.open));
document.querySelector('.top').querySelector('span').textContent = '写作工作台';
document.querySelector('.top .pill').textContent = '原稿保留 · 修改稿另存';
document.querySelector('.notice').textContent = '日常只需选书、选章节、点启动。Gemini 负责写作，Codex 负责审阅与独立终审；产生的修改稿会另存，供你确认。';
document.querySelector('[data-tab="reports"]').textContent = '审阅结果';
document.querySelector('[data-tab="rules"]').textContent = '写作规则';
$('refresh').textContent = '刷新';
style.textContent += `
.show-advanced #download{display:block}
.run-card.automation-card{border:1px solid #dce8df;border-radius:11px;margin:0 0 22px}.sync-card{margin-top:22px}
:root{--bg:#f7f8fa;--ink:#23312e;--muted:#728079;--line:#e5eae7;--green:#28624e}
body{font-family:'Segoe UI','Microsoft YaHei',sans-serif}aside{width:224px;background:#fff;padding:30px 18px}.brand{font-size:19px;letter-spacing:0}.sub{letter-spacing:1px}.book{font-size:13px;border-radius:8px}.book.active{background:#edf5ef;border-color:#d7e6dc;box-shadow:none}.book small{font-size:11px}.label{letter-spacing:1px}main{margin-left:224px;padding:28px 36px;max-width:1600px}.top{border:0;padding:0}.top .pill{border:0;background:#edf4ef;font-size:11px}h1{font-size:24px;margin:25px 0 6px;letter-spacing:0}.stats{display:flex;gap:20px;margin:14px 0 24px;font-size:12px;color:var(--muted)}
.sync-card{background:white;border:1px solid var(--line);border-radius:10px;display:grid;grid-template-columns:1fr auto;gap:9px 20px;padding:15px 20px;margin-bottom:22px}.sync-card strong{font-size:13px;margin-right:15px}.sync-card span{font-size:12px;color:var(--muted)}.sync-card details{grid-column:1/-1;font-size:12px}.sync-card summary{cursor:pointer;color:var(--muted)}.sync-card p{font-size:12px}.layout{grid-template-columns:260px minmax(0,1fr);gap:20px;align-items:start}.panel-head{padding:16px 20px}.panel-head h2{font-size:14px}.panel-head input{width:105px}.chapter-list{height:620px}.chapter{padding:13px 16px}.chapter.selected{padding-left:13px}.chapter .name{font-size:12px;max-width:100%}.chapter small{font-size:11px}.num{font-family:inherit;font-size:13px;font-weight:600;margin-right:8px}.panel{border-radius:11px;box-shadow:0 3px 14px #263e3003}
.run-card{border:0;border-bottom:1px solid var(--line);border-radius:0;margin:0;padding:23px;background:#f1f7f2;gap:12px 18px}.run-card strong{font-size:19px}.run-card span{font-size:12px;line-height:1.8;max-width:480px}.run-card .primary{padding:12px 23px;border-radius:7px;font-weight:600}.run-card details{font-size:11px}.run-card summary{color:var(--muted)}#automatic-result{grid-column:1/-1;color:var(--ink);padding:12px 14px;border:1px solid #dce8df;background:#ffffffa0;border-radius:7px;font-size:12px;line-height:1.8;max-height:320px;overflow:auto}#version-confirm{grid-column:1/-1;padding:10px;border-radius:6px}.tabs{gap:22px;padding:0 20px}.tabs button{font-size:12px}#content{height:420px;padding:24px 28px;font-size:14px;line-height:2.1}.bottom{gap:12px}#meta{max-width:70%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}#download{display:none}.advanced-tab{display:none}.show-advanced .advanced-tab{display:block}.advanced-tools{margin-top:22px;border:1px solid var(--line);border-radius:10px;background:white;padding:16px 20px}.advanced-tools>summary{cursor:pointer;font-size:13px}.advanced-tools>summary span{font-size:11px;color:var(--muted);margin-left:10px}.advanced-tools .flow{margin:15px 0;background:#f8faf8;font-size:11px}.advanced-tools .controls{padding:15px 0}.advanced-tools .history-select{margin:8px 0;width:100%}.advanced-tools .focus{margin:14px 0}.advanced-tools .materials{border:0;padding:12px 0;margin:0}.advanced-tools #project-path{font-size:11px;margin-top:15px;overflow-wrap:anywhere}.manual-report{border-bottom:1px solid var(--line);padding-bottom:14px}.manual-report summary{font-size:12px;cursor:pointer;color:var(--muted)}.notice{font-size:11px;margin:20px 0;max-width:800px}.task-pane{min-height:300px}.task-banner{margin:12px 20px}.task-pane .report-card pre{font-size:13px}.primary:hover:not(:disabled){background:#1f503f}.secondary:hover:not(:disabled){background:#f1f5f2}button:focus-visible,summary:focus-visible{outline:3px solid #92baa4;outline-offset:3px}[hidden]{display:none!important}
@media(max-width:1100px){aside{width:190px}main{margin-left:190px;padding:24px}.layout{grid-template-columns:220px minmax(0,1fr)}.chapter-list{height:620px}.run-card{grid-template-columns:1fr}.run-card .primary{justify-self:start}.sync-card span{display:block;margin-top:3px}.top .pill{display:none}}@media(max-width:800px){aside{position:static;width:auto;padding:16px 20px}.aside-foot,.label,.sub{display:none}#books{display:flex;gap:8px;margin-top:12px}.book{width:50%;margin:0;padding:10px}.book small{display:none}main{margin:0;padding:20px}.layout{grid-template-columns:1fr}.chapter-list{height:190px}.top{font-size:11px}.sync-card{padding:14px}.sync-card .secondary{font-size:12px}h1{font-size:21px;margin-top:18px}.run-card{grid-template-columns:1fr auto}.run-card .primary{padding:11px 15px}#content{padding:20px;height:350px}.advanced-tools>summary span{display:block;margin:4px 0 0}}@media(max-width:480px){.run-card{grid-template-columns:1fr}.run-card .primary{width:100%}.stats{gap:14px}.top-actions{gap:6px}.sync-card{grid-template-columns:1fr}.sync-card .secondary{justify-self:start}}
`;
// Stronger region boundaries keep navigation, execution and reading distinct.
style.textContent += `
:root{--bg:#edf0f3;--line:#c5cfd0;--muted:#586861}
aside{border-right:2px solid #bcc8c4}.top{padding-bottom:16px;border-bottom:2px solid #c5cfd0}
.layout{gap:28px}.panel{border:2px solid #bac7c2;box-shadow:none}.panel-head{background:#e9efec;border-bottom:2px solid #bac7c2;padding:17px 20px}.panel-head h2{font-weight:700;color:#233d32}
.chapter{border-bottom:1px solid #d8e0dc;padding-top:16px;padding-bottom:16px}.chapter.selected{background:#dcece1;border-left:5px solid #28624e;padding-left:11px}.chapter small{color:#52665a}.chapter:focus-visible{outline-offset:-4px}
.run-card.automation-card{border:2px solid #739783;border-top:5px solid #28624e;background:#e8f1eb;margin-bottom:30px;padding:20px 22px}.run-card::before{content:'启动任务';grid-column:1/-1;display:block;font-size:12px;font-weight:700;letter-spacing:1px;color:#365e49;padding-bottom:11px;border-bottom:1px solid #a9c1b2;margin-bottom:3px}
#automatic-result{border:1px solid #afbeb5;background:#fff;border-radius:6px;padding:16px;margin-top:4px}#automatic-result::before{content:'运行进度与结果';display:block;font-weight:700;font-size:12px;color:#365e49;border-bottom:1px solid #d1dbd5;padding-bottom:9px;margin-bottom:11px}
.tabs{background:#f4f7f5;border-bottom:2px solid #c2cec7;padding-top:4px}.tabs button{padding:12px 4px;font-size:13px}.tabs button.on{font-weight:700;border-bottom:3px solid #28624e;color:#204e39;background:#e4eee7}.tabs button+button{margin-left:8px}#content,.task-pane{background:white}.bottom{border-top:2px solid #c5cfd0;background:#f3f6f4}
.sync-card{border:2px solid #bac7c2;border-left:5px solid #7e9589;margin-top:30px;padding:19px 22px}.sync-card strong{font-size:15px}.sync-card details{border-top:1px solid #d1dad5;padding-top:12px;margin-top:4px}.advanced-tools{border:2px solid #c0c9cb;margin-top:26px;background:#f8fafb}.advanced-tools>summary{font-weight:700;color:#3e5048}.advanced-tools>summary span{font-weight:400}.report-card{border:1px solid #bac7c2;background:#fafcfb}.report-card summary{padding-bottom:6px}.report-card[open] summary{border-bottom:1px solid #c5d1c9}.manual-report{border-bottom:2px solid #c5cfd0}.notice{color:#52635a;line-height:1.9}
@media(max-width:800px){aside{border-right:0;border-bottom:2px solid #bcc8c4}.layout{gap:24px}.run-card.automation-card{padding:18px;margin-bottom:26px}.sync-card{padding:17px}.chapter-list{height:210px}}
`;
const contentReader=document.createElement('div');
contentReader.id='content'; contentReader.className='markdown-reader';
$('content').replaceWith(contentReader);
runCard.querySelector('div').insertAdjacentHTML('afterend', `<fieldset class="workflow-choices"><legend>选择本次任务</legend>
<label><input type="radio" name="workflow-mode" value="full" checked><strong>全面写作</strong><span>审纲 → 改纲 → 写正文 → 审正文 → 改正文 → 最终审阅</span></label>
<label><input type="radio" name="workflow-mode" value="outline"><strong>审阅细纲</strong><span>审阅并修改细纲 → 最终细纲审阅，不写正文</span></label></fieldset>
<div id="workflow-progress" class="workflow-progress"></div><details class="model-settings"><summary>模型、返修次数与最终审阅规则</summary>
<p id="model-source">正在读取模型配置…</p><label>Codex 模型 <input id="codex-model" placeholder="留空跟随本机 CLI 配置" maxlength="100"></label>
<label>Antigravity 模型 <select id="gemini-model"><option value="">跟随 CLI 默认（实际模型尚未确认）</option></select></label>
<label>细纲和正文各最多自动修改 <select id="max-revisions"><option>1</option><option>2</option><option selected>3</option><option>4</option><option>5</option><option>6</option></select> 次</label>
<p>最终审阅方式：Codex 全新 CLI 会话，使用本书审查 skill 和工作台内置复核提示词。未部署专用终审 skill，也不是独立子 agent。</p>
<details><summary>查看内置复核要求</summary><p>不查看前轮报告；按本书规则完整审阅当前候选稿。检查因果、连续性、金手指、人物知识边界、内容容量和改稿损伤。每个问题须写原文证据、影响、最小修改方向与验收条件；不确定的作者决定必须明确提出，不凭喜好挑错。</p></details></details>`);
document.querySelector('.top').insertAdjacentHTML('afterend','<section class="usage-panel"><div><strong>账号额度</strong><span id="usage-status">正在读取；CLI 与当前账号共享额度</span></div><button id="refresh-usage" class="secondary">刷新额度</button><div id="usage-details"></div></section>');
function workflowMode(){return document.querySelector('[name="workflow-mode"]:checked')?.value||'full';}
function renderPhases(run=null){
    const names=workflowMode()==='outline'?['审阅细纲','修改细纲','最终细纲审阅']:['审阅细纲','修改细纲','写正文','审阅正文','修改正文','最终正文审阅'];
    const phases=run?.result?.phases || names.map(name=>({name,state:'pending'}));
    const percent=run?.result?.progress??0;
    $('workflow-progress').innerHTML=`<div class="progress-caption"><strong>${run?esc(run.step):'等待启动'}</strong><span>${percent}% · 按完成步骤计算</span></div><progress max="100" value="${percent}" aria-label="流程完成进度"></progress><ol class="phase-list">${phases.map(p=>`<li class="${esc(p.state)}">${p.state==='done'?'✓':p.state==='active'?'●':'○'} ${esc(p.name)}</li>`).join('')}</ol><p class="muted">${run?`任务开始于 ${stamp(run.created_at)} · 本轮状态更新 ${stamp(run.updated_at)}`:'模型生成时进度条不会假装前进；每步结束后更新。无需修改时，该修改步骤自动跳过。'}</p>`;
}
async function paintRun(run,token){
    displayedRun=run;
    chapterRuns.set(`${run.book_id}:${run.chapter}`,run);
    updateChapterRunBadges();
    $('process-detail-count').textContent=`${(run.result?.reviews||run.result?.steps||[]).length} 份报告 · ${['blocked','failed'].includes(run.status)?'已暂停，点击查看原因':'点击查看详细内容'}`;
    renderPhases(run);
    document.querySelectorAll('[name="workflow-mode"],#max-revisions,#codex-model,#gemini-model').forEach(el=>el.disabled=['queued','running'].includes(run.status));
    const reviews=run.result?.reviews||run.result?.steps||[];
    const markdown=await post('/api/local/markdown',{text:run.message});
    if(token!==selectionRevision)return;
    $('automatic-result').innerHTML=`<div class="markdown-reader ${['blocked','failed'].includes(run.status)?'failure-reason':''}">${markdown.html}</div><div class="artifact-links">${(run.artifacts||[]).map(a=>`<a href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.name)}</a>`).join('')}</div><div id="run-reviews"></div>`;
    for(const [i,r] of reviews.entries()){
        const html=await post('/api/local/markdown',{text:r.report||''});
        if(token!==selectionRevision)return;
        $('run-reviews').insertAdjacentHTML('beforeend',`<details class="run-review" ${i===reviews.length-1?'open':''}><summary>${esc(r.stage)} · ${esc({PASS:'通过',REVISE:'需修改',BLOCKED:'待作者裁定'}[r.verdict]||r.verdict)} · ${esc(r.reviewer)}</summary><div class="markdown-reader">${html.html}</div>${r.revision_brief?`<p><strong>修改要点：</strong>${esc(r.revision_brief)}</p>`:''}</details>`);
    }
    if(run.result?.events?.length)$('automatic-result').insertAdjacentHTML('beforeend',`<details class="run-review"><summary>完整运行时间线 · ${run.result.events.length} 条</summary><ol>${run.result.events.map(e=>`<li><strong>${stamp(e.at)} · ${esc(e.stage)}</strong><p>${esc(e.message)}</p></li>`).join('')}</ol></details>`);
    if(tab==='reports'&&!selectedTask)renderReports();
}
document.querySelectorAll('[name="workflow-mode"]').forEach(el=>el.onchange=()=>{renderPhases();$('automatic-run').textContent=workflowMode()==='outline'?'开始审阅细纲':'开始全面写作';if(book&&chapter)loadReadiness(book.id,chapter.number);});
async function loadUsage(){
    $('refresh-usage').disabled=true;
    try{
        const data=await api('/api/local/usage');
        $('usage-status').textContent=`查询于 ${stamp(data.fetched_at*1000)} · Codex 与同账号共享额度`;
        $('usage-details').innerHTML=`<div><strong>Codex</strong>${data.codex.available?data.codex.buckets.map(b=>b.windows.map(w=>`<p>${esc(b.name)} · ${w.minutes===300?'5 小时':w.minutes===10080?'每周':`${w.minutes} 分钟`}剩余 <b>${w.remaining}%</b>${w.resets_at?` · 重置 ${stamp(w.resets_at*1000)}`:''}</p>`).join('')).join(''):`<p>${esc(data.codex.message)}</p>`}</div><div><strong>Antigravity / Gemini</strong><p>${esc(data.gemini.message)}</p></div>`;
    }catch(error){$('usage-status').textContent=error.message;}finally{$('refresh-usage').disabled=false;}
}
$('refresh-usage').onclick=loadUsage;
api('/api/local/models').then(data=>{
    $('model-source').textContent=`Codex 本机配置：${data.codex.model||'未读取到'}，推理强度 ${data.codex.effort||'未读取到'}。Antigravity 当前默认模型：未确认。下方指定值只用于新任务，不修改 CLI 全局配置。`;
    $('codex-model').placeholder=data.codex.model?`留空跟随本机配置：${data.codex.model}`:'留空跟随本机 CLI 配置';
    $('gemini-model').insertAdjacentHTML('beforeend',data.gemini.available_models.map(m=>`<option value="${esc(m.id)}">${esc(m.name)} · ${esc(m.id)}</option>`).join(''));
}).catch(error=>{$('model-source').textContent=error.message;});
style.textContent+=`
.workflow-choices,.model-settings,.workflow-progress{grid-column:1/-1}.workflow-choices{display:grid;grid-template-columns:1fr 1fr;border:0;padding:0;gap:12px;margin:0}.workflow-choices legend{font-size:12px;margin-bottom:8px}.workflow-choices label{border:2px solid #becdc3;padding:14px;background:#fff;border-radius:8px;cursor:pointer}.workflow-choices label:has(input:checked){border-color:#28624e;background:#e0eee4}.workflow-choices input{width:auto;accent-color:#28624e;margin-right:8px}.workflow-choices label strong{font-size:15px}.workflow-choices span{font-size:12px;margin-top:8px}.model-settings{border-top:1px solid #afc2b5;padding-top:10px;font-size:12px}.model-settings label{display:block;margin:10px 0}.model-settings input,.model-settings select{width:auto;max-width:100%;padding:8px;border:1px solid #afbeb5;background:white;border-radius:5px}.model-settings input{width:300px}.model-settings p{line-height:1.9}.progress-caption{display:flex;justify-content:space-between;gap:10px;font-size:12px}.workflow-progress strong{font-size:13px}.workflow-progress progress{width:100%;height:12px;accent-color:#28624e}.phase-list{display:flex;gap:8px;flex-wrap:wrap;list-style:none;padding:0;margin:10px 0}.phase-list li{border:1px solid #bdc9c1;background:white;border-radius:5px;padding:5px 9px;font-size:12px;color:#66746b}.phase-list .done{background:#d7ebdf;color:#215239}.phase-list .active{background:#fff4db;border-color:#bf944c;color:#75501b;font-weight:bold}.workflow-progress>p{font-size:11px}.usage-panel{background:white;border:1px solid #c5cfd0;border-radius:8px;padding:13px 16px;margin:20px 0;display:grid;grid-template-columns:1fr auto;gap:10px;font-size:12px}.usage-panel span{display:block;color:#586861;margin-top:4px}#usage-details{grid-column:1/-1;display:grid;grid-template-columns:1fr 1fr;gap:20px}#usage-details>div+div{border-left:1px solid #c5cfd0;padding-left:20px}.markdown-reader{white-space:normal;overflow-wrap:anywhere;font:14px/1.95 'Segoe UI','Microsoft YaHei',sans-serif}.markdown-reader h1{font-size:23px;margin:18px 0}.markdown-reader h2{font-size:20px;margin:24px 0 12px;padding-bottom:8px;border-bottom:1px solid #c5cfd0}.markdown-reader h3{font-size:17px;margin:20px 0 10px}.markdown-reader p{margin:12px 0}.markdown-reader ul,.markdown-reader ol{padding-left:24px}.markdown-reader li{margin:6px 0}.markdown-reader blockquote{border-left:4px solid #7e9589;margin:15px 0;padding:4px 16px;background:#f0f5f1}.markdown-reader table{border-collapse:collapse;display:block;max-width:100%;overflow:auto;margin:18px 0}.markdown-reader th,.markdown-reader td{border:1px solid #bbc9c0;padding:9px 12px}.markdown-reader th{background:#e9efec}.markdown-reader pre{height:auto;white-space:pre;overflow:auto;padding:15px;background:#eff3f1;border-radius:6px}.markdown-reader code{font-family:Consolas,monospace;background:#eff3f1;padding:2px 4px}.markdown-reader hr{border:0;border-top:2px solid #bac7c2;margin:24px 0}#content{overflow:auto}#content.source-view{white-space:pre-wrap}.run-review{border:1px solid #bac7c2;border-radius:6px;padding:12px;margin:14px 0;background:white}.run-review summary{font-weight:600;cursor:pointer}.run-review[open] summary{border-bottom:1px solid #c5cfd0;padding-bottom:10px;margin-bottom:12px}.failure-reason{border-left:4px solid #b65a46;padding-left:14px}.artifact-links{display:flex;gap:10px;flex-wrap:wrap;margin-top:15px}.artifact-links a{border:1px solid #bac7c2;padding:5px 10px;border-radius:5px;color:#28624e}#automatic-result{white-space:normal;max-height:600px}.run-card .primary{grid-column:2;grid-row:2;align-self:start}.usage-panel+ h1{margin-top:20px}@media(max-width:650px){.workflow-choices,#usage-details{grid-template-columns:1fr}#usage-details>div+div{border:0;border-top:1px solid #c5cfd0;padding:12px 0 0}.progress-caption{flex-direction:column}.run-card .primary{grid-column:1;grid-row:auto}.run-card{grid-template-columns:1fr}}
`;
const workspace=document.createElement('section');
workspace.id='workspace'; workspace.hidden=true;
const main=document.querySelector('main');
for(const child of [...main.children])if(!child.classList.contains('top'))workspace.append(child);
main.append(workspace);
main.insertAdjacentHTML('beforeend','<section id="book-pending" class="book-pending"><div class="pending-book-icon" aria-hidden="true">▤</div><h1>书籍待选择</h1><p>从左侧选择一本书，开始查看章节与写作任务。</p></section>');
const shelf=document.createElement('details');
shelf.id='book-shelf';shelf.open=true;
shelf.innerHTML='<summary><span class="shelf-caption">我的书籍</span><strong id="book-shelf-label">选择一本书</strong><span class="shelf-hint">点击切换</span></summary>';
document.querySelector('aside .label').replaceWith(shelf);
shelf.append($('books'));
const chapterBrowser=document.querySelector('.layout > section:first-child');
chapterBrowser.classList.add('chapter-browser');chapterBrowser.hidden=true;
chapterBrowser.id='chapter-navigation';
chapterBrowser.querySelector('h2').textContent='章节';
chapterBrowser.querySelector('.panel-head').insertAdjacentHTML('beforeend','<button id="navigation-toggle" class="secondary" aria-controls="chapter-navigation" aria-expanded="false" title="展开整个章节导航栏">展开 »</button>');
function setNavigationCollapsed(collapsed){
    document.body.classList.toggle('nav-collapsed',collapsed);
    $('navigation-toggle').setAttribute('aria-expanded',String(!collapsed));
    $('navigation-toggle').textContent=collapsed?'展开 »':'« 收起';
    $('navigation-toggle').title=collapsed?'展开整个章节导航栏':'收起整个章节导航栏';
}
$('navigation-toggle').onclick=()=>setNavigationCollapsed(!document.body.classList.contains('nav-collapsed'));
shelf.after(chapterBrowser);
const processing=document.createElement('details');
processing.id='process-details';processing.innerHTML='<summary>处理详情 <span id="process-detail-count">报告、修改建议与运行日志</span></summary>';
$('automatic-result').before(processing);processing.append($('automatic-result'));
const account=document.createElement('details');account.className='account-disclosure';
account.innerHTML='<summary>账号与额度</summary>';
document.querySelector('.usage-panel').before(account);account.append(document.querySelector('.usage-panel'));
const layoutCss=document.createElement('link');layoutCss.rel='stylesheet';layoutCss.href='/workbench-layout.css';document.head.append(layoutCss);
const chapterRuns=new Map();let chapterRunPollBusy=false;
function updateChapterRunBadges(){
    if(!book)return;
    document.querySelectorAll('[data-chapter-row]').forEach(row=>{
        const run=chapterRuns.get(`${book.id}:${row.dataset.chapterRow}`);
        const label=run?({queued:'排队',running:'处理中',completed:'已完成',needs_author:'待确认',blocked:'已暂停',failed:'未完成'}[run.status]||''):'';
        row.querySelector('.chapter-state').textContent=label;
        row.dataset.runStatus=run?.status||'';
    });
}
async function pollChapterRuns(){
    if(!book||chapterRunPollBusy||document.hidden)return;
    const id=book.id;chapterRunPollBusy=true;
    try{const runs=await api(`/api/local/books/${id}/runs`);const seen=new Set();for(const run of runs){if(run.chapter<1||seen.has(run.chapter))continue;seen.add(run.chapter);chapterRuns.set(`${id}:${run.chapter}`,run);}if(book?.id===id)updateChapterRunBadges();}catch{}finally{chapterRunPollBusy=false;}
}
setInterval(pollChapterRuns,5000);
renderPhases();loadUsage();
loadTrackingSync(true);
api('/api/local/books').then(data => { books=data;renderBooks();if(!books.length){$('book-pending').querySelector('h1').textContent='先连接你的小说项目';$('book-pending').querySelector('p').textContent='复制 books.example.json 为 books.local.json，填入项目目录后重启工作台。';} }).catch(error => { $('book-pending').querySelector('h1').textContent='书籍目录读取失败';toast(error.message); });

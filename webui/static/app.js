/* AI 影视工坊 — web UI for the AFE ComfyUI pipeline. Plain JS, no build step. */
'use strict';

const $ = (sel, el = document) => el.querySelector(sel);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const sleep = ms => new Promise(r => setTimeout(r, ms));

const STEPS = [
  { n: 1, title: '剧本', sub: '拆成分镜、场景、角色', verb: '① 分析剧本' },
  { n: 2, title: '素材', sub: '场景图、角色形象、道具', verb: '② 生成素材' },
  { n: 3, title: '首帧', sub: '每个分镜的第一帧画面', verb: '③ 生成首帧' },
  { n: 4, title: '视频', sub: '让画面动起来', verb: '④ 渲染视频' },
  { n: 5, title: '成片', sub: '拼成完整影片', verb: '⑤ 合成成片' },
];
const VIEWS = [['est', '全景'], ['med', '中景'], ['atm', '氛围']];

const S = {
  project: localStorage.getItem('afe_project') || 'afe_project',
  opts: { styles: [], episodes: [], projects: [], defaults: {} },
  view: null,
  settings: {},
  sel: { cast: {}, scene: {}, kf: {} },
  redo: { cast: {}, scene: {}, kf: {}, video: {} },
  long: {}, links: {}, notes: {}, castNotes: {}, sceneNotes: {}, genders: {}, skip: new Set(),
  open: {}, tab: 'shots',
  run: null, dock: null,
  clientId: 'afe-' + Math.random().toString(36).slice(2),
  ws: null, saveTimer: null,
};

/* ── tiny helpers for "1:2, 3:1" style settings ─────────────────────────── */
function parsePairs(text) {
  const out = {};
  String(text || '').split(/[,;，；\n]+/).forEach(item => {
    const m = item.trim().match(/^(.+?)\s*[:=：]\s*(\d+(?:\.\d+)?)$/);
    if (m) out[m[1].trim()] = Number(m[2]);
  });
  return out;
}
const composePairs = obj => Object.entries(obj).filter(([, v]) => v).map(([k, v]) => `${k}:${v}`).join(', ');
function parseGenders(text) {
  const out = {};
  String(text || '').split(/[,;，；\n]+/).forEach(item => {
    const m = item.trim().match(/^(.+?)\s*[:=：]\s*(female|male|女|男|女性|男性)$/i);
    if (!m) return;
    out[m[1].trim()] = /^(female|女|女性)$/i.test(m[2]) ? 'female' : 'male';
  });
  return out;
}
function castGender(name, fallback) {
  const chosen = S.genders[name];
  if (chosen === 'female' || chosen === 'male') return chosen;
  const g = String(fallback || '').toLowerCase();
  if (/female|woman|girl|女/.test(g)) return 'female';
  if (/male|man|boy|男/.test(g)) return 'male';
  return '';
}
function genderSelect(name, fallback) {
  const cur = castGender(name, fallback);
  return `<label class="gender">性别<select data-gender="${esc(name)}">
    <option value="" ${cur ? '' : 'selected'}>未选</option>
    <option value="female" ${cur === 'female' ? 'selected' : ''}>女</option>
    <option value="male" ${cur === 'male' ? 'selected' : ''}>男</option>
  </select></label>`;
}
function parseLinkText(text) {
  const out = {};
  String(text || '').split(/\n+/).forEach(line => {
    const m = line.trim().match(/^(shot_\d+|\d+)\s*[:=：]\s*(.+)$/i);
    if (!m) return;
    const n = /^\d+$/.test(m[1]) ? Number(m[1]) : Number(m[1].replace(/^shot_/i, ''));
    if (!n) return;
    out['shot_' + String(n).padStart(3, '0')] = m[2].trim();
  });
  return out;
}
const composeLinks = obj => Object.entries(obj).filter(([, v]) => String(v || '').trim())
  .map(([k, v]) => `${k}: ${String(v).replace(/\s+/g, ' ').trim()}`).join('\n');
function parseCastNotes(text) {
  const out = {};
  String(text || '').split(/\n+/).forEach(line => {
    const m = line.trim().match(/^(.+?)\s*[:=：]\s*(.+)$/);
    if (!m) return;
    out[m[1].trim()] = m[2].trim();
  });
  return out;
}

function syncFromSettings() {
  const s = S.settings;
  S.sel.cast = parsePairs(s.cast_picks);
  S.sel.scene = parsePairs(s.scene_view_picks);
  S.sel.kf = parsePairs(s.kf_picks);
  S.redo.cast = parsePairs(s.cast_redo);
  S.redo.scene = parsePairs(s.scene_redo);
  S.redo.kf = parsePairs(s.kf_redo);
  S.redo.video = parsePairs(s.video_redo);
  S.long = parsePairs(s.long_takes);
  S.links = parseLinkText(s.shot_links);
  S.notes = parseLinkText(s.kf_notes);
  S.castNotes = parseCastNotes(s.cast_notes);
  S.sceneNotes = parseCastNotes(s.scene_notes);
  S.skip = new Set(String(s.skip_shots || '').split(/[,;，；\s]+/).filter(Boolean));
  S.genders = parseGenders(s.cast_genders);
}
function syncToSettings() {
  const s = S.settings;
  s.cast_picks = composePairs(S.sel.cast);
  s.scene_view_picks = composePairs(S.sel.scene);
  s.kf_picks = composePairs(S.sel.kf);
  s.cast_redo = composePairs(S.redo.cast);
  s.scene_redo = composePairs(S.redo.scene);
  s.kf_redo = composePairs(S.redo.kf);
  s.video_redo = composePairs(S.redo.video);
  s.long_takes = composePairs(S.long);
  s.shot_links = composeLinks(S.links);
  s.kf_notes = composeLinks(S.notes);
  s.cast_notes = composeLinks(S.castNotes);
  s.scene_notes = composeLinks(S.sceneNotes);
  s.skip_shots = [...S.skip].join(', ');
  s.cast_genders = Object.entries(S.genders).filter(([, v]) => v === 'female' || v === 'male')
    .map(([k, v]) => `${k}:${v}`).join(', ');
}

/* ── network ────────────────────────────────────────────────────────────── */
async function api(path, body) {
  const opt = body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
  try {
    const r = await fetch(path, opt);
    let data = {};
    try { data = await r.json(); } catch (e) { data = { error: `服务器返回了意外内容（${r.status}）` }; }
    if (!r.ok && !data.error) data.error = `请求失败（${r.status}）`;
    return data;
  } catch (e) {
    const detail = e && e.message ? `：${e.message}` : '';
    return { error: `网络请求失败${detail}。请检查服务连接后重试。`, network_error: true };
  }
}
function saveSettingsSoon() {
  syncToSettings();
  clearTimeout(S.saveTimer);
  S.saveTimer = setTimeout(() => {
    api('/afe/api/settings', { project: S.project, settings: S.settings }).then(v => {
      if (v.error) showError(`设置保存失败：${v.error}`, '当前页面的设置仍保留。连接恢复后再次修改设置即可重试。');
    });
  }, 400);
}

function restorePersistedAnalysisRun(view) {
  const p = view && view.analysis_progress;
  // A claim is persisted before /prompt returns. Keep that state visible after
  // a reload so the customer can cancel/release it instead of losing access.
  const batch = p && (p.batches || []).find(b => b.status === 'running');
  if (!batch) return null;
  const promptId = batch.prompt_id ? String(batch.prompt_id) : null;
  const sameBatch = S.run && S.run.stage === 1
    && ((S.run.batchIndex === Number(batch.batch_index) && S.run.promptId === promptId)
      || (promptId && S.run.promptId === promptId));
  if (sameBatch) return null;
  S.run = {
    stage: 1,
    batchIndex: Number(batch.batch_index),
    promptId,
    labels: { '1': `分析剧本第${batch.batch_index}批` },
    label: promptId ? `第${batch.batch_index}批已提交，排队中…`
      : `第${batch.batch_index}批正在提交，可取消并恢复…`,
    t0: Date.now(),
    progress: null,
    persisted: true,
    submissionPending: !promptId,
  };
  return S.run;
}
async function loadProject(name, keep = false) {
  const v = await api('/afe/api/project?name=' + encodeURIComponent(name));
  if (v.error) { showError(v.error, '项目状态没有被覆盖。请检查服务连接后重试。'); return false; }
  S.view = v;
  S.project = v.project;
  localStorage.setItem('afe_project', v.project);
  S.settings = v.settings;
  syncFromSettings();
  const restoredRun = restorePersistedAnalysisRun(v);
  $('#projName').value = S.project;
  if (!keep) {
    S.open = {};
    S.open[currentStep()] = true;
  }
  render();
  if (restoredRun && restoredRun.promptId) monitorPrompt(restoredRun, restoredRun.promptId, 1, 'all', true);
  return true;
}

/* ── progress dock + websocket ──────────────────────────────────────────── */
function connectWs() {
  try {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    S.ws = new WebSocket(`${proto}://${location.host}/ws?clientId=${S.clientId}`);
    S.ws.onmessage = ev => {
      if (typeof ev.data !== 'string' || !S.run) return;
      let m; try { m = JSON.parse(ev.data); } catch (e) { return; }
      const d = m.data || {};
      if (d.prompt_id && d.prompt_id !== S.run.promptId) return;
      if (m.type === 'executing' && d.node) {
        S.run.label = S.run.labels[d.node] || S.run.label;
        S.run.progress = null;
      } else if (m.type === 'progress') {
        S.run.progress = { v: d.value, max: d.max };
      }
      renderDock();
    };
    S.ws.onclose = () => setTimeout(connectWs, 3000);
  } catch (e) { /* progress bar just stays indeterminate */ }
}

function renderDock() {
  const dock = $('#dock');
  const msg = $('#dockMsg'), bar = $('#dockBar'), time = $('#dockTime');
  const det = $('#dockDetail'), cancel = $('#dockCancel'), close = $('#dockClose');
  dock.classList.remove('err', 'ok');
  if (S.run) {
    dock.classList.remove('hidden');
    const sec = Math.floor((Date.now() - S.run.t0) / 1000);
    msg.innerHTML = `<b>${esc(S.run.label)}</b>`;
    time.textContent = `已用时 ${String(Math.floor(sec / 60)).padStart(2, '0')}:${String(sec % 60).padStart(2, '0')}`;
    const p = S.run.progress;
    bar.className = 'bar' + (p ? '' : ' indet');
    $('i', bar).style.width = p ? `${Math.round(100 * p.v / p.max)}%` : '';
    cancel.classList.remove('hidden'); close.classList.add('hidden'); det.classList.add('hidden');
  } else if (S.dock) {
    dock.classList.remove('hidden');
    dock.classList.add(S.dock.kind);
    msg.innerHTML = `<b>${esc(S.dock.text)}</b>`;
    time.textContent = '';
    bar.className = 'bar'; $('i', bar).style.width = S.dock.kind === 'ok' ? '100%' : '0';
    cancel.classList.add('hidden'); close.classList.remove('hidden');
    det.textContent = S.dock.detail || ''; det.classList.toggle('hidden', !S.dock.detail);
  } else {
    dock.classList.add('hidden');
  }
}
setInterval(() => { if (S.run) renderDock(); }, 1000);
const showError = (text, detail) => { S.dock = { kind: 'err', text, detail }; renderDock(); };
const showOk = text => { S.dock = { kind: 'ok', text }; renderDock(); };

/* ── running a step ─────────────────────────────────────────────────────── */
async function monitorPrompt(run, pid, stage = 1, part = 'all', restored = false) {
  let missing = 0, down = 0, lost = '';
  while (S.run === run) {
    await sleep(1500);
    let h = null;
    try { h = await (await fetch('/history/' + encodeURIComponent(pid))).json(); down = 0; } catch (e) {
      // ComfyUI may be restarting. Do not mark a task lost while its API is down.
      if (++down >= 8) { lost = '连接不上 ComfyUI（可能正在重启）。'; break; }
      continue;
    }
    if (h && h[pid]) break;
    try {
      const q = await (await fetch('/queue')).json();
      const live = [...(q.queue_running || []), ...(q.queue_pending || [])]
        .some(it => it && String(it[1]) === String(pid));
      missing = live ? 0 : missing + 1;
    } catch (e) { /* retry on the next round */ }
    if (missing >= 4) {
      try { h = await (await fetch('/history/' + encodeURIComponent(pid))).json(); } catch (e) { h = null; }
      if (h && h[pid]) break;
      lost = '任务被中断了。';
      break;
    }
  }
  if (S.run !== run) return;
  if (lost) {
    // The server checks the persisted prompt against both history and queue,
    // then atomically releases only this batch. Completed batches remain safe.
    const recovery = stage === 1
      ? await api('/afe/api/analysis/recover', { project: S.project, prompt_id: pid })
      : {};
    S.run = null;
    await loadProject(S.project, true);
    const detail = recovery.error && !recovery.network_error
      ? recovery.error
      : '已经完成的批次都保留着，请重新点击这一步的按钮，会接着做。';
    showError(lost + '这通常是因为 ComfyUI 被重启了（比如刚更新过）。' + detail);
    return;
  }
  run.label = '正在整理结果…'; renderDock();
  const c = await api('/afe/api/collect', { project: S.project, stage, part, prompt_id: pid });
  S.run = null;
  await loadProject(S.project, true);
  if (c.ok) {
    S.open[stage] = true;
    if (c.partial) {
      render();
      const p = S.view && S.view.analysis_progress;
      const failed = p && (p.failed_batches || []).length;
      if (p && !failed && p.analysis_status !== 'complete') {
        showOk(`这一镜已保存（${p.completed_shot_count || 0}/${p.target_shot_count || 0}），继续下一镜…`);
        return runStage(1);
      }
      showOk('这一镜已保存。失败的镜头请点「重试这一镜」。');
      return;
    }
    if (stage < 5) S.open[stage + 1] = true;
    render();
    showOk(part === 'cast' ? '角色已重画完成，请在上面重新挑选'
      : part === 'scene' ? '这一处场景已重画，其他场景没有动'
      : part === 'kf' ? '这一张首帧已重画，其他分镜没有动'
      : `「${STEPS[stage - 1].title}」完成` + (stage < 5 ? `，可以进行下一步 ${STEPS[stage].verb}` : '，成片已生成'));
  } else if (c.cancelled) {
    S.dock = { kind: 'ok', text: c.error }; renderDock();
  } else {
    showError(c.error || '运行失败', c.details);
  }
}

async function runStage(stage, part = 'all', onlyShot = '') {
  if (S.run) return;
  syncToSettings();
  S.dock = null;
  S.run = { stage, promptId: null, labels: {}, label: '正在提交…', t0: Date.now(), progress: null };
  renderDock(); render();
  const run = S.run;
  const r = await api('/afe/api/run', {
    project: S.project, stage, part, only_shot: onlyShot, client_id: S.clientId, settings: S.settings,
  });
  if (r.error) {
    S.run = null;
    if (stage === 1) await loadProject(S.project, true);
    render();
    showError(r.error, r.details);
    return;
  }
  if (r.submission_pending) {
    S.run = null;
    await loadProject(S.project, true);
    showOk('当前批次正在提交，请稍后点击“继续分析”。');
    return;
  }
  if (r.complete) { S.run = null; await loadProject(S.project, true); showOk('剧本分析已完成，可以进行下一步'); return; }
  run.promptId = r.prompt_id; run.batchIndex = r.batch && Number(r.batch.batch_index) || null;
  run.labels = r.labels || {}; run.label = '已提交，排队中…';
  renderDock();
  return monitorPrompt(run, r.prompt_id, stage, part);
}
async function cancelRun() {
  const running = (S.view && S.view.analysis_progress && S.view.analysis_progress.batches || [])
    .find(b => b.status === 'running');
  const persisted = running && running.prompt_id ? running : null;
  const promptId = (S.run && S.run.promptId) || (persisted && String(persisted.prompt_id)) || '';
  const stage = (S.run && S.run.stage) || (running ? 1 : null);
  if (!stage) return;
  const r = await api('/afe/api/cancel', {
    project: S.project, stage, prompt_id: promptId,
  });
  if (r.error) {
    S.run = null;
    await loadProject(S.project, true);
    render();
    showError(`取消请求失败：${r.error}`, '已保留项目中已保存的结果。连接恢复后可以重新点击当前步骤继续。');
    return;
  }
  S.run = null;
  await loadProject(S.project, true);
  render();
  showOk('已取消当前任务。已完成批次已保留，可以继续分析。');
}

/* ── what is stale? (choices changed after a step was produced) ─────────── */
const norm = t => JSON.stringify(Object.entries(parsePairs(t)).filter(([, v]) => v).sort());
function changedSince(keys, used) {
  if (!used) return false;                       // projects from before this feature: don't guess
  return keys.some(k => (k === 'kf_variants' || k === 'shot_links')
    ? String(S.settings[k] || '') !== String((used[k] ?? ''))
    : norm(S.settings[k]) !== norm(used[k]));
}
function staleList() {
  const v = S.view; if (!v) return [];
  const d = v.done || {}, u = v.used || {}, out = [];
  const refsChanged = k => u[k] && 'refs' in u[k] && (u[k].refs || '') !== (v.ref_sig || '');
  if (d['2'] && refsChanged('2'))
    out.push({ stage: 2, text: '你上传或更换了参考图，场景和角色需要按新的参考图重画（没变的不会重画）。' });
  if (d['3'] && (refsChanged('3') || changedSince(['cast_picks', 'cast_redo', 'scene_redo', 'scene_view_picks', 'kf_picks', 'kf_variants', 'shot_links'], u['3'])))
    out.push({ stage: 3, text: '你更换了参考图、角色、场景、首帧或衔接提示词。首帧需要更新（只会重画受影响的分镜）。' });
  if (d['4'] && (Number(d['3']) > Number(d['4']) || changedSince(['video_redo', 'long_takes', 'shot_links'], u['4'])))
    out.push({ stage: 4, text: '首帧、时长或衔接提示词有变化，视频需要更新（只会重新渲染受影响的分镜）。' });
  if (d['5'] && (Number(d['4']) > Number(d['5']) || changedSince(['skip_shots'], u['5'])))
    out.push({ stage: 5, text: '视频有变化，成片需要重新合成。' });
  return out;
}

function renderSide() {
  const v = S.view, a = v.analysis, as = v.assets;
  let h = '<div class="side-card"><h3>📌 已选用的素材</h3><p class="mini">后面的步骤会使用这里显示的图片。在左边点图片即可更换，这里会马上跟着变。</p>';
  if (a && as) {
    h += '<h4>场景地点参考</h4>';
    (a.scenes || []).forEach((sc, i) => {
      const cur = S.sel.scene[i + 1] || 1, [key, vname] = VIEWS[cur - 1] || VIEWS[0];
      const url = (as.scene_images[key] || [])[i];
      if (url) h += `<div class="sel"><img src="${esc(url)}" alt=""><span><b>场景 ${i + 1}</b> ${esc(sc.scene_name)}<br><small>${vname}</small></span></div>`;
    });
    h += '<h4>角色形象</h4>';
    (a.cast || []).forEach((c, j) => {
      const imgs = (v.cast_images || []).filter(x => x.char === j + 1);
      const cur = S.sel.cast[j + 1] || (imgs.find(x => x.chosen) || {}).variant || 1;
      const it = imgs.find(x => x.variant === cur) || imgs[0];
      if (it) h += `<div class="sel"><img src="${esc(it.url)}" alt="" class="tall"><span><b>${esc(c.name)}</b><br><small>${it.source === 'upload' ? '你的原图' : '版本 ' + it.variant}</small></span></div>`;
    });
  } else {
    h += '<p class="mini">还没有素材。完成第 ② 步后，这里会显示你选用的图。</p>';
  }
  const nKf = ((a && a.shots) || []).filter(x => v.keyframes[x.id]).length;
  if (nKf) h += `<h4>首帧</h4><p class="mini">已有 ${nKf} 个分镜首帧。视频使用每个分镜当前选用的版本。</p>`;
  const stale = staleList();
  if (stale.length) {
    h += `<div class="stale"><b>⚠ 需要更新</b>${stale.map(s => `<p>${esc(s.text)}</p>`).join('')}
      <button class="primary small" data-act="run" data-stage="${stale[0].stage}" ${S.run ? 'disabled' : ''}>现在更新：${STEPS[stage0(stale)].verb}</button></div>`;
  } else if (done(3)) {
    h += '<div class="fresh">✓ 已生成的内容都是按你当前的选择做的</div>';
  }
  $('#side').innerHTML = h + '</div>';
}
const stage0 = stale => stale[0].stage - 1;

/* ── rendering ──────────────────────────────────────────────────────────── */
const done = n => !!(S.view && S.view.done && S.view.done[String(n)]);
function currentStep() { for (let n = 1; n <= 5; n++) if (!done(n)) return n; return 5; }
const prereqOk = n => n === 1 || (S.view && S.view.has_analysis && (n === 2 || done(n - 1) || n <= currentStep()));

function render() {
  if (!S.view) return;
  renderBanner(); renderStepper(); renderSide();
  const html = [renderStep1(), renderStep2(), renderStep3(), renderStep4(), renderStep5()].join('');
  const keepScroll = window.scrollY;
  const ta = document.activeElement && document.activeElement.tagName === 'TEXTAREA';
  if (!ta) { $('#steps').innerHTML = html; window.scrollTo(0, keepScroll); }
  $('#projList').innerHTML = (S.opts.projects || []).map(p => `<option value="${esc(p)}">`).join('');
}

function renderBanner() {
  const s = S.settings;
  $('#banner').innerHTML = s.test_mode
    ? `<div class="banner test"><div class="grow"><b>🧪 试跑模式已开启</b>：③④⑤ 步只处理前 <input type="number" min="1" max="50" style="width:70px" data-set="test_shots" data-type="int" value="${esc(s.test_shots)}"> 个分镜，用来快速检查画面和效果，节省时间。<br>确认效果没问题后，关闭试跑，再重新点击 ③ ④ ⑤ 生成完整影片（已画好的内容不会重做）。</div>
       <label class="switch"><input type="checkbox" data-set="test_mode" data-type="bool" checked> 试跑模式</label></div>`
    : `<div class="banner live"><div class="grow"><b>🎞 完整影片模式</b>：③④⑤ 步会处理剧本里的全部分镜，耗时较长。</div>
       <label class="switch"><input type="checkbox" data-set="test_mode" data-type="bool"> 试跑模式</label></div>`;
}

function renderStepper() {
  const cur = currentStep();
  const staleSet = new Set(staleList().map(s => s.stage));
  $('#stepper').innerHTML = STEPS.map(st => {
    const busy = S.run && S.run.stage === st.n;
    const stale = staleSet.has(st.n);
    const cls = busy ? 'busy' : stale ? 'stale' : done(st.n) ? 'done' : st.n === cur ? 'cur' : '';
    const status = busy ? '进行中…' : stale ? '⚠ 需要更新' : done(st.n) ? '已完成' : st.n === cur ? '轮到这一步' : '未开始';
    return `<button class="step-chip ${cls}" data-act="goto" data-step="${st.n}"><span class="n">${done(st.n) && !busy ? '✓' : st.n}</span>
      <span><span class="t">${st.title}</span><br><span class="s">${status}</span></span></button>`;
  }).join('');
}

function card(n, title, bodyHtml) {
  const isOpen = !!S.open[n];
  const tag = S.run && S.run.stage === n ? '<span class="tag">进行中…</span>' : done(n) ? '<span class="tag ok">已完成</span>' : '';
  return `<section class="card ${isOpen ? '' : 'closed'}" data-step="${n}">
    <div class="head" data-act="toggle" data-step="${n}"><h2>${STEPS[n - 1].verb.slice(0, 1)} ${title}</h2>${tag}<span>${isOpen ? '▲' : '▼'}</span></div>
    <div class="body">${bodyHtml}</div></section>`;
}
const runBtn = n => `<button class="primary" data-act="run" data-stage="${n}" ${(S.run || !prereqOk(n)) ? 'disabled' : ''}>${STEPS[n - 1].verb}</button>`;
const opt = (v, t, cur) => `<option value="${esc(v)}" ${String(v) === String(cur) ? 'selected' : ''}>${esc(t)}</option>`;

function shotJobLabel(b) {
  if (b && Number(b.shot_start) && Number(b.shot_start) === Number(b.shot_end)) return `镜头 ${b.shot_start}`;
  return `第${b.batch_index}批（镜头${b.shot_start}-${b.shot_end}）`;
}
function renderAnalysisProgress() {
  const p = S.view.analysis_progress;
  if (!p || p.analysis_status === 'none') return '';
  const oneByOne = Number(p.batch_size) === 1;
  const current = p.current_batch ? (oneByOne ? `正在分析镜头 ${p.current_batch}` : `第 ${p.current_batch} 批`)
    : (p.failed_batches || []).length ? '等待重试' : '等待继续';
  const completed = `${p.completed_shot_count || 0}/${p.target_shot_count || 0}`;
  const failed = (p.batches || []).filter(b => b.status === 'failed');
  const chips = oneByOne ? '' : `<div class="batch-list">${(p.batches || []).map(b => `<span class="batch-chip ${esc(b.status)}">第${b.batch_index}批 ${b.status === 'completed' ? '✓' : b.status === 'failed' ? '失败' : b.status === 'running' ? '运行中' : '待处理'}</span>`).join('')}</div>`;
  return `<div class="batch-progress"><div class="batch-head"><b>${esc(current)}</b><span>已完成镜头 ${completed}</span></div>
    ${chips}
    ${failed.map(b => `<div class="batch-error">${esc(shotJobLabel(b))}：${esc(b.error || '未知错误')} <button class="small" data-act="retry-batch" data-batch="${b.batch_index}" ${S.run ? 'disabled' : ''}>重试这一镜</button></div>`).join('')}
    <div class="row batch-actions"><button class="primary small" data-act="continue-analysis" ${S.run || p.analysis_status === 'complete' ? 'disabled' : ''}>${oneByOne ? '继续下一镜' : '继续分析'}</button>
      <button class="small" data-act="cancel-analysis" ${S.run ? '' : 'disabled'}>${S.run && S.run.submissionPending ? '取消提交并恢复' : '取消'}</button></div></div>`;
}
function shotEditors(shots) {
  if (!shots || !shots.length) return '';
  return `<h3 style="margin:18px 0 0">每镜衔接</h3>
    <div class="note">分析已经按剧本把同一机位收尾相连：下一镜从上一镜的最后一秒接着画。换了机位的镜头用自己的首帧开口。下面的衔接提示词是额外的一句，留空就按分析结果画。</div>
    <div class="shot-editors">${shots.map(x => `<div class="shot-edit">
      <div class="id">${esc(x.id)} <span class="meta">${esc(x.scene || '')}</span></div>
      ${x.continuity ? `<div class="meta">${esc(x.continuity_note || (x.continuity === 'continue' ? '接上一镜的最后一秒' : '新机位，从这一镜首帧开口'))}</div>` : ''}
      <label>时长 <input type="number" min="3" max="120" data-long="${esc(x.id)}" value="${esc(S.long[x.id] || '')}" placeholder="${esc(x.duration || S.settings.seconds_per_shot)}" style="width:70px"> 秒</label>
      <label class="link-label">衔接提示词<textarea data-link="${esc(x.id)}" rows="2" placeholder="接上一镜，镜头怎么走，这一镜持续做什么">${esc(S.links[x.id] || '')}</textarea></label>
    </div>`).join('')}</div>`;
}
/* step 1 — script */
function renderStep1() {
  const s = S.settings, a = S.view.analysis;
  let result = renderAnalysisProgress();
  if (S.view.stale_analysis) {
    result = `<div class="batch-error stale-analysis">${esc(S.view.stale_analysis_message || '旧剧本分析已隐藏，请继续当前剧本的分析。')}</div>` + result;
  }
  if (a) {
    const shots = a.shots || [];
    const chips = `<div class="chips"><span class="chip">🎬 ${shots.length} 个分镜</span><span class="chip">🏞 ${(a.scenes || []).length} 个场景</span>
      <span class="chip">👥 ${(a.cast || []).length} 个角色</span><span class="chip">🔧 ${(a.props || []).length} 件道具</span></div>`;
    const tabs = [['shots', '分镜表'], ['cast', '角色'], ['scenes', '场景'], ['props', '道具']];
    let tbl = '';
    if (S.tab === 'shots') {
      tbl = `<table><tr><th>编号</th><th>场景 / 段落</th><th>角色</th><th>表情 / 微表情</th><th>动作起始 / 过程 / 结束</th><th>道具互动</th><th>运镜 / 节奏</th><th>对白</th></tr>${shots.map(x =>
        `<tr><td>${esc(x.id)}</td><td>${esc(x.scene)}<br><small>${esc(x.scene_id || '')} · ${esc(x.section_type || '')}</small></td><td>${esc((x.chars || []).join('、'))}</td>
        <td>${esc(x.expression || '')}<br><small>${esc(x.micro_expression || '')}</small></td>
        <td>${esc(x.action_start || '')}<br>${esc(x.action_process || '')}<br>${esc(x.action_end || '')}</td>
        <td>${esc((x.props || []).join('、'))}<br><small>${esc((x.prop_interactions || []).join('、'))}</small></td>
        <td>${esc(x.camera_motion || '')} · ${esc(x.pace || '')}</td><td>${esc(x.dialogue && x.dialogue !== '（无）' ? x.dialogue : '')}</td></tr>`).join('')}</table>`;
    } else if (S.tab === 'cast') {
      tbl = `<table><tr><th>角色</th><th>类型</th><th>外貌（AI 据此画形象）</th></tr>${(a.cast || []).map(c =>
        `<tr><td>${esc(c.name)}</td><td>${esc(c.role)} ${esc(c.gender)}</td><td>${esc(c.look)}</td></tr>`).join('')}</table>`;
    } else if (S.tab === 'scenes') {
      tbl = `<table><tr><th>场景 ID / 段落</th><th>镜头数</th><th>时间 / 天气 / 光源</th><th>空场景环境描述（AI 据此画场景）</th></tr>${(a.scenes || []).map(c =>
        `<tr><td>${esc(c.scene_name)}<br><small>${esc(c.scene_id || '')} · ${esc(c.section_type || '')}</small></td><td>${(c.shot_appearances || []).length}</td>
        <td>${esc(c.time_of_day || '')} / ${esc(c.weather || '')} / ${esc(c.lighting_style || '')}</td><td>${esc(c.environment_prompt_en)}</td></tr>`).join('')}</table>`;
    } else {
      tbl = `<table><tr><th>道具</th><th>出现分镜</th></tr>${(a.props || []).map(c =>
        `<tr><td>${esc(c.name || c.prop_name)}</td><td>${esc((c.shot_appearances || c.appears_in_shots || []).join(', '))}</td></tr>`).join('')}</table>`;
    }
    result += `<h3 style="margin:18px 0 0">分析结果</h3>${chips}
      <div class="tabs">${tabs.map(([k, t]) => `<button class="${S.tab === k ? 'on' : ''}" data-act="tab" data-tab="${k}">${t}</button>`).join('')}</div>
      <div class="table-wrap">${tbl}</div>
      ${shotEditors(shots)}
      <div class="note">请对照剧本检查场景数量、角色外貌是否正确。有误就修改剧本后重新点「分析剧本」。重新分析会让后面的步骤重新来过。</div>`;
  }
  return card(1, '剧本', `
    ${result}
    <p class="help">把完整剧本粘贴到下面。AI 会把它拆成一个个分镜，并整理出场景、角色和道具。</p>
    <textarea data-set="script" placeholder="在这里粘贴剧本…">${esc(s.script)}</textarea>
    <div class="row">
      <div class="field"><label>画风</label><select data-set="style">${(S.opts.styles || []).map(x => opt(x, x, s.style)).join('')}</select></div>
      <div class="field"><label>影片总时长（秒）</label><input type="number" min="30" max="3600" data-set="duration" data-type="int" value="${esc(s.duration)}"></div>
      <div class="field"><label>每个分镜（秒）</label><input type="number" min="5" max="60" data-set="seconds_per_shot" data-type="int" value="${esc(s.seconds_per_shot)}"></div>
      ${runBtn(1)}
    </div>
    <div class="note">剧本里写了「镜头 001（3 秒）」这种标题时，镜数和每镜时长以标题为准，不再用总时长除以每个分镜的秒数。没有标题时，才用那两个数字来切。现在逐镜分析：一镜完成会自动开始下一镜。失败的镜头再点「分析剧本」会重跑这一镜。第一次要载入语言模型，需要几分钟。</div>
    `);
}

/* step 2 ─ assets */
function renderStep2() {
  const s = S.settings, v = S.view, a = v.analysis, as = v.assets;
  let result = '';
  if (as && a) {
    const scenes = (a.scenes || []).map((sc, i) => {
      const cur = S.sel.scene[i + 1] || 1;
      return `<div class="group"><h3>场景 ${i + 1}：${esc(sc.scene_name)} <small style="color:var(--muted);font-weight:400">选一张作为这个场景所有镜头的地点参考</small> <label class="cast-note">修改意见<textarea data-scene-note="${esc(sc.scene_name)}" rows="2" placeholder="例如：夜间湿漉漉的马路，路边只有一个橙色外卖箱，不要画超市货架">${esc(S.sceneNotes[sc.scene_name] || '')}</textarea></label> <button class="small" data-act="redo-scene" data-scene="${i + 1}" ${S.run ? 'disabled' : ''}>🔄 不满意，重画这个场景</button></h3>
        <div class="gallery scenes">${VIEWS.map(([key, name], vi) => {
          const url = (as.scene_images[key] || [])[i];
          return url ? `<label class="pick ${cur === vi + 1 ? 'on' : ''}"><input type="radio" name="scene${i}" data-sel="scene" data-id="${i + 1}" data-val="${vi + 1}" ${cur === vi + 1 ? 'checked' : ''}>
            <img src="${esc(url)}" loading="lazy"><div class="cap">${name}</div></label>` : '';
        }).join('')}</div></div>`;
    }).join('');
    const cast = (a.cast || []).map((c, j) => {
      const imgs = (v.cast_images || []).filter(x => x.char === j + 1);
      const cur = S.sel.cast[j + 1] || (imgs.find(x => x.chosen) || {}).variant || 1;
      return `<div class="group"><h3>角色：${esc(c.name)} ${genderSelect(c.name, c.gender)} <label class="cast-note">修改意见<textarea data-cast-note="${esc(c.name)}" rows="2" placeholder="例如：成年女人，黑发扎在脑后，浅米色开衫，卡其百褶裙">${esc(S.castNotes[c.name] || '')}</textarea></label> <button class="small" data-act="redo-cast" data-char="${j + 1}" ${S.run ? 'disabled' : ''}>🔄 不满意，重画这个角色</button></h3>
        <div class="gallery">${imgs.map(x => `<label class="pick ${cur === x.variant ? 'on' : ''}"><input type="radio" name="cast${j}" data-sel="cast" data-id="${j + 1}" data-val="${x.variant}" ${cur === x.variant ? 'checked' : ''}>
          <img src="${esc(x.url)}" loading="lazy"><div class="cap">${x.source === 'upload' ? '你的原图' : '版本 ' + x.variant}</div></label>`).join('')}</div></div>`;
    }).join('');
    const props = (as.props_images || []).length ? `<div class="group"><h3>道具白底图</h3><div class="gallery">${as.props_images.map(p =>
      `<div class="pick"><img src="${esc(p.url)}" loading="lazy" style="max-height:130px"><div class="cap">${esc(p.name)}</div></div>`).join('')}</div></div>` : '';
    result = `<h3 style="margin:18px 0 0">请挑选</h3>
      <div class="note">点图片即可选用。角色有原图时，重画以原图的脸、头发和衣服为准，不再套用分析写错的外貌；修改意见是在原图上再改的那一句。场景写下修改意见再点「不满意，重画这个场景」，只重画这一处的三张图。选好后直接进入第 ③ 步。</div>
      ${scenes}${cast}${props}`;
  }
  return card(2, '素材：场景、角色、道具', `
    <p class="help">AI 会为每个场景画 3 张图（全景、中景、氛围），为每个角色画几个版本供你挑选，并画出道具图。</p>
    ${renderRefs()}
    <div class="row">
      <div class="field"><label>每个角色画几个版本</label><input type="number" min="1" max="4" data-set="cast_candidates" data-type="int" value="${esc(s.cast_candidates)}"></div>
      <label class="switch"><input type="checkbox" data-set="make_props" data-type="bool" ${s.make_props ? 'checked' : ''}> 同时画道具图</label>
      ${runBtn(2)}
    </div>${result}`);
}

/* optional reference pictures (uploaded by the user) */
function refRow(kind, name, sub, genderFallback) {
  const url = ((S.view.refs || {})[kind] || {})[name];
  const gender = kind === 'cast' ? genderSelect(name, genderFallback) : '';
  return `<div class="refrow"><div class="thumb">${url ? `<img src="${esc(url)}" alt="">` : '<span>无</span>'}</div>
    <div class="who"><b>${esc(name)}</b><br><small>${esc(sub || '')}</small></div>
    ${gender}
    <label class="upl">📎 ${url ? '更换' : '上传'}参考图<input type="file" accept="image/*" data-ref-kind="${kind}" data-ref-name="${esc(name)}"></label>
    ${url ? `<button class="small ghost" data-act="ref-del" data-kind="${kind}" data-name="${esc(name)}">移除</button>` : ''}</div>`;
}
function renderRefs() {
  const a = S.view.analysis;
  if (!a) {
    return `<details class="refs" open><summary>📎 我有参考图（可选）</summary>
      <p class="help">想让 AI 照着你自己的图来画角色、场景或道具，可以在这里上传参考图；<b>不上传也完全没问题</b>，AI 会根据剧本里的文字描述来画。<br>
      请先完成上面第 ① 步「分析剧本」，分析完成后这里会列出每个角色、场景和道具，你就可以逐个上传。</p></details>`;
  }
  const cast = (a.cast || []).map(c => refRow('cast', c.name, c.look, c.gender)).join('');
  const scenes = (a.scenes || []).map(c => refRow('scene', c.scene_name, c.scene_name_en)).join('');
  const nProps = Object.keys((S.view.refs || {}).prop || {}).length;
  const props = (a.props || []).map(c => refRow('prop', c.name, '')).join('');
  const n = Object.values(S.view.refs || {}).reduce((t, o) => t + Object.keys(o).length, 0);
  return `<details class="refs" open><summary>📎 我有参考图（可选）${n ? `<span class="chip" style="margin-left:8px">已上传 ${n} 张</span>` : ''}</summary>
    <p class="help">有现成的图就上传，AI 会<b>以你的图为准</b>来画，后面的首帧也会按它保持一致；没有就留空，AI 会根据文字描述来画。
    每个角色先选女或男，再点「重画这个角色」，画面会按这个性别画。角色请用正面、清晰、背景干净的图；场景请用没有人的空镜头；道具请用单个物品的图。</p>
    ${cast ? `<h4>角色</h4>${cast}` : ''}${scenes ? `<h4>场景</h4>${scenes}` : ''}
    ${props ? `<details class="props" ${nProps ? 'open' : ''}><summary>道具（${(a.props || []).length} 件，需要时展开）</summary>${props}</details>` : ''}</details>`;
}
async function uploadRef(kind, name, file) {
  if (!file) return;
  const q = `project=${encodeURIComponent(S.project)}&kind=${kind}&name=${encodeURIComponent(name)}`;
  let r;
  try {
    r = await fetch('/afe/api/upload?' + q, {
      method: 'POST', headers: { 'Content-Type': file.type || 'application/octet-stream' }, body: file
    });
  } catch (e) {
    const detail = e && e.message ? `：${e.message}` : '';
    return showError('上传参考图失败', `网络请求失败${detail}。原有选择已保留，请检查服务连接后重试。`);
  }
  let d = {};
  try { d = await r.json(); } catch (e) { d = {}; }
  if (!r.ok || d.error) {
    return showError(d.error || `上传参考图失败（${r.status}）`, '原有选择已保留。请检查图片格式或服务连接后重试。');
  }
  const loaded = await loadProject(S.project, true);
  if (!loaded) return;
  showOk(`已上传「${name}」的参考图` + (done(2) ? '。点右边的「现在更新」让它生效。' : '。点「② 生成素材」时会按它来画。'));
}

/* step 3 ─ keyframes */
function renderStep3() {
  const s = S.settings, v = S.view, a = v.analysis;
  let result = '';
  const shots = ((a && a.shots) || []).filter(x => v.keyframes[x.id]);
  if (shots.length) {
    result = `<h3 style="margin:18px 0 0">首帧（${shots.length} 个）</h3>
      <div class="note">每个分镜的第一帧。在图下写下修改意见，再点「重画」，画面模型会按这句话改这一张，其他分镜不动。画了多个版本的，点下面的小图切换使用哪个。</div>
      <div class="shots">${shots.map(x => {
        const vars = (v.kf_images || []).filter(m => m.shot === x.id);
        const cur = S.sel.kf[x.id] || (vars.find(m => m.chosen) || {}).variant || 1;
        return `<div class="shot"><img src="${esc(v.keyframes[x.id])}" loading="lazy">
          <div class="id">${esc(x.id)} <span class="meta">${esc(x.scene)}</span></div>
          <div class="desc">${esc(x.desc)}</div>
          <label class="kf-note-label">修改意见<textarea class="kf-note" data-kf-note="${esc(x.id)}" rows="2" placeholder="例如：茶杯换成白瓷杯，人物看向镜头">${esc(S.notes[x.id] || '')}</textarea></label>
          ${vars.length > 1 ? `<div class="vars">${vars.map(m => `<label class="pick ${cur === m.variant ? 'on' : ''}"><input type="radio" name="kf${x.id}" data-sel="kf" data-id="${esc(x.id)}" data-val="${m.variant}" ${cur === m.variant ? 'checked' : ''}><img src="${esc(m.url)}" loading="lazy"><div class="cap">v${m.variant}</div></label>`).join('')}</div>` : ''}
          <div class="tools"><button class="small" data-act="redo-kf" data-shot="${esc(x.id)}" ${S.run ? 'disabled' : ''}>🔄 重画</button></div></div>`;
      }).join('')}</div>`;
  }
  return card(3, '首帧：每个分镜的第一帧', `
    <p class="help">用场景图和角色形象，为每个分镜合成第一帧画面，保证人物长相和场景前后一致。</p>
    <div class="row">
      <div class="field"><label>每个分镜画几个版本</label><select data-set="kf_variants" data-type="int">${[1, 2, 3].map(n => opt(n, n + ' 个', s.kf_variants)).join('')}</select></div>
      ${runBtn(3)}
    </div>${result}`);
}

/* step 4 ─ video */
function renderStep4() {
  const s = S.settings, v = S.view, a = v.analysis;
  const size = `${s.video_width}x${s.video_height}`;
  const shots = ((a && a.shots) || []).filter(x => v.clips[x.id]);
  let result = '';
  if (shots.length) {
    result = `<h3 style="margin:18px 0 0">分镜视频（${shots.length} 个）</h3>
      <div class="note">可以直接播放检查。想让某个镜头更长（一镜到底），在「时长」里填秒数后重新点「④ 渲染视频」。不满意点「重做」。</div>
      <div class="shots">${shots.map(x => `<div class="shot"><video src="${esc(v.clips[x.id])}" controls preload="metadata"></video>
        <div class="id">${esc(x.id)} <span class="meta">${esc(x.scene)}</span></div>
        <div class="tools">
          <label>时长 <input type="number" min="3" max="120" placeholder="${esc(x.duration || 5)}" style="width:70px" data-long="${esc(x.id)}" value="${esc(S.long[x.id] || '')}"> 秒</label>
          <button class="small" data-act="redo-video" data-shot="${esc(x.id)}" ${S.run ? 'disabled' : ''}>🔄 重做</button>
          <label><input type="checkbox" data-skip="${esc(x.id)}" ${S.skip.has(x.id) ? 'checked' : ''}> 成片不用</label>
        </div></div>`).join('')}</div>`;
  }
  return card(4, '视频：让画面动起来', `
    <p class="help">按剧本往下画。同一机位从上一镜的最后一秒接着画，换机位用这一镜的首帧开口。一镜超过约 5 秒时，后一段也接在这一镜自己的最后一秒上。可以随时点底部的「取消」，已做好的不会丢。</p>
    ${shotEditors((a && a.shots) || [])}
    <div class="row">
      <div class="field"><label>清晰度</label><select data-size="1">${opt('832x480', '标准 832×480（较快）', size)}${opt('1024x576', '较高 1024×576（较慢）', size)}</select></div>
      <label class="switch"><input type="checkbox" data-set="fast" data-type="bool" ${s.fast ? 'checked' : ''}> 快速模式（推荐）</label>
      ${runBtn(4)}
    </div>${result}`);
}

/* step 5 ─ movie */
function renderStep5() {
  const s = S.settings, m = S.view.movie;
  const result = m ? `<h3 style="margin:18px 0 8px">成片</h3><div class="movie"><video src="${esc(m.url)}" controls preload="metadata"></video></div>
    <div class="row"><a href="${esc(m.url)}" download="${esc(m.file)}"><button>⬇ 下载成片</button></a>
    <span class="help" style="margin:0">文件位置：ComfyUI/output/afe_projects/${esc(S.project)}/${esc(m.file)}</span></div>` : '';
  return card(5, '成片：合成完整影片', `
    <p class="help">把所有分镜视频按剧本顺序拼成一部完整影片。在第 ④ 步勾选了「成片不用」的镜头会被排除。</p>
    <div class="row">
      <div class="field"><label>文件名</label><input type="text" data-set="output_name" value="${esc(s.output_name)}"></div>
      ${runBtn(5)}
    </div>${result}`);
}

/* ── events ─────────────────────────────────────────────────────────────── */
document.addEventListener('click', async ev => {
  const el = ev.target.closest('[data-act]');
  if (!el) return;
  const act = el.dataset.act;
  if (act === 'run') return runStage(Number(el.dataset.stage));
  if (act === 'continue-analysis') return runStage(1);
  if (act === 'retry-batch') {
    const r = await api('/afe/api/analysis/retry', { project: S.project, batch_index: Number(el.dataset.batch) });
    if (r.error) return showError('批次重试失败', r.error);
    await loadProject(S.project, true); return runStage(1);
  }
  if (act === 'cancel-analysis') return cancelRun();
  if (act === 'cancel') return cancelRun();
  if (act === 'close-dock') { S.dock = null; return renderDock(); }
  if (act === 'goto' || act === 'toggle') {
    const n = Number(el.dataset.step);
    S.open[n] = act === 'goto' ? true : !S.open[n];
    render();
    if (act === 'goto') document.querySelector(`.card[data-step="${n}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    return;
  }
  if (act === 'tab') { S.tab = el.dataset.tab; return render(); }
  if (act === 'ref-del') {
    const kind = el.dataset.kind, name = el.dataset.name;
    const r = await api('/afe/api/ref/delete', { project: S.project, kind, name });
    if (r.error) {
      return showError(`移除「${name}」的参考图失败`, `${r.error}。原有选择已保留，请检查服务连接后重试。`);
    }
    const loaded = await loadProject(S.project, true);
    if (!loaded) return;
    return showOk(`已移除「${name}」的参考图。点「现在更新」让它生效。`);
  }
  if (act === 'redo-cast') {
    const box = el.closest('.group')?.querySelector('[data-cast-note]');
    if (box) {
      const name = box.dataset.castNote;
      const v = box.value.trim();
      if (v) S.castNotes[name] = v; else delete S.castNotes[name];
    }
    const k = el.dataset.char; S.redo.cast[k] = (S.redo.cast[k] || 0) + 1; saveSettingsSoon(); return runStage(2, 'cast');
  }
  if (act === 'redo-scene') {
    const box = el.closest('.group')?.querySelector('[data-scene-note]');
    if (box) {
      const name = box.dataset.sceneNote;
      const v = box.value.trim();
      if (v) S.sceneNotes[name] = v; else delete S.sceneNotes[name];
    }
    const k = el.dataset.scene; S.redo.scene[k] = (S.redo.scene[k] || 0) + 1; saveSettingsSoon(); return runStage(2, 'scene');
  }
  if (act === 'redo-kf') {
    const k = el.dataset.shot;
    const box = el.closest('.shot')?.querySelector('[data-kf-note]');
    if (box) {
      const v = box.value.trim();
      if (v) S.notes[k] = v; else delete S.notes[k];
    }
    S.redo.kf[k] = (S.redo.kf[k] || 0) + 1; saveSettingsSoon(); return runStage(3, 'kf', k);
  }
  if (act === 'redo-video') {
    const k = el.dataset.shot; S.redo.video[k] = (S.redo.video[k] || 0) + 1; saveSettingsSoon(); return runStage(4);
  }
});

document.addEventListener('change', ev => {
  const el = ev.target;
  if (el.dataset.set) {
    const t = el.dataset.type;
    let val = el.type === 'checkbox' ? el.checked : el.value;
    if (t === 'int') val = parseInt(val, 10) || 0;
    S.settings[el.dataset.set] = val;
    saveSettingsSoon();
    if (el.dataset.set === 'test_mode') render();
  } else if (el.dataset.refKind) {
    uploadRef(el.dataset.refKind, el.dataset.refName, el.files[0]);
    el.value = '';
  } else if (el.dataset.gender) {
    const name = el.dataset.gender;
    if (el.value === 'female' || el.value === 'male') S.genders[name] = el.value;
    else delete S.genders[name];
    saveSettingsSoon();
    render();
  } else if (el.dataset.sel) {
    const kind = el.dataset.sel;
    S.sel[kind][el.dataset.id] = Number(el.dataset.val);
    saveSettingsSoon(); render();
  } else if (el.dataset.size) {
    const [w, h] = el.value.split('x').map(Number);
    S.settings.video_width = w; S.settings.video_height = h; saveSettingsSoon();
  } else if (el.dataset.long) {
    const secs = parseFloat(el.value);
    if (secs > 0) S.long[el.dataset.long] = secs; else delete S.long[el.dataset.long];
    saveSettingsSoon();
  } else if (el.dataset.skip) {
    if (el.checked) S.skip.add(el.dataset.skip); else S.skip.delete(el.dataset.skip);
    saveSettingsSoon();
  }
});
document.addEventListener('input', ev => {
  const el = ev.target;
  if (el.tagName === 'TEXTAREA' && el.dataset.set) { S.settings[el.dataset.set] = el.value; saveSettingsSoon(); }
  if (el.dataset.link) {
    const v = el.value.trim();
    if (v) S.links[el.dataset.link] = v; else delete S.links[el.dataset.link];
    syncToSettings();
    saveSettingsSoon();
  }
  if (el.dataset.kfNote) {
    const v = el.value.trim();
    if (v) S.notes[el.dataset.kfNote] = v; else delete S.notes[el.dataset.kfNote];
    syncToSettings();
    saveSettingsSoon();
  }
  if (el.dataset.castNote) {
    const v = el.value.trim();
    if (v) S.castNotes[el.dataset.castNote] = v; else delete S.castNotes[el.dataset.castNote];
    syncToSettings();
    saveSettingsSoon();
  }
  if (el.dataset.sceneNote) {
    const v = el.value.trim();
    if (v) S.sceneNotes[el.dataset.sceneNote] = v; else delete S.sceneNotes[el.dataset.sceneNote];
    syncToSettings();
    saveSettingsSoon();
  }
});

$('#projOpen').addEventListener('click', () => {
  const name = $('#projName').value.trim() || 'afe_project';
  if (S.run) return;
  loadProject(name);
});

/* ── start ──────────────────────────────────────────────────────────────── */
(async function init() {
  S.opts = await api('/afe/api/options');
  $('#ver').textContent = S.opts.version ? `· 版本 ${S.opts.version}` : '';
  await loadProject(S.project);
  connectWs();
})();

const demo = {
  city: "Seoul",
  cityZh: "首尔",
  currentView: "overview",
  currentPage: 1,
  filter: "all",
  selectedKey: "1:1",
  imported: false,
  uploaded: false,
  processed: false,
  exported: false,
  processing: false,
  pages: [
    {
      page: 1,
      start: 1,
      end: 8,
      pois: [
        ["Namsan Seoul Tower", "南山首尔塔"],
        ["Gyeongbokgung Palace", "景福宫"],
        ["Bukchon Hanok Village", "北村韩屋村"],
        ["Dongdaemun Design Plaza", "东大门设计广场"],
        ["Hongdae Street", "弘大街区"],
        ["Cheonggyecheon Stream", "清溪川"],
        ["Lotte World Tower", "乐天世界塔"],
        ["Starfield Library", "星空图书馆"],
      ],
    },
  ],
  candidates: [],
  records: [],
};

const colors = [
  ["#4d8fe8", "#84d6cf"],
  ["#ef7c64", "#f7c66b"],
  ["#6f7fd9", "#b9a7ff"],
  ["#23a474", "#9bdc7c"],
  ["#d55f8f", "#f2a0b8"],
  ["#1d9bb8", "#77d7f0"],
  ["#8f72d8", "#dac1ff"],
  ["#cc7a2d", "#f0bf72"],
];

const stages = [
  ["imported", "导入表格", "建立城市和 PAGE Prompt"],
  ["prompts", "复制 Prompt", "外部生图前的内容准备"],
  ["uploaded", "上传候选", "为 PAGE 加入多组候选大图"],
  ["processed", "切图处理", "生成每个 POI 的候选切片"],
  ["reviewed", "人工评估", "为全部 POI 选择最终版本"],
  ["exported", "交付导出", "生成最终 PNG 包"],
];

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

function colorVars(index) {
  const pair = colors[index % colors.length];
  return `--c1:${pair[0]};--c2:${pair[1]}`;
}

function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.add("show");
  window.setTimeout(() => node.classList.remove("show"), 1800);
}

function stageState(key) {
  if (key === "prompts") return demo.imported ? "done" : "todo";
  if (key === "reviewed") return reviewedCount() === totalPoi() && demo.processed ? "done" : demo.processed ? "current" : "todo";
  if (key === "exported") return demo.exported ? "done" : reviewedCount() === totalPoi() ? "current" : "todo";
  if (demo[key]) return "done";
  if (key === "imported") return "current";
  if (key === "uploaded" && demo.imported) return "current";
  if (key === "processed" && demo.uploaded) return "current";
  return "todo";
}

function totalPoi() {
  return demo.pages.reduce((sum, page) => sum + page.pois.length, 0);
}

function reviewedCount() {
  return demo.records.filter((record) => record.decision === "accepted").length;
}

function progressValue() {
  const done = stages.filter(([key]) => stageState(key) === "done").length;
  return Math.round((done / stages.length) * 100);
}

function setView(view) {
  demo.currentView = view;
  $$(".view").forEach((node) => node.classList.toggle("active", node.id === view));
  $$(".side-action").forEach((node) => node.classList.toggle("active", node.dataset.view === view));
  const titles = {
    overview: "项目概览",
    prompts: "Prompt 工作台",
    upload: "候选大图",
    process: "切图处理",
    review: "人工评估",
    export: "交付导出",
  };
  $("#page-title").textContent = titles[view] || "Prototype";
  render();
}

function nextStep() {
  if (!demo.imported) {
    $("#import-dialog").showModal();
    return;
  }
  if (!demo.uploaded) {
    setView("upload");
    return;
  }
  if (!demo.processed) {
    setView("process");
    return;
  }
  if (reviewedCount() < totalPoi()) {
    setView("review");
    return;
  }
  setView("export");
}

function resetDemo() {
  demo.imported = false;
  demo.uploaded = false;
  demo.processed = false;
  demo.exported = false;
  demo.processing = false;
  demo.candidates = [];
  demo.records = [];
  demo.selectedKey = "1:1";
  $("#process-log").textContent = "等待候选大图上传...";
  $("#log-status").textContent = "Idle";
  setView("overview");
  toast("演示已重置");
}

function importDemo() {
  demo.imported = true;
  $("#import-dialog").close();
  setView("prompts");
  toast("已建立 Seoul 项目和 PAGE Prompt");
}

function uploadDemo() {
  demo.uploaded = true;
  demo.candidates = [1, 2, 3].map((group) => ({
    id: `p01_g0${group}`,
    page: 1,
    group,
    status: "pending",
  }));
  $("#upload-dialog").close();
  render();
  toast("PAGE 1 已加入 3 组候选");
}

function runProcess() {
  if (!demo.uploaded || demo.processing) return;
  demo.processing = true;
  $("#run-process").disabled = true;
  $("#log-status").textContent = "Running";
  $("#process-log").textContent = [
    "[配置] OCR 去文字：开启",
    `[配置] AI 整图初审：${$("#ai-toggle").checked ? "开启" : "关闭"}`,
    "",
    "[候选切图] PAGE 1 · 组01",
  ].join("\n");

  const steps = [
    "检测 4x4 网格前景区域...",
    "合并图标碎片并按行优先排序...",
    "去除白底并导出透明 PNG...",
    "[候选切图] PAGE 1 · 组02",
    "检测 4x4 网格前景区域...",
    "去除白底并导出透明 PNG...",
    "[候选切图] PAGE 1 · 组03",
    "生成候选清单 candidate_manifest.json...",
    "处理完成：8 个 POI · 24 张候选切片",
  ];

  let index = 0;
  const timer = window.setInterval(() => {
    $("#process-log").textContent += `\n${steps[index]}`;
    $("#process-log").scrollTop = $("#process-log").scrollHeight;
    index += 1;
    if (index === steps.length) {
      window.clearInterval(timer);
      demo.processing = false;
      demo.processed = true;
      demo.candidates = demo.candidates.map((candidate) => ({ ...candidate, status: "processed" }));
      demo.records = demo.pages[0].pois.map(([name, zh], poiIndex) => ({
        key: `1:${poiIndex + 1}`,
        poi: name,
        poiZh: zh,
        decision: "pending",
        note: "",
        selectedCandidate: "",
        candidates: demo.candidates.map((candidate) => ({
          id: candidate.id,
          group: candidate.group,
          quality: candidate.group === ((poiIndex % 3) + 1) ? "推荐" : "可选",
        })),
      }));
      $("#run-process").disabled = false;
      $("#log-status").textContent = "Done";
      setView("review");
      toast("切图完成，进入人工评估");
    }
  }, 360);
}

function selectCandidate(candidateId) {
  const record = demo.records.find((item) => item.key === demo.selectedKey);
  if (!record) return;
  record.selectedCandidate = candidateId;
  record.decision = "accepted";
  record.note = $(".note-box")?.value || record.note;
  render();
  toast("已设为最终候选");
}

function markRedo() {
  const record = demo.records.find((item) => item.key === demo.selectedKey);
  if (!record) return;
  record.selectedCandidate = "";
  record.decision = "redo";
  record.note = $(".note-box")?.value || "需要重新生成";
  render();
  toast("已标记需要重做");
}

function saveNote() {
  const record = demo.records.find((item) => item.key === demo.selectedKey);
  if (!record) return;
  record.note = $(".note-box")?.value || "";
  toast("备注已保存");
}

function exportFinal() {
  if (reviewedCount() < totalPoi()) {
    toast("请先完成全部 POI 选择");
    return;
  }
  demo.exported = true;
  render();
  toast("已生成最终 PNG 包");
}

function render() {
  renderHero();
  renderMetrics();
  renderStages();
  renderPrompt();
  renderCandidates();
  renderProcess();
  renderReview();
  renderExport();
  renderNavigation();
}

function renderHero() {
  $("#hero-title").textContent = demo.imported ? "Seoul 项目正在准备图标交付" : "从一张 POI 表开始生成图标交付包";
  $("#hero-copy").textContent = demo.imported
    ? `${totalPoi()} 个 POI 已生成 PAGE Prompt，继续上传候选大图完成演示流程。`
    : "内置演示数据会贯穿导入、Prompt、候选图、切图、评估和导出。";
  $("#hero-grid").innerHTML = Array.from({ length: 16 }, (_, index) => (
    `<span class="mini-icon" style="${colorVars(index)}"></span>`
  )).join("");
}

function renderMetrics() {
  $("#metric-cities").textContent = demo.imported ? "1" : "0";
  $("#metric-pois").textContent = demo.imported ? String(totalPoi()) : "0";
  $("#metric-candidates").textContent = String(demo.candidates.length);
  $("#metric-selected").textContent = `${reviewedCount()}/${demo.processed ? totalPoi() : 0}`;
}

function renderStages() {
  $("#stage-board").innerHTML = stages.map(([key, title, body], index) => {
    const state = stageState(key);
    const label = state === "done" ? "已完成" : state === "current" ? "进行中" : "待处理";
    return `
      <article class="stage ${state}">
        <span>0${index + 1} · ${label}</span>
        <strong>${title}</strong>
        <small>${body}</small>
      </article>
    `;
  }).join("");
}

function renderPrompt() {
  const page = demo.pages.find((item) => item.page === demo.currentPage) || demo.pages[0];
  $("#prompt-city").textContent = demo.imported ? `${demo.city} / ${demo.cityZh}` : "等待导入";
  $("#page-list").innerHTML = demo.pages.map((item) => `
    <button class="page-button ${item.page === demo.currentPage ? "active" : ""}" data-page="${item.page}">
      <strong>PAGE ${item.page}</strong><br>
      <span>${item.start}-${item.end} · ${item.pois.length} POI</span>
    </button>
  `).join("");
  $$(".page-button").forEach((button) => {
    button.onclick = () => {
      demo.currentPage = Number(button.dataset.page);
      renderPrompt();
    };
  });
  $("#prompt-page-title").textContent = `PAGE ${page.page}`;
  $("#prompt-meta").textContent = `${page.pois.length} POI · 4x4 Sprite Sheet`;
  $("#prompt-text").value = demo.imported ? buildPrompt(page) : "";
}

function buildPrompt(page) {
  const rows = page.pois.map(([name, zh], index) => `${index + 1}. ${name} / ${zh}，matte clay isometric icon, no text, no platform`).join("\n");
  return `CITY: ${demo.city}
PAGE: ${page.page}
LAYOUT: 4x4 Grid Sprite Sheet
STYLE: clean matte clay, isometric, white background

POIS IN ORDER:
${rows}

NEGATIVE:
No text, no logo, no base, no platform, no hard shadow.`;
}

function renderCandidates() {
  const empty = `
    <article class="candidate-card">
      <div class="candidate-sheet">${Array.from({ length: 8 }, (_, index) => `<span class="candidate-cell" style="${colorVars(index)}"></span>`).join("")}</div>
      <div class="candidate-info">
        <div><strong>等待候选上传</strong><br><span class="status-pill">PAGE 1</span></div>
      </div>
    </article>
  `;
  $("#candidate-grid").innerHTML = demo.candidates.length ? demo.candidates.map((candidate) => `
    <article class="candidate-card">
      <div class="candidate-sheet">
        ${Array.from({ length: 8 }, (_, index) => `<span class="candidate-cell" style="${colorVars(index + candidate.group)}"></span>`).join("")}
      </div>
      <div class="candidate-info">
        <div>
          <strong>组 ${String(candidate.group).padStart(2, "0")}</strong><br>
          <span class="status-pill ${candidate.status === "processed" ? "done" : "current"}">${candidate.status === "processed" ? "已切图" : "待切图"}</span>
        </div>
        <small>PAGE ${candidate.page}</small>
      </div>
    </article>
  `).join("") : empty;
}

function renderProcess() {
  $("#process-readiness").textContent = demo.uploaded ? `${demo.candidates.length} 组候选待处理` : "等待候选图";
  $("#run-process").disabled = !demo.uploaded || demo.processing || demo.processed;
}

function renderReview() {
  $("#review-count").textContent = `${reviewedCount()}/${demo.records.length || 0} selected`;
  const rows = demo.records.filter((record) => {
    if (demo.filter === "all") return true;
    return record.decision === demo.filter;
  });

  $("#review-list").innerHTML = rows.length ? rows.map((record, index) => `
    <button class="review-row ${record.key === demo.selectedKey ? "active" : ""}" data-key="${record.key}">
      <span class="review-thumb" style="${colorVars(index)}"></span>
      <span>
        <strong>${record.poi}</strong><br>
        <small>${record.poiZh}</small>
      </span>
      <span class="status-pill ${record.decision}">${decisionLabel(record.decision)}</span>
    </button>
  `).join("") : `<div class="stage"><strong>暂无评估项</strong><small>切图完成后会显示 POI 候选。</small></div>`;

  $$(".review-row").forEach((button) => {
    button.onclick = () => {
      demo.selectedKey = button.dataset.key;
      renderReview();
    };
  });

  const record = demo.records.find((item) => item.key === demo.selectedKey);
  if (!record) {
    $("#review-detail").innerHTML = `<div class="stage"><strong>等待切图结果</strong><small>完成处理后选择 POI 进行评估。</small></div>`;
    return;
  }

  $("#review-detail").innerHTML = `
    <div class="panel-title">
      <span>详情</span>
      <strong>${record.key}</strong>
    </div>
    <h2>${record.poi}</h2>
    <p class="eyebrow">${record.poiZh}</p>
    <div class="detail-preview">
      ${record.candidates.map((candidate, index) => `
        <button class="choice-card ${record.selectedCandidate === candidate.id ? "selected" : ""}" data-candidate="${candidate.id}">
          <span class="choice-art" style="${colorVars(index + candidate.group)}"></span>
          <strong>组 ${String(candidate.group).padStart(2, "0")}</strong>
          <small>${candidate.quality}</small>
        </button>
      `).join("")}
    </div>
    <textarea class="note-box" placeholder="备注">${record.note || ""}</textarea>
    <div class="detail-actions">
      <button class="secondary-button" id="save-note">保存备注</button>
      <button class="secondary-button" id="mark-redo">需要重做</button>
    </div>
  `;
  $$(".choice-card").forEach((button) => {
    button.onclick = () => selectCandidate(button.dataset.candidate);
  });
  $("#save-note").onclick = saveNote;
  $("#mark-redo").onclick = markRedo;
}

function renderExport() {
  const complete = reviewedCount() === totalPoi() && demo.processed;
  $("#export-title").textContent = demo.exported ? "最终图标包已生成" : complete ? "可以导出最终图片" : "等待全部 POI 选择最终候选";
  $("#export-copy").textContent = demo.exported
    ? "演示交付包包含 8 张中英双语命名 PNG。"
    : complete
      ? "全部 POI 已选择最终候选，可以生成交付包。"
      : "完成评估后即可生成中英双语命名的 100px 图标包。";
  $("#export-final").disabled = !complete || demo.exported;
  $("#export-list").innerHTML = demo.exported ? demo.records.map((record) => `
    <div class="export-file">Seoul_首尔_${record.poi.replaceAll(" ", "_")}_${record.poiZh}.png</div>
  `).join("") : "";
}

function renderNavigation() {
  $("#nav-progress").textContent = `${progressValue()}%`;
  $("#side-city").textContent = demo.imported ? demo.city : "None";
  $("#side-status").textContent = demo.exported ? "已导出" : stageStatusText();
  const next = $("#next-step");
  if (!demo.imported) next.textContent = "开始导入";
  else if (!demo.uploaded) next.textContent = "上传候选";
  else if (!demo.processed) next.textContent = "开始切图";
  else if (reviewedCount() < totalPoi()) next.textContent = "继续评估";
  else next.textContent = "查看导出";
}

function stageStatusText() {
  if (!demo.imported) return "等待导入";
  if (!demo.uploaded) return "等待候选图";
  if (!demo.processed) return "等待切图";
  if (reviewedCount() < totalPoi()) return "评估中";
  return "可导出";
}

function decisionLabel(decision) {
  return {
    pending: "待选择",
    accepted: "已选择",
    redo: "需重做",
  }[decision] || "待选择";
}

function bindEvents() {
  $$(".side-action").forEach((button) => {
    button.onclick = () => setView(button.dataset.view);
  });
  $$(".filter").forEach((button) => {
    button.onclick = () => {
      demo.filter = button.dataset.filter;
      $$(".filter").forEach((item) => item.classList.toggle("active", item === button));
      renderReview();
    };
  });
  $("#next-step").onclick = nextStep;
  $("#reset-demo").onclick = resetDemo;
  $("#confirm-import").onclick = importDemo;
  $("#upload-candidate").onclick = () => {
    if (!demo.imported) {
      toast("请先导入 POI 表");
      return;
    }
    $("#upload-dialog").showModal();
  };
  $("#confirm-upload").onclick = uploadDemo;
  $("#run-process").onclick = runProcess;
  $("#export-final").onclick = exportFinal;
  $("#copy-prompt").onclick = async () => {
    if (!$("#prompt-text").value) {
      toast("请先导入项目");
      return;
    }
    await navigator.clipboard.writeText($("#prompt-text").value);
    toast("Prompt 已复制");
  };
}

bindEvents();
render();

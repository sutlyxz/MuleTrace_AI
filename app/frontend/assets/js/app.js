"use strict";

const D = window.MULETRACE_DATA;

const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];

const fmt = value =>
  "฿" + Number(value).toLocaleString("th-TH", {
    maximumFractionDigits: 0
  });

const dateLabel = iso => {
  if (!iso) return "\u2014";
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return String(iso);
  return parsed.toLocaleString("th-TH", {
    dateStyle: "medium",
    timeStyle: "short"
  });
};

let byTime = [...D.transactions].sort(
  (a, b) => String(a.time || "").localeCompare(String(b.time || ""))
);

function refreshTransactions() {
  byTime = [...D.transactions].sort(
    (a, b) => String(a.time || "").localeCompare(String(b.time || ""))
  );
}

const state = {
  page: "overview",
  caseId: D.cases[0].caseId,
  hops: 3,
  replay: byTime.length,
  selectedTx: D.cases[0].transactionId,
  aiText: "",
  aiResult: null,
  aiCaseId: null,
  aiResultsByCase: {},
  isInvestigating: false
};

function syncCaseAiState() {
  const cached = state.aiResultsByCase[state.caseId] || null;
  state.aiResult = cached;
  state.aiCaseId = cached ? state.caseId : null;
  state.aiText = cached ? cleanAgentSummary(cached.summary) : "";

  const progress = $("#agentProgress");
  if (progress) {
    if (state.isInvestigating) {
      progress.textContent = "AI is investigating this case... (Calling Bedrock Converse Tool Use)";
    } else if (cached && cached.status === "completed") {
      progress.textContent = `ตรวจสอบเสร็จแล้ว · เรียกเครื่องมือ ${cached.executed_tools?.length || 0} ครั้ง`;
    } else {
      progress.textContent = "ยังไม่ได้เริ่มตรวจสอบด้วย AI · กด 'Run AI Investigation' เพื่อเริ่มต้น";
    }
  }
}

const currentCase = () =>
  D.cases.find(c => c.caseId === state.caseId) || D.cases[0];

function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}

function put(parent, ...children) {
  parent.replaceChildren(...children);
  return parent;
}

function detailRow(label, value) {
  const div = el("div", undefined, "detail-row");
  div.append(
    el("span", label),
    el("strong", String(value))
  );
  return div;
}

// ==========================================
// NAVIGATION
// ==========================================

function showPage(page) {
  state.page = page;

  $$(".page").forEach(p => {
    p.hidden = p.id !== "page-" + page;
    p.classList.toggle("active", !p.hidden);
  });

  $$(".nav-item").forEach(b => {
    b.classList.toggle(
      "active",
      b.dataset.page === page
    );
  });

  const names = {
    overview: "Overview",
    cases: "Case Queue",
    trail: "Money Trail",
    investigation: "Investigation",
    report: "Outcome & Report"
  };

  $("#pageTitle").textContent = names[page];

  render();

  window.scrollTo({
    top: 0,
    behavior: "smooth"
  });
}

// ==========================================
// NETWORK ANALYSIS — RULE BASED
// ==========================================

function network(seed, maxHops = 3) {
  const depth = { [seed]: 0 };
  const queue = [seed];

  while (queue.length) {
    const account = queue.shift();

    if (depth[account] >= maxHops) continue;

    for (const t of D.transactions) {
      const next =
        t.from === account ? t.to :
        t.to === account ? t.from :
        null;

      if (next && !(next in depth)) {
        depth[next] = depth[account] + 1;
        queue.push(next);
      }
    }
  }

  const nodes = Object.keys(depth);

  const edges = D.transactions.filter(
    t => t.from in depth && t.to in depth
  );

  return { nodes, edges, depth };
}

// ==========================================
// CASE INVESTIGATION — DEMO RULES
// ==========================================

function analyze(c) {
  const n = network(c.target, 3);
  const account = D.accounts[c.target] || {
    name: `Account ${c.target}`,
    status: "flagged",
    openedDays: 12,
    avgAmount: 3200
  };

  const ref = new Date(c.time).getTime();
  const hour = 3600000;

  const isSim = String(c.caseId || "").startsWith("SIM-");

  const inbound = D.transactions.filter(t =>
    t.to === c.target &&
    new Date(t.time).getTime() >= ref - 24 * hour &&
    new Date(t.time).getTime() <= (isSim ? ref + 2 * hour : ref)
  );

  const outbound = D.transactions.filter(t =>
    t.from === c.target &&
    new Date(t.time).getTime() >= (isSim ? ref - 2 * hour : ref) &&
    new Date(t.time).getTime() <= ref + 4 * hour
  );

  const signals = [];
  const maxIn = Math.max(0, ...inbound.map(t => t.amount));

  // Rule 1: บัญชีใหม่และยอดรับสูง
  if (
    account.openedDays <= 30 &&
    maxIn >= Math.max(50000, account.avgAmount * 10)
  ) {
    signals.push({
      type: "new",
      title: "บัญชีใหม่พร้อมยอดรับสูงผิดปกติ",
      detail:
        `เปิดบัญชี ${account.openedDays} วัน · ` +
        `ยอดรับสูงสุด ${fmt(maxIn)} ` +
        `เทียบยอดเฉลี่ย ${fmt(account.avgAmount)}`,
      transactionIds: inbound
        .filter(t => t.amount === maxIn)
        .map(t => t.id)
    });
  }

  // Rule 2: รับเงินจากหลายบัญชี
  const senders = new Set(inbound.map(t => t.from));

  if (senders.size >= 3) {
    signals.push({
      type: "funnel",
      title: "รับเงินจากผู้โอนหลายบัญชี",
      detail:
        `พบผู้โอนเข้าจำนวน ${senders.size} ` +
        `บัญชีในช่วง 24 ชั่วโมงก่อน Alert`,
      transactionIds: inbound.map(t => t.id)
    });
  }

  // Rule 3: โอนเงินต่ออย่างรวดเร็ว
  const large = inbound.filter(
    t => t.amount >= 50000 || (isSim && inbound.length >= 3 && outbound.length >= 1)
  );

  if (large.length) {
    const t0 = Math.min(
      ...large.map(t => new Date(t.time).getTime())
    );

    const quick = outbound.filter(t => {
      const time = new Date(t.time).getTime();
      return time >= t0 && time <= t0 + 90 * 60000;
    });

    if (quick.length) {
      signals.push({
        type: "rapid",
        title: "มีการโอนเงินต่ออย่างรวดเร็ว",
        detail:
          `โอนออก ${fmt(
            quick.reduce((sum, t) => sum + t.amount, 0)
          )} ภายใน 90 นาทีหลังรับเงินก้อนใหญ่`,
        transactionIds: [
          ...large.map(t => t.id),
          ...quick.map(t => t.id)
        ]
      });
    }
  }

  // Rule 4: เชื่อมโยงเคสก่อนหน้า
  const overlaps = D.previousCases
    .map(p => ({
      ...p,
      matched: p.accounts.filter(
        a => n.nodes.includes(a)
      )
    }))
    .filter(p => p.matched.length);

  if (overlaps.length) {
    signals.push({
      type: "cross",
      title: "เครือข่ายเชื่อมโยงเคสก่อนหน้า",
      detail: overlaps.map(
        p => `${p.caseId} ผ่านบัญชี ${p.matched.join(", ")}`
      ).join(" · "),
      transactionIds: n.edges
        .filter(t => overlaps.some(
          p =>
            p.matched.includes(t.from) ||
            p.matched.includes(t.to)
        ))
        .map(t => t.id)
    });
  }

  // Investigation Priority ไม่ใช่ Probability of Guilt
  let score = 10;

  if (c.amount >= 100000) score += 18;
  else if (c.amount >= 50000) score += 10;

  const weights = {
    new: 18,
    funnel: 18,
    rapid: 22,
    cross: 20
  };

  for (const s of signals) {
    score += weights[s.type];
  }

  if (n.nodes.length >= 5) score += 8;

  score = Math.min(100, score);

  const risk =
    score >= 80 ? "HIGH" :
    score >= 55 ? "MEDIUM" : "LOW";

  // บัญชีที่ควรตรวจต่อ
  const next = n.nodes
    .filter(a => a !== c.target)
    .map(id => {
      const p = D.accounts[id] || {
        status: "external"
      };

      const previous = D.previousCases.filter(
        k => k.accounts.includes(id)
      );

      const count = D.transactions.filter(
        t => t.from === id || t.to === id
      ).length;

      const nodeScore =
        (p.status === "flagged" ? 40 :
         p.status === "watch" ? 20 : 0) +
        previous.length * 30 +
        Math.min(count * 3, 15);

      return { id, score: nodeScore };
    })
    .sort((a, b) => b.score - a.score)
    .slice(0, 5);

  return {
    caseId: c.caseId,
    score,
    risk,
    signals,
    overlaps,
    next,
    network: n
  };
}

// ==========================================
// DASHBOARD
// ==========================================

function renderMetrics(a) {
  const data = [
    ["ACTIVE CASES", D.cases.length, "cases"],
    ["TRANSACTIONS", D.transactions.length, "trail"],
    ["LINKED ACCOUNTS", a.network.nodes.length, "trail"],
    ["PRIORITY SCORE", a.score + "/100", "investigation"]
  ];

  put(
    $("#metrics"),
    ...data.map(([name, num, targetPage]) => {
      const box = el("div", undefined, "metric clickable");
      box.style.cursor = "pointer";

      box.append(
        el("small", name),
        el("strong", String(num))
      );

      box.addEventListener("click", () => {
        showPage(targetPage);
      });

      return box;
    })
  );
}

function caseButton(c) {
  const b = el(
    "button",
    undefined,
    "case-row" +
    (state.caseId === c.caseId ? " active" : "")
  );

  const left = el("span");

  left.append(
    el(
      "span",
      `${c.caseId} · ${c.source} → ${c.target}`,
      "case-title"
    ),
    el("span", dateLabel(c.time), "case-desc")
  );

  const right = el("span");

  right.append(
    el("span", fmt(c.amount), "amount"),
    el("span", "View investigation →", "risk")
  );

  b.append(left, right);

  b.addEventListener("click", () => {
    state.caseId = c.caseId;
    state.selectedTx = c.transactionId;
    syncCaseAiState();

    $("#caseSelect").value = c.caseId;

    showPage("investigation");
  });

  return b;
}

function renderOverview(a, c) {
  renderMetrics(a);

  put(
    $("#overviewCases"),
    ...D.cases.map(caseButton)
  );

  put(
    $("#allCases"),
    ...D.cases.map(caseButton)
  );

  $("#overviewRisk").textContent =
    `${a.risk} PRIORITY`;

  const blocks = [
    ["CASE ID", c.caseId, "investigation"],
    ["TARGET ACCOUNT", c.target, "trail"],
    ["AMOUNT", fmt(c.amount), "investigation"],
    ["EVIDENCE SIGNALS", a.signals.length, "report"]
  ];

  put(
    $("#snapshot"),
    ...blocks.map(([name, num, targetPage]) => {
      const div = el(
        "div",
        undefined,
        "snapshot-item clickable"
      );
      div.style.cursor = "pointer";

      div.append(
        el("small", name),
        el("strong", String(num))
      );

      div.addEventListener("click", () => {
        showPage(targetPage);
      });

      return div;
    })
  );
}

// ==========================================
// INTERACTIVE MONEY FLOW GRAPH
// ==========================================

const nodePositions = {
  A001: [125, 72],
  A024: [125, 182],
  X311: [125, 292],
  Y904: [125, 402],
  B782: [410, 225],
  C991: [625, 120],
  D201: [625, 340],
  F002: [775, 225],
  Z120: [775, 35]
};

const SVGNS = "http://www.w3.org/2000/svg";

function svg(tag, attrs = {}) {
  const e = document.createElementNS(SVGNS, tag);

  for (const [key, value] of Object.entries(attrs)) {
    e.setAttribute(key, String(value));
  }

  return e;
}

function pos(id, index, total) {
  if (nodePositions[id]) {
    return nodePositions[id];
  }

  const rad = 2 * Math.PI * index / Math.max(1, total);

  return [
    420 + 300 * Math.cos(rad),
    225 + 170 * Math.sin(rad)
  ];
}

function renderTrail(a, c) {
  const n = network(c.target, state.hops);

  const allowed = new Set(
    byTime.slice(0, state.replay).map(t => t.id)
  );

  const visible = n.edges.filter(
    t => allowed.has(t.id)
  );

  const graph = $("#moneyGraph");
  graph.replaceChildren();

  // ลูกศร
  const defs = svg("defs");

  const marker = svg("marker", {
    id: "arrowTip",
    viewBox: "0 0 10 10",
    refX: 10,
    refY: 5,
    markerWidth: 6,
    markerHeight: 6,
    orient: "auto-start-reverse"
  });

  marker.append(svg("path", {
    d: "M 0 0 L 10 5 L 0 10 z",
    fill: "#b6a18a"
  }));

  defs.append(marker);
  graph.append(defs);

  // วาดเส้นธุรกรรม
  const duplicates = {};

  visible.forEach(t => {
    const key = t.from + ">" + t.to;
    const ordinal = duplicates[key] || 0;
    duplicates[key] = ordinal + 1;

    const [x1, y1] = pos(
      t.from,
      n.nodes.indexOf(t.from),
      n.nodes.length
    );

    const [x2, y2] = pos(
      t.to,
      n.nodes.indexOf(t.to),
      n.nodes.length
    );

    const dx = x2 - x1;
    const dy = y2 - y1;
    const length = Math.hypot(dx, dy) || 1;

    const offset = ordinal * 18;

    const sx = x1 + dx / length * 30;
    const sy = y1 + dy / length * 30;

    const ex = x2 - dx / length * 32;
    const ey = y2 - dy / length * 32;

    const mx =
      (sx + ex) / 2 - dy / length * offset;

    const my =
      (sy + ey) / 2 + dx / length * offset;

    const path = svg("path", {
      d: `M ${sx} ${sy} Q ${mx} ${my} ${ex} ${ey}`,
      fill: "none",
      class:
        "graph-edge" +
        (state.selectedTx === t.id ? " selected" : ""),
      "marker-end": "url(#arrowTip)",
      "data-id": t.id
    });

    const title = svg("title");

    title.textContent =
      `${t.id}: ${t.from} → ${t.to} · ${fmt(t.amount)}`;

    path.append(title);

    path.addEventListener("click", () => {
      state.selectedTx = t.id;
      render();
    });

    graph.append(path);
  });

  // วาดวงกลมบัญชี
  n.nodes.forEach((id, i) => {
    const [x, y] = pos(id, i, n.nodes.length);

    const status = (D.accounts[id] || {}).status;

    const color =
      id === c.target ? "#cfaa78" :
      status === "flagged" ? "#ca7975" :
      status === "watch" ? "#c5a26b" :
      "#86a7aa";

    const group = svg("g");

    const circle = svg("circle", {
      cx: x,
      cy: y,
      r: id === c.target ? 34 : 29,
      fill: "#ffffff",
      stroke: color,
      class: "graph-node"
    });

    const label = svg("text", {
      x,
      y: y + 5,
      "text-anchor": "middle",
      class: "graph-label"
    });

    label.textContent = id;

    group.append(circle, label);

    const title = svg("title");

    title.textContent =
      `${id} · ${status || "unknown"}`;

    group.append(title);

    group.addEventListener("click", () => {
      const tx = visible.find(
        t => t.from === id || t.to === id
      );

      if (tx) {
        state.selectedTx = tx.id;
        render();
      }
    });

    graph.append(group);
  });

  // Time Replay
  $("#replayRange").max = byTime.length;
  $("#replayRange").value = state.replay;

  $("#replayCount").textContent =
    `${state.replay}/${byTime.length} transactions`;

  $("#replayTime").textContent =
    state.replay === 0
      ? "ยังไม่แสดงธุรกรรม"
      : `จนถึง ${dateLabel(byTime[state.replay - 1].time)}`;

  // Transaction Detail
  const selected = D.transactions.find(
    t => t.id === state.selectedTx
  );

  $("#selectedTxTag").textContent =
    selected?.id || "—";

  const detail = $("#transactionDetail");

  if (
    selected &&
    visible.some(t => t.id === selected.id)
  ) {
    put(
      detail,
      detailRow(
        "From → To",
        `${selected.from} → ${selected.to}`
      ),
      detailRow("Amount", fmt(selected.amount)),
      detailRow("Time", dateLabel(selected.time)),
      detailRow("Reference", selected.id)
    );
  } else {
    put(
      detail,
      el(
        "p",
        "ธุรกรรมที่เลือกยังไม่อยู่ในช่วงเวลา / จำนวนทอดที่แสดง",
        "helper"
      )
    );
  }

  // Transaction Table
  const rows = visible
    .slice()
    .sort((a, b) => a.time.localeCompare(b.time))
    .map(t => {
      const tr = el(
        "tr",
        undefined,
        "clickable" +
        (t.id === state.selectedTx ? " selected" : "")
      );

      for (const text of [
        t.id,
        `${t.from} → ${t.to}`,
        fmt(t.amount),
        dateLabel(t.time)
      ]) {
        tr.append(el("td", text));
      }

      tr.addEventListener("click", () => {
        state.selectedTx = t.id;
        render();
      });

      return tr;
    });

  put($("#transactionRows"), ...rows);
}

// ==========================================
// INVESTIGATION WORKSPACE
// ==========================================

function renderInvestigation(a, c) {
  // Case Header
  const heading = $("#investigationHeading");
  if (heading) heading.textContent = `${c.caseId} · ${c.target}`;

  const priorityEl = $("#priorityLabel");
  const riskClass = (c.risk || a.risk || "medium").toLowerCase();
  const alertScoreText = `${c.risk || a.risk} ${c.priorityScore ?? a.score}/100`;
  if (priorityEl) {
    priorityEl.textContent = alertScoreText;
    priorityEl.setAttribute("data-risk", riskClass);
  }

  // Active AI Result for this specific case
  const caseAiResult = (state.aiCaseId === c.caseId) ? state.aiResult : (state.aiResultsByCase[c.caseId] || null);

  const aiAssessmentBadge = $("#invAiAssessmentBadge");
  if (aiAssessmentBadge) {
    if (caseAiResult && caseAiResult.status === "completed") {
      aiAssessmentBadge.textContent = `ASSESSED · ${caseAiResult.executed_tools?.length || 0} TOOLS`;
      aiAssessmentBadge.className = "soft-pill badge-assessed";
    } else if (state.isInvestigating && state.caseId === c.caseId) {
      aiAssessmentBadge.textContent = "INVESTIGATING...";
      aiAssessmentBadge.className = "soft-pill badge-investigating";
    } else {
      aiAssessmentBadge.textContent = "AWAITING AI";
      aiAssessmentBadge.className = "soft-pill";
    }
  }

  // Metadata strip
  const metaSource = $("#invMetaSource");
  if (metaSource) metaSource.textContent = c.source && c.source !== "—" ? c.source : "—";
  const metaTarget = $("#invMetaTarget");
  if (metaTarget) metaTarget.textContent = c.target && c.target !== "—" ? c.target : "—";
  const metaAmount = $("#invMetaAmount");
  if (metaAmount) metaAmount.textContent = fmt(c.amount);
  const metaTime = $("#invMetaTime");
  if (metaTime) metaTime.textContent = dateLabel(c.time);
  const metaStatus = $("#invMetaStatus");
  if (metaStatus) {
    const st = String(c.status || "new").toLowerCase();
    metaStatus.innerHTML = `<span class="status-tag ${st}">${st.toUpperCase()}</span>`;
  }

  // Outcome nav button enablement
  const btnGoOutcome = $("#btnGoOutcome");
  if (btnGoOutcome) {
    btnGoOutcome.disabled = !caseAiResult || caseAiResult.status !== "completed";
  }

  // Preliminary findings
  const findingsEmpty = $("#invFindingsEmpty");
  const findingsContent = $("#invFindingsContent");
  const findingBadge = $("#agentFindingBadge");

  if (caseAiResult && caseAiResult.status === "completed") {
    if (findingsEmpty) findingsEmpty.hidden = true;
    if (findingsContent) {
      findingsContent.hidden = false;
      const cleanText = cleanAgentSummary(caseAiResult.summary);
      const isSim = String(c.caseId || "").startsWith("SIM-");

      const blocks = [];
      const summaryDiv = el("div", undefined, "ai-officer-summary-prose");
      summaryDiv.textContent = cleanText || "Investigation synthesis completed.";
      blocks.push(summaryDiv);

      if (isSim) {
        const simNotice = el("div", undefined, "inv-sim-notice-callout");
        simNotice.innerHTML = `
          <strong>🔍 การตรวจสอบข้อมูลจำลอง (Synthetic Case Notice)</strong>
          <p>ข้อมูลเคสนี้มาจากฐานข้อมูลจำลอง DynamoDB ซึ่งเครื่องมือของ Bedrock Agent ได้เข้าตรวจสอบข้อมูลและประเมินเส้นทางเรียบร้อยแล้ว เนื่องจากเป็นเคสจำลอง ธุรกรรมนี้จึงยังไม่ปรากฏในชุดข้อมูลประวัติศาสตร์ CSV หลัก เจ้าหน้าที่ต้องยืนยันข้อมูลกับระบบงานจริงก่อนดำเนินการอายัดบัญชี</p>
        `;
        blocks.push(simNotice);
      }

      put(findingsContent, ...blocks);
    }
    if (findingBadge) {
      findingBadge.textContent = "AGENT SYNTHESIS";
      findingBadge.className = "soft-pill badge-completed";
    }
  } else {
    if (findingsEmpty) findingsEmpty.hidden = false;
    if (findingsContent) {
      findingsContent.hidden = true;
      findingsContent.replaceChildren();
    }
    if (findingBadge) {
      findingBadge.textContent = state.isInvestigating ? "INVESTIGATING..." : "AWAITING AI";
      findingBadge.className = "soft-pill";
    }
  }

  // Baseline rule-based summary
  const summary = $("#caseSummary");
  if (summary) {
    const wrap = el("div", undefined, `summary-score risk-${riskClass}`);
    wrap.setAttribute("data-risk", riskClass);
    const circle = el("div", String(c.priorityScore ?? a.score), "score-circle");
    circle.setAttribute("data-risk", riskClass);
    wrap.append(circle);

    const txt = el("div", undefined, "summary-score-text");
    txt.append(
      el("strong", `${c.risk || a.risk} alert priority`),
      el("p", `${a.signals.length} evidence signals · ${a.network.nodes.length} linked accounts`, "helper")
    );
    wrap.append(txt);

    const grid = el("div", undefined, "case-metrics-grid");
    grid.append(
      detailRow("Alert source", c.source),
      detailRow("Target", c.target),
      detailRow("Alert amount", fmt(c.amount)),
      detailRow("Alert date", dateLabel(c.time))
    );

    const signalsStrip = el("div", undefined, "investigation-signals-strip");
    if (a.signals && a.signals.length) {
      a.signals.forEach(s => {
        const pill = el("span", s.title, "signal-tag");
        signalsStrip.append(pill);
      });
    }

    put(summary, wrap, grid, signalsStrip);
  }

  // Render real tool execution list
  renderAgentTrace();

  // Recommended Accounts
  const recAccounts = $("#recommendedAccounts");
  if (recAccounts) {
    put(
      recAccounts,
      ...a.next.map(x => {
        const chip = el("button", `${x.id} · ${x.score} points`, "chip clickable rec-account-card");
        chip.type = "button";
        chip.style.cursor = "pointer";
        chip.setAttribute("data-score", x.score);
        if (x.score >= 50) chip.classList.add("rec-high-risk");
        chip.addEventListener("click", () => {
          const linkedTx = D.transactions.find(t => t.from === x.id || t.to === x.id);
          if (linkedTx) state.selectedTx = linkedTx.id;
          state.replay = byTime.length;
          showPage("trail");
        });
        return chip;
      })
    );
  }
}

// ==========================================
// EVIDENCE CHAIN
// ==========================================

function renderEvidence(a) {
  const list = $("#evidenceList");

  put(
    list,
    ...a.signals.map((s, i) => {
      const item = el(
        "article",
        undefined,
        "evidence-item"
      );

      item.append(
        el(
          "h4",
          `${String(i + 1).padStart(2, "0")} · ${s.title}`
        ),
        el("p", s.detail)
      );

      for (const id of [...new Set(s.transactionIds)]) {
        const b = el("button", id, "tx-link");

        b.addEventListener("click", () => {
          state.selectedTx = id;
          state.replay = byTime.length;
          state.hops = 3;

          $("#hopSelect").value = "3";
          showPage("trail");
        });

        item.append(b);
      }

      return item;
    })
  );

  const crossElements = a.overlaps.length
    ? a.overlaps.map(p => {
        const box = el(
          "div",
          undefined,
          "evidence-item"
        );

        box.append(
          el(
            "h4",
            `${p.caseId} · ${p.matched.join(", ")}`
          ),
          el("p", p.summary)
        );

        return box;
      })
    : [
        el(
          "p",
          "ไม่พบเคสที่เชื่อมโยง",
          "helper"
        )
      ];

  put($("#crossCases"), ...crossElements);

  if (state.aiText) {
    $("#aiResult").textContent = state.aiText;
  }
}

// ==========================================
// REPORT GENERATION
// ==========================================

function reportText(a, c) {
  const lines = [
    "MULETRACE AI — INVESTIGATION REPORT",
    "OFFICIAL INVESTIGATION REPORT",
    "================================",
    `Case: ${c.caseId}`,
    `Target: ${c.target}`,
    `Amount: ${fmt(c.amount)}`,
    `Priority: ${a.score}/100 (${a.risk})`,
    "",
    "EVIDENCE CHAIN"
  ];

  a.signals.forEach((s, i) => {
    lines.push(
      `${i + 1}. ${s.title}`,
      s.detail,
      `Transaction IDs: ${s.transactionIds.join(", ") || "none"}`,
      ""
    );
  });

  lines.push(
    "CROSS CASES",
    ...a.overlaps.map(
      p => `${p.caseId}: ${p.matched.join(", ")}`
    ),
    "",
    "NEXT ACCOUNTS",
    ...a.next.map(
      n => `${n.id} — ${n.score} points`
    ),
    "",
    "Human review required.",
    "Priority is not probability of guilt."
  );

  if (state.aiText) {
    lines.push("", "API SUMMARY", state.aiText);
  }

  return lines.join("\n");
}

function download(a, c) {
  const blob = new Blob(
    ["\ufeff", reportText(a, c)],
    { type: "text/plain;charset=utf-8" }
  );

  const url = URL.createObjectURL(blob);

  const link = document.createElement("a");
  link.href = url;
  link.download = `MuleTrace_${c.caseId}.txt`;
  link.click();

  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ==========================================
// AI INVESTIGATION TOOLS & OUTCOME DASHBOARD
// ==========================================

const TOOL_DESCRIPTIONS_EN = {
  get_simulation_case: "Review Alert Details",
  get_account_profile: "Review Account Profile",
  get_transaction_history: "Examine Transaction History",
  detect_risk: "Assess Risk Indicators",
  trace_money: "Trace Money Transfers",
  score_investigation: "Assess Investigation Priority",
  get_evidence: "Review Supporting Evidence",
  find_cross_case_links: "Find Related Cases"
};

const TOOL_DESCRIPTIONS_TH = {
  get_simulation_case: "ตรวจสอบรายละเอียดการแจ้งเตือน",
  get_account_profile: "ตรวจสอบข้อมูลบัญชีผู้ต้องสงสัย",
  get_transaction_history: "ตรวจสอบประวัติการทำธุรกรรม",
  detect_risk: "ประเมินสัญญาณความเสี่ยงทางบัญชี",
  trace_money: "ติดตามเส้นทางการโอนเงินในเครือข่าย",
  score_investigation: "ประเมินลำดับความสำคัญการตรวจสอบ",
  get_evidence: "รวบรวมและตรวจสอบหลักฐานประกอบ",
  find_cross_case_links: "ตรวจสอบความเชื่อมโยงกับเคสอื่น"
};

const TOOL_DESCRIPTIONS = TOOL_DESCRIPTIONS_TH;

function extractToolTarget(input) {
  if (!input || typeof input !== "object") return "";
  if (input.account_id) return `Account ${input.account_id}`;
  if (input.case_id) return `Case ${input.case_id}`;
  if (input.source_account && input.target_account) return `${input.source_account} → ${input.target_account}`;
  if (input.source_account) return `From ${input.source_account}`;
  if (input.target_account) return `To ${input.target_account}`;
  if (input.account) return `Account ${input.account}`;
  return "";
}

function getToolDescription(toolName) {
  const isEn = window.MuleI18N?.getLanguage?.() === "en";
  const dict = isEn ? TOOL_DESCRIPTIONS_EN : TOOL_DESCRIPTIONS_TH;
  if (dict[toolName]) return dict[toolName];
  return String(toolName || "").replace(/_/g, " ").replace(/\b\w/g, l => l.toUpperCase());
}

function cleanAgentSummary(text) {
  return String(text || "")
    .replace(/<thinking>[\s\S]*?<\/thinking>/gi, "")
    .replace(/<response>|<\/response>/gi, "")
    .replace(/<\/?reasoning>/gi, "")
    .replace(/<\/?thought>/gi, "")
    .trim();
}

function renderAgentTrace() {
  const list = $("#toolSteps");
  const detail = $("#agentTrace");
  const badge = $("#agentActivityBadge");
  const toolsEmpty = $("#invToolsEmpty");

  const c = currentCase();
  const data = (state.aiCaseId === c.caseId) ? state.aiResult : (state.aiResultsByCase[c.caseId] || null);
  const calls = Array.isArray(data?.executed_tools) ? data.executed_tools : [];

  if (badge) {
    if (state.isInvestigating && state.caseId === c.caseId) {
      badge.textContent = "INVESTIGATING...";
      badge.className = "soft-pill badge-investigating";
    } else if (data?.status === "completed") {
      badge.textContent = "BEDROCK AGENT · COMPLETED";
      badge.className = "soft-pill badge-completed";
    } else {
      badge.textContent = "AWAITING AI";
      badge.className = "soft-pill";
    }
  }

  if (toolsEmpty) toolsEmpty.hidden = calls.length > 0;

  if (list) {
    if (!calls.length) {
      list.replaceChildren();
    } else {
      const items = calls.map((item, i) => {
        const li = el("li", undefined, "inv-tool-step-item");
        li.setAttribute("data-step", String(i + 1).padStart(2, "0"));

        const head = el("div", undefined, "tool-step-header");
        const titleStrong = el("strong", getToolDescription(item.tool));
        const statusSpan = el(
          "span",
          item.status === "success" ? "Success" : (item.status || "Completed"),
          `tool-status-badge ${item.status === "success" ? "success" : "warning"}`
        );
        head.append(titleStrong, statusSpan);

        const metaDiv = el("div", undefined, "tool-step-meta");
        const turnText = el("span", `Turn ${item.turn || (i + 1)} · Step ${i + 1}`, "tool-turn-tag");
        metaDiv.append(turnText);

        const targetEntity = extractToolTarget(item.input);
        if (targetEntity) {
          const targetTag = el("span", `Target: ${targetEntity}`, "tool-target-pill");
          metaDiv.append(targetTag);
        }

        const techDetails = el("details", undefined, "tool-tech-collapsible");
        const techSummary = el("summary", undefined, "tool-tech-summary");
        techSummary.textContent = `Technical: ${item.tool}`;
        const techPre = el("pre", JSON.stringify({ tool: item.tool, input: item.input, status: item.status }, null, 2));
        techDetails.append(techSummary, techPre);

        li.append(head, metaDiv, techDetails);
        return li;
      });
      put(list, ...items);
    }
  }

  // Telemetry for judges
  const traceModel = $("#traceModelId");
  if (traceModel) traceModel.textContent = data?.model_id || "amazon.nova-micro-v1:0";
  const traceTurns = $("#traceTurnsCount");
  if (traceTurns) traceTurns.textContent = data?.turns_taken ? String(data.turns_taken) : (calls.length ? String(calls.length) : "—");
  const traceTools = $("#traceToolsCount");
  if (traceTools) traceTools.textContent = calls.length ? String(calls.length) : "—";

  if (detail) {
    detail.hidden = !calls.length;
    if (calls.length) {
      const traceRows = calls.map(item => {
        const row = el("div", undefined, "mt-trace-row");
        const strong = el("strong", item.tool);
        const code = el("code", JSON.stringify(item.input || {}));
        const stat = el("span", item.status || "ok", `trace-stat-tag ${item.status === "success" ? "success" : ""}`);
        row.append(strong, code, stat);
        return row;
      });
      put(detail, ...traceRows);
    }
  }
}

function renderOutcomeDashboard(a, c) {
  const caseAiResult = (state.aiCaseId === c.caseId) ? state.aiResult : (state.aiResultsByCase[c.caseId] || null);

  // --- CARD 1: Money Flow Visualization ---
  const flowContainer = $("#outcomeFlowPreview");
  const flowMetrics = $("#outcomeFlowMetrics");
  if (flowContainer) {
    flowContainer.replaceChildren();
    if (c.source && c.target && c.source !== "—" && c.target !== "—") {
      const flowWrap = el("div", undefined, "mini-flow-diagram");

      // Source node
      const srcNode = el("div", undefined, "flow-node source-node");
      srcNode.append(el("span", "SOURCE", "node-type-label"), el("strong", c.source));

      // Arrow & amount
      const arrowWrap = el("div", undefined, "flow-arrow-wrap");
      const amtPill = el("div", fmt(c.amount), "flow-amount-pill");
      const arrowLine = el("div", undefined, "flow-arrow-line");
      const txTag = el("small", c.transactionId || "Transfer Alert", "flow-tx-tag");
      arrowWrap.append(amtPill, arrowLine, txTag);

      // Target node
      const tgtNode = el("div", undefined, "flow-node target-node");
      tgtNode.append(el("span", "TARGET (MULE)", "node-type-label"), el("strong", c.target));

      flowWrap.append(srcNode, arrowWrap, tgtNode);
      flowContainer.append(flowWrap);
    } else {
      const emptyFlow = el("div", undefined, "flow-empty-box");
      emptyFlow.textContent = "No verified transaction flow data available for this case.";
      flowContainer.append(emptyFlow);
    }
  }

  if (flowMetrics) {
    const p1 = el("div", undefined, "metric-pill");
    p1.append(el("small", "ALERT AMOUNT"), el("strong", fmt(c.amount)));
    const p2 = el("div", undefined, "metric-pill");
    p2.append(el("small", "DATE / TIME"), el("strong", dateLabel(c.time)));
    const p3 = el("div", undefined, "metric-pill");
    p3.append(el("small", "NETWORK NODES"), el("strong", `${a.network.nodes.length} Accounts`));
    put(flowMetrics, p1, p2, p3);
  }

  // Wire up view trail button
  const btnTrail = $("#btnOutcomeViewTrail");
  if (btnTrail) {
    btnTrail.onclick = () => {
      state.caseId = c.caseId;
      state.selectedTx = c.transactionId || state.selectedTx;
      state.replay = byTime.length;
      showPage("trail");
    };
  }

  // --- CARD 2: Evidence Chain ---
  const evidenceList = $("#outcomeEvidenceList");
  const evidenceBadge = $("#outcomeEvidenceBadge");
  if (evidenceBadge) evidenceBadge.textContent = `${a.signals.length} SIGNALS`;

  if (evidenceList) {
    evidenceList.replaceChildren();
    if (!a.signals || !a.signals.length) {
      const emptyEv = el("div", undefined, "evidence-empty-box");
      emptyEv.textContent = "No rule-based evidence signals detected for this case.";
      evidenceList.append(emptyEv);
    } else {
      const items = a.signals.map((s, i) => {
        const itemCard = el("div", undefined, "outcome-evidence-item");
        const head = el("div", undefined, "evidence-item-head");
        const numTitle = el("strong", `${String(i + 1).padStart(2, "0")} · ${s.title}`);

        const hasMatch = s.transactionIds && s.transactionIds.some(id => D.transactions.some(t => t.id === id));
        const isSim = String(c.caseId || "").startsWith("SIM-");
        const isVerified = hasMatch && !isSim;

        const badge = el(
          "span",
          isVerified ? "Verified in Network Data" : (isSim ? "Requires Core Verification" : "Verified Signal"),
          `badge-evidence-pill ${isVerified ? "verified" : "unverified"}`
        );
        head.append(numTitle, badge);

        const desc = el("p", s.detail, "evidence-item-desc");
        const txContainer = el("div", undefined, "evidence-item-txs");

        (s.transactionIds || []).forEach(txId => {
          const btn = el("button", `Tx: ${txId}`, "tx-pill-btn");
          btn.type = "button";
          btn.addEventListener("click", () => {
            state.selectedTx = txId;
            state.replay = byTime.length;
            showPage("trail");
          });
          txContainer.append(btn);
        });

        itemCard.append(head, desc, txContainer);
        return itemCard;
      });
      put(evidenceList, ...items);
    }
  }

  // --- CARD 3: AI Investigation Summary ---
  const summaryEmpty = $("#outcomeAiEmpty");
  const summaryText = $("#outcomeAiSummaryText");
  const summaryBadge = $("#outcomeSummaryBadge");
  const oldSummary = $("#outcomeAiSummary");

  if (caseAiResult && caseAiResult.status === "completed") {
    if (summaryEmpty) summaryEmpty.hidden = true;
    if (summaryText) {
      summaryText.hidden = false;
      const clean = cleanAgentSummary(caseAiResult.summary);
      summaryText.textContent = clean || "Investigation completed.";
    }
    if (oldSummary) oldSummary.textContent = cleanAgentSummary(caseAiResult.summary);
    if (summaryBadge) {
      summaryBadge.textContent = "BEDROCK VERIFIED";
      summaryBadge.className = "soft-pill badge-completed";
    }
  } else {
    if (summaryEmpty) summaryEmpty.hidden = false;
    if (summaryText) {
      summaryText.hidden = true;
      summaryText.replaceChildren();
    }
    if (oldSummary) oldSummary.textContent = "กรุณาเริ่ม AI Investigation จากหน้า Investigation ก่อน";
    if (summaryBadge) {
      summaryBadge.textContent = "AWAITING AI";
      summaryBadge.className = "soft-pill";
    }
  }

  // --- CARD 4: Investigation Report ---
  const reportMeta = $("#outcomeReportMetaGrid");
  if (reportMeta) {
    put(
      reportMeta,
      detailRow("Case ID", c.caseId),
      detailRow("Target Account", c.target),
      detailRow("Inbound Account", c.source),
      detailRow("Alert Amount", fmt(c.amount)),
      detailRow("Alert Priority", `${c.risk || a.risk} ${c.priorityScore ?? a.score}/100`),
      detailRow("Investigation Assessment", caseAiResult?.status === "completed" ? "Assessed by AI" : "Pending AI Execution")
    );
  }

  const keyFindings = $("#outcomeKeyFindings");
  if (keyFindings) {
    const findingsList = el("ul", undefined, "report-findings-list");
    findingsList.append(
      el("li", `Target account ${c.target} flagged with ${c.risk || a.risk} priority score (${c.priorityScore ?? a.score}/100).`),
      el("li", `Inbound alert transfer of ${fmt(c.amount)} received from ${c.source}.`),
      el("li", `${a.signals.length} behavioral anomaly signals detected across ${a.network.nodes.length} connected accounts.`),
      caseAiResult?.status === "completed"
        ? el("li", `Bedrock agent executed ${caseAiResult.executed_tools?.length || 0} autonomous investigation tools to analyze network behavior.`)
        : el("li", "Autonomous AI investigation pending execution by bank officer.")
    );
    put(keyFindings, findingsList);
  }

  const nextActions = $("#outcomeNextActions");
  if (nextActions) {
    const actionsList = el("ol", undefined, "report-actions-list");
    if (caseAiResult?.recommended_next_actions && Array.isArray(caseAiResult.recommended_next_actions) && caseAiResult.recommended_next_actions.length) {
      caseAiResult.recommended_next_actions.slice(0, 4).forEach(act => {
        actionsList.append(el("li", `${act} (AI Recommendation)`));
      });
    } else {
      actionsList.append(
        el("li", "ตรวจสอบเอกสารแสดงตน (KYC) และข้อมูลการเปิดบัญชีของบัญชีเป้าหมาย"),
        el("li", "ตรวจสอบพฤติกรรมการโอนเงินต่อเนื่องและ cross-check กับรายชื่อบัญชีม้าในระบบ"),
        el("li", "ติดต่อยืนยันความถูกต้องของคำสั่งโอนเงินกับเจ้าของบัญชีต้นทาง"),
        el("li", "หากพบข้อบ่งชี้การฟอกเงิน ให้ส่งรายงานธุรกรรมมีเหตุอันควรสงสัย (STR) ต่อ ปปง.")
      );
    }
    put(nextActions, actionsList);
  }

  // Download buttons on card
  const btnDownloadCard = $("#btnDownloadReportCard");
  if (btnDownloadCard) {
    btnDownloadCard.onclick = () => download(a, c);
  }
}

async function callAi(a, c) {
  if (state.isInvestigating) return;

  const box = $("#aiResult");
  const button = $("#runAi");
  const progress = $("#agentProgress");
  const spinner = $("#invAgentSpinner");
  const btnGoOutcome = $("#btnGoOutcome");

  if (!c || !c.caseId) {
    if (progress) progress.textContent = "กรุณาเลือกเคสก่อนเริ่มการสืบสวน";
    return;
  }

  let url = window.MULETRACE_CONFIG?.agentApiUrl || "/api/ai/investigate";
  if (url.startsWith("/")) url = window.location.origin + url;
  if (!url.startsWith("https://") && !/^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?\//.test(url)) {
    if (progress) progress.textContent = "ไม่สามารถเชื่อมต่อระบบตรวจสอบได้ (Invalid URL)";
    return;
  }

  const requestedCase = c.caseId;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 90000);

  state.isInvestigating = true;
  if (button) button.disabled = true;
  if (spinner) spinner.hidden = false;
  if (progress) progress.textContent = "AI is investigating this case... (Calling Bedrock Converse Tool Use)";
  if (box) box.textContent = "กำลังตรวจสอบด้วย Bedrock Agent...";

  const actBadge = $("#agentActivityBadge");
  if (actBadge) {
    actBadge.textContent = "INVESTIGATING...";
    actBadge.className = "soft-pill badge-investigating";
  }

  const findBadge = $("#agentFindingBadge");
  if (findBadge) {
    findBadge.textContent = "INVESTIGATING...";
    findBadge.className = "soft-pill badge-investigating";
  }

  try {
    const response = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        case_id: requestedCase,
        language: window.MuleI18N?.getLanguage?.() || "th",
        investigation: {
          case_id: requestedCase,
          source_account: c.source,
          target_account: c.target,
          alert_amount: c.amount,
          alert_time: c.time,
          priority_score: c.priorityScore ?? a.score,
          risk_level: c.risk || a.risk
        }
      }),
      signal: controller.signal,
      cache: "no-store"
    });

    const output = await response.json().catch(() => ({ status: "error", message: "Invalid JSON response" }));

    if (!response.ok || output.status !== "completed") {
      const errMsg = output.status === "content_filtered"
        ? "ไม่สามารถสร้างบทสรุปได้ (Content Filter Triggered) กรุณาลองใหม่อีกครั้ง"
        : (output.message || `การตรวจสอบไม่สำเร็จ (Status: ${output.status || response.status})`);
      throw new Error(errMsg);
    }

    if (typeof output.summary !== "string" || !cleanAgentSummary(output.summary)) {
      throw new Error("ยังไม่ได้รับบทสรุปจากการวิเคราะห์ของ AI");
    }

    // Cache result by case ID so switching cases never leaks stale data
    state.aiResultsByCase[requestedCase] = output;

    // Only update view if the officer is still on the requested case
    if (state.caseId === requestedCase) {
      state.aiCaseId = requestedCase;
      state.aiResult = output;
      state.aiText = cleanAgentSummary(output.summary);

      if (progress) progress.textContent = `ตรวจสอบเสร็จสิ้น · เครื่องมือถูกเลือกใช้จริง ${output.executed_tools?.length || 0} ครั้ง`;
      if (box) box.textContent = state.aiText;
      if ($("#awsStatus")) $("#awsStatus").textContent = "AGENT COMPLETED";

      if (btnGoOutcome) btnGoOutcome.disabled = false;

      renderInvestigation(a, c);
      renderOutcomeDashboard(a, c);
    }
  } catch (error) {
    if (state.caseId === requestedCase) {
      const isTimeout = error.name === "AbortError";
      const displayErr = isTimeout ? "การเชื่อมต่อหมดเวลา (Request Timeout 90s) กรุณาลองใหม่" : error.message;
      if (progress) progress.textContent = `การตรวจสอบไม่สำเร็จ: ${displayErr}`;
      if (box) box.textContent = progress.textContent;
      if ($("#awsStatus")) $("#awsStatus").textContent = "RETRY NEEDED";

      if (actBadge) {
        actBadge.textContent = "RETRY NEEDED";
        actBadge.className = "soft-pill badge-retry";
      }
      if (findBadge) {
        findBadge.textContent = "INCOMPLETE";
        findBadge.className = "soft-pill badge-retry";
      }
    }
  } finally {
    clearTimeout(timeout);
    state.isInvestigating = false;
    if (spinner) spinner.hidden = true;
    if (button) button.disabled = false;
  }
}

// ==========================================
// RENDER ALL SCREENS
// ==========================================

function render() {
  const c = currentCase();
  const a = analyze(c);

  renderOverview(a, c);
  renderTrail(a, c);
  renderInvestigation(a, c);
  renderEvidence(a);
  renderOutcomeDashboard(a, c);

  // แปล UI หลังสร้างข้อมูลบนหน้าจอ
  window.MuleI18N?.apply();
}


// ==========================================
// INITIALIZE APP
// ==========================================

function populateCaseSelect() {
  const select = $("#caseSelect");
  if (!select) return;
  put(
    select,
    ...D.cases.map(c => {
      const option = el("option", c.caseId);
      option.value = c.caseId;
      return option;
    })
  );
  if (D.cases.some(c => c.caseId === state.caseId)) {
    select.value = state.caseId;
  }
}

function syncMuleTraceCases(incomingCases) {
  if (!Array.isArray(incomingCases) || !incomingCases.length) return;

  const existingById = new Map(D.cases.map(c => [c.caseId, c]));
  const mergedCases = [];

  for (const item of incomingCases) {
    if (!item || !item.caseId) continue;
    const rawTxList = item.transactions || item.raw?.transactions;
    if (Array.isArray(rawTxList)) {
      for (const tx of rawTxList) {
        if (!tx || !tx.id) continue;
        if (!D.transactions.some(existing => existing.id === tx.id)) {
          D.transactions.push({
            id: String(tx.id),
            from: String(tx.from),
            to: String(tx.to),
            amount: Number(tx.amount) || 0,
            time: String(tx.time || "2026-09-16T02:13:00")
          });
        }
        if (tx.from && !D.accounts[tx.from]) {
          D.accounts[tx.from] = {
            name: `Account ${tx.from}`,
            status: tx.from === item.target ? "flagged" : "watch",
            openedDays: 14,
            avgAmount: 3200
          };
        }
        if (tx.to && !D.accounts[tx.to]) {
          D.accounts[tx.to] = {
            name: `Account ${tx.to}`,
            status: tx.to === item.target ? "flagged" : "watch",
            openedDays: 10,
            avgAmount: 2900
          };
        }
      }
    }

    const prev = existingById.get(item.caseId) || {};
    const src = item.source && item.source !== "—" && item.source !== "-" ? item.source : (item.accounts?.[0] || prev?.source || "—");
    const tgt = item.target && item.target !== "—" && item.target !== "-" ? item.target : (item.accounts?.[1] || prev?.target || "—");

    if (!D.accounts[src]) {
      D.accounts[src] = {
        name: `Account ${src}`,
        status: "watch",
        openedDays: 45,
        avgAmount: 3500
      };
    }
    if (!D.accounts[tgt]) {
      D.accounts[tgt] = {
        name: `Account ${tgt}`,
        status: "flagged",
        openedDays: 10,
        avgAmount: 2800
      };
    }

    const txId = item.transactionId || `TX-${item.caseId}`;
    const txTime = item.time || "2026-09-16T02:13:00";
    if (item.transactionId && Number(item.amount) > 0 && !D.transactions.some(t => t.id === txId)) {
      D.transactions.push({
        id: txId,
        from: src,
        to: tgt,
        amount: Number(item.amount) || 0,
        time: txTime
      });
    }

    mergedCases.push({
      ...prev,
      caseId: item.caseId,
      source: src,
      target: tgt,
      amount: Number(item.amount ?? prev.amount ?? 0),
      time: txTime,
      status: item.status || prev.status || "new",
      transactionId: item.transactionId || prev.transactionId || "",
      risk: item.risk || prev.risk,
      priorityScore: item.priorityScore ?? prev.priorityScore,
      description: item.description || prev.description
    });
    existingById.delete(item.caseId);
  }

  for (const leftover of existingById.values()) {
    mergedCases.push(leftover);
  }

  D.cases = mergedCases;
  refreshTransactions();
  state.replay = byTime.length;
  populateCaseSelect();
  render();
}

function openCaseInvestigation(caseId, targetPage = "investigation") {
  if (!caseId) return;
  const found = D.cases.find(c => c.caseId === caseId);
  if (!found && window.MuleCaseManager) {
    const cmCases = window.MuleCaseManager.getCases?.() || [];
    if (cmCases.length) {
      syncMuleTraceCases(cmCases);
    }
  }
  const c = D.cases.find(item => item.caseId === caseId) || D.cases[0];
  if (!c) return;

  state.caseId = c.caseId;
  state.selectedTx =
    c.transactionId ||
    D.transactions.find(t => t.to === c.target || t.from === c.target)?.id ||
    state.selectedTx;
  state.replay = byTime.length;
  syncCaseAiState();

  populateCaseSelect();
  showPage(targetPage);
}

window.showPage = showPage;
window.syncMuleTraceCases = syncMuleTraceCases;
window.openCaseInvestigation = openCaseInvestigation;

function initialize() {
  const select = $("#caseSelect");
  populateCaseSelect();

  select?.addEventListener("change", () => {
    state.caseId = select.value;
    state.selectedTx = currentCase().transactionId;
    state.replay = byTime.length;
    syncCaseAiState();

    $("#awsStatus").textContent =
      state.aiResult ? "AGENT COMPLETED" : "NOT CONNECTED";

    render();
  });

  $$("[data-page]").forEach(b => {
    b.addEventListener("click", () => {
      showPage(b.dataset.page);
    });
  });

  $$("[data-go]").forEach(b => {
    b.addEventListener("click", () => {
      showPage(b.dataset.go);
    });
  });

  $("#hopSelect").addEventListener("change", e => {
    state.hops = Number(e.target.value);
    render();
  });

  $("#replayRange").addEventListener("input", e => {
    state.replay = Number(e.target.value);
    render();
  });

  $("#resetReplay").addEventListener("click", () => {
    state.replay = byTime.length;
    render();
  });

  $("#downloadReport")?.addEventListener("click", () => {
    download(
      analyze(currentCase()),
      currentCase()
    );
  });

  $("#btnDownloadReportCard")?.addEventListener("click", () => {
    download(
      analyze(currentCase()),
      currentCase()
    );
  });

  $("#btnGoOutcome")?.addEventListener("click", () => {
    showPage("report");
  });

  // Logout Action
  const logoutBtn = $("#logoutBtn");
  if (logoutBtn) {
    logoutBtn.addEventListener("click", async () => {
      try {
        await fetch("/api/auth/logout", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin"
        });
      } catch (e) {
        // Fallback
      }
      window.location.replace("login.html");
    });
  }

  $("#runAi").addEventListener("click", () => {
    callAi(
      analyze(currentCase()),
      currentCase()
    );
  });

  const toggleAwsKeyBtn = $("#toggleAwsKeyBox");
  const awsKeyPanel = $("#awsKeyPanel");
  const saveDashboardAwsKeyBtn = $("#saveDashboardAwsKeyBtn");
  const dashboardAwsRawInput = $("#dashboardAwsRawInput");
  const dashboardAwsKeyStatus = $("#dashboardAwsKeyStatus");

  if (toggleAwsKeyBtn && awsKeyPanel) {
    toggleAwsKeyBtn.addEventListener("click", async () => {
      awsKeyPanel.hidden = !awsKeyPanel.hidden;
      if (!awsKeyPanel.hidden && dashboardAwsKeyStatus) {
        try {
          const r = await fetch("/api/aws/credentials", { credentials: "same-origin" });
          if (r.ok) {
            const d = await r.json();
            dashboardAwsKeyStatus.textContent = d.configured
              ? `Key ปัจจุบัน: ${d.masked_key_id} (${d.region})`
              : "ยังไม่ได้ตั้งค่า AWS Key";
          }
        } catch (_) {}
      }
    });
  }

  if (saveDashboardAwsKeyBtn && dashboardAwsRawInput) {
    saveDashboardAwsKeyBtn.addEventListener("click", async () => {
      const rawText = dashboardAwsRawInput.value.trim();
      if (!rawText) {
        if (dashboardAwsKeyStatus) {
          dashboardAwsKeyStatus.textContent = "กรุณาวาง AWS Credentials ก่อนบันทึก";
        }
        return;
      }
      saveDashboardAwsKeyBtn.disabled = true;
      try {
        const r = await fetch("/api/aws/credentials", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ raw_text: rawText })
        });
        const d = await r.json().catch(() => ({}));
        if (r.ok && d.status === "success") {
          dashboardAwsRawInput.value = "";
          if (dashboardAwsKeyStatus) {
            dashboardAwsKeyStatus.textContent = `✓ อัปเดตสำเร็จ: ${d.masked_key_id} (${d.region})`;
          }
          $("#awsStatus").textContent = `KEY READY (${d.masked_key_id})`;
        } else if (dashboardAwsKeyStatus) {
          dashboardAwsKeyStatus.textContent = d.message || "อัปเดต Key ไม่สำเร็จ";
        }
      } catch (_) {
        if (dashboardAwsKeyStatus) {
          dashboardAwsKeyStatus.textContent = "เชื่อมต่อเซิร์ฟเวอร์ไม่สำเร็จ";
        }
      } finally {
        saveDashboardAwsKeyBtn.disabled = false;
      }
    });
  }
    window.MuleI18N?.init();
  render();

  // PWA: ทำงานเมื่อรันผ่าน localhost หรือ HTTPS
  if (
    "serviceWorker" in navigator &&
    (
      location.protocol === "https:" ||
      location.hostname === "localhost" ||
      location.hostname === "127.0.0.1"
    )
  ) {
    navigator.serviceWorker
      .register("./sw.js")
      .catch(() => {});
  }
}

initialize();
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
  aiText: ""
};

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
    report: "Evidence & Report"
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
    state.aiText = "";

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
  $("#investigationHeading").textContent =
    `${c.caseId} · ${c.target}`;

  $("#priorityLabel").textContent =
    `${a.risk} · ${a.score}/100`;

  const summary = $("#caseSummary");

  const wrap = el(
    "div",
    undefined,
    "summary-score"
  );

  wrap.append(
    el("div", String(a.score), "score-circle")
  );

  const txt = el("div");

  txt.append(
    el("strong", `${a.risk} investigation priority`),
    el(
      "p",
      `${a.signals.length} evidence signals · ` +
      `${a.network.nodes.length} linked accounts`,
      "helper"
    )
  );

  wrap.append(txt);

  put(
    summary,
    wrap,
    detailRow("Alert source", c.source),
    detailRow("Target", c.target),
    detailRow("Alert amount", fmt(c.amount)),
    detailRow("Alert date", dateLabel(c.time))
  );

  // Tool Activity ในโหมดกฎจำลอง
  const stepNames = [
    [
      "get_account_profile",
      `ตรวจสถานะบัญชี ${c.target}`
    ],
    [
      "get_transaction_history",
      "ดึงข้อมูลรับ-โอนที่เกี่ยวข้อง"
    ],
    [
      "expand_network",
      `สำรวจเครือข่าย 3 ทอด (${a.network.nodes.length} บัญชี)`
    ],
    [
      "search_previous_cases",
      `เชื่อมโยง ${a.overlaps.length} เคสก่อนหน้า`
    ],
    [
      "score_investigation",
      `คำนวณคะแนน Priority ${a.score}/100`
    ]
  ];

  put(
    $("#toolSteps"),
    ...stepNames.map(([name, desc]) => {
      const li = el("li");

      li.append(
        el("strong", name),
        el("small", desc)
      );

      return li;
    })
  );

  put(
    $("#recommendedAccounts"),
    ...a.next.map(x => {
      const chip = el(
        "button",
        `${x.id} · ${x.score} points`,
        "chip clickable"
      );
      chip.type = "button";
      chip.style.cursor = "pointer";
      chip.addEventListener("click", () => {
        const linkedTx = D.transactions.find(
          t => t.from === x.id || t.to === x.id
        );
        if (linkedTx) {
          state.selectedTx = linkedTx.id;
        }
        state.replay = byTime.length;
        showPage("trail");
      });
      return chip;
    })
  );
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
// OPTIONAL AWS API CONNECTION
// ==========================================

async function callAi(a, c) {
  const box = $("#aiResult");
  const button = $("#runAi");

  let url =
    window.MULETRACE_CONFIG?.apiUrl?.trim() || "";

  if (typeof window !== "undefined" && window.location?.origin) {
    if (!url) {
      url = `${window.location.origin}/api/ai/summary`;
    } else if (url.startsWith("/")) {
      url = `${window.location.origin}${url}`;
    }
  }

  if (!url) {
    box.textContent =
      "ยังไม่ได้กำหนด API endpoint ใน config.js · " +
      "ใช้ Rule-based อยู่";
    return;
  }

  if (
    !url.startsWith("https://") &&
    !/^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?\//.test(url)
  ) {
    box.textContent =
      "API ต้องเป็น HTTPS หรือ localhost ขณะพัฒนา";
    return;
  }

  const controller = new AbortController();

  const timeout = setTimeout(
    () => controller.abort(),
    20000
  );

  button.disabled = true;
  box.textContent =
    "กำลังรอผลจาก Investigation API...";

  try {
    const response = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        case_id: c.caseId,
        language:
          window.MuleI18N?.getLanguage?.() ||
          window.MULETRACE_I18N?.getLanguage?.() ||
          "th",
        investigation: {
          case_id: c.caseId,
          source_account: c.source,
          target_account: c.target,
          alert_amount: c.amount,
          alert_time: c.time,
          priority_score: a.score,
          risk_level: a.risk,
          linked_accounts: a.network.nodes,
          recommended_next_accounts: a.next,
          evidence_chain: a.signals.map(s => ({
            title: s.title,
            detail: s.detail,
            transaction_ids: s.transactionIds
          })),
          transactions: a.network.edges.map(t => ({
            transaction_id: t.id,
            source_account: t.from,
            target_account: t.to,
            amount: t.amount,
            timestamp: t.time
          }))
        }
      }),
      signal: controller.signal,
      cache: "no-store"
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const output = await response.json();

    if (
      typeof output.summary !== "string" ||
      !output.summary.trim()
    ) {
      throw new Error(
        "API response missing summary"
      );
    }

    state.aiText = output.summary;

    box.textContent = output.summary;

    $("#awsStatus").textContent =
      "API RESPONDED";

  } catch (error) {
    box.textContent =
      `เชื่อม API ไม่สำเร็จ: ${error.message}. ` +
      "โหมด Rule-based ยังใช้ได้";

    $("#awsStatus").textContent =
      "NOT CONNECTED";

  } finally {
    clearTimeout(timeout);
    button.disabled = false;
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

    const src = item.source && item.source !== "—" && item.source !== "-" ? item.source : "A001";
    const tgt = item.target && item.target !== "—" && item.target !== "-" ? item.target : "B782";

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
    if (!D.transactions.some(t => t.id === txId)) {
      D.transactions.push({
        id: txId,
        from: src,
        to: tgt,
        amount: Number(item.amount) || 0,
        time: txTime
      });
    }

    const prev = existingById.get(item.caseId) || {};
    mergedCases.push({
      ...prev,
      caseId: item.caseId,
      source: src,
      target: tgt,
      amount: Number(item.amount ?? prev.amount ?? 0),
      time: txTime,
      status: item.status || prev.status || "new",
      transactionId: txId
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
  state.aiText = "";

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
    state.aiText = "";

    $("#awsStatus").textContent =
      "NOT CONNECTED";

    $("#aiResult").textContent =
      "ยังไม่ได้เชื่อม AWS · " +
      "ใช้รายงานแบบ Rule-based ได้";

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

  $("#downloadReport").addEventListener("click", () => {
    download(
      analyze(currentCase()),
      currentCase()
    );
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
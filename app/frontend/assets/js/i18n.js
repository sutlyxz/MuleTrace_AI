
/*
  MuleTrace AI — Language System
  Thai / English
  ใช้แปล UI โดยไม่เปลี่ยนข้อมูลทางการเงิน
*/

(() => {
  const STORAGE_KEY = "muletrace-language";

  let language = "th";

  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "th" || saved === "en") {
      language = saved;
    }
  } catch (error) {
    // ถ้าเบราว์เซอร์บันทึกไม่ได้ ยังเปลี่ยนภาษาได้
  }

  const $ = selector => document.querySelector(selector);

  const $$ = selector =>
    [...document.querySelectorAll(selector)];

  const choose = (th, en) =>
    language === "th" ? th : en;

  const money = value =>
    "฿" + Number(value).toLocaleString("en-US");

  // เปลี่ยนข้อความของ Element หนึ่งตัว
  function text(selector, th, en) {
    const element = $(selector);

    if (element) {
      element.textContent = choose(th, en);
    }
  }

  // เปลี่ยนข้อความของ Element หลายตัว
  function list(selector, thai, english) {
    $$(selector).forEach((element, index) => {
      const value = choose(
        thai[index],
        english[index]
      );

      if (value !== undefined) {
        element.textContent = value;
      }
    });
  }

  // เปลี่ยนเฉพาะข้อความ ไม่ลบ Element ลูก
  function plainTextNode(selector, th, en) {
    const container = $(selector);
    if (!container) return;

    const node = [...container.childNodes].find(
      item =>
        item.nodeType === Node.TEXT_NODE &&
        item.textContent.trim()
    );

    if (node) {
      node.textContent = " " + choose(th, en) + " ";
    }
  }

  // =====================================
  // STATIC UI TRANSLATIONS
  // =====================================

  function applyStatic() {
    document.documentElement.lang = language;

    // อัปเดตปุ่ม TH / EN
    $$("[data-lang]").forEach(button => {
      const active =
        button.dataset.lang === language;

      button.classList.toggle("active", active);
      button.setAttribute(
        "aria-pressed",
        String(active)
      );
    });

    // Sidebar
    text(".nav-label", "พื้นที่ทำงาน", "WORKSPACE");

    list(
      ".nav-item span",
      [
        "ภาพรวม",
        "รายการเคส",
        "เส้นทางเงิน",
        "การสืบสวน",
        "หลักฐานและรายงาน"
      ],
      [
        "Overview",
        "Case Queue",
        "Money Trail",
        "Investigation",
        "Evidence & Report"
      ]
    );

    plainTextNode(
      ".sidebar-foot",
      "โหมดข้อมูลจำลองเปิดอยู่",
      "Demo mode active"
    );

    text(
      ".sidebar-foot small",
      "ข้อมูลจำลองเท่านั้น · ไม่เชื่อมระบบธนาคารจริง",
      "Synthetic data only · No live banking connection"
    );

    // Header
    text(
      ".topbar .eyebrow",
      "ศูนย์บัญชาการตรวจสอบธุรกรรม",
      "FINANCIAL INVESTIGATION / COMMAND CENTER"
    );

    text(".case-select-label", "เคส", "CASE");

    text(
      ".mode-badge",
      "● ข้อมูลจำลอง",
      "● DEMO DATA"
    );

    // ชื่อหน้าปัจจุบัน
    const page =
      $(".nav-item.active")?.dataset.page ||
      "overview";

    const pageTitles = {
      overview: ["ภาพรวม", "Overview"],
      cases: ["รายการเคส", "Case Queue"],
      trail: ["เส้นทางเงิน", "Money Trail"],
      investigation: ["การสืบสวน", "Investigation"],
      report: ["หลักฐานและรายงาน", "Evidence & Report"]
    };

    if (pageTitles[page]) {
      text("#pageTitle", ...pageTitles[page]);
    }

    // =====================================
    // OVERVIEW
    // =====================================

    text(
      "#page-overview .intro p:not(.eyebrow)",
      "เปลี่ยนการแจ้งเตือนธุรกรรมให้เป็นการสืบสวนที่ตรวจสอบหลักฐานย้อนหลังได้",
      "Turn transaction alerts into evidence-backed investigations."
    );

    text(
      '#page-overview [data-go="investigation"]',
      "เริ่มสืบสวน ↗",
      "Start Investigation ↗"
    );

    list(
      "#page-overview .panel .section-head h3",
      ["รายการเคส", "เคสปัจจุบัน"],
      ["Case Queue", "Current Case"]
    );

    list(
      "#page-overview .panel .section-head .eyebrow",
      ["การจัดการแจ้งเตือน", "ภาพรวมเครือข่าย"],
      ["ALERT MANAGEMENT", "NETWORK SNAPSHOT"]
    );

    text(
      '#page-overview [data-go="cases"]',
      "ดูทั้งหมด →",
      "View All →"
    );

    text(
      '#page-overview [data-go="trail"]',
      "เปิดเส้นทางเงิน →",
      "Open Money Trail →"
    );

    // =====================================
    // CASE QUEUE
    // =====================================

    text(
      "#page-cases .eyebrow",
      "การแจ้งเตือนธุรกรรม",
      "FRAUD ALERTS"
    );

    text(
      "#page-cases h2",
      "รายการเคสที่ต้องตรวจสอบ",
      "Investigation Queue"
    );

    text(
      "#page-cases .soft-pill",
      "จัดลำดับเพื่อให้เจ้าหน้าที่ตรวจสอบต่อ",
      "Prioritized for investigator review"
    );

    // =====================================
    // MONEY TRAIL
    // =====================================

    text(
      "#page-trail .eyebrow",
      "วิเคราะห์เส้นทางธุรกรรม",
      "TRANSACTION INTELLIGENCE"
    );

    text(
      "#page-trail h2",
      "เส้นทางเงินหลายทอด",
      "Multi-Hop Money Trail"
    );

    text(
      "#page-trail > .section-head .soft-pill",
      "คลิกบัญชีหรือเส้นธุรกรรม",
      "Select an account or transaction"
    );

    plainTextNode(
      "#page-trail .controls label",
      "ความลึกเครือข่าย",
      "Network depth"
    );

    text(
      "#resetReplay",
      "แสดงทั้งหมด",
      "Show All"
    );

    list(
      "#page-trail h3",
      [
        "ย้อนดูตามเวลา",
        "ธุรกรรมที่เลือก",
        "รายการธุรกรรม"
      ],
      [
        "Time Replay",
        "Selected Transaction",
        "Transaction Records"
      ]
    );

    text(
      "#page-trail .field-label",
      "เลื่อนเพื่อดูธุรกรรมตามลำดับเวลา",
      "Move the slider to replay transactions chronologically"
    );

    list(
      "#page-trail th",
      [
        "รหัส",
        "ต้นทาง → ปลายทาง",
        "จำนวนเงิน",
        "วันที่ / เวลา"
      ],
      [
        "ID",
        "From → To",
        "Amount",
        "Date / Time"
      ]
    );

    const legendLabels = [
      ["บัญชีเป้าหมาย", "Target account"],
      ["บัญชีที่ถูก Flag", "Flagged account"],
      ["บัญชี Watch", "Watch account"],
      ["บัญชีอื่น", "Other account"]
    ];

    $$("#page-trail .legend span").forEach(
      (element, index) => {
        const words = legendLabels[index];
        if (!words) return;

        const node = [...element.childNodes].find(
          n => n.nodeType === Node.TEXT_NODE
        );

        if (node) {
          node.textContent = choose(...words);
        }
      }
    );

    // =====================================
    // INVESTIGATION
    // =====================================

    text(
      "#page-investigation > .section-head .eyebrow",
      "พื้นที่สืบสวน",
      "INVESTIGATION WORKSPACE"
    );

    list(
      "#page-investigation h3",
      [
        "สรุปการสืบสวน",
        "กิจกรรมเครื่องมือ",
        "บัญชีที่แนะนำให้ตรวจต่อ"
      ],
      [
        "Investigation Summary",
        "Tool Activity",
        "Recommended Next Accounts"
      ]
    );

    text(
      "#page-investigation .disclaimer",
      "คะแนน Priority ใช้จัดลำดับการตรวจสอบ ไม่ใช่ความน่าจะเป็นในการกระทำผิด และไม่ใช่คำตัดสิน",
      "The priority score helps order investigations. It is not a probability of guilt or a verdict."
    );

    text(
      "#page-investigation .text-btn",
      "ดูกราฟ →",
      "View Graph →"
    );

    text(
      "#page-investigation .two-col .soft-pill",
      "เดโม่แบบกฎ",
      "RULE-BASED DEMO"
    );

    // =====================================
    // EVIDENCE & REPORT
    // =====================================

    text(
      "#page-report > .section-head .eyebrow",
      "การตรวจสอบที่อธิบายได้",
      "EXPLAINABLE INVESTIGATION"
    );

    text(
      "#page-report > .section-head h2",
      "หลักฐานและรายงาน",
      "Evidence Chain & Report"
    );

    text(
      "#downloadReport",
      "↓ ดาวน์โหลดรายงาน",
      "↓ Download Report"
    );

    list(
      "#page-report h3",
      [
        "ห่วงโซ่หลักฐาน",
        "เชื่อมโยงเคสก่อนหน้า",
        "เชื่อมต่อ AWS Agent"
      ],
      [
        "Evidence Chain",
        "Cross-Case Connections",
        "AWS Agent Handoff"
      ]
    );

    text(
      "#page-report > .panel .section-head .helper",
      "อ้างอิงรหัสธุรกรรมจากข้อมูลจำลอง",
      "References synthetic transaction IDs"
    );

    text(
      "#page-report .two-col .panel:last-child .helper",
      "พื้นที่รับข้อมูลจริงจาก Backend ของทีม · ยังไม่เรียก Bedrock โดยอัตโนมัติ",
      "Receives results from the team's backend · Bedrock is not called automatically"
    );

    text(
      "#runAi",
      "ขอสรุปผลจาก AI API",
      "Request AI Summary via API"
    );

    text(
      "footer",
      "MuleTrace AI · ต้นแบบการแข่งขัน · ข้อมูลจำลอง · เจ้าหน้าที่ตรวจสอบขั้นสุดท้าย",
      "MuleTrace AI · Hackathon Prototype · Synthetic Data Only · Human Review Required"
    );
  }

  // =====================================
  // DYNAMIC CONTENT TRANSLATIONS
  // =====================================

  function applyDynamic() {
    const data = window.MULETRACE_DATA;
    const caseId = $("#caseSelect")?.value;

    const selectedCase = data?.cases?.find(
      item => item.caseId === caseId
    );

    if (!selectedCase) return;

    const result =
      typeof analyze === "function"
        ? analyze(selectedCase)
        : null;

    if (!result) return;

    // KPI Labels
    list(
      "#metrics .metric small",
      [
        "เคสที่เปิดอยู่",
        "ธุรกรรม",
        "บัญชีที่เชื่อมโยง",
        "คะแนนจัดลำดับ"
      ],
      [
        "ACTIVE CASES",
        "TRANSACTIONS",
        "LINKED ACCOUNTS",
        "PRIORITY SCORE"
      ]
    );

    // Network Snapshot
    list(
      "#snapshot .snapshot-item small",
      [
        "รหัสเคส",
        "บัญชีเป้าหมาย",
        "ยอดแจ้งเตือน",
        "สัญญาณหลักฐาน"
      ],
      [
        "CASE ID",
        "TARGET ACCOUNT",
        "AMOUNT",
        "EVIDENCE SIGNALS"
      ]
    );

    text(
      "#overviewRisk",
      `${result.risk} · ความสำคัญ`,
      `${result.risk} PRIORITY`
    );

    $$(".case-row .risk").forEach(element => {
      element.textContent = choose(
        "ดูการสืบสวน →",
        "View investigation →"
      );
    });

    // Time Replay
    const replay = Number(
      $("#replayRange")?.value ?? 0
    );

    const transactions = [...data.transactions].sort(
      (a, b) => a.time.localeCompare(b.time)
    );

    text(
      "#replayCount",
      `${replay}/${transactions.length} ธุรกรรม`,
      `${replay}/${transactions.length} transactions`
    );

    if (language === "en") {
      const latest = transactions[replay - 1];

      text(
        "#replayTime",
        "",
        latest
          ? "Through " + new Date(
              latest.time
            ).toLocaleString("en-GB", {
              dateStyle: "medium",
              timeStyle: "short"
            })
          : "No transactions displayed"
      );
    }

    // Transaction detail labels
    list(
      "#transactionDetail .detail-row span:first-child",
      [
        "จาก → ถึง",
        "จำนวนเงิน",
        "เวลา",
        "อ้างอิง"
      ],
      [
        "From → To",
        "Amount",
        "Time",
        "Reference"
      ]
    );

    // Investigation labels
    list(
      "#caseSummary .detail-row span:first-child",
      [
        "บัญชีต้นทาง",
        "บัญชีเป้าหมาย",
        "ยอดแจ้งเตือน",
        "เวลาแจ้งเตือน"
      ],
      [
        "Alert source",
        "Target",
        "Alert amount",
        "Alert date"
      ]
    );

    text(
      "#caseSummary .summary-score strong",
      `ความสำคัญในการตรวจสอบ: ${result.risk}`,
      `${result.risk} investigation priority`
    );

    text(
      "#caseSummary .summary-score p",
      `${result.signals.length} สัญญาณหลักฐาน · ${result.network.nodes.length} บัญชีเชื่อมโยง`,
      `${result.signals.length} evidence signals · ${result.network.nodes.length} linked accounts`
    );

    // Tool activity descriptions
    const steps = [
      [
        `ตรวจข้อมูลบัญชี ${selectedCase.target}`,
        `Check profile for ${selectedCase.target}`
      ],
      [
        "ดึงประวัติรับและโอนเงิน",
        "Retrieve incoming and outgoing transfers"
      ],
      [
        `ขยายเครือข่าย 3 ทอด (${result.network.nodes.length} บัญชี)`,
        `Explore 3 hops (${result.network.nodes.length} accounts)`
      ],
      [
        `พบ ${result.overlaps.length} เคสก่อนหน้าที่เกี่ยวข้อง`,
        `Find ${result.overlaps.length} linked previous cases`
      ],
      [
        `คะแนนลำดับความสำคัญ ${result.score}/100`,
        `Investigation priority score ${result.score}/100`
      ]
    ];

    $$("#toolSteps li small").forEach(
      (element, index) => {
        if (steps[index]) {
          element.textContent = choose(...steps[index]);
        }
      }
    );

    // Recommended Accounts
    $$("#recommendedAccounts .chip").forEach(
      (element, index) => {
        const item = result.next[index];
        if (!item) return;

        element.textContent = choose(
          `${item.id} · ${item.score} คะแนน`,
          `${item.id} · ${item.score} points`
        );
      }
    );

    // Evidence Chain
    if (language === "en") {
      const titles = {
        new: "New account with unusually high incoming amount",
        funnel: "Inbound transfers from multiple senders",
        rapid: "Rapid outgoing transfers after a large deposit",
        cross: "Linked to previous investigations"
      };

      const ref = new Date(
        selectedCase.time
      ).getTime();

      const inbound = data.transactions.filter(
        t =>
          t.to === selectedCase.target &&
          new Date(t.time).getTime() >=
            ref - 24 * 3600000 &&
          new Date(t.time).getTime() <= ref
      );

      const account =
        data.accounts[selectedCase.target];

      $$("#evidenceList .evidence-item").forEach(
        (element, index) => {
          const signal = result.signals[index];
          if (!signal) return;

          const title = element.querySelector("h4");
          const detail = element.querySelector("p");

          if (title) {
            title.textContent =
              `${String(index + 1).padStart(2, "0")} · ` +
              (titles[signal.type] || signal.title);
          }

          if (!detail) return;

          if (signal.type === "new") {
            const maximum = Math.max(
              0,
              ...inbound.map(t => t.amount)
            );

            detail.textContent =
              `Account opened ${account.openedDays} days ago. ` +
              `Maximum inbound amount ${money(maximum)} ` +
              `versus average ${money(account.avgAmount)}.`;

          } else if (signal.type === "funnel") {
            const count = new Set(
              inbound.map(t => t.from)
            ).size;

            detail.textContent =
              `Transfers received from ${count} distinct ` +
              `senders in the 24 hours before this alert.`;

          } else if (signal.type === "rapid") {
            const outgoing = data.transactions.filter(
              t =>
                signal.transactionIds.includes(t.id) &&
                t.from === selectedCase.target
            );

            const total = outgoing.reduce(
              (sum, t) => sum + t.amount,
              0
            );

            detail.textContent =
              `Outgoing transfers totaling ${money(total)} ` +
              `within 90 minutes of a high-value inbound transfer.`;

          } else if (signal.type === "cross") {
            detail.textContent =
              result.overlaps.map(
                p =>
                  `${p.caseId} via ${p.matched.join(", ")}`
              ).join(" · ");
          }
        }
      );
    }

    // AWS connection status
    if (!window.MULETRACE_CONFIG?.apiUrl) {
      text(
        "#aiResult",
        "ยังไม่เชื่อม AWS · ใช้รายงานแบบกฎได้",
        "AWS not connected · Rule-based report is available"
      );
    } else if (!state.aiText) {
      text(
        "#aiResult",
        "ระบบพร้อมเชื่อมต่อ AWS Bedrock แล้ว กดปุ่ม 'ขอ AI Summary ผ่าน API' ด้านบนเพื่อเริ่มวิเคราะห์เคสนี้",
        "AWS Bedrock ready · Click 'Request AI Summary via API' button above to analyze this case"
      );
    }
  }

  // =====================================
  // APPLY LANGUAGE
  // =====================================

  function apply() {
    applyStatic();
    applyDynamic();
  }

  function init() {
    $$("[data-lang]").forEach(button => {
      button.addEventListener("click", () => {
        language =
          button.dataset.lang === "en"
            ? "en"
            : "th";

        try {
          localStorage.setItem(
            STORAGE_KEY,
            language
          );
        } catch (error) {}

        // วาดข้อมูลใหม่แล้วแปลตามภาษาที่เลือก
        if (typeof render === "function") {
          render();
        } else {
          apply();
        }
      });
    });

    apply();
  }

  window.MuleI18N = {
    init,
    apply,
    getLanguage: () => language
  };
})();

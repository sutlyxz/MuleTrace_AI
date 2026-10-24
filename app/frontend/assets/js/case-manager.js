
/*
  MuleTrace AI — Case Manager
  Search / Filter / Sort / Pagination / Details
  Up to 500 cases, 20 cases per page
*/

(() => {
  "use strict";

  const PAGE_SIZE = 20;

  const state = {
    cases: [],
    source: "demo",
    receivedCount: 0,
    limited: false,
    loading: false,
    error: "",
    query: "",
    status: "all",
    risk: "all",
    sort: "newest",
    page: 1,
    selectedId: null
  };

  let root = null;

  function isEnglish() {
    return (
      window.MuleI18N?.getLanguage?.() === "en"
    );
  }

  function tr(th, en) {
    return isEnglish() ? en : th;
  }

  function escapeHTML(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function money(value) {
    const number = Number(value) || 0;

    return "฿" + number.toLocaleString("en-US", {
      maximumFractionDigits: 2
    });
  }

  function formatTime(value) {
    if (!value) return "—";

    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
      return String(value);
    }

    return date.toLocaleString(
      isEnglish() ? "en-GB" : "th-TH",
      {
        dateStyle: "medium",
        timeStyle: "short"
      }
    );
  }

  function statusLabel(value) {
    const labels = {
      new: ["ใหม่", "New"],
      in_progress: [
        "กำลังตรวจสอบ",
        "In Progress"
      ],
      review: [
        "รอตรวจทาน",
        "In Review"
      ],
      closed: [
        "ปิดเคสแล้ว",
        "Closed"
      ]
    };

    const entry = labels[value];

    return entry
      ? tr(...entry)
      : String(value || "—");
  }

  function riskLabel(value) {
    const labels = {
      HIGH: ["สูง", "High"],
      MEDIUM: ["ปานกลาง", "Medium"],
      LOW: ["ต่ำ", "Low"],
      UNKNOWN: ["ไม่ระบุ", "Not Provided"]
    };

    return tr(
      ...(labels[value] || labels.UNKNOWN)
    );
  }

  function riskClass(value) {
    return ["HIGH", "MEDIUM", "LOW"].includes(
      value
    )
      ? value.toLowerCase()
      : "unknown";
  }

  function statusClass(value) {
    return [
      "new",
      "in_progress",
      "review",
      "closed"
    ].includes(value)
      ? value
      : "other";
  }

  function rankRisk(value) {
    return {
      HIGH: 3,
      MEDIUM: 2,
      LOW: 1,
      UNKNOWN: 0
    }[value] ?? 0;
  }

  function timestamp(value) {
    const result = Date.parse(value);
    return Number.isFinite(result) ? result : 0;
  }

  function filteredCases() {
    const query = state.query
      .trim()
      .toLowerCase();

    const filtered = state.cases.filter(item => {
      const searchText = [
        item.caseId,
        item.source,
        item.target,
        item.transactionId,
        item.description,
        item.status,
        item.risk
      ].join(" ").toLowerCase();

      const matchesSearch =
        !query || searchText.includes(query);

      const matchesStatus =
        state.status === "all" ||
        item.status === state.status;

      const matchesRisk =
        state.risk === "all" ||
        item.risk === state.risk;

      return (
        matchesSearch &&
        matchesStatus &&
        matchesRisk
      );
    });

    const sorters = {
      newest: (a, b) =>
        timestamp(b.time) - timestamp(a.time),

      oldest: (a, b) =>
        timestamp(a.time) - timestamp(b.time),

      amount_desc: (a, b) =>
        b.amount - a.amount,

      amount_asc: (a, b) =>
        a.amount - b.amount,

      risk_desc: (a, b) =>
        rankRisk(b.risk) - rankRisk(a.risk),

      priority_desc: (a, b) =>
        (b.priorityScore ?? -1) -
        (a.priorityScore ?? -1)
    };

    filtered.sort(
      sorters[state.sort] || sorters.newest
    );

    return filtered;
  }

  function selectOptions(values, current, labelFn) {
    return values.map(value => {
      const selected =
        current === value ? "selected" : "";

      return `
        <option value="${escapeHTML(value)}"
          ${selected}>
          ${escapeHTML(labelFn(value))}
        </option>
      `;
    }).join("");
  }

  function renderDetails(item) {
    if (!item) return "";

    const score =
      item.priorityScore === null
        ? tr("ไม่มีข้อมูล", "Not provided")
        : `${item.priorityScore}/100`;

    const description =
      item.description ||
      tr(
        "ยังไม่มีคำอธิบายจากแหล่งข้อมูล",
        "No description provided by data source."
      );

    const canOpenDemo =
      state.source === "demo" &&
      [...document.querySelectorAll(
        "#caseSelect option"
      )].some(option => option.value === item.caseId);

    return `
      <section class="mtcm-details"
        aria-label="Case details">

        <div class="mtcm-detail-heading">
          <div>
            <div class="mtcm-overline">
              ${tr("รายละเอียดเคส", "CASE DETAILS")}
            </div>

            <h3>${escapeHTML(item.caseId)}</h3>
          </div>

          <button type="button"
            class="mtcm-icon-button"
            data-action="close"
            aria-label="Close details">
            ✕
          </button>
        </div>

        <div class="mtcm-detail-grid">
          <div>
            <small>${tr("บัญชีต้นทาง", "Source Account")}</small>
            <strong>${escapeHTML(item.source)}</strong>
          </div>

          <div>
            <small>${tr("บัญชีปลายทาง", "Target Account")}</small>
            <strong>${escapeHTML(item.target)}</strong>
          </div>

          <div>
            <small>${tr("จำนวนเงิน", "Amount")}</small>
            <strong>${money(item.amount)}</strong>
          </div>

          <div>
            <small>${tr("วันที่ / เวลา", "Date / Time")}</small>
            <strong>${escapeHTML(formatTime(item.time))}</strong>
          </div>

          <div>
            <small>${tr("สถานะ", "Status")}</small>
            <strong>${escapeHTML(statusLabel(item.status))}</strong>
          </div>

          <div>
            <small>${tr("ระดับความเสี่ยง", "Risk Level")}</small>
            <strong>${escapeHTML(riskLabel(item.risk))}</strong>
          </div>

          <div>
            <small>${tr("คะแนน Priority", "Priority Score")}</small>
            <strong>${escapeHTML(score)}</strong>
          </div>

          <div>
            <small>Transaction ID</small>
            <strong>${escapeHTML(item.transactionId || "—")}</strong>
          </div>
        </div>

        <div class="mtcm-description">
          <small>${tr("คำอธิบาย", "Description")}</small>
          <p>${escapeHTML(description)}</p>
        </div>
        <div style="display: flex; gap: 10px; flex-wrap: wrap; align-items: center;">
          <button type="button"
            class="mtcm-primary"
            data-action="investigate"
            data-id="${escapeHTML(item.caseId)}">
            ${tr(
              "เปิด Investigation สำหรับเคสนี้ →",
              "Open Investigation for this case →"
            )}
          </button>

          <button type="button"
            class="mtcm-secondary"
            data-action="trail"
            data-id="${escapeHTML(item.caseId)}">
            ${tr(
              "ดูกราฟเส้นทางเงิน (Money Trail) →",
              "View Money Trail Graph →"
            )}
          </button>
        </div>
      </section>
    `;
  }

  function renderRows(items) {
    if (!items.length) {
      return `
        <tr>
          <td colspan="8">
            <div class="mtcm-empty">
              <div class="mtcm-empty-icon">⌕</div>
              <strong>
                ${tr(
                  "ไม่พบเคสที่ตรงกับเงื่อนไข",
                  "No matching cases"
                )}
              </strong>
              <p>
                ${tr(
                  "ลองเปลี่ยนคำค้นหาหรือล้างตัวกรอง",
                  "Try another search or reset the filters."
                )}
              </p>
              <button type="button"
                class="mtcm-secondary"
                data-action="reset">
                ${tr("ล้างตัวกรอง", "Reset Filters")}
              </button>
            </div>
          </td>
        </tr>
      `;
    }

    return items.map(item => {
      const score =
        item.priorityScore === null
          ? "—"
          : `${item.priorityScore}/100`;

      return `
        <tr>
          <td>
            <button type="button"
              class="mtcm-case-link"
              data-action="view"
              data-id="${escapeHTML(item.caseId)}">
              ${escapeHTML(item.caseId)}
            </button>

            ${
              item.transactionId
                ? `<small class="mtcm-muted">
                     ${escapeHTML(item.transactionId)}
                   </small>`
                : ""
            }
          </td>

          <td>${escapeHTML(formatTime(item.time))}</td>

          <td>
            <span class="mtcm-account">
              ${escapeHTML(item.source)}
              <span class="mtcm-arrow">→</span>
              ${escapeHTML(item.target)}
            </span>
          </td>

          <td class="mtcm-amount">
            ${money(item.amount)}
          </td>

          <td>
            <span class="mtcm-pill risk-${riskClass(item.risk)}">
              ${escapeHTML(riskLabel(item.risk))}
            </span>
          </td>

          <td>
            <span class="mtcm-pill status-${statusClass(item.status)}">
              ${escapeHTML(statusLabel(item.status))}
            </span>
          </td>

          <td>${escapeHTML(score)}</td>

          <td>
            <div style="display: flex; gap: 6px; flex-wrap: wrap;">
              <button type="button"
                class="mtcm-view"
                data-action="view"
                data-id="${escapeHTML(item.caseId)}">
                ${tr("รายละเอียด", "Details")}
              </button>
              <button type="button"
                class="mtcm-view"
                style="background: #745b3e; color: #fff; border-color: #745b3e;"
                data-action="investigate"
                data-id="${escapeHTML(item.caseId)}">
                ${tr("สืบสวน →", "Investigate →")}
              </button>
            </div>
          </td>
        </tr>
      `;
    }).join("");
  }

  function pagination(totalPages) {
    if (totalPages <= 1) return "";

    const start = Math.max(
      1,
      Math.min(
        state.page - 2,
        totalPages - 4
      )
    );

    const end = Math.min(
      totalPages,
      start + 4
    );

    let buttons = "";

    for (let number = start; number <= end; number++) {
      buttons += `
        <button type="button"
          class="${number === state.page ? "active" : ""}"
          data-action="page"
          data-page="${number}">
          ${number}
        </button>
      `;
    }

    return `
      <div class="mtcm-pages"
        aria-label="Case pagination">

        <button type="button"
          data-action="page"
          data-page="${state.page - 1}"
          ${state.page === 1 ? "disabled" : ""}>
          ‹
        </button>

        ${buttons}

        <button type="button"
          data-action="page"
          data-page="${state.page + 1}"
          ${state.page === totalPages ? "disabled" : ""}>
          ›
        </button>
      </div>
    `;
  }

  function render() {
    if (!root) return;

    const filtered = filteredCases();

    const totalPages = Math.max(
      1,
      Math.ceil(filtered.length / PAGE_SIZE)
    );

    state.page = Math.max(
      1,
      Math.min(state.page, totalPages)
    );

    const start = (state.page - 1) * PAGE_SIZE;
    const end = Math.min(
      start + PAGE_SIZE,
      filtered.length
    );

    const visibleCases = filtered.slice(start, end);

    const selectedCase = state.cases.find(
      item => item.caseId === state.selectedId
    );

    const availableStatuses = [
      "all",
      ...new Set(
        state.cases.map(item => item.status)
      )
    ];

    const availableRisks = [
      "all",
      ...new Set(
        state.cases.map(item => item.risk)
      )
    ];

    const sourceLabel =
      state.source === "api"
        ? "API DATA"
        : "SYSTEM DATA";

    root.innerHTML = `
      <div class="mtcm-container">

        <div class="mtcm-heading">
          <div>
            <div class="mtcm-overline">
              ${tr(
                "จัดการการแจ้งเตือน",
                "ALERT MANAGEMENT"
              )}
            </div>

            <h2>
              ${tr(
                "รายการเคสที่ต้องตรวจสอบ",
                "Investigation Case Queue"
              )}
            </h2>

            <p>
              ${tr(
                "ค้นหา กรอง และจัดลำดับเคส เพื่อส่งต่อให้เจ้าหน้าที่ตรวจสอบ",
                "Search, filter, and prioritize cases for investigator review."
              )}
            </p>
          </div>

          <div class="mtcm-heading-actions">
            <span class="mtcm-source">
              ● ${sourceLabel}
            </span>

            <button type="button"
              class="mtcm-secondary"
              data-action="refresh"
              ${state.loading ? "disabled" : ""}>
              ↻ ${tr("โหลดข้อมูลใหม่", "Refresh")}
            </button>
          </div>
        </div>

        <div class="mtcm-summary">
          <div class="mtcm-stat">
            <small>${tr("เคสที่โหลดแล้ว", "Loaded Cases")}</small>
            <strong>${state.cases.length}</strong>
          </div>

          <div class="mtcm-stat">
            <small>${tr("ตรงกับตัวกรอง", "Matching Cases")}</small>
            <strong>${filtered.length}</strong>
          </div>

          <div class="mtcm-stat">
            <small>${tr("ขนาดหน้าละ", "Cases Per Page")}</small>
            <strong>${PAGE_SIZE}</strong>
          </div>

          <div class="mtcm-stat">
            <small>${tr("รองรับสูงสุด", "Maximum Supported")}</small>
            <strong>500</strong>
          </div>
        </div>

        ${
          state.limited
            ? `
              <div class="mtcm-warning">
                ${tr(
                  `ได้รับ ${state.receivedCount} เคส ระบบแสดงเฉพาะ 500 เคสแรก`,
                  `Received ${state.receivedCount} cases. Only the first 500 are loaded.`
                )}
              </div>
            `
            : ""
        }

        ${
          state.error
            ? `
              <div class="mtcm-error" role="alert">
                <strong>
                  ${tr(
                    "โหลดข้อมูลจาก API ไม่สำเร็จ",
                    "Could Not Load API Data"
                  )}
                </strong>

                <p>${escapeHTML(state.error)}</p>

                <button type="button"
                  class="mtcm-secondary"
                  data-action="demo">
                  ${tr(
                    "ใช้ข้อมูลเริ่มต้น",
                    "Use Default Data"
                  )}
                </button>
              </div>
            `
            : ""
        }

        <div class="mtcm-filters">
          <label class="mtcm-search-field">
            <span>${tr("ค้นหาเคส", "Search Cases")}</span>

            <input
              type="search"
              data-field="query"
              value="${escapeHTML(state.query)}"
              placeholder="${tr(
                "Case ID, บัญชี, Transaction ID...",
                "Case ID, account, transaction ID..."
              )}"
              autocomplete="off"
            />
          </label>

          <label>
            <span>${tr("สถานะ", "Status")}</span>

            <select data-field="status">
              ${selectOptions(
                availableStatuses,
                state.status,
                value =>
                  value === "all"
                    ? tr("ทุกสถานะ", "All Statuses")
                    : statusLabel(value)
              )}
            </select>
          </label>

          <label>
            <span>${tr("ความเสี่ยง", "Risk Level")}</span>

            <select data-field="risk">
              ${selectOptions(
                availableRisks,
                state.risk,
                value =>
                  value === "all"
                    ? tr("ทุกระดับ", "All Risk Levels")
                    : riskLabel(value)
              )}
            </select>
          </label>

          <label>
            <span>${tr("เรียงลำดับ", "Sort By")}</span>

            <select data-field="sort">
              ${selectOptions(
                [
                  "newest",
                  "oldest",
                  "amount_desc",
                  "amount_asc",
                  "risk_desc",
                  "priority_desc"
                ],
                state.sort,
                value => ({
                  newest: tr(
                    "ใหม่ล่าสุด",
                    "Newest First"
                  ),
                  oldest: tr(
                    "เก่าสุด",
                    "Oldest First"
                  ),
                  amount_desc: tr(
                    "จำนวนเงินมาก → น้อย",
                    "Highest Amount"
                  ),
                  amount_asc: tr(
                    "จำนวนเงินน้อย → มาก",
                    "Lowest Amount"
                  ),
                  risk_desc: tr(
                    "ความเสี่ยงสูงสุด",
                    "Highest Risk"
                  ),
                  priority_desc: tr(
                    "Priority สูงสุด",
                    "Highest Priority"
                  )
                }[value])
              )}
            </select>
          </label>

          <button type="button"
            class="mtcm-reset"
            data-action="reset">
            ${tr("ล้างตัวกรอง", "Clear")}
          </button>
        </div>

        ${
          selectedCase
            ? renderDetails(selectedCase)
            : ""
        }

        <div class="mtcm-table-card">

          <div class="mtcm-table-top">
            <strong>
              ${tr("รายการเคส", "Case List")}
            </strong>

            <span>
              ${
                filtered.length
                  ? start + 1
                  : 0
              }–${end}
              ${tr("จาก", "of")}
              ${filtered.length}
            </span>
          </div>

          ${
            state.loading
              ? `
                <div class="mtcm-loading"
                  role="status">
                  ${tr(
                    "กำลังโหลดข้อมูลเคส...",
                    "Loading cases..."
                  )}
                </div>
              `
              : `
                <div class="mtcm-table-scroll">
                  <table class="mtcm-table">
                    <thead>
                      <tr>
                        <th>CASE ID</th>
                        <th>${tr("วันที่ / เวลา", "Date / Time")}</th>
                        <th>${tr("บัญชี", "Accounts")}</th>
                        <th>${tr("จำนวนเงิน", "Amount")}</th>
                        <th>${tr("ความเสี่ยง", "Risk")}</th>
                        <th>${tr("สถานะ", "Status")}</th>
                        <th>PRIORITY</th>
                        <th>${tr("การทำงาน", "Action")}</th>
                      </tr>
                    </thead>

                    <tbody>
                      ${renderRows(visibleCases)}
                    </tbody>
                  </table>
                </div>
              `
          }

          <div class="mtcm-table-bottom">
            <small>
              ${tr(
                `หน้า ${state.page} จาก ${totalPages}`,
                `Page ${state.page} of ${totalPages}`
              )}
            </small>

            ${pagination(totalPages)}
          </div>
        </div>

        <p class="mtcm-footnote">
          ${tr(
            "คะแนน Priority และระดับความเสี่ยงแสดงเฉพาะค่าที่แหล่งข้อมูลส่งมา ไม่ได้หมายถึงการตัดสินความผิด",
            "Priority and risk values are displayed only when supplied by the data source. They are not determinations of guilt."
          )}
        </p>
      </div>
    `;
  }

  async function refresh() {
    state.loading = true;
    state.error = "";
    render();

    try {
      const result =
        await window.MuleTraceAPI.getCases();

      state.cases = result.cases;
      state.source = result.source;
      state.receivedCount = result.receivedCount;
      state.limited = result.limited;
      state.page = 1;
      state.selectedId = result.cases[0]?.caseId || null;
      state.status = "all";
      state.risk = "all";

      if (typeof window.syncMuleTraceCases === "function") {
        window.syncMuleTraceCases(state.cases);
      }

    } catch (error) {
      state.error = error.message ||
        "Unknown API error.";

    } finally {
      state.loading = false;
      render();
    }
  }

  function showDemo() {
    const result =
      window.MuleTraceAPI.getDemoCases();

    state.cases = result.cases;
    state.source = "demo";
    state.receivedCount = result.receivedCount;
    state.limited = result.limited;
    state.page = 1;
    state.selectedId = null;
    state.error = "";
    state.status = "all";
    state.risk = "all";

    render();
  }

  function resetFilters() {
    state.query = "";
    state.status = "all";
    state.risk = "all";
    state.sort = "newest";
    state.page = 1;
    render();
  }

  function openExistingInvestigation(caseId, targetPage = "investigation") {
    const targetId = caseId || state.selectedId;
    if (!targetId) return;

    if (typeof window.openCaseInvestigation === "function") {
      window.openCaseInvestigation(targetId, targetPage);
      return;
    }

    const selector =
      document.querySelector("#caseSelect");

    if (selector) {
      if (![...selector.options].some(o => o.value === targetId)) {
        const opt = document.createElement("option");
        opt.value = targetId;
        opt.textContent = targetId;
        selector.appendChild(opt);
      }
      selector.value = targetId;
      selector.dispatchEvent(
        new Event("change", {
          bubbles: true
        })
      );
    }

    const navBtn =
      document.querySelector(
        `.nav-item[data-page="${targetPage}"]`
      );

    navBtn?.click();
  }

  function handleClick(event) {
    const button = event.target.closest(
      "[data-action]"
    );

    if (!button || !root.contains(button)) {
      return;
    }

    const action = button.dataset.action;

    if (action === "refresh") {
      refresh();
      return;
    }

    if (action === "demo") {
      showDemo();
      return;
    }

    if (action === "reset") {
      resetFilters();
      return;
    }

    if (action === "view") {
      state.selectedId = button.dataset.id;
      render();
      return;
    }

    if (action === "close") {
      state.selectedId = null;
      render();
      return;
    }

    if (action === "investigate") {
      openExistingInvestigation(
        button.dataset.id || state.selectedId,
        "investigation"
      );
      return;
    }

    if (action === "trail") {
      openExistingInvestigation(
        button.dataset.id || state.selectedId,
        "trail"
      );
      return;
    }

    if (action === "page") {
      const requested = Number(
        button.dataset.page
      );

      const pages = Math.max(
        1,
        Math.ceil(
          filteredCases().length / PAGE_SIZE
        )
      );

      if (
        Number.isInteger(requested) &&
        requested >= 1 &&
        requested <= pages
      ) {
        state.page = requested;
        render();
      }
    }
  }

  function handleInput(event) {
    if (
      !event.target.matches(
        '[data-field="query"]'
      )
    ) {
      return;
    }

    const position =
      event.target.selectionStart;

    state.query = event.target.value;
    state.page = 1;

    render();

    // คืน Focus เพื่อพิมพ์ค้นหาต่อได้
    const input = root.querySelector(
      '[data-field="query"]'
    );

    input?.focus();

    if (
      input &&
      position !== null
    ) {
      input.setSelectionRange(
        position,
        position
      );
    }
  }

  function handleChange(event) {
    const field = event.target.dataset.field;

    if (!field || field === "query") {
      return;
    }

    if (
      ![
        "status",
        "risk",
        "sort"
      ].includes(field)
    ) {
      return;
    }

    state[field] = event.target.value;
    state.page = 1;
    render();
  }

  function init() {
    const page = document.querySelector(
      "#page-cases"
    );

    if (!page) {
      console.warn(
        "MuleTrace Case Manager: #page-cases not found."
      );
      return;
    }

    if (!window.MuleTraceAPI) {
      console.error(
        "MuleTrace Case Manager: api.js is missing."
      );
      return;
    }

    root = document.createElement("div");
    root.id = "mt-case-manager";

    // ไม่ลบ HTML เดิม เพื่อไม่ให้ app.js พัง
    page.prepend(root);

    root.addEventListener(
      "click",
      handleClick
    );

    root.addEventListener(
      "input",
      handleInput
    );

    root.addEventListener(
      "change",
      handleChange
    );

    // เมื่อผู้ใช้กด TH / EN ให้อัปเดตหน้านี้ด้วย
    document.addEventListener(
      "click",
      event => {
        if (event.target.closest("[data-lang]")) {
          setTimeout(render, 0);
        }
      }
    );

    refresh();
  }

  window.MuleCaseManager = {
    refresh,
    getCases: () => [...state.cases],
    getSelectedCase: () =>
      state.cases.find(
        item => item.caseId === state.selectedId
      ) || null
  };

  if (document.readyState === "loading") {
    document.addEventListener(
      "DOMContentLoaded",
      init
    );
  } else {
    init();
  }
})();

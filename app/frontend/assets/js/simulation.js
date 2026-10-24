/*
  MuleTrace AI — Simulation Controller
  Controls the "Simulate Transactions" action on the Overview page.
  Submits simulation requests to /api/simulation/run, manages button states,
  and facilitates navigation to the Case Queue upon completion.
*/
(() => {
  "use strict";

  function isEnglish() {
    return window.MuleI18N?.getLanguage?.() === "en";
  }

  function getElements() {
    return {
      btn: document.getElementById("btnSimulate"),
      feedback: document.getElementById("simFeedback"),
    };
  }

  function setButtonState(state, customText) {
    const { btn } = getElements();
    if (!btn) return;

    const textEl = btn.querySelector(".sim-text");
    const iconEl = btn.querySelector(".sim-icon");

    btn.classList.remove("loading", "completed", "failed");

    if (state === "loading") {
      btn.disabled = true;
      btn.classList.add("loading");
      if (iconEl) iconEl.textContent = "⏳";
      if (textEl) textEl.textContent = customText || (isEnglish() ? "Simulating..." : "กำลังจำลอง...");
    } else if (state === "completed") {
      btn.disabled = true;
      btn.classList.add("completed");
      if (iconEl) iconEl.textContent = "✓";
      if (textEl) textEl.textContent = customText || (isEnglish() ? "Simulation completed" : "จำลองธุรกรรมสำเร็จ");
    } else if (state === "failed") {
      btn.disabled = false;
      btn.classList.add("failed");
      if (iconEl) iconEl.textContent = "⚠";
      if (textEl) textEl.textContent = customText || (isEnglish() ? "Simulation failed (Retry)" : "จำลองล้มเหลว (ลองใหม่)");
    } else {
      btn.disabled = false;
      if (iconEl) iconEl.textContent = "⚡";
      if (textEl) textEl.textContent = customText || (isEnglish() ? "Simulate Transactions" : "จำลองธุรกรรม");
    }
  }

  function showFeedback(type, message, showCaseLink) {
    const { feedback } = getElements();
    if (!feedback) return;

    feedback.hidden = false;
    feedback.className = "sim-feedback-toast " + type;

    const linkText = isEnglish() ? "View Case Queue →" : "ดู Case Queue →";
    const actionHtml = showCaseLink
      ? `<button type="button" class="toast-btn" id="btnGoCasesToast">${linkText}</button>`
      : "";

    feedback.innerHTML = `<span>${message}</span>${actionHtml}`;

    const goBtn = document.getElementById("btnGoCasesToast");
    if (goBtn) {
      goBtn.addEventListener("click", () => {
        if (typeof window.showPage === "function") {
          window.showPage("cases");
        } else {
          const navCases = document.querySelector(".nav-item[data-page='cases']");
          if (navCases) navCases.click();
        }
      });
    }
  }

  async function triggerSimulation() {
    const { btn, feedback } = getElements();
    if (!btn || btn.disabled) return;

    setButtonState("loading");
    if (feedback) feedback.hidden = true;

    try {
      const res = await fetch("/api/simulation/run", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Accept": "application/json",
        },
        credentials: "same-origin",
        body: JSON.stringify({}),
      });

      const data = await res.json().catch(() => ({}));

      if (!res.ok || data.status !== "success") {
        const errorMsg = data.message || (isEnglish() ? "Failed to trigger simulation." : "ไม่สามารถจำลองธุรกรรมได้");
        setButtonState("failed");
        showFeedback("error", errorMsg, false);
        return;
      }

      const runInfo = data.data || {};
      const count = runInfo.events_submitted || 20;
      const successMsg = isEnglish()
        ? `Simulation completed: ${count} transactions submitted to pipeline.`
        : `จำลองธุรกรรมสำเร็จ: ส่ง ${count} รายการธุรกรรมเข้าสู่ระบบ`;

      setButtonState("completed");
      showFeedback("success", successMsg, true);

      // Return button to ready state after 4 seconds
      setTimeout(() => {
        setButtonState("initial");
      }, 4000);

    } catch (err) {
      setButtonState("failed");
      const errText = isEnglish() ? "Network error during simulation." : "เกิดข้อผิดพลาดในการเชื่อมต่อ";
      showFeedback("error", errText, false);
    }
  }

  function init() {
    const { btn } = getElements();
    if (!btn) {
      console.warn("[Simulation] #btnSimulate element not found in DOM");
      return;
    }

    // Avoid duplicate listeners
    btn.removeEventListener("click", onSimulateClick);
    btn.addEventListener("click", onSimulateClick);
    console.log("[Simulation] Initialized and click listener attached to #btnSimulate");
  }

  function onSimulateClick(e) {
    e.preventDefault();
    triggerSimulation();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  // Export for testing and external trigger
  window.MuleTraceSimulation = {
    trigger: triggerSimulation,
    setButtonState: setButtonState,
    init: init,
  };
})();

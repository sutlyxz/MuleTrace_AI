
/*
  MuleTrace AI — Case Data Adapter
  รองรับ Demo Data และ Backend API
  จำกัดข้อมูลที่แสดงสูงสุด 500 เคส
  ไม่มี AWS Credentials ใน Frontend
*/

(() => {
  "use strict";

  const MAX_CASES = 500;
  const TIMEOUT_MS = 15000;

  function first(...values) {
    return values.find(
      value =>
        value !== undefined &&
        value !== null &&
        String(value).trim() !== ""
    );
  }

  function asText(value, fallback = "") {
    return String(
      value === undefined || value === null
        ? fallback
        : value
    ).trim();
  }

  function asAmount(value) {
    if (typeof value === "number") {
      return Number.isFinite(value) ? value : 0;
    }

    const cleaned = asText(value)
      .replace(/[฿,\s]/g, "");

    const result = Number(cleaned);

    return Number.isFinite(result) ? result : 0;
  }

  function normalizeRisk(value) {
    const raw = asText(value).toUpperCase();

    if (
      raw === "HIGH" ||
      raw === "CRITICAL" ||
      raw === "สูง"
    ) {
      return "HIGH";
    }

    if (
      raw === "MEDIUM" ||
      raw === "MODERATE" ||
      raw === "กลาง"
    ) {
      return "MEDIUM";
    }

    if (
      raw === "LOW" ||
      raw === "ต่ำ"
    ) {
      return "LOW";
    }

    return "UNKNOWN";
  }

  function normalizeStatus(value) {
    const raw = asText(value, "new")
      .toLowerCase()
      .replace(/[\s-]+/g, "_");

    const aliases = {
      open: "new",
      pending: "new",
      new: "new",

      in_progress: "in_progress",
      investigating: "in_progress",
      investigation: "in_progress",
      working: "in_progress",

      review: "review",
      human_review: "review",
      under_review: "review",

      closed: "closed",
      completed: "closed",
      resolved: "closed"
    };

    return aliases[raw] || raw;
  }

  function normalizeCase(record, index = 0) {
    if (!record || typeof record !== "object") {
      return null;
    }

    const caseId = asText(
      first(
        record.caseId,
        record.case_id,
        record.id,
        record.alert_id
      ),
      `CASE-${index + 1}`
    );

    const source = asText(
      first(
        record.source,
        record.source_account,
        record.sourceAccount,
        record.from,
        record.sender
      ),
      "—"
    );

    const target = asText(
      first(
        record.target,
        record.target_account,
        record.targetAccount,
        record.to,
        record.receiver
      ),
      "—"
    );

    const amount = asAmount(
      first(
        record.amount,
        record.alert_amount,
        record.alertAmount,
        0
      )
    );

    const time = asText(
      first(
        record.time,
        record.alert_time,
        record.alertTime,
        record.created_at,
        record.timestamp
      )
    );

    const scoreValue = first(
      record.priority_score,
      record.priorityScore,
      record.score
    );

    const numericScore =
      scoreValue === undefined
        ? null
        : Number(scoreValue);

    const priorityScore =
      numericScore !== null &&
      Number.isFinite(numericScore)
        ? Math.max(
            0,
            Math.min(100, numericScore)
          )
        : null;

    return {
      caseId,
      source,
      target,
      amount,
      time,

      status: normalizeStatus(
        first(
          record.status,
          record.case_status,
          "new"
        )
      ),

      risk: normalizeRisk(
        first(
          record.risk,
          record.risk_level,
          record.riskLevel
        )
      ),

      priorityScore,

      transactionId: asText(
        first(
          record.transactionId,
          record.transaction_id,
          record.alert_transaction_id
        )
      ),

      description: asText(
        first(
          record.description,
          record.notes,
          record.summary
        )
      ),

      // เก็บข้อมูลต้นฉบับให้เพื่อนนำไปใช้ต่อ
      raw: record
    };
  }

  function normalizeList(records, source) {
    if (!Array.isArray(records)) {
      throw new Error(
        "Case data must be an array."
      );
    }

    const cases = records
      .slice(0, MAX_CASES)
      .map(normalizeCase)
      .filter(Boolean);

    return {
      cases,
      source,
      receivedCount: records.length,
      limited: records.length > MAX_CASES
    };
  }

  function extractCases(payload) {
    if (Array.isArray(payload)) {
      return payload;
    }

    if (!payload || typeof payload !== "object") {
      throw new Error(
        "Invalid API response."
      );
    }

    const candidates = [
      payload.cases,
      payload.items,
      payload.results,
      payload.data,
      payload.data?.cases,
      payload.data?.items,
      payload.result?.cases
    ];

    const found = candidates.find(Array.isArray);

    if (!found) {
      throw new Error(
        "API response does not contain a cases array."
      );
    }

    return found;
  }

  function hasRemote() {
    return Boolean(
      asText(
        window.MULETRACE_CONFIG?.casesApiUrl
      )
    );
  }

  function getDemoCases() {
    const records =
      window.MULETRACE_DATA?.cases || [];

    return normalizeList(records, "demo");
  }

  async function getCases() {
    const endpoint = asText(
      window.MULETRACE_CONFIG?.casesApiUrl
    );

    if (!endpoint) {
      return getDemoCases();
    }

    const controller = new AbortController();

    const timer = setTimeout(
      () => controller.abort(),
      TIMEOUT_MS
    );

    try {
      const response = await fetch(endpoint, {
        method: "GET",
        headers: {
          Accept: "application/json"
        },
        cache: "no-store",
        signal: controller.signal
      });

      if (!response.ok) {
        throw new Error(
          `API returned HTTP ${response.status}`
        );
      }

      const payload = await response.json();

      const records = extractCases(payload);

      return normalizeList(records, "api");

    } catch (error) {
      if (error.name === "AbortError") {
        throw new Error(
          "Request timed out after 15 seconds."
        );
      }

      throw error;

    } finally {
      clearTimeout(timer);
    }
  }

  window.MuleTraceAPI = {
    MAX_CASES,
    normalizeCase,
    normalizeList,
    getDemoCases,
    getCases,
    hasRemote
  };
})();

/**
 * MuleTrace AI — Administration Portal Client
 * Handles session verification, user management, password resets,
 * activation/deactivation, and security audit log viewing.
 *
 * Security Constraints:
 * - Credentials: "same-origin" with HttpOnly cookies.
 * - Strict client-side and server-side role enforcement (role=admin).
 * - Safe DOM manipulation via textContent and createElement (Zero innerHTML injection).
 * - Passwords never stored, persisted in storage, or logged.
 */

(function () {
  "use strict";

  // Application State
  const state = {
    currentUser: null,
    users: [],
    adminUsers: [],
    officerUsers: [],
    filteredOfficers: [],
    usersTotal: 0,
    usersLimit: 25,
    usersOffset: 0,
    userSearchTerm: "",
    auditLogs: [],
    auditTotal: 0,
    auditLimit: 25,
    auditOffset: 0,
    statusTargetUser: null,
    resetTargetUser: null,
  };

  // DOM Elements Cache
  const elements = {
    // Header
    adminDisplayName: document.getElementById("adminDisplayName"),
    adminEmail: document.getElementById("adminEmail"),
    adminAvatar: document.getElementById("adminAvatar"),
    logoutBtn: document.getElementById("adminLogoutBtn"),

    // Tabs
    tabOverview: document.getElementById("tabOverview"),
    tabUsers: document.getElementById("tabUsers"),
    tabAudit: document.getElementById("tabAudit"),
    panelOverview: document.getElementById("panelOverview"),
    panelUsers: document.getElementById("panelUsers"),
    panelAudit: document.getElementById("panelAudit"),

    // Overview statistics
    statTotalOfficers: document.getElementById("statTotalOfficers"),
    statActiveOfficers: document.getElementById("statActiveOfficers"),
    statDisabledOfficers: document.getElementById("statDisabledOfficers"),
    overviewQuickCreateBtn: document.getElementById("overviewQuickCreateBtn"),
    recentAuditList: document.getElementById("recentAuditList"),

    // User Tables (Administrator & Bank Officer)
    adminUsersTableBody: document.getElementById("adminUsersTableBody"),
    usersTableBody: document.getElementById("usersTableBody"),
    usersLoadingState: document.getElementById("usersLoadingState"),
    usersEmptyState: document.getElementById("usersEmptyState"),
    usersErrorState: document.getElementById("usersErrorState"),
    usersErrorMessage: document.getElementById("usersErrorMessage"),
    usersRetryBtn: document.getElementById("usersRetryBtn"),
    userSearchInput: document.getElementById("userSearchInput"),
    refreshUsersBtn: document.getElementById("refreshUsersBtn"),
    openCreateUserModalBtn: document.getElementById("openCreateUserModalBtn"),
    emptyStateCreateBtn: document.getElementById("emptyStateCreateBtn"),
    usersPaginationInfo: document.getElementById("usersPaginationInfo"),
    usersPrevBtn: document.getElementById("usersPrevBtn"),
    usersNextBtn: document.getElementById("usersNextBtn"),
    usersBadgeCount: document.getElementById("usersBadgeCount"),

    // Create Officer Modal
    createModal: document.getElementById("createUserModal"),
    closeCreateModalBtn: document.getElementById("closeCreateModalBtn"),
    cancelCreateModalBtn: document.getElementById("cancelCreateModalBtn"),
    createForm: document.getElementById("createUserForm"),
    createSubmitBtn: document.getElementById("createSubmitBtn"),
    createFeedback: document.getElementById("createModalFeedback"),
    createDisplayName: document.getElementById("createDisplayName"),
    createEmail: document.getElementById("createEmail"),
    createPassword: document.getElementById("createPassword"),
    createConfirmPassword: document.getElementById("createConfirmPassword"),
    createPwToggle: document.getElementById("createPwToggle"),
    createConfirmPwToggle: document.getElementById("createConfirmPwToggle"),

    // Create Password Policy Items
    policyLen: document.getElementById("policyLen"),
    policyCase: document.getElementById("policyCase"),
    policyNum: document.getElementById("policyNum"),
    policySpec: document.getElementById("policySpec"),

    // Status Confirmation Modal
    statusModal: document.getElementById("statusConfirmModal"),
    closeStatusModalBtn: document.getElementById("closeStatusModalBtn"),
    cancelStatusModalBtn: document.getElementById("cancelStatusModalBtn"),
    confirmStatusBtn: document.getElementById("confirmStatusBtn"),
    statusModalTitle: document.getElementById("statusModalTitle"),
    statusModalMessage: document.getElementById("statusModalMessage"),
    statusTargetInfo: document.getElementById("statusTargetInfo"),
    statusDeactivateWarning: document.getElementById("statusDeactivateWarning"),

    // Reset Password Modal
    resetModal: document.getElementById("resetPasswordModal"),
    closeResetModalBtn: document.getElementById("closeResetModalBtn"),
    cancelResetModalBtn: document.getElementById("cancelResetModalBtn"),
    resetForm: document.getElementById("resetPasswordForm"),
    resetSubmitBtn: document.getElementById("resetSubmitBtn"),
    resetFeedback: document.getElementById("resetModalFeedback"),
    resetTargetInfo: document.getElementById("resetTargetInfo"),
    resetNewPassword: document.getElementById("resetNewPassword"),
    resetConfirmPassword: document.getElementById("resetConfirmPassword"),
    resetPwToggle: document.getElementById("resetPwToggle"),
    resetConfirmPwToggle: document.getElementById("resetConfirmPwToggle"),
    resetPolicyLen: document.getElementById("resetPolicyLen"),
    resetPolicyCase: document.getElementById("resetPolicyCase"),
    resetPolicyNum: document.getElementById("resetPolicyNum"),
    resetPolicySpec: document.getElementById("resetPolicySpec"),

    // Audit Logs
    auditTableBody: document.getElementById("auditTableBody"),
    auditLoadingState: document.getElementById("auditLoadingState"),
    auditEmptyState: document.getElementById("auditEmptyState"),
    auditErrorState: document.getElementById("auditErrorState"),
    auditErrorMessage: document.getElementById("auditErrorMessage"),
    auditRetryBtn: document.getElementById("auditRetryBtn"),
    refreshAuditBtn: document.getElementById("refreshAuditBtn"),
    auditPaginationInfo: document.getElementById("auditPaginationInfo"),
    auditPrevBtn: document.getElementById("auditPrevBtn"),
    auditNextBtn: document.getElementById("auditNextBtn"),
    auditBadgeCount: document.getElementById("auditBadgeCount"),

    // Toast Container
    toastContainer: document.getElementById("toastContainer"),
  };

  // ==========================================================================
  // Toast Notifications
  // ==========================================================================

  function showToast(message, type = "info", duration = 4000) {
    if (!elements.toastContainer) return;

    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    toast.setAttribute("role", "status");
    toast.setAttribute("aria-live", "polite");

    const iconSpan = document.createElement("span");
    iconSpan.setAttribute("aria-hidden", "true");
    if (type === "success") iconSpan.textContent = "✓";
    else if (type === "error") iconSpan.textContent = "⚠";
    else iconSpan.textContent = "ℹ";

    const textSpan = document.createElement("span");
    textSpan.textContent = message;

    toast.appendChild(iconSpan);
    toast.appendChild(textSpan);
    elements.toastContainer.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = "0";
      toast.style.transform = "translateY(10px)";
      toast.style.transition = "all 0.2s ease-out";
      setTimeout(() => {
        if (toast.parentNode) {
          toast.parentNode.removeChild(toast);
        }
      }, 200);
    }, duration);
  }

  // ==========================================================================
  // Password Policy Checker (Matches backend security.py)
  // ==========================================================================

  function evaluatePassword(pwd) {
    const s = String(pwd || "");
    const hasLen = s.length >= 10;
    const hasUpper = /[A-Z]/.test(s);
    const hasLower = /[a-z]/.test(s);
    const hasNum = /[0-9]/.test(s);
    const hasSpec = /[!@#$%^&*()\-_=+\[\]{}|;:,.<>?]/.test(s);

    return {
      isValid: hasLen && hasUpper && hasLower && hasNum && hasSpec,
      hasLen,
      hasCase: hasUpper && hasLower,
      hasNum,
      hasSpec,
    };
  }

  function updatePolicyChecklist(evalResult, elLen, elCase, elNum, elSpec) {
    if (!elLen) return;
    elLen.className = `policy-item ${evalResult.hasLen ? "valid" : ""}`;
    elCase.className = `policy-item ${evalResult.hasCase ? "valid" : ""}`;
    elNum.className = `policy-item ${evalResult.hasNum ? "valid" : ""}`;
    elSpec.className = `policy-item ${evalResult.hasSpec ? "valid" : ""}`;
  }

  // ==========================================================================
  // Session & Authentication Verification
  // ==========================================================================

  async function verifySession() {
    try {
      const res = await fetch("/api/auth/me", {
        method: "GET",
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });

      if (!res.ok) {
        window.location.replace("login.html");
        return;
      }

      const data = await res.json();
      if (data && data.status === "success" && data.user) {
        if (data.user.role !== "admin") {
          // Bank Officer should not access Admin Portal; redirect safely
          window.location.replace("index.html");
          return;
        }

        state.currentUser = data.user;
        updateHeaderUI(data.user);

        // Load initial data
        loadUsersData();
        loadAuditData();
      } else {
        window.location.replace("login.html");
      }
    } catch (err) {
      window.location.replace("login.html");
    }
  }

  function updateHeaderUI(user) {
    const name = user.display_name || user.email.split("@")[0];
    if (elements.adminDisplayName) {
      elements.adminDisplayName.textContent = name;
    }
    if (elements.adminEmail) {
      elements.adminEmail.textContent = user.email;
    }
    if (elements.adminAvatar) {
      elements.adminAvatar.textContent = name.charAt(0).toUpperCase();
    }
  }

  // ==========================================================================
  // Tab Navigation Handling
  // ==========================================================================

  function switchTab(targetTab) {
    const tabs = [
      { btn: elements.tabOverview, panel: elements.panelOverview, id: "overview" },
      { btn: elements.tabUsers, panel: elements.panelUsers, id: "users" },
      { btn: elements.tabAudit, panel: elements.panelAudit, id: "audit" },
    ];

    tabs.forEach(({ btn, panel, id }) => {
      const isActive = id === targetTab;
      if (btn) {
        btn.classList.toggle("active", isActive);
        btn.setAttribute("aria-selected", isActive ? "true" : "false");
      }
      if (panel) {
        panel.classList.toggle("active", isActive);
      }
    });
  }

  // ==========================================================================
  // User Management & Statistics
  // ==========================================================================

  async function loadUsersData(offset = 0) {
    state.usersOffset = offset;
    showUsersLoading(true);

    try {
      const res = await fetch(`/api/admin/users?limit=${state.usersLimit}&offset=${state.usersOffset}`, {
        method: "GET",
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });

      if (res.status === 401) {
        window.location.replace("login.html");
        return;
      }
      if (res.status === 403) {
        showUsersError("การเข้าถึงถูกปฏิเสธ: ต้องใช้สิทธิ์ผู้ดูแลระบบ (Admin authorization required)");
        return;
      }
      if (!res.ok) {
        showUsersError("ไม่สามารถดึงข้อมูลบัญชีผู้ใช้ได้ กรุณาลองใหม่อีกครั้ง");
        return;
      }

      const data = await res.json();
      if (data && data.status === "success") {
        state.users = Array.isArray(data.users) ? data.users : [];
        state.usersTotal = typeof data.total === "number" ? data.total : state.users.length;
        state.adminUsers = state.users.filter((user) => user.role === "admin");
        state.officerUsers = state.users.filter((user) => user.role === "user");
        renderAdminUsersTable();
        applyUserFilter();
        updateOverviewStats();
        showUsersLoading(false);
      } else {
        showUsersError(data.message || "รูปแบบข้อมูลที่ได้รับไม่ถูกต้อง");
      }
    } catch (err) {
      showUsersError("เกิดข้อผิดพลาดในการเชื่อมต่อเซิร์ฟเวอร์ กรุณาตรวจสอบเครือข่าย");
    }
  }

  function renderAdminUsersTable() {
    if (!elements.adminUsersTableBody) return;
    elements.adminUsersTableBody.textContent = "";

    if (state.adminUsers.length === 0) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 6;
      td.className = "state-desc";
      td.style.textAlign = "center";
      td.style.padding = "20px";
      td.textContent = "ไม่พบบัญชีผู้ดูแลระบบในชุดข้อมูลปัจจุบัน";
      tr.appendChild(td);
      elements.adminUsersTableBody.appendChild(tr);
      return;
    }

    state.adminUsers.forEach((user) => {
      const tr = document.createElement("tr");

      // 1. Display Name
      const tdName = document.createElement("td");
      tdName.className = "col-admin-name";
      const nameStrong = document.createElement("strong");
      nameStrong.textContent = user.display_name || "—";
      tdName.appendChild(nameStrong);
      tr.appendChild(tdName);

      // 2. Email
      const tdEmail = document.createElement("td");
      tdEmail.className = "col-admin-email";
      tdEmail.textContent = user.email || "—";
      tr.appendChild(tdEmail);

      // 3. Role
      const tdRole = document.createElement("td");
      tdRole.className = "col-admin-role";
      const roleBadge = document.createElement("span");
      roleBadge.className = "badge badge-admin";
      roleBadge.textContent = "Administrator";
      tdRole.appendChild(roleBadge);
      tr.appendChild(tdRole);

      // 4. Status
      const tdStatus = document.createElement("td");
      tdStatus.className = "col-admin-status";
      const statusBadge = document.createElement("span");
      const dot = document.createElement("span");
      dot.className = "badge-dot";
      dot.setAttribute("aria-hidden", "true");

      if (user.is_active) {
        statusBadge.className = "badge badge-active";
        statusBadge.appendChild(dot);
        statusBadge.appendChild(document.createTextNode(" เปิดใช้งาน (Active)"));
      } else {
        statusBadge.className = "badge badge-disabled";
        statusBadge.appendChild(dot);
        statusBadge.appendChild(document.createTextNode(" ระงับการใช้งาน (Disabled)"));
      }
      tdStatus.appendChild(statusBadge);
      tr.appendChild(tdStatus);

      // 5. Created Date
      const tdCreated = document.createElement("td");
      tdCreated.className = "col-admin-created";
      tdCreated.textContent = formatDateTime(user.created_at);
      tr.appendChild(tdCreated);

      // 6. Protection Indicator (Strictly read-only, NO mutation controls)
      const tdProtect = document.createElement("td");
      tdProtect.className = "col-admin-protect";
      const protectBadge = document.createElement("span");
      protectBadge.className = "badge badge-protected";
      protectBadge.textContent = "🛡️ สงวนสิทธิ์ระบบ (Protected)";
      tdProtect.appendChild(protectBadge);
      tr.appendChild(tdProtect);

      elements.adminUsersTableBody.appendChild(tr);
    });
  }

  function applyUserFilter() {
    const term = state.userSearchTerm.trim().toLowerCase();
    if (!term) {
      state.filteredOfficers = state.officerUsers.slice();
    } else {
      state.filteredOfficers = state.officerUsers.filter((u) => {
        const email = String(u.email || "").toLowerCase();
        const dname = String(u.display_name || "").toLowerCase();
        const status = u.is_active ? "active เปิดใช้งาน" : "disabled ระงับ";
        return (
          email.includes(term) ||
          dname.includes(term) ||
          status.includes(term)
        );
      });
    }
    renderUsersTable();
    updateUsersPagination();
  }

  function renderUsersTable() {
    if (!elements.usersTableBody) return;
    elements.usersTableBody.textContent = ""; // Clear existing safely

    // Check if there are no Bank Officer accounts loaded
    if (state.officerUsers.length === 0) {
      showUsersEmpty(true);
      return;
    }
    showUsersEmpty(false);

    // If search term filtered out all officers
    if (state.filteredOfficers.length === 0) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 7;
      td.className = "state-desc";
      td.style.textAlign = "center";
      td.style.padding = "24px";
      td.textContent = `ไม่พบบัญชีเจ้าหน้าที่ธนาคารที่ตรงกับคำค้นหา "${state.userSearchTerm}"`;
      tr.appendChild(td);
      elements.usersTableBody.appendChild(tr);
      return;
    }

    state.filteredOfficers.forEach((user) => {
      // Security defense-in-depth: Administrator accounts must never render in this table
      if (user.role !== "user") return;

      const tr = document.createElement("tr");

      // 1. Display Name
      const tdName = document.createElement("td");
      tdName.className = "col-officer-name";
      const nameStrong = document.createElement("strong");
      nameStrong.textContent = user.display_name || "—";
      tdName.appendChild(nameStrong);
      tr.appendChild(tdName);

      // 2. Email
      const tdEmail = document.createElement("td");
      tdEmail.className = "col-officer-email";
      tdEmail.textContent = user.email || "—";
      tr.appendChild(tdEmail);

      // 3. Role
      const tdRole = document.createElement("td");
      tdRole.className = "col-officer-role";
      const roleBadge = document.createElement("span");
      roleBadge.className = "badge badge-user";
      roleBadge.textContent = "Bank Officer";
      tdRole.appendChild(roleBadge);
      tr.appendChild(tdRole);

      // 4. Status
      const tdStatus = document.createElement("td");
      tdStatus.className = "col-officer-status";
      const statusBadge = document.createElement("span");
      const dot = document.createElement("span");
      dot.className = "badge-dot";
      dot.setAttribute("aria-hidden", "true");

      if (user.is_active) {
        statusBadge.className = "badge badge-active";
        statusBadge.appendChild(dot);
        statusBadge.appendChild(document.createTextNode(" เปิดใช้งาน (Active)"));
      } else {
        statusBadge.className = "badge badge-disabled";
        statusBadge.appendChild(dot);
        statusBadge.appendChild(document.createTextNode(" ระงับการใช้งาน (Disabled)"));
      }
      tdStatus.appendChild(statusBadge);
      tr.appendChild(tdStatus);

      // 5. Created Date
      const tdCreated = document.createElement("td");
      tdCreated.className = "col-officer-created";
      tdCreated.textContent = formatDateTime(user.created_at);
      tr.appendChild(tdCreated);

      // 6. Last Login Date
      const tdLogin = document.createElement("td");
      tdLogin.className = "col-officer-login";
      tdLogin.textContent = formatDateTime(user.last_login_at) || "ยังไม่เคยเข้าสู่ระบบ";
      tr.appendChild(tdLogin);

      // 7. Actions (Activate/Deactivate Toggle & Reset Password)
      const tdActions = document.createElement("td");
      tdActions.className = "col-officer-actions";
      const actionGroup = document.createElement("div");
      actionGroup.className = "actions-cell";

      const toggleBtn = document.createElement("button");
      toggleBtn.type = "button";
      if (user.is_active) {
        toggleBtn.className = "btn btn-outline-danger";
        toggleBtn.textContent = "ระงับการใช้งาน";
        toggleBtn.setAttribute("aria-label", `ระงับบัญชี ${user.email}`);
      } else {
        toggleBtn.className = "btn btn-outline-success";
        toggleBtn.textContent = "เปิดใช้งาน";
        toggleBtn.setAttribute("aria-label", `เปิดใช้งานบัญชี ${user.email}`);
      }
      toggleBtn.addEventListener("click", () => openStatusModal(user));
      actionGroup.appendChild(toggleBtn);

      const resetBtn = document.createElement("button");
      resetBtn.type = "button";
      resetBtn.className = "btn btn-secondary";
      resetBtn.textContent = "รีเซ็ตรหัสผ่าน";
      resetBtn.setAttribute("aria-label", `รีเซ็ตรหัสผ่านบัญชี ${user.email}`);
      resetBtn.addEventListener("click", () => openResetModal(user));
      actionGroup.appendChild(resetBtn);

      tdActions.appendChild(actionGroup);
      tr.appendChild(tdActions);

      elements.usersTableBody.appendChild(tr);
    });
  }

  function updateOverviewStats() {
    // Exclude Admin accounts from Bank Officer statistics
    const officers = state.users.filter((u) => u.role === "user");
    const active = officers.filter((u) => u.is_active).length;
    const disabled = officers.filter((u) => !u.is_active).length;

    if (elements.statTotalOfficers) {
      elements.statTotalOfficers.textContent = officers.length;
    }
    if (elements.statActiveOfficers) {
      elements.statActiveOfficers.textContent = active;
    }
    if (elements.statDisabledOfficers) {
      elements.statDisabledOfficers.textContent = disabled;
    }
    if (elements.usersBadgeCount) {
      elements.usersBadgeCount.textContent = officers.length;
    }
  }

  function updateUsersPagination() {
    const total = state.usersTotal;
    const officerCountOnPage = state.officerUsers.length;
    const filteredCount = state.filteredOfficers.length;

    if (elements.usersPaginationInfo) {
      if (state.userSearchTerm.trim()) {
        elements.usersPaginationInfo.textContent = `ผลการค้นหา: ${filteredCount} จาก ${officerCountOnPage} บัญชีเจ้าหน้าที่ (ในหน้านี้)`;
      } else if (total <= state.usersLimit) {
        elements.usersPaginationInfo.textContent = `แสดง ${officerCountOnPage} บัญชีเจ้าหน้าที่ธนาคาร`;
      } else {
        const pageNum = Math.floor(state.usersOffset / state.usersLimit) + 1;
        const totalPages = Math.ceil(total / state.usersLimit) || 1;
        elements.usersPaginationInfo.textContent = `แสดง ${officerCountOnPage} บัญชีเจ้าหน้าที่ในหน้านี้ (หน้า ${pageNum}/${totalPages})`;
      }
    }
    if (elements.usersPrevBtn) {
      elements.usersPrevBtn.disabled = state.usersOffset === 0;
    }
    if (elements.usersNextBtn) {
      elements.usersNextBtn.disabled = state.usersOffset + state.usersLimit >= total;
    }
  }

  function showUsersLoading(isLoading) {
    if (elements.usersLoadingState) {
      elements.usersLoadingState.style.display = isLoading ? "flex" : "none";
    }
    if (elements.usersTableBody) {
      elements.usersTableBody.style.display = isLoading ? "none" : "";
    }
    if (elements.usersEmptyState) elements.usersEmptyState.style.display = "none";
    if (elements.usersErrorState) elements.usersErrorState.style.display = "none";
  }

  function showUsersEmpty(isEmpty) {
    if (elements.usersEmptyState) {
      elements.usersEmptyState.style.display = isEmpty ? "flex" : "none";
    }
  }

  function showUsersError(msg) {
    showUsersLoading(false);
    if (elements.usersErrorState) {
      elements.usersErrorState.style.display = "flex";
    }
    if (elements.usersErrorMessage) {
      elements.usersErrorMessage.textContent = msg;
    }
    if (elements.usersTableBody) {
      elements.usersTableBody.textContent = "";
    }
  }

  // ==========================================================================
  // Create Bank Officer Modal Flow
  // ==========================================================================

  function openCreateModal() {
    clearCreateForm();
    if (elements.createModal) {
      elements.createModal.classList.add("open");
      const bodyEl = elements.createModal.querySelector(".modal-body");
      if (bodyEl) bodyEl.scrollTop = 0;
      if (elements.createDisplayName) elements.createDisplayName.focus();
    }
  }

  function closeCreateModal() {
    clearCreateForm();
    if (elements.createModal) {
      elements.createModal.classList.remove("open");
    }
  }

  function clearCreateForm() {
    if (elements.createForm) elements.createForm.reset();
    if (elements.createPassword) elements.createPassword.type = "password";
    if (elements.createConfirmPassword) elements.createConfirmPassword.type = "password";
    if (elements.createFeedback) {
      elements.createFeedback.className = "modal-feedback";
      elements.createFeedback.textContent = "";
      elements.createFeedback.style.display = "none";
    }
    if (elements.createSubmitBtn) {
      elements.createSubmitBtn.disabled = false;
      elements.createSubmitBtn.textContent = "สร้างบัญชีเจ้าหน้าที่";
    }
    updatePolicyChecklist(
      evaluatePassword(""),
      elements.policyLen,
      elements.policyCase,
      elements.policyNum,
      elements.policySpec
    );
  }

  async function handleCreateOfficer(e) {
    e.preventDefault();
    const dname = (elements.createDisplayName?.value || "").trim();
    const email = (elements.createEmail?.value || "").trim();
    const pwd = elements.createPassword?.value || "";
    const cpwd = elements.createConfirmPassword?.value || "";

    // 1. Validate Email
    if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      showCreateFeedback("กรุณากรอกอีเมลที่ถูกต้อง (Invalid email format)", "error");
      return;
    }

    // 2. Validate Password policy
    const policy = evaluatePassword(pwd);
    if (!policy.isValid) {
      showCreateFeedback("รหัสผ่านไม่ตรงตามนโยบายความปลอดภัยที่กำหนด", "error");
      return;
    }

    // 3. Confirm password matches
    if (pwd !== cpwd) {
      showCreateFeedback("รหัสผ่านและยืนยันรหัสผ่านไม่ตรงกัน", "error");
      return;
    }

    // Submit to server
    if (elements.createSubmitBtn) {
      elements.createSubmitBtn.disabled = true;
      elements.createSubmitBtn.textContent = "กำลังสร้างบัญชี...";
    }

    try {
      const res = await fetch("/api/admin/users", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        // Role is fixed to "user" on server and client
        body: JSON.stringify({
          email,
          password: pwd,
          display_name: dname || email.split("@")[0],
          role: "user",
        }),
      });

      const data = await res.json();
      if (res.status === 201 && data && data.status === "success") {
        showToast(`สร้างบัญชีเจ้าหน้าที่ ${email} เรียบร้อยแล้ว`, "success");
        closeCreateModal();
        loadUsersData(state.usersOffset);
        loadAuditData(); // Refresh audit logs
      } else if (res.status === 409) {
        showCreateFeedback(`อีเมล '${email}' มีอยู่ในระบบแล้ว กรุณาใช้อีเมลอื่น`, "error");
      } else if (res.status === 403) {
        showCreateFeedback(data.message || "ไม่มีสิทธิ์ในการสร้างบัญชี หรือล้มเหลวในการตรวจสอบ CSRF", "error");
      } else {
        showCreateFeedback(data.message || "ไม่สามารถสร้างบัญชีได้ กรุณาตรวจสอบข้อมูล", "error");
      }
    } catch (err) {
      showCreateFeedback("เกิดข้อผิดพลาดในการเชื่อมต่อเซิร์ฟเวอร์", "error");
    } finally {
      if (elements.createSubmitBtn) {
        elements.createSubmitBtn.disabled = false;
        elements.createSubmitBtn.textContent = "สร้างบัญชีเจ้าหน้าที่";
      }
    }
  }

  function showCreateFeedback(msg, type) {
    if (!elements.createFeedback) return;
    elements.createFeedback.className = `modal-feedback ${type}`;
    elements.createFeedback.textContent = msg;
    elements.createFeedback.style.display = "block";
  }

  // ==========================================================================
  // Activate / Deactivate Status Modal Flow
  // ==========================================================================

  function openStatusModal(user) {
    state.statusTargetUser = user;
    const isActivating = !user.is_active;

    if (elements.statusModalTitle) {
      elements.statusModalTitle.textContent = isActivating
        ? "ยืนยันการเปิดใช้งานบัญชีเจ้าหน้าที่"
        : "ยืนยันการระงับการใช้งานบัญชีเจ้าหน้าที่";
    }

    if (elements.statusTargetInfo) {
      elements.statusTargetInfo.textContent = `${user.display_name || "เจ้าหน้าที่"} (${user.email})`;
    }

    if (elements.statusDeactivateWarning) {
      elements.statusDeactivateWarning.style.display = isActivating ? "none" : "block";
    }

    if (elements.confirmStatusBtn) {
      elements.confirmStatusBtn.textContent = isActivating ? "เปิดใช้งานบัญชี" : "ระงับการใช้งานทันที";
      elements.confirmStatusBtn.className = isActivating ? "btn btn-primary" : "btn btn-outline-danger";
      elements.confirmStatusBtn.disabled = false;
    }

    if (elements.statusModal) {
      elements.statusModal.classList.add("open");
      const bodyEl = elements.statusModal.querySelector(".modal-body");
      if (bodyEl) bodyEl.scrollTop = 0;
    }
  }

  function closeStatusModal() {
    state.statusTargetUser = null;
    if (elements.statusModal) {
      elements.statusModal.classList.remove("open");
    }
  }

  async function handleConfirmStatus() {
    if (!state.statusTargetUser) return;
    const target = state.statusTargetUser;
    const newStatus = !target.is_active;

    if (elements.confirmStatusBtn) {
      elements.confirmStatusBtn.disabled = true;
      elements.confirmStatusBtn.textContent = "กำลังดำเนินการ...";
    }

    try {
      const res = await fetch(`/api/admin/users/${encodeURIComponent(target.id)}/status`, {
        method: "PATCH",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify({ is_active: newStatus }),
      });

      const data = await res.json();
      if (res.ok && data && data.status === "success") {
        const actionLabel = newStatus ? "เปิดใช้งาน" : "ระงับการใช้งาน";
        showToast(`${actionLabel}บัญชี ${target.email} เรียบร้อยแล้ว`, "success");
        closeStatusModal();
        loadUsersData(state.usersOffset);
        loadAuditData();
      } else {
        showToast(data.message || "เกิดข้อผิดพลาดในการปรับปรุงสถานะ", "error");
      }
    } catch (err) {
      showToast("เกิดข้อผิดพลาดในการเชื่อมต่อเซิร์ฟเวอร์", "error");
    } finally {
      if (elements.confirmStatusBtn) {
        elements.confirmStatusBtn.disabled = false;
      }
    }
  }

  // ==========================================================================
  // Reset Password Modal Flow
  // ==========================================================================

  function openResetModal(user) {
    state.resetTargetUser = user;
    clearResetForm();

    if (elements.resetTargetInfo) {
      elements.resetTargetInfo.textContent = `${user.display_name || "เจ้าหน้าที่"} (${user.email})`;
    }

    if (elements.resetModal) {
      elements.resetModal.classList.add("open");
      const bodyEl = elements.resetModal.querySelector(".modal-body");
      if (bodyEl) bodyEl.scrollTop = 0;
      if (elements.resetNewPassword) elements.resetNewPassword.focus();
    }
  }

  function closeResetModal() {
    state.resetTargetUser = null;
    clearResetForm();
    if (elements.resetModal) {
      elements.resetModal.classList.remove("open");
    }
  }

  function clearResetForm() {
    if (elements.resetForm) elements.resetForm.reset();
    if (elements.resetNewPassword) elements.resetNewPassword.type = "password";
    if (elements.resetConfirmPassword) elements.resetConfirmPassword.type = "password";
    if (elements.resetFeedback) {
      elements.resetFeedback.className = "modal-feedback";
      elements.resetFeedback.textContent = "";
      elements.resetFeedback.style.display = "none";
    }
    if (elements.resetSubmitBtn) {
      elements.resetSubmitBtn.disabled = false;
      elements.resetSubmitBtn.textContent = "บันทึกรหัสผ่านใหม่";
    }
    updatePolicyChecklist(
      evaluatePassword(""),
      elements.resetPolicyLen,
      elements.resetPolicyCase,
      elements.resetPolicyNum,
      elements.resetPolicySpec
    );
  }

  async function handleResetPassword(e) {
    e.preventDefault();
    if (!state.resetTargetUser) return;
    const target = state.resetTargetUser;
    const newPwd = elements.resetNewPassword?.value || "";
    const confirmPwd = elements.resetConfirmPassword?.value || "";

    const policy = evaluatePassword(newPwd);
    if (!policy.isValid) {
      showResetFeedback("รหัสผ่านใหม่ไม่ตรงตามนโยบายความปลอดภัย", "error");
      return;
    }

    if (newPwd !== confirmPwd) {
      showResetFeedback("รหัสผ่านใหม่และยืนยันรหัสผ่านไม่ตรงกัน", "error");
      return;
    }

    if (elements.resetSubmitBtn) {
      elements.resetSubmitBtn.disabled = true;
      elements.resetSubmitBtn.textContent = "กำลังรีเซ็ตรหัสผ่าน...";
    }

    try {
      const res = await fetch(`/api/admin/users/${encodeURIComponent(target.id)}/reset-password`, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify({ new_password: newPwd }),
      });

      const data = await res.json();
      if (res.ok && data && data.status === "success") {
        showToast(`รีเซ็ตรหัสผ่านของ ${target.email} เรียบร้อยแล้ว (เซสชันเดิมถูกเพิกถอน)`, "success");
        closeResetModal();
        loadAuditData();
      } else {
        showResetFeedback(data.message || "ไม่สามารถรีเซ็ตรหัสผ่านได้", "error");
      }
    } catch (err) {
      showResetFeedback("เกิดข้อผิดพลาดในการเชื่อมต่อเซิร์ฟเวอร์", "error");
    } finally {
      if (elements.resetSubmitBtn) {
        elements.resetSubmitBtn.disabled = false;
        elements.resetSubmitBtn.textContent = "บันทึกรหัสผ่านใหม่";
      }
    }
  }

  function showResetFeedback(msg, type) {
    if (!elements.resetFeedback) return;
    elements.resetFeedback.className = `modal-feedback ${type}`;
    elements.resetFeedback.textContent = msg;
    elements.resetFeedback.style.display = "block";
  }

  // ==========================================================================
  // Security Audit Log Viewer
  // ==========================================================================

  async function loadAuditData(offset = 0) {
    state.auditOffset = offset;
    showAuditLoading(true);

    try {
      const res = await fetch(`/api/admin/audit-logs?limit=${state.auditLimit}&offset=${state.auditOffset}`, {
        method: "GET",
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });

      if (res.status === 401) {
        window.location.replace("login.html");
        return;
      }
      if (res.status === 403) {
        showAuditError("การเข้าถึงถูกปฏิเสธ: ต้องใช้สิทธิ์ผู้ดูแลระบบ");
        return;
      }
      if (!res.ok) {
        showAuditError("ไม่สามารถดึงข้อมูลบันทึกความปลอดภัยได้");
        return;
      }

      const data = await res.json();
      if (data && data.status === "success") {
        state.auditLogs = Array.isArray(data.audit_logs)
          ? data.audit_logs
          : Array.isArray(data.logs)
          ? data.logs
          : [];
        state.auditTotal = typeof data.total === "number" ? data.total : state.auditLogs.length;

        renderAuditTable();
        updateAuditPagination();
        updateRecentAuditHighlights();
        showAuditLoading(false);
      } else {
        showAuditError(data.message || "รูปแบบข้อมูลบันทึกความปลอดภัยไม่ถูกต้อง");
      }
    } catch (err) {
      showAuditError("เกิดข้อผิดพลาดในการเชื่อมต่อเซิร์ฟเวอร์");
    }
  }

  function renderAuditTable() {
    if (!elements.auditTableBody) return;
    elements.auditTableBody.textContent = "";

    if (state.auditLogs.length === 0) {
      showAuditEmpty(true);
      return;
    }
    showAuditEmpty(false);

    state.auditLogs.forEach((log) => {
      const tr = document.createElement("tr");

      // 1. Timestamp
      const tdTime = document.createElement("td");
      tdTime.textContent = formatDateTime(log.created_at || log.timestamp);
      tr.appendChild(tdTime);

      // 2. Action
      const tdAction = document.createElement("td");
      const actionBadge = createActionBadge(log.action);
      tdAction.appendChild(actionBadge);
      tr.appendChild(tdAction);

      // 3. Actor ID
      const tdActor = document.createElement("td");
      const actorCode = document.createElement("code");
      actorCode.textContent = formatId(log.actor_user_id || log.actor_id);
      tdActor.appendChild(actorCode);
      tr.appendChild(tdActor);

      // 4. Target ID
      const tdTarget = document.createElement("td");
      if (log.target_user_id) {
        const targetCode = document.createElement("code");
        targetCode.textContent = formatId(log.target_user_id);
        tdTarget.appendChild(targetCode);
      } else {
        tdTarget.textContent = "—";
      }
      tr.appendChild(tdTarget);

      // 5. Details / Safe Metadata
      const tdDetails = document.createElement("td");
      tdDetails.textContent = formatSafeMetadata(log.safe_metadata);
      tr.appendChild(tdDetails);

      elements.auditTableBody.appendChild(tr);
    });
  }

  function createActionBadge(rawAction) {
    const badge = document.createElement("span");
    badge.className = "badge";

    const dot = document.createElement("span");
    dot.className = "badge-dot";
    dot.setAttribute("aria-hidden", "true");
    badge.appendChild(dot);

    const action = String(rawAction || "").toLowerCase();
    let text = rawAction;

    if (action === "user_created") {
      badge.classList.add("badge-active");
      text = "สร้างบัญชีผู้ใช้ (user_created)";
    } else if (action === "user_activated") {
      badge.classList.add("badge-active");
      text = "เปิดใช้งานบัญชี (user_activated)";
    } else if (action === "user_deactivated") {
      badge.classList.add("badge-disabled");
      text = "ระงับการใช้งาน (user_deactivated)";
    } else if (action === "password_reset") {
      badge.classList.add("badge-admin");
      text = "รีเซ็ตรหัสผ่าน (password_reset)";
    } else if (action === "admin_bootstrap") {
      badge.classList.add("badge-admin");
      text = "ติดตั้งระบบครั้งแรก (admin_bootstrap)";
    } else if (action === "login_success") {
      badge.classList.add("badge-user");
      text = "เข้าสู่ระบบสำเร็จ (login_success)";
    } else if (action.includes("failure")) {
      badge.classList.add("badge-disabled");
      text = "เข้าสู่ระบบล้มเหลว (login_failure)";
    } else {
      badge.classList.add("badge-protected");
    }

    badge.appendChild(document.createTextNode(` ${text}`));
    return badge;
  }

  function formatSafeMetadata(meta) {
    if (!meta || typeof meta !== "object") return "—";
    const parts = [];
    if (meta.email) parts.push(`อีเมล: ${meta.email}`);
    if (meta.role) parts.push(`บทบาท: ${meta.role}`);
    if (typeof meta.is_active === "boolean") parts.push(`สถานะ: ${meta.is_active ? "เปิด" : "ปิด"}`);
    if (meta.revoked_sessions) parts.push(`เพิกถอนเซสชัน: ${meta.revoked_sessions}`);
    if (meta.ip) parts.push(`IP: ${meta.ip}`);
    if (meta.reason) parts.push(`เหตุผล: ${meta.reason}`);

    return parts.length > 0 ? parts.join(" | ") : JSON.stringify(meta);
  }

  function updateRecentAuditHighlights() {
    if (!elements.recentAuditList) return;
    elements.recentAuditList.textContent = "";

    const recent = state.auditLogs.slice(0, 5);
    if (recent.length === 0) {
      const li = document.createElement("li");
      li.className = "state-desc";
      li.textContent = "ยังไม่มีประวัติกิจกรรมล่าสุด";
      elements.recentAuditList.appendChild(li);
      return;
    }

    recent.forEach((item) => {
      const li = document.createElement("li");
      li.style.padding = "8px 0";
      li.style.borderBottom = "1px solid var(--line)";
      li.style.display = "flex";
      li.style.justifyContent = "space-between";
      li.style.alignItems = "center";
      li.style.fontSize = "13px";

      const left = document.createElement("div");
      left.style.display = "flex";
      left.style.alignItems = "center";
      left.style.gap = "8px";
      left.appendChild(createActionBadge(item.action));

      const right = document.createElement("span");
      right.style.color = "var(--muted)";
      right.style.fontSize = "12px";
      right.textContent = formatDateTime(item.created_at || item.timestamp);

      li.appendChild(left);
      li.appendChild(right);
      elements.recentAuditList.appendChild(li);
    });

    if (elements.auditBadgeCount) {
      elements.auditBadgeCount.textContent = state.auditTotal;
    }
  }

  function updateAuditPagination() {
    const total = state.auditTotal;
    const start = total === 0 ? 0 : state.auditOffset + 1;
    const end = Math.min(state.auditOffset + state.auditLimit, total);

    if (elements.auditPaginationInfo) {
      elements.auditPaginationInfo.textContent = `แสดง ${start} - ${end} จาก ${total} บันทึก`;
    }
    if (elements.auditPrevBtn) {
      elements.auditPrevBtn.disabled = state.auditOffset === 0;
    }
    if (elements.auditNextBtn) {
      elements.auditNextBtn.disabled = state.auditOffset + state.auditLimit >= total;
    }
  }

  function showAuditLoading(isLoading) {
    if (elements.auditLoadingState) {
      elements.auditLoadingState.style.display = isLoading ? "flex" : "none";
    }
    if (elements.auditTableBody) {
      elements.auditTableBody.style.display = isLoading ? "none" : "";
    }
    if (elements.auditEmptyState) elements.auditEmptyState.style.display = "none";
    if (elements.auditErrorState) elements.auditErrorState.style.display = "none";
  }

  function showAuditEmpty(isEmpty) {
    if (elements.auditEmptyState) {
      elements.auditEmptyState.style.display = isEmpty ? "flex" : "none";
    }
  }

  function showAuditError(msg) {
    showAuditLoading(false);
    if (elements.auditErrorState) {
      elements.auditErrorState.style.display = "flex";
    }
    if (elements.auditErrorMessage) {
      elements.auditErrorMessage.textContent = msg;
    }
    if (elements.auditTableBody) {
      elements.auditTableBody.textContent = "";
    }
  }

  // ==========================================================================
  // Logout Handler
  // ==========================================================================

  async function handleLogout() {
    if (elements.logoutBtn) {
      elements.logoutBtn.disabled = true;
      elements.logoutBtn.textContent = "กำลังออกจากระบบ...";
    }

    try {
      await fetch("/api/auth/logout", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
      });
    } catch (e) {
      // Proceed to login redirect on network failure
    }
    window.location.replace("login.html");
  }

  // ==========================================================================
  // Formatters & Utilities
  // ==========================================================================

  function formatDateTime(isoString) {
    if (!isoString) return "";
    try {
      const d = new Date(isoString);
      if (isNaN(d.getTime())) return isoString;
      return d.toLocaleString("th-TH", {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return isoString;
    }
  }

  function formatId(id) {
    if (!id) return "—";
    if (id.length <= 16) return id;
    return id.substring(0, 14) + "…";
  }

  function togglePasswordVisibility(inputEl, btnEl) {
    if (!inputEl) return;
    const isPassword = inputEl.type === "password";
    inputEl.type = isPassword ? "text" : "password";
    if (btnEl) {
      btnEl.setAttribute("aria-label", isPassword ? "ซ่อนรหัสผ่าน" : "แสดงรหัสผ่าน");
      btnEl.innerHTML = isPassword
        ? `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path><line x1="1" y1="1" x2="23" y2="23"></line></svg>`
        : `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>`;
    }
  }

  // ==========================================================================
  // Event Listeners Binding
  // ==========================================================================

  function bindEvents() {
    // Logout
    if (elements.logoutBtn) {
      elements.logoutBtn.addEventListener("click", handleLogout);
    }

    // Tabs
    if (elements.tabOverview) {
      elements.tabOverview.addEventListener("click", () => switchTab("overview"));
    }
    if (elements.tabUsers) {
      elements.tabUsers.addEventListener("click", () => switchTab("users"));
    }
    if (elements.tabAudit) {
      elements.tabAudit.addEventListener("click", () => switchTab("audit"));
    }

    // Overview Quick Create Button
    if (elements.overviewQuickCreateBtn) {
      elements.overviewQuickCreateBtn.addEventListener("click", () => {
        switchTab("users");
        openCreateModal();
      });
    }

    // Search Input
    if (elements.userSearchInput) {
      elements.userSearchInput.addEventListener("input", (e) => {
        state.userSearchTerm = e.target.value;
        applyUserFilter();
      });
    }

    // Refresh Users
    if (elements.refreshUsersBtn) {
      elements.refreshUsersBtn.addEventListener("click", () => loadUsersData(state.usersOffset));
    }
    if (elements.usersRetryBtn) {
      elements.usersRetryBtn.addEventListener("click", () => loadUsersData(state.usersOffset));
    }

    // Users Pagination
    if (elements.usersPrevBtn) {
      elements.usersPrevBtn.addEventListener("click", () => {
        if (state.usersOffset > 0) {
          loadUsersData(Math.max(0, state.usersOffset - state.usersLimit));
        }
      });
    }
    if (elements.usersNextBtn) {
      elements.usersNextBtn.addEventListener("click", () => {
        if (state.usersOffset + state.usersLimit < state.usersTotal) {
          loadUsersData(state.usersOffset + state.usersLimit);
        }
      });
    }

    // Modals Open/Close
    if (elements.openCreateUserModalBtn) {
      elements.openCreateUserModalBtn.addEventListener("click", openCreateModal);
    }
    if (elements.emptyStateCreateBtn) {
      elements.emptyStateCreateBtn.addEventListener("click", openCreateModal);
    }
    if (elements.closeCreateModalBtn) {
      elements.closeCreateModalBtn.addEventListener("click", closeCreateModal);
    }
    if (elements.cancelCreateModalBtn) {
      elements.cancelCreateModalBtn.addEventListener("click", closeCreateModal);
    }
    if (elements.createForm) {
      elements.createForm.addEventListener("submit", handleCreateOfficer);
    }

    // Create Password Live Policy Validation
    if (elements.createPassword) {
      elements.createPassword.addEventListener("input", (e) => {
        const policy = evaluatePassword(e.target.value);
        updatePolicyChecklist(
          policy,
          elements.policyLen,
          elements.policyCase,
          elements.policyNum,
          elements.policySpec
        );
      });
    }

    // Create Show/Hide PW toggles
    if (elements.createPwToggle) {
      elements.createPwToggle.addEventListener("click", () => {
        togglePasswordVisibility(elements.createPassword, elements.createPwToggle);
      });
    }
    if (elements.createConfirmPwToggle) {
      elements.createConfirmPwToggle.addEventListener("click", () => {
        togglePasswordVisibility(elements.createConfirmPassword, elements.createConfirmPwToggle);
      });
    }

    // Status Confirmation Modal
    if (elements.closeStatusModalBtn) {
      elements.closeStatusModalBtn.addEventListener("click", closeStatusModal);
    }
    if (elements.cancelStatusModalBtn) {
      elements.cancelStatusModalBtn.addEventListener("click", closeStatusModal);
    }
    if (elements.confirmStatusBtn) {
      elements.confirmStatusBtn.addEventListener("click", handleConfirmStatus);
    }

    // Reset Password Modal
    if (elements.closeResetModalBtn) {
      elements.closeResetModalBtn.addEventListener("click", closeResetModal);
    }
    if (elements.cancelResetModalBtn) {
      elements.cancelResetModalBtn.addEventListener("click", closeResetModal);
    }
    if (elements.resetForm) {
      elements.resetForm.addEventListener("submit", handleResetPassword);
    }
    if (elements.resetNewPassword) {
      elements.resetNewPassword.addEventListener("input", (e) => {
        const policy = evaluatePassword(e.target.value);
        updatePolicyChecklist(
          policy,
          elements.resetPolicyLen,
          elements.resetPolicyCase,
          elements.resetPolicyNum,
          elements.resetPolicySpec
        );
      });
    }
    if (elements.resetPwToggle) {
      elements.resetPwToggle.addEventListener("click", () => {
        togglePasswordVisibility(elements.resetNewPassword, elements.resetPwToggle);
      });
    }
    if (elements.resetConfirmPwToggle) {
      elements.resetConfirmPwToggle.addEventListener("click", () => {
        togglePasswordVisibility(elements.resetConfirmPassword, elements.resetConfirmPwToggle);
      });
    }

    // Audit Logs
    if (elements.refreshAuditBtn) {
      elements.refreshAuditBtn.addEventListener("click", () => loadAuditData(state.auditOffset));
    }
    if (elements.auditRetryBtn) {
      elements.auditRetryBtn.addEventListener("click", () => loadAuditData(state.auditOffset));
    }
    if (elements.auditPrevBtn) {
      elements.auditPrevBtn.addEventListener("click", () => {
        if (state.auditOffset > 0) {
          loadAuditData(Math.max(0, state.auditOffset - state.auditLimit));
        }
      });
    }
    if (elements.auditNextBtn) {
      elements.auditNextBtn.addEventListener("click", () => {
        if (state.auditOffset + state.auditLimit < state.auditTotal) {
          loadAuditData(state.auditOffset + state.auditLimit);
        }
      });
    }

    // Close modals on Escape key
    window.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        if (elements.createModal?.classList.contains("open")) closeCreateModal();
        if (elements.statusModal?.classList.contains("open")) closeStatusModal();
        if (elements.resetModal?.classList.contains("open")) closeResetModal();
      }
    });

    // Close modal on backdrop click
    [elements.createModal, elements.statusModal, elements.resetModal].forEach((modal) => {
      if (!modal) return;
      modal.addEventListener("click", (e) => {
        if (e.target === modal) {
          if (modal === elements.createModal) closeCreateModal();
          else if (modal === elements.statusModal) closeStatusModal();
          else if (modal === elements.resetModal) closeResetModal();
        }
      });
    });
  }

  // ==========================================================================
  // Initialization
  // ==========================================================================


  async function loadAwsCredentialsStatus() {
    const badge = document.getElementById("awsCredStatusBadge");
    if (!badge) return;
    try {
      const res = await fetch("/api/admin/aws-credentials", {
        method: "GET",
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      if (!res.ok) return;
      const data = await res.json();
      if (data.configured) {
        badge.className = "badge badge-active";
        badge.textContent = `AWS Key: ${data.masked_key_id} (${data.region || "us-east-1"})`;
      } else {
        badge.className = "badge badge-disabled";
        badge.textContent = "AWS Key: Not Configured";
      }
    } catch (_) {}
  }

  async function handleSaveAwsCredentials() {
    const rawEl = document.getElementById("awsRawInput");
    const btnEl = document.getElementById("saveAwsCredsBtn");
    const fbEl = document.getElementById("awsCredFeedback");
    if (!rawEl || !btnEl) return;

    const rawText = rawEl.value.trim();
    if (!rawText) {
      if (fbEl) {
        fbEl.style.color = "#a13a2e";
        fbEl.textContent = "กรุณาวางข้อมูล AWS Credentials ก่อนกดบันทึก";
      }
      return;
    }

    btnEl.disabled = true;
    try {
      const res = await fetch("/api/admin/aws-credentials", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ raw_text: rawText }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.status !== "success") {
        if (fbEl) {
          fbEl.style.color = "#a13a2e";
          fbEl.textContent = data.message || "ไม่สามารถอัปเดต AWS Key ได้";
        }
        showToast(data.message || "อัปเดต AWS Key ไม่สำเร็จ", "error");
        return;
      }
      rawEl.value = "";
      if (fbEl) {
        fbEl.style.color = "#275649";
        fbEl.textContent = `อัปเดตสำเร็จ: ${data.masked_key_id} (${data.region})`;
      }
      showToast(`อัปเดต AWS Key (${data.masked_key_id}) เรียบร้อยแล้ว`, "success");
      await loadAwsCredentialsStatus();
    } catch (_) {
      showToast("เกิดข้อผิดพลาดในการเชื่อมต่อเซิร์ฟเวอร์", "error");
    } finally {
      btnEl.disabled = false;
    }
  }

  bindEvents();
  const saveAwsBtn = document.getElementById("saveAwsCredsBtn");
  if (saveAwsBtn) {
    saveAwsBtn.addEventListener("click", handleSaveAwsCredentials);
  }
  verifySession().then(() => {
    loadAwsCredentialsStatus();
  });
})();

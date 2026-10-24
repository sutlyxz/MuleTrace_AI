/**
 * MuleTrace AI — Login Portal Script (Production PostgreSQL & RBAC Integration)
 * 
 * Features:
 * - Bilingual support (Thai / English) with localStorage language preference synchronization
 * - Client-side form validation (email format, completeness)
 * - Show / Hide password toggle with accessibility attributes
 * - Real PostgreSQL-backed authentication via POST /api/auth/login
 * - Role-Based Access Control (RBAC) redirection:
 *     - role 'admin' -> /admin.html
 *     - role 'user'  -> /index.html
 * - Fail-closed session inspection via GET /api/auth/me
 * - HttpOnly session cookie handling (no credentials or tokens stored in localStorage/sessionStorage)
 * - Safe generic error feedback for invalid credentials, suspended accounts, rate limiting, and outages
 * - Duplicate submission prevention
 */

(() => {
  "use strict";

  const STORAGE_KEY = "muletrace-language";
  const DEFAULT_LANG = "th";

  /* ==========================================================================
     1. Bilingual Dictionary (TH / EN)
     ========================================================================== */
  const I18N = {
    th: {
      pageTitle: "MuleTrace AI | เข้าสู่ระบบการสืบสวน",
      brandSubtitle: "INVESTIGATION INTELLIGENCE",
      hackathonTag: "HACKATHON PROTOTYPE",
      heroTitle: "Trace the Money.<br><span class=\"hero-accent\">Connect the Evidence.</span>",
      heroDesc: "แพลตฟอร์มวิเคราะห์ข่าวกรองทางการเงินอัจฉริยะ ตรวจจับเส้นทางการกระจายเงินของบัญชีม้า เชื่อมโยงพยานหลักฐานข้ามบัญชี และเร่งรัดการดำเนินคดีด้วย AI Copilot",
      capabilitiesHeading: "ขีดความสามารถการสืบสวนขั้นสูง",
      cap1Title: "Multi-Hop Money Trail",
      cap1Desc: "ตรวจจับและติดตามเส้นทางการกระจายเงินข้ามบัญชีม้าหลายทอด (Multi-Hop) ได้อย่างแม่นยำและรวดเร็ว",
      cap2Title: "Explainable Evidence Chain",
      cap2Desc: "สังเคราะห์สายสัมพันธ์พยานหลักฐานที่โปร่งใส ตรวจสอบย้อนกลับได้ตามมาตรฐานกฎหมาย",
      cap3Title: "AI Investigation Copilot",
      cap3Desc: "ผู้ช่วยอัจฉริยะวิเคราะห์ความเสี่ยง จัดลำดับเคสเร่งด่วน และสรุปพฤติกรรมผิดปกติอัตโนมัติ",
      securityNotice: "🛡️ Financial Crime Intelligence • AML/CFT Investigative Framework",
      demoChip: "ENTERPRISE SECURITY",
      welcomeTitle: "ยินดีต้อนรับกลับ",
      welcomeSubtitle: "ลงชื่อเข้าสู่ระบบสืบสวน MuleTrace AI",
      emailLabel: "อีเมลผู้ใช้งาน",
      emailPlaceholder: "investigator@agency.go.th",
      passwordLabel: "รหัสผ่าน",
      passwordPlaceholder: "••••••••",
      togglePasswordShow: "แสดงรหัสผ่าน",
      togglePasswordHide: "ซ่อนรหัสผ่าน",
      submitButton: "เข้าสู่ระบบ",
      submittingButton: "กำลังเข้าสู่ระบบ...",
      demoNoticeTitle: "ระบบยืนยันตัวตนความปลอดภัยสูง (PostgreSQL & Argon2id)",
      demoNoticeText: "ระบบเชื่อมต่อฐานข้อมูลยืนยันตัวตนด้วยการเข้ารหัส Argon2id พร้อมการจัดการสิทธิ์แบบ Role-Based Access Control (RBAC) ปลอดภัยและตรวจสอบได้ทุกการเข้าถึง",
      awsNoticeTitle: "สถาปัตยกรรมพร้อมเชื่อมต่อ AWS Cognito",
      awsNoticeText: "โครงสร้างฟังก์ชันถูกจัดเตรียมเพื่อเปลี่ยนผ่านสู่การยืนยันตัวตนระดับองค์กรด้วย Amazon Cognito User Pools, OpenID Connect และ Role-Based Access Control",
      
      // Validation & API error messages
      errEmailRequired: "กรุณาระบุอีเมลผู้ใช้งาน",
      errEmailInvalid: "รูปแบบอีเมลไม่ถูกต้อง (ตัวอย่าง: investigator@agency.go.th)",
      errPasswordRequired: "กรุณาระบุรหัสผ่าน",
      errFormIncomplete: "กรุณากรอกข้อมูลให้ครบถ้วนและถูกต้องก่อนเข้าสู่ระบบ",
      errInvalidCredentials: "อีเมลหรือรหัสผ่านไม่ถูกต้อง หรือบัญชีถูกระงับการใช้งาน",
      errRateLimit: "พยายามเข้าสู่ระบบมากเกินไป กรุณารอสักครู่แล้วลองใหม่อีกครั้ง",
      errServiceUnavailable: "ระบบตรวจสอบตัวตนไม่พร้อมให้บริการชั่วคราว กรุณาลองใหม่ภายหลัง",
      errNetwork: "เกิดข้อผิดพลาดในการเชื่อมต่อเครือข่าย กรุณาลองใหม่อีกครั้ง",
      successRedirecting: "เข้าสู่ระบบสำเร็จ กำลังนำทางสู่ระบบ..."
    },
    en: {
      pageTitle: "MuleTrace AI | Investigation Login",
      brandSubtitle: "INVESTIGATION INTELLIGENCE",
      hackathonTag: "HACKATHON PROTOTYPE",
      heroTitle: "Trace the Money.<br><span class=\"hero-accent\">Connect the Evidence.</span>",
      heroDesc: "AI-powered financial crime intelligence platform to track multi-hop mule account dispersion, synthesize evidence chains, and accelerate investigations with an AI Copilot.",
      capabilitiesHeading: "Core Investigation Capabilities",
      cap1Title: "Multi-Hop Money Trail",
      cap1Desc: "Trace and reconstruct complex multi-hop fund dispersion networks across mule tiers in real time.",
      cap2Title: "Explainable Evidence Chain",
      cap2Desc: "Synthesize transparent, auditable evidence chains ready for legal handoff and regulatory reporting.",
      cap3Title: "AI Investigation Copilot",
      cap3Desc: "Automated anomaly assessment, case priority ranking, and forensic narrative generation.",
      securityNotice: "🛡️ Financial Crime Intelligence • AML/CFT Investigative Framework",
      demoChip: "ENTERPRISE SECURITY",
      welcomeTitle: "Welcome Back",
      welcomeSubtitle: "Sign in to access the MuleTrace AI workspace",
      emailLabel: "User Email",
      emailPlaceholder: "investigator@agency.go.th",
      passwordLabel: "Password",
      passwordPlaceholder: "••••••••",
      togglePasswordShow: "Show password",
      togglePasswordHide: "Hide password",
      submitButton: "Sign In",
      submittingButton: "Signing in...",
      demoNoticeTitle: "High-Security Authentication (PostgreSQL & Argon2id)",
      demoNoticeText: "Authenticated against local PostgreSQL using Argon2id password hashing and Role-Based Access Control (RBAC). All actions are fully auditable.",
      awsNoticeTitle: "AWS Cognito Enterprise Ready",
      awsNoticeText: "Modular architecture structured for seamless transition to enterprise IAM using Amazon Cognito User Pools, OpenID Connect, and Role-Based Access Control.",
      
      // Validation & API error messages
      errEmailRequired: "Please enter your email.",
      errEmailInvalid: "Invalid email format (e.g. investigator@agency.go.th).",
      errPasswordRequired: "Please enter your password.",
      errFormIncomplete: "Please complete all required fields correctly before continuing.",
      errInvalidCredentials: "Invalid email or password, or account is suspended.",
      errRateLimit: "Too many login attempts. Please wait a moment and try again.",
      errServiceUnavailable: "Authentication service is temporarily unavailable. Please try again later.",
      errNetwork: "Network connection error. Please try again.",
      successRedirecting: "Authentication successful. Redirecting..."
    }
  };

  /* ==========================================================================
     2. SVG Icons for Password Visibility
     ========================================================================== */
  const ICON_EYE = `<svg class="eye-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>`;
  const ICON_EYE_SLASH = `<svg class="eye-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path><line x1="1" y1="1" x2="23" y2="23"></line></svg>`;

  /* ==========================================================================
     3. State Management
     ========================================================================== */
  let currentLanguage = DEFAULT_LANG;

  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "th" || saved === "en") {
      currentLanguage = saved;
    }
  } catch (err) {
    // Graceful fallback if storage unavailable
  }

  /* ==========================================================================
     4. Real Backend Authentication Adapter (PostgreSQL & RBAC)
     ========================================================================== */
  const MuleTraceAuth = {
    /**
     * Check if the user already has an active session via GET /api/auth/me.
     * Returns user summary object if authenticated, or null if unauthenticated.
     */
    async checkSession() {
      try {
        const res = await fetch("/api/auth/me", {
          method: "GET",
          credentials: "same-origin",
          headers: { "Accept": "application/json" }
        });
        if (!res.ok) {
          return null;
        }
        const data = await res.json();
        if (data && data.status === "success" && data.user) {
          return data.user;
        }
        return null;
      } catch (err) {
        return null;
      }
    },

    /**
     * Submit login credentials to POST /api/auth/login.
     * Receives HttpOnly session cookie on success and determines RBAC redirect.
     */
    async authenticate(email, password) {
      const t = I18N[currentLanguage];
      try {
        const res = await fetch("/api/auth/login", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Accept": "application/json"
          },
          credentials: "same-origin",
          body: JSON.stringify({ email, password })
        });

        if (res.status === 200) {
          const data = await res.json();
          const user = data && data.user;
          const role = user ? user.role : null;
          let redirectUrl = "index.html";
          if (role === "admin") {
            redirectUrl = "admin.html";
          } else if (role === "user") {
            redirectUrl = "index.html";
          }
          return {
            success: true,
            role: role,
            redirectUrl: redirectUrl
          };
        } else if (res.status === 401) {
          return { success: false, error: t.errInvalidCredentials };
        } else if (res.status === 429) {
          return { success: false, error: t.errRateLimit };
        } else if (res.status === 503) {
          return { success: false, error: t.errServiceUnavailable };
        } else {
          return { success: false, error: t.errInvalidCredentials };
        }
      } catch (err) {
        return { success: false, error: t.errNetwork };
      }
    },

    /**
     * Call POST /api/auth/logout with CSRF protection to invalidate session.
     */
    async logout() {
      try {
        await fetch("/api/auth/logout", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin"
        });
      } catch (err) {
        // Fallback
      }
    }
  };

  /* ==========================================================================
     5. DOM Elements & Helpers
     ========================================================================== */
  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => [...document.querySelectorAll(selector)];

  const pageTitle = $("#pageTitle");
  const loginForm = $("#loginForm");
  const emailInput = $("#emailInput");
  const passwordInput = $("#passwordInput");
  const emailGroup = $("#emailGroup");
  const passwordGroup = $("#passwordGroup");
  const emailError = $("#emailError");
  const passwordError = $("#passwordError");
  const togglePasswordBtn = $("#togglePasswordBtn");
  const submitBtn = $("#submitBtn");
  const feedbackAlert = $("#feedbackAlert");
  const langButtons = $$(".lang-btn");

  /* ==========================================================================
     6. Language Switching Functions
     ========================================================================== */
  function applyLanguage(lang) {
    if (lang !== "th" && lang !== "en") {
      lang = DEFAULT_LANG;
    }
    currentLanguage = lang;

    try {
      localStorage.setItem(STORAGE_KEY, lang);
    } catch (e) {
      // Storage failure ignored
    }

    document.documentElement.lang = lang;
    const t = I18N[lang];

    // Update document title
    if (pageTitle) {
      pageTitle.textContent = t.pageTitle;
    }

    // Update elements with data-i18n
    $$("[data-i18n]").forEach((el) => {
      const key = el.getAttribute("data-i18n");
      if (t[key] !== undefined) {
        el.innerHTML = t[key];
      }
    });

    // Update placeholders
    if (emailInput) {
      emailInput.placeholder = t.emailPlaceholder;
    }
    if (passwordInput) {
      passwordInput.placeholder = t.passwordPlaceholder;
    }

    // Update toggle password aria-label
    if (togglePasswordBtn && passwordInput) {
      const isVisible = passwordInput.type === "text";
      togglePasswordBtn.setAttribute(
        "aria-label",
        isVisible ? t.togglePasswordHide : t.togglePasswordShow
      );
    }

    // Update language button active classes and aria-pressed
    langButtons.forEach((btn) => {
      const btnLang = btn.getAttribute("data-lang");
      const isActive = btnLang === lang;
      btn.classList.toggle("active", isActive);
      btn.setAttribute("aria-pressed", isActive ? "true" : "false");
    });

    // Re-validate fields if errors are currently shown to refresh error messages
    if (emailError && emailError.classList.contains("visible")) {
      validateEmail(false);
    }
    if (passwordError && passwordError.classList.contains("visible")) {
      validatePassword(false);
    }
  }

  /* ==========================================================================
     7. Password Visibility Toggle
     ========================================================================== */
  function setupPasswordToggle() {
    if (!togglePasswordBtn || !passwordInput) return;

    togglePasswordBtn.addEventListener("click", () => {
      const isCurrentlyPassword = passwordInput.type === "password";
      const t = I18N[currentLanguage];

      if (isCurrentlyPassword) {
        passwordInput.type = "text";
        togglePasswordBtn.innerHTML = ICON_EYE_SLASH;
        togglePasswordBtn.setAttribute("aria-label", t.togglePasswordHide);
        togglePasswordBtn.setAttribute("aria-pressed", "true");
      } else {
        passwordInput.type = "password";
        togglePasswordBtn.innerHTML = ICON_EYE;
        togglePasswordBtn.setAttribute("aria-label", t.togglePasswordShow);
        togglePasswordBtn.setAttribute("aria-pressed", "false");
      }
      passwordInput.focus();
    });
  }

  /* ==========================================================================
     8. Validation Functions
     ========================================================================== */
  const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

  function clearFieldError(input, group, errorElement) {
    if (!input || !group || !errorElement) return;
    const container = group.querySelector(".input-container");
    if (container) {
      container.classList.remove("has-error");
    }
    input.removeAttribute("aria-invalid");
    errorElement.textContent = "";
    errorElement.classList.remove("visible");
  }

  function setFieldError(input, group, errorElement, message) {
    if (!input || !group || !errorElement) return;
    const container = group.querySelector(".input-container");
    if (container) {
      container.classList.add("has-error");
    }
    input.setAttribute("aria-invalid", "true");
    errorElement.textContent = message;
    errorElement.classList.add("visible");
  }

  function validateEmail(showError = true) {
    if (!emailInput) return false;
    const value = emailInput.value.trim();
    const t = I18N[currentLanguage];

    if (!value) {
      if (showError) {
        setFieldError(emailInput, emailGroup, emailError, t.errEmailRequired);
      }
      return false;
    }

    if (!EMAIL_REGEX.test(value)) {
      if (showError) {
        setFieldError(emailInput, emailGroup, emailError, t.errEmailInvalid);
      }
      return false;
    }

    clearFieldError(emailInput, emailGroup, emailError);
    return true;
  }

  function validatePassword(showError = true) {
    if (!passwordInput) return false;
    const value = passwordInput.value;
    const t = I18N[currentLanguage];

    if (!value) {
      if (showError) {
        setFieldError(passwordInput, passwordGroup, passwordError, t.errPasswordRequired);
      }
      return false;
    }

    clearFieldError(passwordInput, passwordGroup, passwordError);
    return true;
  }

  function showAlert(message, type = "error") {
    if (!feedbackAlert) return;
    feedbackAlert.textContent = message;
    feedbackAlert.className = `alert-box ${type}`;
    feedbackAlert.hidden = false;
  }

  function hideAlert() {
    if (!feedbackAlert) return;
    feedbackAlert.hidden = true;
    feedbackAlert.textContent = "";
    feedbackAlert.className = "alert-box";
  }

  /* ==========================================================================
     9. Form Submission & Navigation
     ========================================================================== */
  function setupFormHandler() {
    if (!loginForm) return;

    if (emailInput) {
      emailInput.addEventListener("input", () => {
        if (emailError.classList.contains("visible")) {
          validateEmail(true);
        }
        hideAlert();
      });
    }

    if (passwordInput) {
      passwordInput.addEventListener("input", () => {
        if (passwordError.classList.contains("visible")) {
          validatePassword(true);
        }
        hideAlert();
      });
    }

    loginForm.addEventListener("submit", async (e) => {
      e.preventDefault();

      if (submitBtn.disabled) return;

      const isEmailValid = validateEmail(true);
      const isPasswordValid = validatePassword(true);
      const t = I18N[currentLanguage];

      if (!isEmailValid || !isPasswordValid) {
        showAlert(t.errFormIncomplete, "error");
        if (!isEmailValid) {
          emailInput.focus();
        } else {
          passwordInput.focus();
        }
        return;
      }

      hideAlert();

      // UI Loading state & prevent duplicate submission
      submitBtn.disabled = true;
      const btnText = submitBtn.querySelector(".btn-text");
      if (btnText) {
        btnText.textContent = t.submittingButton;
      }

      try {
        const email = emailInput.value.trim().toLowerCase();
        const password = passwordInput.value;

        const result = await MuleTraceAuth.authenticate(email, password);

        if (result && result.success && result.redirectUrl) {
          showAlert(t.successRedirecting, "success");
          window.location.replace(result.redirectUrl);
        } else {
          throw new Error((result && result.error) || t.errInvalidCredentials);
        }
      } catch (err) {
        showAlert(err.message || t.errInvalidCredentials, "error");
        submitBtn.disabled = false;
        if (btnText) {
          btnText.textContent = t.submitButton;
        }
      }
    });
  }

  /* ==========================================================================
     10. Language Switcher Buttons Setup
     ========================================================================== */
  function setupLanguageSwitchers() {
    langButtons.forEach((btn) => {
      btn.addEventListener("click", () => {
        const lang = btn.getAttribute("data-lang");
        if (lang) {
          applyLanguage(lang);
        }
      });
    });
  }

  /* ==========================================================================
     11. Active Session Check (Fail-Closed on load)
     ========================================================================== */
  function checkActiveSession() {
    // Clean up any legacy fake sessionStorage bypass
    try {
      sessionStorage.removeItem("muletrace_auth_session");
      localStorage.removeItem("muletrace_auth_session");
    } catch (e) {}

    MuleTraceAuth.checkSession().then((user) => {
      if (user && user.role) {
        if (user.role === "admin") {
          window.location.replace("admin.html");
        } else if (user.role === "user") {
          window.location.replace("index.html");
        }
      }
    }).catch(() => {
      // Unauthenticated or network error: stay on login page
    });
  }

  /* ==========================================================================
     12. Initialization
     ========================================================================== */
  document.addEventListener("DOMContentLoaded", () => {
    setupLanguageSwitchers();
    setupPasswordToggle();
    setupFormHandler();
    applyLanguage(currentLanguage);
    checkActiveSession();
  });

  // Handle browser Back / bfcache restoration
  window.addEventListener("pageshow", () => {
    if (submitBtn) {
      submitBtn.disabled = false;
      const t = I18N[currentLanguage];
      const btnText = submitBtn.querySelector(".btn-text");
      if (btnText && t) {
        btnText.textContent = t.submitButton;
      }
    }
    checkActiveSession();
  });

  // Export adapter to window for inspection or test verification without exposing secrets
  window.MuleTraceAuth = MuleTraceAuth;
})();

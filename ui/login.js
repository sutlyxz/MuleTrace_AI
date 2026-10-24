/**
 * MuleTrace AI — Login Portal Script (Demo & Future AWS Cognito Architecture)
 * 
 * Features:
 * - Bilingual support (Thai / English) with localStorage synchronization
 * - Client-side form validation (email format, completeness)
 * - Show / Hide password toggle with accessibility attributes
 * - Clean Demo navigation to dashboard (`index.html`)
 * - Privacy safe: No credentials, tokens, or passwords stored or transmitted
 * - Modular AWS Cognito Adapter interface for future enterprise authentication
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
      pageTitle: "MuleTrace AI | เข้าสู่ระบบการสืบสวน (Demo)",
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
      demoChip: "DEMO ENVIRONMENT",
      welcomeTitle: "ยินดีต้อนรับกลับ",
      welcomeSubtitle: "ลงชื่อเข้าสู่พื้นที่จำลองระบบสืบสวน MuleTrace AI",
      emailLabel: "อีเมลผู้สืบสวน",
      emailPlaceholder: "investigator@agency.go.th",
      passwordLabel: "รหัสผ่าน",
      passwordPlaceholder: "••••••••",
      togglePasswordShow: "แสดงรหัสผ่าน",
      togglePasswordHide: "ซ่อนรหัสผ่าน",
      submitButton: "เข้าสู่ระบบ Demo Dashboard",
      submittingButton: "กำลังเข้าสู่ Dashboard...",
      demoNoticeTitle: "โหมดทดสอบระบบ (Demo Simulation)",
      demoNoticeText: "ระบบนี้เป็นการจำลองการนำทางเพื่อการนำเสนอต้นแบบ ไม่มีการเชื่อมต่อฐานข้อมูลผู้ใช้งานจริง และไม่มีการบันทึกรหัสผ่านในเครื่องหรือส่งออกภายนอก",
      awsNoticeTitle: "สถาปัตยกรรมพร้อมเชื่อมต่อ AWS Cognito",
      awsNoticeText: "โครงสร้างฟังก์ชันถูกจัดเตรียมเพื่อเปลี่ยนผ่านสู่การยืนยันตัวตนระดับองค์กรด้วย Amazon Cognito User Pools, OpenID Connect และ Role-Based Access Control",
      
      // Validation error messages
      errEmailRequired: "กรุณาระบุอีเมลผู้สืบสวน",
      errEmailInvalid: "รูปแบบอีเมลไม่ถูกต้อง (ตัวอย่าง: investigator@agency.go.th)",
      errPasswordRequired: "กรุณาระบุรหัสผ่าน",
      errFormIncomplete: "กรุณากรอกข้อมูลให้ครบถ้วนและถูกต้องก่อนเข้าสู่ระบบ",
      successRedirecting: "ตรวจสอบข้อมูลรูปแบบ Demo ถูกต้อง กำลังนำทางสู่ Dashboard..."
    },
    en: {
      pageTitle: "MuleTrace AI | Investigation Login (Demo)",
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
      demoChip: "DEMO ENVIRONMENT",
      welcomeTitle: "Welcome Back",
      welcomeSubtitle: "Sign in to access the MuleTrace AI investigation workspace",
      emailLabel: "Investigator Email",
      emailPlaceholder: "investigator@agency.go.th",
      passwordLabel: "Password",
      passwordPlaceholder: "••••••••",
      togglePasswordShow: "Show password",
      togglePasswordHide: "Hide password",
      submitButton: "Enter Demo Dashboard",
      submittingButton: "Entering Dashboard...",
      demoNoticeTitle: "Demo Simulation Mode",
      demoNoticeText: "This page simulates navigation for prototype demonstration. No real authentication or user database is connected, and passwords are never stored or transmitted.",
      awsNoticeTitle: "AWS Cognito Enterprise Ready",
      awsNoticeText: "Modular architecture structured for seamless transition to enterprise IAM using Amazon Cognito User Pools, OpenID Connect, and Role-Based Access Control.",
      
      // Validation error messages
      errEmailRequired: "Please enter your investigator email.",
      errEmailInvalid: "Invalid email format (e.g. investigator@agency.go.th).",
      errPasswordRequired: "Please enter your password.",
      errFormIncomplete: "Please complete all required fields correctly before continuing.",
      successRedirecting: "Valid demo input. Navigating to Dashboard..."
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
     4. Future AWS Cognito Authentication Adapter Interface
     ========================================================================== */
  /**
   * MuleTraceAuth: Modular auth controller.
   * 
   * Current behavior (Hackathon Prototype):
   * - Performs strict client-side syntax checks.
   * - Never persists or transmits credentials.
   * - Directs user to demo dashboard upon validation.
   * 
   * Transition path for AWS Engineering Team:
   * 1. Set `isDemoMode = false`.
   * 2. Configure `userPoolId`, `userPoolClientId`, and AWS region.
   * 3. Integrate with Amazon Cognito SDK or AWS Amplify Auth.
   * 4. Replace simulated resolution in `authenticate()` with Cognito `InitiateAuth` / `RespondToAuthChallenge`.
   * 5. Store retrieved JWT in secure httpOnly cookies or application session memory (never localStorage).
   */
  const MuleTraceAuth = {
    isDemoMode: true,
    targetDashboardUrl: "index.html",
    sessionKey: "muletrace_auth_session",

    setSession() {
      try {
        sessionStorage.setItem(this.sessionKey, "active");
      } catch (e) {
        // Storage fallback
      }
    },

    clearSession() {
      try {
        sessionStorage.removeItem(this.sessionKey);
      } catch (e) {
        // Storage fallback
      }
    },

    isAuthenticated() {
      try {
        return sessionStorage.getItem(this.sessionKey) === "active";
      } catch (e) {
        return false;
      }
    },

    async authenticate(email, password) {
      if (this.isDemoMode) {
        // Prototype Demo Navigation: activate session upon valid credentials
        this.setSession();
        return new Promise((resolve) => {
          setTimeout(() => {
            resolve({
              success: true,
              mode: "demo",
              redirectUrl: this.targetDashboardUrl
            });
          }, 350);
        });
      }

      /* --- AWS COGNITO PRODUCTION IMPLEMENTATION PLACEHOLDER ---
       * Example future implementation:
       * 
       * const cognitoClient = new CognitoIdentityProviderClient({ region: AWS_CONFIG.region });
       * const command = new InitiateAuthCommand({
       *   AuthFlow: "USER_PASSWORD_AUTH",
       *   ClientId: AWS_CONFIG.clientId,
       *   AuthParameters: { USERNAME: email, PASSWORD: password }
       * });
       * const response = await cognitoClient.send(command);
       * return processCognitoTokens(response.AuthenticationResult);
       * -------------------------------------------------------- */
      throw new Error("AWS Cognito production provider is not configured in this environment.");
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
  // Email regex: Standard format check (username@domain.tld)
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

    // Real-time error clearance on typing
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

      // UI Loading state
      submitBtn.disabled = true;
      const btnText = submitBtn.querySelector(".btn-text");
      if (btnText) {
        btnText.textContent = t.submittingButton;
      }
      showAlert(t.successRedirecting, "success");

      try {
        const email = emailInput.value.trim();
        const password = passwordInput.value;

        // Perform authentication through modular adapter
        const result = await MuleTraceAuth.authenticate(email, password);

        if (result && result.success && result.redirectUrl) {
          MuleTraceAuth.setSession();
          window.location.href = result.redirectUrl;
        } else {
          throw new Error("Navigation failed.");
        }
      } catch (err) {
        showAlert(err.message || t.errFormIncomplete, "error");
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
     11. Initialization
     ========================================================================== */
  document.addEventListener("DOMContentLoaded", () => {
    setupLanguageSwitchers();
    setupPasswordToggle();
    setupFormHandler();
    applyLanguage(currentLanguage);
  });

  // Export adapter to window for inspection or test verification without exposing secrets
  window.MuleTraceAuth = MuleTraceAuth;
})();

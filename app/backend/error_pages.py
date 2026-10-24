"""Reusable, accessible, and secure HTML error page generator for MuleTrace AI.

Visual design matches the MuleTrace AI design language (warm off-white background,
muted brown sand accents, clean centered card, security iconography, bilingual copy).
"""
from __future__ import annotations

import html
from typing import Any


def render_error_page(
    status_code: int,
    user: dict[str, Any] | None = None,
) -> str:
    """Generate a self-contained, responsive, accessible HTML error page.

    Role-safe navigation links are determined strictly from the verified server-side user session:
    - Admin -> returns to /admin.html
    - User (Bank Officer) -> returns to /index.html
    - Anonymous / Unverified -> returns to /login.html
    """
    user_role = (user.get("role") if user else None) or ""

    # 1. Determine title, copy, badge, and actions based on status_code
    if status_code == 401:
        badge_text = "401 UNAUTHORIZED"
        badge_class = "badge-warning"
        title_th = "กรุณาเข้าสู่ระบบ"
        desc_th = "คุณต้องเข้าสู่ระบบก่อนจึงจะสามารถเข้าถึงหน้านี้ได้"
        title_en = "Authentication Required"
        desc_en = "Please sign in with your credentials to access this page."
        icon_svg = """<svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="#92400e" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
            <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
        </svg>"""
        primary_btn_text = "ไปหน้าเข้าสู่ระบบ"
        primary_btn_url = "/login.html"
        secondary_btn_text = ""
        secondary_btn_url = ""

    elif status_code == 403:
        badge_text = "403 FORBIDDEN"
        badge_class = "badge-danger"
        title_th = "ไม่มีสิทธิ์เข้าถึงหน้านี้"
        desc_th = "บัญชีของคุณไม่มีสิทธิ์เข้าถึงส่วนนี้ของระบบ ตามมาตรฐานการแบ่งแยกหน้าที่ (Role-Based Access Control)"
        title_en = "Access Denied"
        desc_en = "Your account does not have permission to access this area."
        icon_svg = """<svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="#991b1b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
            <line x1="9" y1="9" x2="15" y2="15"></line>
            <line x1="15" y1="9" x2="9" y2="15"></line>
        </svg>"""

        if user_role == "admin":
            primary_btn_text = "กลับไปหน้าผู้ดูแลระบบ"
            primary_btn_url = "/admin.html"
            secondary_btn_text = ""
            secondary_btn_url = ""
        elif user_role == "user":
            primary_btn_text = "กลับไปหน้า Dashboard"
            primary_btn_url = "/index.html"
            secondary_btn_text = ""
            secondary_btn_url = ""
        else:
            primary_btn_text = "ไปหน้าเข้าสู่ระบบ"
            primary_btn_url = "/login.html"
            secondary_btn_text = ""
            secondary_btn_url = ""

    elif status_code == 404:
        badge_text = "404 NOT FOUND"
        badge_class = "badge-muted"
        title_th = "ไม่พบหน้าที่คุณต้องการ"
        desc_th = "หน้าที่คุณกำลังค้นหาอาจถูกย้าย เปลี่ยนชื่อ หรือไม่มีอยู่ในระบบ"
        title_en = "Page Not Found"
        desc_en = "The page you are looking for could not be found."
        icon_svg = """<svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="#475569" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <circle cx="11" cy="11" r="8"></circle>
            <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
            <line x1="8" y1="11" x2="14" y2="11"></line>
        </svg>"""

        if user_role == "admin":
            primary_btn_text = "กลับไปหน้าผู้ดูแลระบบ"
            primary_btn_url = "/admin.html"
        elif user_role == "user":
            primary_btn_text = "กลับไปหน้า Dashboard"
            primary_btn_url = "/index.html"
        else:
            primary_btn_text = "ไปหน้าเข้าสู่ระบบ"
            primary_btn_url = "/login.html"
        secondary_btn_text = ""
        secondary_btn_url = ""

    else:  # 500 or any other unclassified server error
        status_code = 500
        badge_text = "500 SERVER ERROR"
        badge_class = "badge-danger"
        title_th = "ระบบขัดข้องชั่วคราว"
        desc_th = "ไม่สามารถดำเนินการตามคำขอได้ในขณะนี้ กรุณาลองใหม่อีกครั้งในภายหลัง"
        title_en = "Something Went Wrong"
        desc_en = "We could not complete your request. Please try again later."
        icon_svg = """<svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="#991b1b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
            <line x1="12" y1="9" x2="12" y2="13"></line>
            <line x1="12" y1="17" x2="12.01" y2="17"></line>
        </svg>"""

        if user_role == "admin":
            primary_btn_text = "กลับไปหน้าผู้ดูแลระบบ"
            primary_btn_url = "/admin.html"
        elif user_role == "user":
            primary_btn_text = "กลับไปหน้า Dashboard"
            primary_btn_url = "/index.html"
        else:
            primary_btn_text = "ไปหน้าเข้าสู่ระบบ"
            primary_btn_url = "/login.html"
        secondary_btn_text = "ลองใหม่อีกครั้ง"
        secondary_btn_url = "#reload"

    # Role detail note (only for 403 Forbidden with verified role)
    role_note_html = ""
    if status_code == 403 and user_role in ("admin", "user"):
        role_label = "ผู้ดูแลระบบ" if user_role == "admin" else "เจ้าหน้าที่ธนาคาร"
        role_note_html = f"""
        <div class="user-session-card" role="status">
          <span class="user-session-icon" aria-hidden="true">👤</span>
          <div class="user-session-content">
            <span>บทบาทปัจจุบัน: <code>{html.escape(user_role)}</code> ({role_label})</span>
          </div>
        </div>
        """

    # Secondary action markup
    secondary_markup = ""
    if secondary_btn_text:
        if secondary_btn_url == "#reload":
            secondary_markup = f"""<button type="button" class="btn btn-secondary" onclick="window.location.reload()">{html.escape(secondary_btn_text)}</button>"""
        else:
            secondary_markup = f"""<a href="{html.escape(secondary_btn_url)}" class="btn btn-secondary">{html.escape(secondary_btn_text)}</a>"""

    return f"""<!doctype html>
<html lang="th">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
  <meta http-equiv="Pragma" content="no-cache">
  <meta http-equiv="Expires" content="0">
  <meta name="theme-color" content="#f7f5f1">
  <title>MuleTrace AI &bull; {html.escape(title_th)} ({status_code})</title>
  <style>
    :root {{
      --bg: #f7f5f1;
      --bg-gradient: linear-gradient(135deg, #f7f5f1 0%, #f1ece3 100%);
      --paper: #ffffff;
      --ink: #25251f;
      --ink-light: #44453e;
      --muted: #777870;
      --line: #e9e5df;
      --line-strong: #ded7cc;
      --sand-primary: #9c7951;
      --sand-hover: #88653f;
      --sand-dark: #745b3e;
      --radius-md: 12px;
      --radius-lg: 16px;
      --shadow-lg: 0 12px 32px rgba(60, 45, 30, 0.08);
      --transition-fast: 0.18s ease;
    }}

    *, *::before, *::after {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }}

    html {{
      font-family: "Segoe UI", -apple-system, BlinkMacSystemFont, Tahoma, sans-serif;
      background-color: var(--bg);
      color: var(--ink);
      line-height: 1.5;
      -webkit-font-smoothing: antialiased;
    }}

    body {{
      min-height: 100vh;
      background: var(--bg-gradient);
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 24px 16px;
    }}

    .error-wrapper {{
      width: 100%;
      max-width: 520px;
      display: flex;
      flex-direction: column;
      gap: 20px;
    }}

    .brand-bar {{
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 10px;
      margin-bottom: 4px;
    }}

    .brand-mark {{
      width: 32px;
      height: 32px;
      background: var(--sand-dark);
      color: #ffffff;
      border-radius: 8px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 750;
      font-size: 16px;
    }}

    .brand-text {{
      font-size: 15px;
      font-weight: 750;
      color: var(--ink);
      letter-spacing: -0.2px;
    }}

    .brand-text span {{
      color: var(--sand-dark);
      font-weight: 800;
    }}

    .brand-sub {{
      font-size: 11px;
      color: var(--muted);
      letter-spacing: 0.8px;
      text-transform: uppercase;
      font-weight: 600;
    }}

    .error-card {{
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: var(--radius-lg);
      padding: 36px 32px;
      box-shadow: var(--shadow-lg);
      display: flex;
      flex-direction: column;
      align-items: center;
      text-align: center;
      gap: 20px;
    }}

    .icon-container {{
      width: 72px;
      height: 72px;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      background: #faf7f2;
      border: 1px solid var(--line);
    }}

    .badge {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 4px 12px;
      border-radius: 20px;
      font-size: 12px;
      font-weight: 750;
      letter-spacing: 0.5px;
      text-transform: uppercase;
    }}

    .badge-warning {{
      background: #fef3c7;
      color: #92400e;
      border: 1px solid #fde68a;
    }}

    .badge-danger {{
      background: #fee2e2;
      color: #991b1b;
      border: 1px solid #fecaca;
    }}

    .badge-muted {{
      background: #f1f5f9;
      color: #475569;
      border: 1px solid #cbd5e1;
    }}

    .error-title {{
      font-size: 24px;
      font-weight: 750;
      color: var(--ink);
      letter-spacing: -0.3px;
      line-height: 1.3;
    }}

    .error-desc {{
      font-size: 14.5px;
      color: var(--ink-light);
      line-height: 1.55;
    }}

    .error-sub {{
      font-size: 13px;
      color: var(--muted);
      line-height: 1.45;
    }}

    .user-session-card {{
      width: 100%;
      background: #faf8f5;
      border: 1px dashed var(--line-strong);
      border-radius: var(--radius-md);
      padding: 10px 14px;
      display: flex;
      align-items: center;
      gap: 10px;
      text-align: left;
      font-size: 13px;
      color: var(--ink-light);
    }}

    .user-session-icon {{
      font-size: 18px;
      flex-shrink: 0;
    }}

    .user-session-content {{
      display: flex;
      align-items: center;
      overflow: hidden;
    }}

    .user-session-content strong {{
      color: var(--ink);
      font-weight: 650;
      white-space: nowrap;
      text-overflow: ellipsis;
      overflow: hidden;
    }}

    .user-session-content code {{
      background: #f0ebe1;
      padding: 1px 5px;
      border-radius: 4px;
      font-weight: 600;
      font-family: Consolas, monospace;
    }}

    .action-group {{
      width: 100%;
      display: flex;
      flex-direction: column;
      gap: 10px;
      margin-top: 6px;
    }}

    .btn {{
      width: 100%;
      min-height: 46px;
      padding: 10px 20px;
      border-radius: var(--radius-md);
      font-family: inherit;
      font-size: 14.5px;
      font-weight: 700;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      text-decoration: none;
      cursor: pointer;
      transition: all var(--transition-fast);
    }}

    .btn:focus-visible {{
      outline: 3px solid #c9ad87;
      outline-offset: 2px;
    }}

    .btn-primary {{
      background: var(--sand-primary);
      border: 1px solid var(--sand-hover);
      color: #ffffff;
      box-shadow: 0 2px 8px rgba(116, 91, 62, 0.2);
    }}

    .btn-primary:hover {{
      background: var(--sand-hover);
      transform: translateY(-1px);
      box-shadow: 0 4px 12px rgba(116, 91, 62, 0.25);
    }}

    .btn-secondary {{
      background: #ffffff;
      border: 1px solid var(--line-strong);
      color: var(--ink-light);
    }}

    .btn-secondary:hover {{
      background: #fbf9f6;
      border-color: var(--sand-primary);
      color: var(--sand-dark);
    }}

    .footer-note {{
      text-align: center;
      font-size: 12px;
      color: var(--muted);
    }}

    @media (max-width: 480px) {{
      .error-card {{
        padding: 28px 20px;
      }}
      .error-title {{
        font-size: 21px;
      }}
      .error-desc {{
        font-size: 13.5px;
      }}
    }}
  </style>
</head>
<body>
  <main class="error-wrapper">
    <div class="brand-bar" aria-label="MuleTrace AI">
      <div class="brand-mark" aria-hidden="true">M</div>
      <div>
        <div class="brand-text">MuleTrace <span>AI</span></div>
        <div class="brand-sub">INVESTIGATION INTELLIGENCE</div>
      </div>
    </div>

    <section class="error-card" aria-labelledby="errorHeading">
      <div class="icon-container" aria-hidden="true">
        {icon_svg}
      </div>

      <div class="badge {badge_class}" role="status">{badge_text}</div>

      <h1 id="errorHeading" class="error-title">{html.escape(title_th)}</h1>
      <p class="error-desc">{html.escape(desc_th)}</p>
      <p class="error-sub">{html.escape(title_en)} &bull; {html.escape(desc_en)}</p>

      {role_note_html}

      <div class="action-group">
        <a href="{html.escape(primary_btn_url)}" class="btn btn-primary">{html.escape(primary_btn_text)} &rarr;</a>
        {secondary_markup}
      </div>
    </section>

    <footer class="footer-note">
      MuleTrace AI &bull; Financial Crime Intelligence & AML/CFT Investigative Framework
    </footer>
  </main>
</body>
</html>
"""

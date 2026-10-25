@echo off
chcp 65001 >nul
title MuleTrace AI - Mobile Access
cls
echo ===================================================================
echo     MuleTrace AI - เปิดระบบสำหรับเข้าใช้งานจากโทรศัพท์มือถือ
echo ===================================================================
echo.
echo [*] กำลังเริ่มเซิร์ฟเวอร์บนโหมดเครือข่าย (0.0.0.0)...
echo.
echo -------------------------------------------------------------------
echo  [+] ลิงก์สำหรับเปิดบนโทรศัพท์มือถือ:
echo      👉 http://192.168.1.176:8000/login.html
echo.
echo  [+] ลิงก์สำหรับเปิดบนคอมพิวเตอร์เครื่องนี้:
echo      👉 http://localhost:8000/login.html
echo.
echo  [+] บัญชีสำหรับเข้าสู่ระบบ:
echo      - เจ้าหน้าที่: officer@agency.go.th / OfficerPass123!@#
echo      - ผู้ดูแลระบบ: admin@agency.go.th   / AdminPass123!@#
echo -------------------------------------------------------------------
echo  * โปรดตรวจสอบว่าโทรศัพท์ต่อ Wi-Fi เดียวกันกับคอมพิวเตอร์เครื่องนี้
echo.

".venv\Scripts\python.exe" -m app.backend.server 8000 --bind 0.0.0.0 --directory app/frontend
pause

@echo off
chcp 65001 >nul
title MuleTrace AI Launcher
echo ====================================================
echo        กำลังเริ่มการทำงาน MuleTrace AI...
echo ====================================================
echo.

REM ตรวจสอบ live-server
where live-server >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo [✓] ตรวจพบ Live Server: กำลังเปิดระบบพร้อมโหมด Real-time Reload...
    live-server app\frontend
    goto end
)

REM ตรวจสอบ Python (py launcher)
where py >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo [✓] ตรวจพบ Python: กำลังเปิดระบบที่ http://localhost:8000...
    start http://localhost:8000
    py -m http.server 8000 --bind 127.0.0.1 --directory app\frontend
    goto end
)

REM ตรวจสอบ Python ปกติ
where python >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo [✓] ตรวจพบ Python: กำลังเปิดระบบที่ http://localhost:8000...
    start http://localhost:8000
    python -m http.server 8000 --bind 127.0.0.1 --directory app\frontend
    goto end
)

REM ตรวจสอบ npx
where npx >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo [✓] ตรวจพบ Node.js (npx): กำลังเปิดระบบ...
    npx live-server app\frontend
    goto end
)

echo [X] ไม่พบโปรแกรมสำหรับรันเว็บเซิร์ฟเวอร์ (Live Server / Python / Node.js)
echo กรุณาเปิดไฟล์ app\frontend\index.html ผ่านเบราว์เซอร์โดยตรง
pause

:end

@echo off
chcp 65001 >nul
echo ========================================================
echo   กำลังเปิดระบบ Omnichannel Chat ^& AI Admin (5 เพจ)
echo   แบรนด์หลัก: ข้าวบุกสุขใจ (LINE OA + Facebook + IG)
echo ========================================================
cd /d "%~dp0messenger-engine"
start "" "http://localhost:8000"
python -m uvicorn app.main:app --reload --port 8000
pause

@echo off
chcp 65001 >nul
echo ============================================================================
echo   🚀 ระบบ Import โฟลว์ทั้ง 4 ตัว และเปิดหน้ากระดาน n8n Self-Hosted (ฟรี 100%%)
echo ============================================================================
echo.
echo [1/2] กำลังนำเข้าไฟล์ JSON ทั้ง 4 โฟลว์จาก D:\chat bot\messenger-engine\n8n_workflows ...
call npx --yes n8n import:workflow --separate --input="D:\chat bot\messenger-engine\n8n_workflows"
echo.
echo [2/2] กำลังเปิดเซิร์ฟเวอร์ n8n Self-Hosted ที่ http://localhost:5678 ...
start "" "http://localhost:5678"
call npx --yes n8n start
pause

@echo off
REM ==========================================================
REM Thu thap dac trung so lenh - CAN CHAY LIEN TUC NHIEU THANG.
REM
REM So lenh la du lieu duy nhat KHONG tai lai duoc: san khong luu lich su L2.
REM Moi ngay khong chay la mot ngay lui thoi diem co the kiem dinh.
REM
REM Chay tay:      nhap dup file nay
REM Chay tu dong:  xem huong dan Task Scheduler o cuoi file
REM Dung lai:      dong cua so, hoac Ctrl+C
REM
REM An toan de chay lai bat cu luc nao - file ghi noi theo tung ngay.
REM ==========================================================
cd /d "%~dp0"

echo Bat dau thu thap so lenh...
echo Du lieu ghi vao: %~dp0data\orderbook
echo Dong cua so nay de dung.
echo.

:vong_lap
".venv\Scripts\python.exe" -m research.collect_orderbook ^
    --symbols BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,DOGEUSDT,BNBUSDT,LINKUSDT,AVAXUSDT ^
    --depth 50 --category linear

REM Neu tien trinh chet vi mat mang hay loi websocket thi khoi dong lai sau 30s.
REM Mot thang du lieu bi dut mot doan la mot thang phai cho lai.
echo.
echo [%date% %time%] Tien trinh dung. Khoi dong lai sau 30 giay...
timeout /t 30 /nobreak >nul
goto vong_lap

REM ==========================================================
REM CHAY TU DONG KHI BAT MAY (khuyen nghi):
REM
REM Mo PowerShell voi quyen Administrator roi chay:
REM
REM   schtasks /create /tn "AITrade thu thap so lenh" ^
REM     /tr "C:\Users\Admin\Desktop\AITrade\thu_thap_so_lenh.bat" ^
REM     /sc onstart /ru "%USERNAME%" /rl highest /f
REM
REM Kiem tra:  schtasks /query /tn "AITrade thu thap so lenh"
REM Chay ngay: schtasks /run   /tn "AITrade thu thap so lenh"
REM Go bo:     schtasks /delete /tn "AITrade thu thap so lenh" /f
REM ==========================================================

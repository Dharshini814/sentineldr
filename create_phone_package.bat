@echo off
echo 📱 Creating SentinelDR Phone Server Package for Termux
echo ════════════════════════════════════════════════════

REM Create a clean package directory
if exist "phone_package" rmdir /s /q "phone_package"
mkdir phone_package
mkdir phone_package\backend
mkdir phone_package\backend\phone
mkdir phone_package\backend\shared

echo 📁 Copying phone server files...
xcopy "backend\phone\*" "phone_package\backend\phone\" /E /Y
xcopy "backend\shared\*" "phone_package\backend\shared\" /E /Y

echo 📋 Copying documentation...
copy "TERMUX_SETUP_GUIDE.md" "phone_package\"

echo 🗜️ Creating ZIP package...
powershell -Command "Compress-Archive -Path 'phone_package\*' -DestinationPath 'sentineldr_phone_server.zip' -Force"

echo ✅ Package created: sentineldr_phone_server.zip
echo 
echo 📱 Next steps:
echo 1. Transfer sentineldr_phone_server.zip to your Android phone
echo 2. Follow instructions in TERMUX_SETUP_GUIDE.md
echo 3. Extract in Termux and run the phone server
echo 
pause
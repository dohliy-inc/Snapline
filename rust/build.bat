@echo off
cd /d "%~dp0"
cargo test --release -p engine || exit /b 1
cargo build --release -p snapline || exit /b 1
target\release\snapline.exe --uitest || exit /b 1
if not exist ..\dist\rust mkdir ..\dist\rust
copy /y target\release\snapline.exe ..\dist\rust\snapline.exe >nul || exit /b 1
echo.
echo Done: %~dp0..\dist\rust\snapline.exe

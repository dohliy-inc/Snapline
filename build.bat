@echo off
cd /d "%~dp0"
if not exist .venv py -m venv .venv || exit /b 1
.venv\Scripts\python -m pip install --quiet --disable-pip-version-check -r requirements.txt pyinstaller || exit /b 1
.venv\Scripts\python test_snapline.py || exit /b 1
.venv\Scripts\python -c "import ui; ui.make_icon().save('icon.ico', sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])" || exit /b 1
.venv\Scripts\pyinstaller --noconfirm --onefile --windowed --icon icon.ico --name snapline --add-data "samples\example_bg.webp;samples" --add-data "samples\example_chat.png;samples" --add-data "assets\ls_project.png;assets" ui.py || exit /b 1
echo.
echo Done: %~dp0dist\snapline.exe

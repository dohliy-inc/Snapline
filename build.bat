@echo off
cd /d "%~dp0"
set EXCLUDE=--exclude-module PIL._avif --exclude-module PIL.AvifImagePlugin --exclude-module numpy.random --exclude-module numpy.fft --exclude-module numpy.polynomial --exclude-module numpy.ma --exclude-module numpy.testing --exclude-module numpy.f2py --exclude-module asyncio --exclude-module unittest --exclude-module multiprocessing --exclude-module concurrent --exclude-module xmlrpc --exclude-module xml --exclude-module pydoc --exclude-module pydoc_data --exclude-module _pyrepl --exclude-module decimal --exclude-module _decimal --exclude-module sqlite3 --exclude-module ssl --exclude-module _ssl --exclude-module _hashlib --exclude-module lzma --exclude-module _lzma --exclude-module bz2 --exclude-module _bz2 --exclude-module compression.zstd --exclude-module _zstd
if not exist .venv py -m venv .venv || exit /b 1
.venv\Scripts\python -m pip install --quiet --disable-pip-version-check -r requirements.txt pyinstaller || exit /b 1
.venv\Scripts\python test_snapline.py || exit /b 1
.venv\Scripts\python -c "import ui; ui.make_icon().save('icon.ico', sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])" || exit /b 1
.venv\Scripts\pyinstaller --noconfirm --onefile --windowed --icon icon.ico --name snapline %EXCLUDE% --add-data "samples\example_bg.webp;samples" --add-data "samples\example_chat.png;samples" --add-data "assets\ls_project.png;assets" ui.py || exit /b 1
echo.
echo Done: %~dp0dist\snapline.exe

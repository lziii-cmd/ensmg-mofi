@echo off
cd /d "%~dp0"
call venv\Scripts\activate.bat

:: Charger les variables du fichier .env si présent
if exist .env (
    for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
        if not "%%A"=="" if not "%%A:~0,1%"=="#" (
            set "%%A=%%B"
        )
    )
)

python manage.py runserver 0.0.0.0:8002

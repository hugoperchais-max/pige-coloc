@echo off
rem ---------------------------------------------------------------------------
rem Run local du bot de pige, lance par le Planificateur de taches Windows.
rem But : depuis ton PC (IP residentielle), LeBonCoin passe (DataDome ne bloque
rem pas), contrairement aux serveurs GitHub. GitHub reste le filet 24/7.
rem Sequence : maj depuis GitHub -> run -> renvoi de l'etat (seen.json).
rem Les secrets sont dans .env.local (non versionne).
rem ---------------------------------------------------------------------------
setlocal enabledelayedexpansion
cd /d "%~dp0"
set "GIT=C:\Program Files\Git\mingw64\bin\git.exe"
set "PY=C:\Users\hugop\AppData\Local\Programs\Python\Launcher\py.exe"

if exist ".env.local" (
  for /f "usebackq eol=# tokens=1,2 delims==" %%A in (".env.local") do set "%%A=%%B"
)

"%GIT%" pull --rebase --autostash
"%PY%" -3.12 main.py
"%GIT%" add seen.json
"%GIT%" commit -m "chore: maj etat pige local [skip ci]"
"%GIT%" push
if errorlevel 1 (
  "%GIT%" pull --rebase --autostash
  "%GIT%" push
)
endlocal

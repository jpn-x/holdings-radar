@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo [holdings-radar] %date% %time%

REM Python が入っていなければ py ランチャーで
where python >nul 2>&1 && set PY=python || set PY=py

REM MSワラント行使ウォッチ（失敗してもfetchは続行）
%PY% scripts\warrant_watch.py

%PY% scripts\fetch.py
if errorlevel 1 (
    echo ERROR: fetch.py failed
    exit /b 1
)

git add index.html data\warrants.json
git diff --staged --quiet && (
    echo No changes to commit.
    exit /b 0
)

for /f "tokens=1-3 delims=/ " %%a in ("%date%") do set TODAY=%%a-%%b-%%c
git commit -m "chore: update holdings data %TODAY%"
git push

echo Done.

@echo off
title SUPER GIT TOOL 🚀
color 0A

:menu
cls
echo ================================
echo        SUPER GIT TOOL
echo ================================
echo [1] Auto Add + Commit + Push
echo [2] Clean Junk Files (.idea, **pycache**)
echo [3] Setup .gitignore
echo [4] Revert Last Commit (soft)
echo [5] HARD Reset (WARNING)
echo [6] Show Status
echo [7] Set Git User
echo [0] Exit
echo ================================
set /p choice=Choose option:

if "%choice%"=="1" goto push
if "%choice%"=="2" goto clean
if "%choice%"=="3" goto ignore
if "%choice%"=="4" goto revert
if "%choice%"=="5" goto hardreset
if "%choice%"=="6" goto status
if "%choice%"=="7" goto setuser
if "%choice%"=="0" exit

goto menu

:push
echo.
set /p msg=Enter commit message:
git add .
git commit -m "%msg%"
git push
pause
goto menu

:clean
echo Removing junk files...
git rm -r --cached .idea 2>nul
git rm -r --cached **pycache** 2>nul
git rm -r --cached *.pyc 2>nul
echo Done cleaning.
pause
goto menu

:ignore
echo Creating .gitignore...
(
echo .idea/
echo **pycache**/
echo *.pyc
echo venv/
echo *.log
echo .env
echo dist/
echo build/
) > .gitignore

git add .gitignore
git commit -m "Added .gitignore"
git push
echo .gitignore created and pushed.
pause
goto menu

:revert
echo Reverting last commit (soft)...
git reset --soft HEAD~1
pause
goto menu

:hardreset
echo WARNING: This will delete ALL uncommitted changes!
pause
git reset --hard
pause
goto menu

:status
git status
pause
goto menu

:setuser
set /p name=Enter Git username:
set /p email=Enter Git email:
git config user.name "%name%"
git config user.email "%email%"
echo User set.
pause
goto menu

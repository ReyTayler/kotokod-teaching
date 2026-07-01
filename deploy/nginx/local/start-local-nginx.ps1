<#
.SYNOPSIS
    Запускает локальный nginx перед Django runserver (Windows, без Docker).

.DESCRIPTION
    nginx раздаёт статику фронта и проксирует /api + /health на runserver :8000.
    Конфиг: deploy/nginx/local/nginx.conf (общий сниппет статики с продом).

    Перед запуском подними Django отдельно:
        cd journal_django
        .venv/Scripts/python.exe manage.py runserver 8000

    Затем:  ./deploy/nginx/local/start-local-nginx.ps1
    Открыть: http://localhost:8080/

.PARAMETER Stop
    Остановить nginx (nginx -s stop).

.PARAMETER Reload
    Перечитать конфиг без остановки (nginx -s reload) — например после правки сниппета.

.PARAMETER Test
    Только проверить синтаксис конфига (nginx -t) и выйти.

.PARAMETER NginxExe
    Явный путь к nginx.exe (если автопоиск не нашёл).

.NOTES
    Установка nginx (без админ-прав): официальный zip с https://nginx.org/en/download.html,
    распаковать в %USERPROFILE%\nginx\ (скрипт сам найдёт nginx-*\nginx.exe).
    Альтернатива: `winget install nginxinc.nginx`.
    -p указывает каталог установки nginx (там logs/ и temp/), -c — наш конфиг.
#>
[CmdletBinding()]
param(
    [switch]$Stop,
    [switch]$Reload,
    [switch]$Test,
    [string]$NginxExe
)

$ErrorActionPreference = 'Stop'

# Абсолютный путь к нашему конфигу (рядом со скриптом).
$ConfigPath = Join-Path $PSScriptRoot 'nginx.conf'
if (-not (Test-Path $ConfigPath)) {
    throw "Не найден конфиг: $ConfigPath"
}

# Найти nginx.exe: явный параметр → PATH → %USERPROFILE%\nginx\nginx-*\ → C:\nginx\.
if (-not $NginxExe) {
    $cmd = Get-Command nginx -ErrorAction SilentlyContinue
    if ($cmd) {
        $NginxExe = $cmd.Source
    } else {
        $candidates = @(
            "$env:USERPROFILE\nginx",
            'C:\nginx'
        ) | Where-Object { Test-Path $_ } |
            ForEach-Object { Get-ChildItem -Path $_ -Recurse -Filter nginx.exe -ErrorAction SilentlyContinue } |
            Sort-Object FullName -Descending
        if ($candidates) { $NginxExe = $candidates[0].FullName }
    }
}
if (-not $NginxExe -or -not (Test-Path $NginxExe)) {
    throw "nginx.exe не найден. Скачай zip с https://nginx.org/en/download.html в %USERPROFILE%\nginx\, или укажи -NginxExe <путь>."
}

# Prefix = каталог установки nginx (нужны logs/ и temp/ для служебных файлов).
# Для scoop/choco бинарь лежит в .../nginx-<ver>/, prefix = его каталог.
$Prefix = Split-Path -Parent $NginxExe

Write-Host "nginx:  $NginxExe"
Write-Host "prefix: $Prefix"
Write-Host "config: $ConfigPath"

if ($Stop) {
    & $NginxExe -p "$Prefix" -s stop
    Write-Host "nginx остановлен." -ForegroundColor Green
    return
}

if ($Reload) {
    & $NginxExe -p "$Prefix" -c "$ConfigPath" -s reload
    Write-Host "Конфиг перечитан." -ForegroundColor Green
    return
}

# Всегда сначала проверяем синтаксис.
& $NginxExe -p "$Prefix" -c "$ConfigPath" -t
if ($LASTEXITCODE -ne 0) {
    throw "nginx -t завершился с ошибкой ($LASTEXITCODE). Конфиг не запущен."
}

if ($Test) {
    Write-Host "Синтаксис ОК (только проверка, nginx не запущен)." -ForegroundColor Green
    return
}

# Запуск (nginx демонизируется на Windows — отдаёт управление сразу).
& $NginxExe -p "$Prefix" -c "$ConfigPath"
Write-Host "nginx запущен → http://localhost:8080/  (остановка: -Stop, перезагрузка: -Reload)" -ForegroundColor Green

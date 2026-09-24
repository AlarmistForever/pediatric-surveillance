# Ежедневный локальный запуск. Он намеренно не отправляет письмо:
# отправку выполняет Codex через подключённый Gmail только после успеха этого сценария.
$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

$runDate = Get-Date -Format 'yyyy-MM-dd'
$outputDir = Join-Path $projectRoot "outputs\daily\$runDate"
$statusPath = Join-Path $projectRoot 'outputs\daily\latest.json'
$logDir = Join-Path $projectRoot 'outputs\daily\logs'
$logPath = Join-Path $logDir "$runDate.log"

New-Item -ItemType Directory -Force -Path $outputDir, $logDir | Out-Null

try {
    # Команды идут по порядку конвейера; следующая не запускается, если предыдущая дала ошибку.
    python -m pediatric_surveillance.cli discover --db data\clean.sqlite3 2>&1 | Tee-Object -FilePath $logPath -Append
    if ($LASTEXITCODE -ne 0) { throw "Discovery завершился с кодом $LASTEXITCODE" }

    python -m pediatric_surveillance.cli screen --db data\clean.sqlite3 2>&1 | Tee-Object -FilePath $logPath -Append
    if ($LASTEXITCODE -ne 0) { throw "Screening завершился с кодом $LASTEXITCODE" }

    python -m pediatric_surveillance.cli appraise --db data\clean.sqlite3 2>&1 | Tee-Object -FilePath $logPath -Append
    if ($LASTEXITCODE -ne 0) { throw "Appraisal завершился с кодом $LASTEXITCODE" }

    python -m pediatric_surveillance.cli import-context --db data\clean.sqlite3 --file data\editorial_context.json 2>&1 | Tee-Object -FilePath $logPath -Append
    if ($LASTEXITCODE -ne 0) { throw "Импорт редакционного контекста завершился с кодом $LASTEXITCODE" }

    $recipient = if ($env:DIGEST_TO) { $env:DIGEST_TO } else { throw 'Не задана переменная DIGEST_TO' }
    python -m pediatric_surveillance.cli digest --db data\clean.sqlite3 --output $outputDir --recipient $recipient 2>&1 | Tee-Object -FilePath $logPath -Append
    if ($LASTEXITCODE -ne 0) { throw "Формирование дайджеста завершилось с кодом $LASTEXITCODE" }

    $html = Get-ChildItem -LiteralPath $outputDir -Filter '*.html' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($null -eq $html) { throw 'HTML-письмо не создано' }

    [pscustomobject]@{
        status = 'ok'
        generated_at = (Get-Date).ToString('o')
        recipient = $recipient
        html_path = $html.FullName
        run_date = $runDate
    } | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding utf8
}
catch {
    [pscustomobject]@{
        status = 'failed'
        generated_at = (Get-Date).ToString('o')
        error = $_.Exception.Message
        run_date = $runDate
    } | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding utf8
    Add-Content -LiteralPath $logPath -Value "ERROR: $($_.Exception.Message)"
    exit 1
}

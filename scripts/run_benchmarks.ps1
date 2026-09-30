# RepairLens benchmark runner — writes benchmarks/results/latest.json
#
# GET /api/benchmarks reads that file and the UI renders it under
# "Snapdragon / System → Benchmarks". Honesty rule: NPU/QNN numbers are
# printed as NOT EXECUTED unless this machine actually has a Snapdragon NPU
# with the QNN execution provider available.
#
# Examples:
#   powershell -ExecutionPolicy Bypass -File scripts\run_benchmarks.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\run_benchmarks.ps1 -Runs 50 -SkipAsr

param(
    [int]$Runs = 30,
    [int]$AsrRuns = 4,
    [switch]$SkipAsr
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root

$pyArgs = @("benchmarks\bench.py", "--runs", "$Runs", "--asr-runs", "$AsrRuns")
if ($SkipAsr) { $pyArgs += "--skip-asr" }

Write-Host "RepairLens benchmarks (runs=$Runs, asr-runs=$AsrRuns, skip-asr=$SkipAsr)" -ForegroundColor Cyan
python @pyArgs
$code = $LASTEXITCODE

if ($code -eq 0) {
    Write-Host ""
    Write-Host "Done. Reload the UI (or click 'New session') to show the fresh numbers." -ForegroundColor Green
}
exit $code

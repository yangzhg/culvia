param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Resolve-Path (Join-Path $ScriptDir "..")
$Venv = if ($env:CULVIA_VENV) { $env:CULVIA_VENV } else { Join-Path $HOME ".venvs/culvia" }
$BasePython = if ($env:PYTHON) { $env:PYTHON } else { "python" }

$Candidates = @(
    (Join-Path $Venv "Scripts/python.exe"),
    (Join-Path $Venv "bin/python")
)
$Python = $BasePython
foreach ($Candidate in $Candidates) {
    if (Test-Path $Candidate) {
        $Python = $Candidate
        break
    }
}

Push-Location $Root
try {
    & $Python -c "from culvia.server import main; import sys; sys.argv[0] = 'bin/culvia-web.ps1'; raise SystemExit(main(sys.argv[1:]))" @Args
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}

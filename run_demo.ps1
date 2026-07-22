$ErrorActionPreference = 'Stop'

$ProjectRoot = $PSScriptRoot
$VenvRoot = Join-Path $ProjectRoot '.venv'
$VenvPython = Join-Path $VenvRoot 'Scripts\python.exe'

if (-not (Test-Path -LiteralPath $VenvPython)) {
    if (-not [string]::IsNullOrWhiteSpace($env:TENS_HQ_PYTHON)) {
        $BasePython = $env:TENS_HQ_PYTHON
    }
    else {
        $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $PythonCommand) {
            throw 'Install Python 3.11+ or set TENS_HQ_PYTHON.'
        }
        $BasePython = $PythonCommand.Source
    }
    & $BasePython -m venv $VenvRoot
    & $VenvPython -m pip install --disable-pip-version-check -r (Join-Path $ProjectRoot 'requirements-dev.txt')
}

& $VenvPython -m streamlit run (Join-Path $ProjectRoot 'app.py')

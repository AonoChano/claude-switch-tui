$CswHome = Split-Path -Parent $MyInvocation.MyCommand.Path
& (Join-Path $CswHome ".venv\Scripts\python.exe") (Join-Path $CswHome "claude_switch.py") @args
exit $LASTEXITCODE

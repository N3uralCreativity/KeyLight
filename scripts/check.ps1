$ErrorActionPreference = "Stop"

. .\.venv\Scripts\Activate.ps1
python -m ruff check .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m mypy .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m pytest -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

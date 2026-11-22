SHELL := pwsh.exe
.SHELLFLAGS := -NoProfile -Command
PNPM_PATH := $(APPDATA)\npm-global;$(PATH)
PY := .\backend\.venv\Scripts\python.exe
PYTEST := .\backend\.venv\Scripts\pytest.exe

.PHONY: setup migrate seed fixtures eval-categorization coverage test test-e2e browser-qa load-smoke cloud-plan cloud-destroy

setup:
	cmd /c 'wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/Users/devan/OneDrive/Desktop/apple_ads/sololedger && docker compose -p sololedger --env-file .env -f infra/docker/docker-compose.yml up -d --wait"'
	$$env:Path = "$(PNPM_PATH)"; pnpm --dir frontend install
	$(MAKE) migrate && $(MAKE) seed

migrate:
	Set-Location backend; .\.venv\Scripts\python.exe manage.py migrate

seed:
	$(PY) scripts\seed.py

fixtures:
	$(PY) scripts\generate_statements.py --seed 2026 --count 12 --rows 90

eval-categorization:
	$(PY) scripts\score_classifier.py

coverage:
	Set-Location backend; .\.venv\Scripts\pytest.exe --cov=apps --cov=classification --cov=tasks --cov-report=term-missing --cov-report=json:../evidence/coverage/backend-coverage.json --cov-fail-under=91
	$$env:Path = "$(PNPM_PATH)"; Set-Location frontend; pnpm run test:coverage

test:
	Set-Location backend; .\.venv\Scripts\ruff.exe check .
	$(MAKE) coverage
	$$env:Path = "$(PNPM_PATH)"; Set-Location frontend; pnpm run typecheck && pnpm run lint

load-smoke:
	$(PY) scripts\run_live_qa.py

test-e2e:
	$(PY) scripts\run_live_qa.py

browser-qa: test-e2e

cloud-plan:
	@Write-Output "BLOCKED_EXTERNAL: Inspect CLOUD_APPROVAL.md and export AWS credentials before running terraform plan/apply."
	@exit 1

cloud-destroy:
	@Write-Output "BLOCKED_EXTERNAL: No AWS resources deployed; run terraform destroy -auto-approve in infra/terraform/aws if provisioned."


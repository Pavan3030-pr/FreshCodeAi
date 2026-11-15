PY := $(shell command -v python3 || command -v python)
.PHONY: record install run test test-py test-js e2e doctor live deploycheck audit docker runner-image
install:
	$(PY) -m pip install -r requirements-dev.txt
run:
	uvicorn app.main:app --reload --port 8000
test: test-py test-js
test-py:
	$(PY) -m pytest -q
test-js:
	node --test tests/js/lib.test.js tests/js/dom.test.js tests/js/landing.test.js
record:
	$(PY) tests/e2e/record_all.py

e2e:
	$(PY) tests/e2e/run_e2e.py /tmp/freshcode-e2e
doctor:
	$(PY) scripts/preflight.py
live:
	$(PY) scripts/live_check.py
deploycheck:
	$(PY) scripts/deploycheck.py
audit:
	$(PY) -m pip_audit -r requirements.txt
docker:
	docker build -t freshcode-ai .
runner-image:
	docker build -f runner/Dockerfile -t freshcode-runner:latest runner

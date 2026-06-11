.PHONY: verify test test-docker lint

verify: lint test

lint:
	bash -n install.sh scripts/configure-remote.sh tests/smoke.sh tests/fake-agent.sh tests/fake-project-test.sh
	bash -n templates/common/loopctl templates/common/.agentic-loop/bin/verify.sh
	bash -n templates/common/.agentic-loop/bin/test.sh templates/common/.agentic-loop/bin/smoke.sh
	bash -n examples/signoz/signoz.sh
	python3 -m py_compile runtime/loopctl.py runtime/quality_gate.py tests/otel_receiver.py tests/fake-openspec.py tests/test_jira.py
	@if command -v ruff >/dev/null 2>&1; then ruff format --check runtime tests && ruff check runtime tests; fi

test:
	bash tests/smoke.sh
	bash tests/quality-gate.sh
	python3 tests/test_jira.py

test-docker:
	bash tests/docker-smoke.sh

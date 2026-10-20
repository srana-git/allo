# allo — Phase 1
#
# Secrets come from pass; Cloudflare auth from cf-env. Nothing secret is echoed.

SHELL := /bin/bash
WORKER_DIR := worker
CF_PROFILE := srana

.PHONY: help install deploy-worker worker-secrets d1-schema d1-seed seed push-agent \
        push-tests test-agent test-worker lint show-agent credits clean

help:
	@echo "allo — make targets"
	@echo ""
	@echo "  install        npm install in worker/ and uv sync at the root"
	@echo "  deploy-worker  apply D1 schema, push secrets, deploy the Worker"
	@echo "  test-worker    run the Worker vitest suite (npm test)"
	@echo "  push-agent     push the agent config in agent/ to ElevenLabs"
	@echo "  test-agent     run the 5-test suite in tests/ and write evals/results/"
	@echo "  show-agent     print the live agent config from the API"
	@echo "  credits        print the ElevenLabs subscription character count"
	@echo "  lint           local repo hygiene checks"

install:
	cd $(WORKER_DIR) && npm install
	uv sync

# --- Worker -----------------------------------------------------------------

d1-schema:
	cd $(WORKER_DIR) && eval "$$(cf-env $(CF_PROFILE))" && \
	  wrangler d1 execute allo --file=schema.sql --remote

d1-seed:
	cd $(WORKER_DIR) && eval "$$(cf-env $(CF_PROFILE))" && \
	  wrangler d1 execute allo --file=seed.sql --remote

seed:
	uv run python scripts/gen_seed.py
	$(MAKE) d1-seed

worker-secrets:
	cd $(WORKER_DIR) && eval "$$(cf-env $(CF_PROFILE))" && \
	  pass show apis/allo-tools-secret | head -1 | wrangler secret put TOOLS_SECRET && \
	  if pass show apis/allo-webhook-secret >/dev/null 2>&1; then \
	    pass show apis/allo-webhook-secret | head -1 | wrangler secret put ELEVENLABS_WEBHOOK_SECRET; \
	  fi

deploy-worker:
	cd $(WORKER_DIR) && eval "$$(cf-env $(CF_PROFILE))" && wrangler deploy

# --- agent ------------------------------------------------------------------

push-agent:
	uv run python scripts/push_agent.py

push-tests:
	uv run python scripts/run_tests.py --no-push

test-agent:
	uv run python scripts/run_tests.py

show-agent:
	uv run python scripts/show_agent.py

credits:
	uv run python scripts/credits.py

# --- hygiene ----------------------------------------------------------------

test-worker:
	cd $(WORKER_DIR) && npm test

lint:
	uv run python -m compileall -q scripts >/dev/null && echo "python: ok"
	cd $(WORKER_DIR) && npx tsc --noEmit && echo "typescript: ok"
	gitleaks detect --source . --no-banner && echo "gitleaks: no leaks"

clean:
	rm -rf $(WORKER_DIR)/node_modules $(WORKER_DIR)/.wrangler

# Hound dev targets. Override the interpreter with: make test PY=/path/to/python
BACKEND := $(CURDIR)/backend
PY ?= $(BACKEND)/.venv/bin/python
PORT ?= 8000

.PHONY: dev test demo schemas-check

dev:
	cd $(BACKEND) && $(PY) -m uvicorn hound.api:app --reload --port $(PORT)

test:
	cd $(BACKEND) && $(PY) -m pytest -q

demo:
	cd $(BACKEND) && HOUND_CACHE_MODE=prefer_cache $(PY) -m uvicorn hound.api:app --port $(PORT)

schemas-check:
	cd $(BACKEND) && $(PY) -c "from hound.contracts import EXAMPLES, validate_case, validate_trace; \
	files = sorted(EXAMPLES.glob('*.case.json')) + sorted(EXAMPLES.glob('*.trace.json')); \
	assert files, f'no examples found in {EXAMPLES}'; \
	import json; [((validate_case if f.name.endswith('.case.json') else validate_trace)(json.loads(f.read_text())), print('ok', f.name)) for f in files]"

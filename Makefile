.PHONY: install lint test evals demo all
install: ; pip install -e ".[dev]"
lint:    ; ruff check src tests examples
test:    ; pytest -q
evals:   ; python examples/run_evals.py
demo:    ; python examples/run_close.py --level A3 && python examples/run_close.py --level A1
all: lint test evals

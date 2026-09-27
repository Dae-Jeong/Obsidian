.PHONY: check test index

check: test
	uv run python -m harness check

test:
	uv run python -W error::ResourceWarning -m unittest discover -s tests -v

index:
	uv run python -m harness index

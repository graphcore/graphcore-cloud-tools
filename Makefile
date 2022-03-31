# Add to PHONY target list so cmds always run even when nothing has changed
.PHONY: lint test

lint:
	yapf --recursive --in-place .
	python3 examples_utils/testing/test_copyright.py

test:
	pytest --forked -n 5

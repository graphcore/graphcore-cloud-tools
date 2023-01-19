# Add to PHONY target list so cmds always run even when nothing has changed
.PHONY: test compile

test:
	pytest --forked -n 5

compile:
	python -m examples_utils cppimport_build .

# README

This hook checks any requirements files in the commit to ensure that all requirements are pinned to a specific version.

It will allow flexibility at the semver patch-level; i.e. the `~=` operator is allowed, but `>=` or completely
unversioned requirements will cause a failure.

There may be occasions where it's actually preferable not to pin requirements, in those cases you can add a comment
`# req: unpinned` next to the requirement in the `requirements.txt`, e.g.:

```text
protobuf==3.19.4
torch>=2.0.0+cpu # req: unpinned
```

If unversioned named requirements are found, the hook will attempt to detect the versions installed in the current
venv. This means that it must run as `language: system`, in order to prevent `pre-commit` creating a new environment
which would prevent us detecting installed packages. Because of this, we call a bash wrapper script rather than directly
calling the module, which allows us to install the hook requirements.

> **`Note`**: This means that the hook will pollute the parent environment by installing the `requirements-parser` package.

The script is unable to auto-fix repository-based requirements.

```yaml
repos:
  - repo: git@github.com:graphcore/graphcore-cloud-tools.git
    hooks:
      - id: pinned-requirements
        name: Pinned Requirements
        description: Checks that all requirements files have been pinned. Has to be run as a system hook to allow reading local deps
        entry: bash utils/linters/pinned_requirements/entrypoint.sh
        language: system
```

## To run the tests

Install the development requirements:

```bash
$ pip install requirements-dev.txt
...
```

Run the tests with pytest:

```bash
$ python3 -m pytest test_pinned_requirements.py
...
```

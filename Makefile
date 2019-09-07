VENV = . ./venv/bin/activate;
TEST = pytest --cov-config=setup.cfg --cov=result_types tests
PKG_DIR = falcon_marshmallow
TEST_DIR = tests
LINE_LENGTH = 80

.PHONY: build clean distribute fmt lint setup test

all: fmt lint test

venv: venv/bin/activate
venv/bin/activate: setup.py
	python3 -m venv venv
	$(VENV) pip install \
		black \
		flake8 \
		mypy \
		pylint \
		pydocstyle \
		pytest \
		tox \
		wheel
	$(VENV) pip install -e .
	touch venv/bin/activate


venv-clean:
	rm -rf venv


build: venv build-clean
	$(VENV) python setup.py sdist bdist_wheel


# Requires BUILD_TAG to be set on the CLI or in an environment variable,
# e.g. BUILD_TAG=1 make build-dev
build-dev: venv build-clean
	$(VENV) python setup.py sdist bdist_wheel


build-clean:
	rm -rf build dist
	rm -rf *.egg-info

clean:
	find . -type f -name "*.py[co]" -delete
	find . -type d -name "__pycache__" -delete

# Requires VERSION to be set on the CLI or in an environment variable,
# e.g. VESRSION=1.0.0 make distribute
distribute: build
	git tag -s "v$(VERSION)"
	twine upload -s dist/*
	git push --tags

fmt: venv
	$(VENV) black --line-length $(LINE_LENGTH) *.py $(PKG_DIR) $(TEST_DIR)

lint: venv
	$(VENV) pylint --errors-only *.py $(PKG_DIR) $(TEST_DIR)
	$(VENV) mypy *.py $(PKG_DIR) $(TEST_DIR)
	$(VENV) black --check --line-length $(LINE_LENGTH) *.py $(PKG_DIR) $(TEST_DIR)

setup: venv-clean venv

test: venv
	$(VENV) tox

# Requires TESTENV to be set on the CLI or in an environment variable,
# e.g. TESTENV=py37 make test-env to test against python3.7. The specified
# test env must be configured in the tox configuration file.
test-env: venv
	$(VENV) tox -e $(TESTENV)

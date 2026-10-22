# ==============================================================================
# Makefile — sun-flat-yamada/dotfiles
# ==============================================================================

.PHONY: help install dry-run status doctor validate test hooks

PYTHON ?= python

help:
	@echo "sun-flat-yamada/dotfiles — Available Targets:"
	@echo "  make dry-run    Preview dotfiles installation without modifying disk"
	@echo "  make install    Install dotfiles for current OS with automatic backup"
	@echo "  make status     Show synchronization status of all managed dotfiles"
	@echo "  make doctor     Run environment and CLI tool diagnostics"
	@echo "  make validate   Validate manifest, config syntax, front-matter, and filenames"
	@echo "  make test       Run all automated unit & integration test suites"
	@echo "  make hooks      Install local Git pre-commit and commit-msg hooks"

dry-run:
	$(PYTHON) scripts/dotfiles.py install --dry-run

install:
	$(PYTHON) scripts/dotfiles.py install

status:
	$(PYTHON) scripts/dotfiles.py status

doctor:
	$(PYTHON) scripts/dotfiles.py doctor

validate:
	$(PYTHON) scripts/dotfiles.py validate
	$(PYTHON) scripts/validate-frontmatter.py
	$(PYTHON) scripts/validate-filenames.py
	$(PYTHON) scripts/apply-template.py --check

test:
	$(PYTHON) tests/test-dotfiles.py -v
	$(PYTHON) tests/test-permission-guard.py -v
	$(PYTHON) tests/test-validate-frontmatter.py -v

hooks:
	$(PYTHON) scripts/install-hooks.py

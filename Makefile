SHELL := /bin/sh
.DEFAULT_GOAL := help

TASK := ./scripts/culvia-dev
WEB_BIN := ./bin/culvia-web
HOST ?= 127.0.0.1
PORT ?= 8501
WEB_ARGS ?=
SERVER_ARGS ?=
CLI_ARGS ?=

TASK_COMMANDS := help init install test js-check lint format pre-commit-install pre-commit \
	desktop-ready desktop-dev app-icons backend-plan backend-placeholder backend-build \
	python-release-plan python-release \
	macos-release-plan macos-release macos-lite-release-plan macos-lite-release \
	macos-notarized-release-plan macos-notarized-release \
	windows-release-plan windows-release windows-lite-release-plan windows-lite-release \
	linux-release-plan linux-release linux-lite-release-plan linux-lite-release \
	lite-release-plan lite-release release-status clean

CLI_COMMANDS := cli runtime-config runtime-configure runtime-reset-config runtime-doctor \
	runtime-create runtime-install runtime-ensure

.PHONY: $(TASK_COMMANDS) $(CLI_COMMANDS) web server

$(TASK_COMMANDS):
	@$(TASK) $@

$(CLI_COMMANDS):
	@$(TASK) $@ $(CLI_ARGS)

web:
	@$(WEB_BIN) --host $(HOST) --port $(PORT) $(WEB_ARGS)

server:
	@$(TASK) server $(SERVER_ARGS)

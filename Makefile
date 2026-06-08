SHELL := /bin/sh

TASK := ./scripts/culvia-dev
WEB_BIN := ./bin/culvia-web
HOST ?= 127.0.0.1
PORT ?= 8501
WEB_ARGS ?=
SERVER_ARGS ?=
CLI_ARGS ?=

.PHONY: help init install web server cli runtime-config runtime-configure runtime-reset-config runtime-doctor runtime-create runtime-install runtime-ensure test js-check lint format pre-commit-install pre-commit gate gate-full desktop-ready desktop-dev app-icons backend-plan backend-placeholder backend-build python-release-plan python-release macos-release-plan macos-release macos-lite-release-plan macos-lite-release macos-notarized-release-plan macos-notarized-release windows-release-plan windows-release windows-lite-release-plan windows-lite-release linux-release-plan linux-release linux-lite-release-plan linux-lite-release lite-release-plan lite-release release-status clean

help:
	@$(TASK) help

init:
	@$(TASK) init

install:
	@$(TASK) install

web:
	@$(WEB_BIN) --host $(HOST) --port $(PORT) $(WEB_ARGS)

server:
	@$(TASK) server $(SERVER_ARGS)

cli:
	@$(TASK) cli $(CLI_ARGS)

runtime-config:
	@$(TASK) runtime-config $(CLI_ARGS)

runtime-configure:
	@$(TASK) runtime-configure $(CLI_ARGS)

runtime-reset-config:
	@$(TASK) runtime-reset-config $(CLI_ARGS)

runtime-doctor:
	@$(TASK) runtime-doctor $(CLI_ARGS)

runtime-create:
	@$(TASK) runtime-create $(CLI_ARGS)

runtime-install:
	@$(TASK) runtime-install $(CLI_ARGS)

runtime-ensure:
	@$(TASK) runtime-ensure $(CLI_ARGS)

test:
	@$(TASK) test

js-check:
	@$(TASK) js-check

lint:
	@$(TASK) lint

format:
	@$(TASK) format

pre-commit-install:
	@$(TASK) pre-commit-install

pre-commit:
	@$(TASK) pre-commit

gate:
	@$(TASK) gate

gate-full:
	@$(TASK) gate-full

desktop-ready:
	@$(TASK) desktop-ready

desktop-dev:
	@$(TASK) desktop-dev

app-icons:
	@$(TASK) app-icons

backend-plan:
	@$(TASK) backend-plan

backend-placeholder:
	@$(TASK) backend-placeholder

backend-build:
	@$(TASK) backend-build

python-release-plan:
	@$(TASK) python-release-plan

python-release:
	@$(TASK) python-release

macos-release-plan:
	@$(TASK) macos-release-plan

macos-release:
	@$(TASK) macos-release

macos-lite-release-plan:
	@$(TASK) macos-lite-release-plan

macos-lite-release:
	@$(TASK) macos-lite-release

macos-notarized-release-plan:
	@$(TASK) macos-notarized-release-plan

macos-notarized-release:
	@$(TASK) macos-notarized-release

windows-release-plan:
	@$(TASK) windows-release-plan

windows-release:
	@$(TASK) windows-release

windows-lite-release-plan:
	@$(TASK) windows-lite-release-plan

windows-lite-release:
	@$(TASK) windows-lite-release

linux-release-plan:
	@$(TASK) linux-release-plan

linux-release:
	@$(TASK) linux-release

linux-lite-release-plan:
	@$(TASK) linux-lite-release-plan

linux-lite-release:
	@$(TASK) linux-lite-release

lite-release-plan:
	@$(TASK) lite-release-plan

lite-release:
	@$(TASK) lite-release

release-status:
	@$(TASK) release-status

clean:
	@$(TASK) clean

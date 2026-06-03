INSTALL_DIR := /usr/local/bin
BINARY      := jarvis-cli

.PHONY: build release install clean

## build — debug build
build:
	cargo build

## release — optimized build
release:
	cargo build --release

## install — release build → /usr/local/bin, ad-hoc codesign for macOS Gatekeeper
install: release
	cp target/release/$(BINARY) $(INSTALL_DIR)/$(BINARY)
	codesign --force --sign - $(INSTALL_DIR)/$(BINARY)
	@echo "✓ Installed $(INSTALL_DIR)/$(BINARY)"
	@$(INSTALL_DIR)/$(BINARY) --help | head -1

## clean — remove build artifacts
clean:
	cargo clean

# Contributing

Contributions are welcome under the project's GPL-3.0-only license.

## Before opening a pull request

1. Create an isolated Python environment and install `requirements.lock`. Update both
   dependency files when intentionally changing a direct dependency.
2. Keep credential discovery read-only and never add real tokens, account IDs, balances,
   device identifiers, or local absolute paths to tests and fixtures.
3. Exercise image and provider changes with `--dry-run`; do not make a test connect to BLE or
   overwrite a device slot.
4. Add behavior-focused regression tests for provider parsing, credential boundaries, layout,
   and scheduler generation.
5. Run:

   ```bash
   .venv/bin/python -m unittest discover -s tests -v
   .venv/bin/python -m compileall -q balances config.py refresh.py render.py tests vendor/epdiy_display.py
   bash -n scheduler/install.sh scheduler/uninstall.sh
   plutil -lint scheduler/com.eink.printer.refresh.plist
   git diff --check
   ```

Document protocol-derived changes in `vendor/README.md` and `THIRD_PARTY_NOTICES.md`, including
the upstream URL, exact commit or resource version, and license.

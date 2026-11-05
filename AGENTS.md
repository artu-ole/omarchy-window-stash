# Desktop test etiquette

Before any automated test that takes focus, injects mouse or keyboard input,
changes monitor/layout state, or restarts desktop components, send a desktop
notification telling the user to pause input and wait three full seconds.
Use the shared `tests/desktop_test.py` context/decorator for test suites and
equivalent notification/countdown handling for ad hoc desktop checks.

Send a completion notification after cleanup so the user knows they can resume
input. Preserve existing windows, stash entries, settings, and monitor geometry.
Non-graphical unit tests, linting, and read-only checks do not need a countdown.

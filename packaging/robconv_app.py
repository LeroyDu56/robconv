"""PyInstaller entry script for robconv.exe (see .github/workflows/release.yml)."""

from robconv.app import main

raise SystemExit(main())

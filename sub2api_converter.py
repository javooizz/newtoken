"""Compatibility wrapper for the desktop converter app."""

from __future__ import annotations

from newtoken.desktop.converter_app import *  # noqa: F401,F403
from newtoken.desktop.converter_app import ConverterApp


if __name__ == "__main__":
    ConverterApp().run()


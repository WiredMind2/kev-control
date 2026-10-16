"""Pytest must not click, type, move the pointer, or focus another app."""

import os

os.environ["KEV_CONTROL_INJECT"] = "0"

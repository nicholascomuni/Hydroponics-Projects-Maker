"""Exceptions and warnings raised by the design model."""

from __future__ import annotations


class DesignError(ValueError):
    """A design input is physically impossible or violates a hard constraint."""


class DesignWarning(UserWarning):
    """A design is feasible but falls outside a recommended engineering range."""

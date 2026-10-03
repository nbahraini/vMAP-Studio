"""File Format Adapter system. Only adapters that really exist are registered."""
from vmap.formats.base import (ConversionReport, FormatAdapter, FormatError,
                               FormatRegistry, ImportResult)
from vmap.formats.universal import UniversalAdapter


def default_registry() -> FormatRegistry:
    reg = FormatRegistry()
    reg.register(UniversalAdapter())
    return reg


__all__ = ["ConversionReport", "FormatAdapter", "FormatError", "FormatRegistry",
           "ImportResult", "UniversalAdapter", "default_registry"]

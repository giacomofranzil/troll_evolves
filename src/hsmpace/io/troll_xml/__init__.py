"""TRoll XML → Case workbook. TRoll is an adapter, not the internal schema."""

from .reader import case_from_troll, write_troll_case

__all__ = ["case_from_troll", "write_troll_case"]

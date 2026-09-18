"""RAPID -> FANUC TP conversion: evaluation of RAPID data, mapping rules, report."""

from robconv.convert.config import ConversionConfig
from robconv.convert.report import build_report
from robconv.convert.translate import ConversionResult, convert

__all__ = ["ConversionConfig", "ConversionResult", "build_report", "convert"]

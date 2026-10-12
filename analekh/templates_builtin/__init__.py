"""Built-in sector templates (design doc 15.2), generated in code so the repository carries no
binary workbooks. Used as a fallback when the analyst has not uploaded a template."""

from analekh.templates_builtin.base import TemplateSpec, build
from analekh.templates_builtin.specs import BUILTIN, CONSUMER, NBFC

__all__ = ["BUILTIN", "CONSUMER", "NBFC", "TemplateSpec", "build"]

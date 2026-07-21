"""Thin re-export shim — all public names now live in lore_audit.read.*

This module is preserved verbatim so every existing ``from lore_audit.read_contracts
import <anything>`` (including ``AuditReadError``) continues to work unchanged.
"""

from lore_audit.read import *  # noqa: F401, F403
from lore_audit.read import __all__

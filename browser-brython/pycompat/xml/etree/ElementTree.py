"""Minimal ElementTree shim for the Brython demo.

Brython 3.14 does not currently ship ``xml.etree.ElementTree``. The main
legacy ``.doc`` path does not need XML parsing, but importing ``doc2md.cli``
loads the OOXML fallback module. This shim keeps import-time compatibility and
makes OOXML fallback fail softly through the existing ``ParseError`` path.
"""


class ParseError(Exception):
    """Raised when XML parsing is unavailable in this browser wrapper."""


class Element:
    """Placeholder used only for annotations in the imported package."""


def fromstring(_data):
    raise ParseError("xml.etree.ElementTree is unavailable in Brython")

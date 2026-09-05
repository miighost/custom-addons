# -*- coding: utf-8 -*-
"""Pure-python ESC/POS ticket renderer.

No external dependencies: builds the raw byte stream that generic thermal
printers (Xprinter, Rongta, Gprinter, Sunmi, most no-name 58/80mm units)
accept on TCP port 9100.

The renderer is deliberately transport-agnostic.  It only produces bytes;
whether those bytes reach the printer from the Odoo server or from a local
agent is decided elsewhere.  That separation is what makes the move to
cloud hosting a config change instead of a rewrite.
"""

# --- ESC/POS command constants -------------------------------------------
ESC = b"\x1b"
GS = b"\x1d"

INIT = ESC + b"@"                 # initialise printer
ALIGN_LEFT = ESC + b"a\x00"
ALIGN_CENTER = ESC + b"a\x01"
ALIGN_RIGHT = ESC + b"a\x02"
BOLD_ON = ESC + b"E\x01"
BOLD_OFF = ESC + b"E\x00"
UNDERLINE_ON = ESC + b"-\x01"
UNDERLINE_OFF = ESC + b"-\x00"
# GS ! n  -- n high nibble = width multiplier, low nibble = height multiplier
SIZE_NORMAL = GS + b"!\x00"
SIZE_2H = GS + b"!\x01"           # double height
SIZE_2W2H = GS + b"!\x11"         # double width + double height
CUT_PARTIAL = GS + b"V\x42\x00"   # feed and partial cut
FEED = b"\n"


def _feed(n=1):
    return ESC + b"d" + bytes([max(0, min(255, n))])


class EscposTicket(object):
    """Accumulates ESC/POS bytes for one ticket."""

    def __init__(self, width=48, codepage="cp437"):
        # width = characters per line in normal font.
        # 80mm paper at font A is 48; 58mm paper at font A is 32.
        self.width = width
        self.codepage = codepage
        self._buf = bytearray()
        self._buf += INIT

    # -- low level -------------------------------------------------------
    def raw(self, data):
        self._buf += data
        return self

    def _encode(self, text):
        if text is None:
            text = ""
        if not isinstance(text, str):
            text = str(text)
        try:
            return text.encode(self.codepage, "replace")
        except LookupError:
            return text.encode("ascii", "replace")

    # -- text ------------------------------------------------------------
    def text(self, value, bold=False, center=False, right=False,
             double=False, big=False, underline=False):
        if center:
            self._buf += ALIGN_CENTER
        elif right:
            self._buf += ALIGN_RIGHT
        else:
            self._buf += ALIGN_LEFT

        if big:
            self._buf += SIZE_2W2H
        elif double:
            self._buf += SIZE_2H
        else:
            self._buf += SIZE_NORMAL

        if bold:
            self._buf += BOLD_ON
        if underline:
            self._buf += UNDERLINE_ON

        self._buf += self._encode(value) + FEED

        if underline:
            self._buf += UNDERLINE_OFF
        if bold:
            self._buf += BOLD_OFF
        self._buf += SIZE_NORMAL + ALIGN_LEFT
        return self

    def rule(self, char="-"):
        return self.text(char * self.width)

    def blank(self, n=1):
        self._buf += _feed(n)
        return self

    def columns(self, left, right, bold=False):
        """Left-aligned + right-aligned on one line, padded to self.width."""
        left = "" if left is None else str(left)
        right = "" if right is None else str(right)
        pad = self.width - len(left) - len(right)
        if pad < 1:
            # Truncate the left side rather than wrapping unpredictably.
            left = left[: max(0, self.width - len(right) - 1)]
            pad = max(1, self.width - len(left) - len(right))
        return self.text(left + (" " * pad) + right, bold=bold)

    def wrap(self, value, indent=0, bold=False):
        """Word-wrap a long string to the paper width."""
        value = "" if value is None else str(value)
        avail = max(8, self.width - indent)
        prefix = " " * indent
        words = value.split()
        if not words:
            return self
        line = ""
        for word in words:
            candidate = word if not line else line + " " + word
            if len(candidate) <= avail:
                line = candidate
            else:
                if line:
                    self.text(prefix + line, bold=bold)
                # A single word longer than the line gets hard-split.
                while len(word) > avail:
                    self.text(prefix + word[:avail], bold=bold)
                    word = word[avail:]
                line = word
        if line:
            self.text(prefix + line, bold=bold)
        return self

    def cut(self, feed_lines=4):
        self._buf += _feed(feed_lines) + CUT_PARTIAL
        return self

    def bytes(self):
        return bytes(self._buf)


def _render_line_group(ticket, title, lines, marker=""):
    """Render one group of order lines (new / cancelled / already sent)."""
    if not lines:
        return
    if title:
        ticket.text(title, bold=True, underline=True)
    for line in lines:
        qty = line.get("qty") or line.get("qty_num") or ""
        name = line.get("product_name") or ""
        prefix = "%s%-4s" % (marker, str(qty))
        # Product name is the thing the kitchen reads across the room:
        # double height, and wrapped so nothing is silently lost.
        ticket.text("%s%s" % (prefix, name[: ticket.width - len(prefix)]),
                    bold=True, double=True)
        overflow = name[ticket.width - len(prefix):]
        if overflow:
            ticket.wrap(overflow, indent=len(prefix), bold=True)
        attrs = line.get("attribute_values")
        if attrs:
            ticket.wrap("(%s)" % attrs, indent=len(prefix))
        note = line.get("note")
        if note:
            ticket.wrap("** %s" % note, indent=len(prefix), bold=True)
    ticket.blank(1)


def render_kot(data, width=48, codepage="cp437", station="KITCHEN"):
    """Render a kitchen/bar ticket from the dict produced by utils.js.

    `data` is the object returned by exportForKitchenPrinting(): it carries
    name, table_name, floor_name, cashier, datetime, print_label and the
    new_lines / cancelled_lines / sent_lines groups.
    """
    data = data or {}
    ticket = EscposTicket(width=width, codepage=codepage)

    ticket.text(station or "KITCHEN", bold=True, big=True, center=True)
    ticket.rule("=")

    table = data.get("table_name")
    floor = data.get("floor_name")
    if table:
        label = "TABLE %s" % table
        if floor:
            label += "  (%s)" % floor
        ticket.text(label, bold=True, double=True, center=True)

    ticket.columns("Order:", data.get("name") or "")
    ticket.columns("Time:", data.get("datetime") or "")
    if data.get("cashier"):
        ticket.columns("Staff:", data.get("cashier"))

    print_label = data.get("print_label")
    if print_label:
        ticket.text(print_label, bold=True, center=True)

    ticket.rule("=")

    is_addition = bool(data.get("is_addition"))
    new_lines = data.get("new_lines") or []
    cancelled_lines = data.get("cancelled_lines") or []

    if is_addition:
        # A re-fire: the kitchen must see only what changed, loudly.
        _render_line_group(ticket, "*** ADDED ***", new_lines, marker="+ ")
        if cancelled_lines:
            ticket.rule("-")
            _render_line_group(ticket, "*** CANCELLED ***", cancelled_lines,
                               marker="- ")
    else:
        _render_line_group(ticket, None, data.get("orderlines") or [])

    note = data.get("general_note")
    if note:
        ticket.rule("-")
        ticket.text("ORDER NOTE", bold=True)
        ticket.wrap(note, bold=True)

    ticket.rule("=")
    ticket.cut()
    return ticket.bytes()

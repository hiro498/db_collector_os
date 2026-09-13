"""Explicitly unimplemented P1+ extension points.

Per spec section 46/53: these modules exist so CORE's data model and
interfaces don't have to change shape later, but none of them contain real
logic in this P0, and none of them call any external/paid API. Every public
function raises NotImplementedError with a clear message rather than
returning a plausible-looking but fabricated result -- see section 46's
explicit "do not fake completion with dummy values" instruction.
"""

"""Counterfactual branching (#82): replay every alternative of a decision Jev made, from the same
saved state, and measure which one reached the milestone soonest.

Nothing in this package imports pyboy or the TypeSafe SDK at module scope; the worker imports both
inside the function that runs a branch."""

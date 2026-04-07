"""
Execution package.

Execution is the layer that applies a ChangePlan to devices and returns:
pre snapshot state and observed post apply state.

The orchestration engine depends on the interface, not on the transport.
"""

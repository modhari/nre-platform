# BGP diagnostics validation guide

This guide is for Check in 3.

It gives you a fast way to validate that the new deterministic BGP diagnostics path is
behaving correctly and that grouped alerts reduce noise when many symptoms share one
dependency.

## What changed in Check in 3

The diagnosis response now includes:

- `diagnosis_counts`
- `validation_summary`

Those fields make testing easier because you no longer need to inspect the whole
response body manually for every scenario.

## Validation fields

### `diagnosis_counts`

This is a compact count of findings by type.

Example:

```json
{
  "session_down": 2,
  "peer_not_advertising": 1,
  "inbound_policy_drop": 1
}

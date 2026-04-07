# BGP Option B sample notes

Check in 4 keeps the diagnostics path read only, but it now returns `proposed_actions`
and `approval_summary`.

## What to look for

When you post the existing BGP sample request to:

```bash
curl -X POST http://localhost:8091/diagnostics/bgp \
  -H "Content-Type: application/json" \
  -d @bgp_test.json

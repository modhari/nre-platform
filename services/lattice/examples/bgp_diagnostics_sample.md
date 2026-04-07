# BGP diagnostics sample request for Lattice

This example shows the stronger normalized snapshot contract introduced in Check in 2.

Use it to test:

- one established session with no received routes
- two failed sessions that share one route reflector dependency
- one inbound policy drop
- one grouped incident that should reduce alert fatigue

## Sample curl

```bash
curl -X POST http://localhost:8081/diagnostics/bgp \
  -H "Content-Type: application/json" \
  -d '{
    "fabric": "prod-dc-west",
    "device": "leaf-01",
    "snapshot": {
      "correlation_window_seconds": 180,
      "neighbors": [
        {
          "peer": "10.0.0.11",
          "session_state": "Established",
          "prefixes_received": 0,
          "shared_dependency": "rr-01",
          "last_event_at": "2026-03-29T12:00:05Z"
        },
        {
          "peer": "10.0.0.12",
          "session_state": "Idle",
          "shared_dependency": "rr-01",
          "last_error": "tcp_connect_failed",
          "last_event_at": "2026-03-29T12:00:06Z"
        },
        {
          "peer": "10.0.0.13",
          "session_state": "Idle",
          "shared_dependency": "rr-01",
          "last_error": "tcp_connect_failed",
          "last_event_at": "2026-03-29T12:00:07Z"
        }
      ],
      "adj_rib_in": [
        {
          "prefix": "192.0.2.0/24",
          "peer": "10.0.0.11",
          "reason": "received_pre_policy",
          "shared_dependency": "policy-domain-a"
        }
      ],
      "loc_rib": [],
      "adj_rib_out": [],
      "events": [
        {
          "event_type": "session_flap",
          "peer": "10.0.0.12",
          "shared_dependency": "rr-01",
          "occurred_at": "2026-03-29T12:00:06Z",
          "message": "peer flap detected"
        }
      ],
      "logs": [
        {
          "occurred_at": "2026-03-29T12:00:05Z",
          "source": "bgp",
          "peer": "10.0.0.11",
          "shared_dependency": "rr-01",
          "message": "neighbor 10.0.0.11 established but no prefixes received"
        },
        {
          "occurred_at": "2026-03-29T12:00:06Z",
          "source": "tcp",
          "peer": "10.0.0.12",
          "shared_dependency": "rr-01",
          "message": "tcp connect failed to route reflector rr-01"
        },
        {
          "occurred_at": "2026-03-29T12:00:07Z",
          "source": "tcp",
          "peer": "10.0.0.13",
          "shared_dependency": "rr-01",
          "message": "tcp connect failed to route reflector rr-01"
        },
        {
          "occurred_at": "2026-03-29T12:00:08Z",
          "source": "policy",
          "prefix": "192.0.2.0/24",
          "shared_dependency": "policy-domain-a",
          "message": "prefix 192.0.2.0/24 denied by inbound policy"
        }
      ]
    }
  }'

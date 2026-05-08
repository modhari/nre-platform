# Real device connectivity

The NRE Platform ships with a gNMI simulator for local development.
Switching to real devices requires two changes — no code changes needed.

## Step 1 — Disable the simulator

In `values.local.yaml`:

```yaml
gnmiSimulator:
  enabled: false
```

## Step 2 — Enable gnmic with real targets

```yaml
gnmic:
  enabled: true
  defaultUsername: "admin"
  defaultPassword: "your-password"
  insecure: false
  skipVerify: false
  targets:
    - name: leaf-01
      address: 192.168.1.1:6030
    - name: leaf-02
      address: 192.168.1.2:6030
    - name: leaf-03
      address: 192.168.1.3:6030
    - name: leaf-04
      address: 192.168.1.4:6030
```

## Step 3 — Deploy

```bash
make deploy
```

## What happens

gnmic subscribes to BGP and EVPN sensor groups on all targets.
It writes event-format JSON to /data/gnmic_bgp.json and
/data/gnmic_evpn.json on the shared PVC — the same paths
the simulator writes to. Capsule picks up the changes via
watchfiles within 500ms. The nre-agent loop continues unchanged.

## Supported platforms

- Arista EOS (gNMI port 6030)
- Juniper Junos (gNMI port 32767)
- Cisco NX-OS (gNMI port 50051)
- Nokia SR Linux (gNMI port 57400)

Nokia SR Linux uses native paths for EVPN MAC mobility detection.
All other vendors use OpenConfig paths.

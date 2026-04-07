from pathlib import Path

from internal.knowledge.planning.evpn_capability_bridge import (
    EVPNCapabilityBridge,
    EVPNCapabilityRegistry,
    pretty_print_governed_plan,
)
from internal.knowledge.planning.evpn_mcp_planner import EVPNMCPPlanner
from internal.knowledge.reasoning.evpn_reasoner import EvpnReasoner, ProblemContext


def main() -> None:
    coverage_path = Path("data/generated/schema/evpn_vxlan_coverage_summary.json")

    registry = EVPNCapabilityRegistry(coverage_summary_path=coverage_path)
    bridge = EVPNCapabilityBridge(registry=registry)
    planner = EVPNMCPPlanner()
    reasoner = EvpnReasoner()

    tests = [
        ProblemContext(
            question="A Juniper EVPN VXLAN fabric is showing host movement and duplicate MAC symptoms. What governed inspections are allowed?",
            vendor="juniper",
            nos_family="junos",
            scenario="mac_mobility_analysis",
            capability="evpn_mac_vrf_state",
            limit=4,
        ),
        ProblemContext(
            question="An Arista deployment spans multiple EVPN domains across sites. What governed MCP checks should survive capability gating?",
            vendor="arista",
            nos_family="eos",
            scenario="dci_connectivity_analysis",
            capability="vxlan_vni_oper_state",
            limit=4,
        ),
        ProblemContext(
            question="In Cisco MP BGP EVPN, what remains allowed once capability coverage is enforced for gateway and ARP suppression analysis?",
            vendor="cisco",
            nos_family="nx_os",
            scenario="anycast_gateway_validation",
            capability="bgp_evpn_peer_state",
            limit=4,
        ),
    ]

    for ctx in tests:
        reasoning = reasoner.reason(ctx)
        mcp_plan = planner.build_plan(ctx, reasoning)
        governed = bridge.govern(ctx, reasoning, mcp_plan)
        pretty_print_governed_plan(governed)
        print("\n" + "#" * 120 + "\n")


if __name__ == "__main__":
    main()

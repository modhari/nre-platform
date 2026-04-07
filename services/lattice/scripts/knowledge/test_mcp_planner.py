from internal.knowledge.planning.evpn_mcp_planner import EVPNMCPPlanner, pretty_print_plan
from internal.knowledge.reasoning.evpn_reasoner import EvpnReasoner, ProblemContext


def main() -> None:
    reasoner = EvpnReasoner()
    planner = EVPNMCPPlanner()

    tests = [
        ProblemContext(
            question="A Juniper EVPN VXLAN fabric is showing host movement and duplicate MAC symptoms. What should I inspect next?",
            vendor="juniper",
            nos_family="junos",
            scenario="mac_mobility_analysis",
            capability="evpn_mac_vrf_state",
            limit=4,
        ),
        ProblemContext(
            question="An Arista deployment spans multiple EVPN domains across sites. What MCP inspections should be planned next?",
            vendor="arista",
            nos_family="eos",
            scenario="dci_connectivity_analysis",
            capability="vxlan_vni_oper_state",
            limit=4,
        ),
        ProblemContext(
            question="In Cisco MP BGP EVPN, what safe inspections should follow questions around anycast gateway and ARP suppression?",
            vendor="cisco",
            nos_family="nx_os",
            scenario="anycast_gateway_validation",
            capability="bgp_evpn_peer_state",
            limit=4,
        ),
    ]

    for ctx in tests:
        reasoning = reasoner.reason(ctx)
        plan = planner.build_plan(ctx, reasoning)
        pretty_print_plan(plan)
        print("\n" + "#" * 120 + "\n")


if __name__ == "__main__":
    main()

from internal.knowledge.reasoning.evpn_reasoner import (
    EvpnReasoner,
    ProblemContext,
    pretty_print_reasoning,
)


def main() -> None:
    reasoner = EvpnReasoner()

    tests = [
        ProblemContext(
            question="A Juniper EVPN VXLAN fabric is showing host movement and duplicate MAC symptoms. What should I infer?",
            vendor="juniper",
            nos_family="junos",
            scenario="mac_mobility_analysis",
            capability="evpn_mac_vrf_state",
            limit=4,
        ),
        ProblemContext(
            question="An Arista deployment spans multiple EVPN domains across sites. What is the likely interpretation of gateway and DCI behavior?",
            vendor="arista",
            nos_family="eos",
            scenario="dci_connectivity_analysis",
            capability="vxlan_vni_oper_state",
            limit=4,
        ),
        ProblemContext(
            question="In Cisco MP BGP EVPN, how should I reason about anycast gateway and ARP suppression behavior?",
            vendor="cisco",
            nos_family="nx_os",
            scenario="anycast_gateway_validation",
            capability="bgp_evpn_peer_state",
            limit=4,
        ),
    ]

    for test in tests:
        result = reasoner.reason(test)
        pretty_print_reasoning(result)
        print("\n" + "#" * 120 + "\n")


if __name__ == "__main__":
    main()

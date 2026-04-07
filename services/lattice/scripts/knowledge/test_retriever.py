from internal.knowledge.retrieval.query_builder import EvpnQuestion, build_request
from internal.knowledge.retrieval.retriever import EvpnVxlanRetriever, pretty_print_results


def main() -> None:
    retriever = EvpnVxlanRetriever()

    tests = [
        EvpnQuestion(
            question="What does Juniper say about MAC mobility and duplicate MAC detection in EVPN VXLAN?",
            vendor="juniper",
            scenario="mac_mobility_analysis",
            limit=3,
        ),
        EvpnQuestion(
            question="How does Arista describe hierarchical multi domain EVPN and DCI gateway behavior?",
            vendor="arista",
            scenario="dci_connectivity_analysis",
            limit=3,
        ),
        EvpnQuestion(
            question="How does Cisco describe anycast gateway and ARP suppression in MP BGP EVPN?",
            vendor="cisco",
            scenario="anycast_gateway_validation",
            limit=3,
        ),
    ]

    for test in tests:
        print("\n" + "#" * 120)
        print(f"QUERY: {test.question}")
        req = build_request(test)
        results = retriever.retrieve(req)
        pretty_print_results(results)


if __name__ == "__main__":
    main()

import json

from internal.knowledge.orchestration.evpn_analysis_service import (
    EVPNAnalysisRequest,
    EVPNAnalysisService,
)


def main() -> None:
    service = EVPNAnalysisService()

    tests = [
        EVPNAnalysisRequest(
            question="A Juniper EVPN VXLAN fabric is showing host movement and duplicate MAC symptoms. What should the agent inspect next?",
            vendor="juniper",
            nos_family="junos",
            scenario="mac_mobility_analysis",
            capability="evpn_mac_vrf_state",
            device="leaf01",
            fabric="fabric-a",
            site="sjc1",
            pod="pod-a",
            vni=10101,
            mac="aa:bb:cc:dd:ee:ff",
            incident_id="INC-1001",
            timestamp_utc="2026-04-05T00:45:00Z",
            limit=4,
        ),
        EVPNAnalysisRequest(
            question="An Arista deployment spans multiple EVPN domains across sites. What should the agent verify about DCI and gateway behavior?",
            vendor="arista",
            nos_family="eos",
            scenario="dci_connectivity_analysis",
            capability="vxlan_vni_oper_state",
            device="border-leaf-01",
            fabric="fabric-west",
            site="sfo1",
            pod="edge-pod",
            vni=20500,
            vtep="10.10.10.10",
            incident_id="INC-1002",
            timestamp_utc="2026-04-05T00:46:00Z",
            limit=4,
        ),
        EVPNAnalysisRequest(
            question="In Cisco MP BGP EVPN, what inspections should survive capability governance for gateway and ARP suppression analysis?",
            vendor="cisco",
            nos_family="nx_os",
            scenario="anycast_gateway_validation",
            capability="bgp_evpn_peer_state",
            device="leaf22",
            fabric="fabric-cisco",
            site="dfw1",
            vni=33001,
            vrf="tenant-blue",
            incident_id="INC-1003",
            timestamp_utc="2026-04-05T00:47:00Z",
            limit=4,
        ),
    ]

    for req in tests:
        result = service.analyze(req)
        print("=" * 120)
        print(json.dumps(result.to_dict(), indent=2))
        print()


if __name__ == "__main__":
    main()

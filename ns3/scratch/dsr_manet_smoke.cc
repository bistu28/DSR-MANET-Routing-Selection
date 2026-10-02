#include "ns3/applications-module.h"
#include "ns3/core-module.h"
#include "ns3/dsr-module.h"
#include "ns3/flow-monitor-module.h"
#include "ns3/internet-module.h"
#include "ns3/mobility-module.h"
#include "ns3/network-module.h"
#include "ns3/wifi-module.h"

#include <fstream>
#include <iomanip>
#include <string>

using namespace ns3;

int main(int argc, char* argv[])
{
    uint32_t nodeCount = 20;
    double simulationTime = 100.0;
    double areaSize = 200.0;
    double nodeSpeed = 5.0;
    std::string trafficRate = "2kbps";
    uint32_t packetSize = 512;
    uint32_t source = 0;
    uint32_t destination = 19;
    uint32_t randomSeed = 7;
    uint32_t randomRun = 1;
    uint16_t port = 9000;
    std::string outputDir = "results";

    CommandLine commandLine(__FILE__);
    commandLine.AddValue("nodeCount", "Number of mobile nodes", nodeCount);
    commandLine.AddValue("simulationTime", "Simulation duration in seconds", simulationTime);
    commandLine.AddValue("areaSize", "Square mobility area side in metres", areaSize);
    commandLine.AddValue("nodeSpeed", "Maximum random-walk speed in m/s", nodeSpeed);
    commandLine.AddValue("trafficRate", "UDP application data rate", trafficRate);
    commandLine.AddValue("packetSize", "UDP payload size in bytes", packetSize);
    commandLine.AddValue("source", "UDP source node index", source);
    commandLine.AddValue("destination", "UDP destination node index", destination);
    commandLine.AddValue("randomSeed", "ns-3 global seed", randomSeed);
    commandLine.AddValue("randomRun", "ns-3 run number", randomRun);
    commandLine.AddValue("port", "UDP destination port", port);
    commandLine.AddValue("outputDir", "Directory for CSV and FlowMonitor files", outputDir);
    commandLine.Parse(argc, argv);

    NS_ABORT_MSG_IF(nodeCount < 2, "nodeCount must be at least 2");
    NS_ABORT_MSG_IF(source >= nodeCount || destination >= nodeCount || source == destination,
                    "source and destination must be distinct valid node indices");

    RngSeedManager::SetSeed(randomSeed);
    RngSeedManager::SetRun(randomRun);

    NodeContainer nodes;
    nodes.Create(nodeCount);

    WifiHelper wifi;
    wifi.SetStandard(WIFI_STANDARD_80211b);
    wifi.SetRemoteStationManager("ns3::ConstantRateWifiManager",
                                 "DataMode", StringValue("DsssRate2Mbps"),
                                 "ControlMode", StringValue("DsssRate1Mbps"));
    YansWifiChannelHelper channel = YansWifiChannelHelper::Default();
    YansWifiPhyHelper phy;
    phy.SetChannel(channel.Create());
    WifiMacHelper mac;
    mac.SetType("ns3::AdhocWifiMac");
    NetDeviceContainer devices = wifi.Install(phy, mac, nodes);

    MobilityHelper mobility;
    mobility.SetPositionAllocator("ns3::RandomRectanglePositionAllocator",
                                  "X", StringValue("ns3::UniformRandomVariable[Min=0|Max=" + std::to_string(areaSize) + "]"),
                                  "Y", StringValue("ns3::UniformRandomVariable[Min=0|Max=" + std::to_string(areaSize) + "]"));
    mobility.SetMobilityModel("ns3::RandomWalk2dMobilityModel",
                              "Mode", StringValue("Time"),
                              "Time", TimeValue(Seconds(1.0)),
                              "Speed", StringValue("ns3::ConstantRandomVariable[Constant=" + std::to_string(nodeSpeed) + "]"),
                              "Bounds", RectangleValue(Rectangle(0, areaSize, 0, areaSize)));
    mobility.Install(nodes);

    DsrHelper dsr;
    DsrMainHelper dsrMain;
    InternetStackHelper internet;
    internet.Install(nodes);
    Ipv4AddressHelper address;
    address.SetBase("10.1.0.0", "255.255.0.0");
    Ipv4InterfaceContainer interfaces = address.Assign(devices);
    dsrMain.Install(dsr, nodes);

    OnOffHelper onOff("ns3::UdpSocketFactory",
                      Address(InetSocketAddress(interfaces.GetAddress(destination), port)));
    onOff.SetAttribute("DataRate", DataRateValue(DataRate(trafficRate)));
    onOff.SetAttribute("PacketSize", UintegerValue(packetSize));
    ApplicationContainer sender = onOff.Install(nodes.Get(source));
    sender.Start(Seconds(1.0));
    sender.Stop(Seconds(simulationTime - 1.0));

    PacketSinkHelper sink("ns3::UdpSocketFactory",
                          Address(InetSocketAddress(Ipv4Address::GetAny(), port)));
    ApplicationContainer receiver = sink.Install(nodes.Get(destination));
    receiver.Start(Seconds(0.0));
    receiver.Stop(Seconds(simulationTime));

    FlowMonitorHelper flowMonitorHelper;
    Ptr<FlowMonitor> flowMonitor = flowMonitorHelper.InstallAll();
    Simulator::Stop(Seconds(simulationTime));
    Simulator::Run();

    auto classifier = DynamicCast<Ipv4FlowClassifier>(flowMonitorHelper.GetClassifier());
    auto stats = flowMonitor->GetFlowStats();
    std::string prefix = outputDir + "/dsr_smoke_seed_" + std::to_string(randomSeed);
    std::ofstream csv(prefix + ".csv");
    csv << "flow_id,source,destination,tx_packets,rx_packets,tx_bytes,rx_bytes,packet_loss,pdr,throughput_bps,delay_ms,random_seed\n";
    for (const auto& entry : stats)
    {
        Ipv4FlowClassifier::FiveTuple tuple = classifier->FindFlow(entry.first);
        const FlowMonitor::FlowStats& flow = entry.second;
        double loss = flow.txPackets > 0 ? 1.0 - static_cast<double>(flow.rxPackets) / flow.txPackets : 0.0;
        double pdr = flow.txPackets > 0 ? static_cast<double>(flow.rxPackets) / flow.txPackets : 0.0;
        double throughput = flow.timeLastRxPacket.GetSeconds() > flow.timeFirstTxPacket.GetSeconds()
                                ? flow.rxBytes * 8.0 / (flow.timeLastRxPacket.GetSeconds() - flow.timeFirstTxPacket.GetSeconds())
                                : 0.0;
        double delay = flow.rxPackets > 0 ? flow.delaySum.GetMilliSeconds() / static_cast<double>(flow.rxPackets) : 0.0;
        csv << entry.first << ',' << tuple.sourceAddress << ',' << tuple.destinationAddress << ','
            << flow.txPackets << ',' << flow.rxPackets << ',' << flow.txBytes << ',' << flow.rxBytes << ','
            << std::fixed << std::setprecision(6) << loss << ',' << pdr << ',' << throughput << ',' << delay << ','
            << randomSeed << '\n';
    }
    csv.close();
    flowMonitor->SerializeToXmlFile(prefix + ".flowmon.xml", true, true);
    Simulator::Destroy();
    return 0;
}

#include "ns3/applications-module.h"
#include "ns3/core-module.h"
#include "ns3/dsr-module.h"
#include "ns3/flow-monitor-module.h"
#include "ns3/internet-module.h"
#include "ns3/mobility-module.h"
#include "ns3/netanim-module.h"
#include "ns3/network-module.h"
#include "ns3/wifi-module.h"
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <sstream>
#include <string>
#include <vector>

using namespace ns3;

namespace
{
std::vector<std::string> gMobilityRows;
std::vector<std::string> gRouteEvents;
uint64_t gApplicationTxPackets = 0;
uint64_t gApplicationTxBytes = 0;
uint64_t gApplicationRxPackets = 0;
uint64_t gApplicationRxBytes = 0;

void RecordApplicationTx(Ptr<const Packet> packet)
{
    ++gApplicationTxPackets;
    gApplicationTxBytes += packet->GetSize();
}

void RecordApplicationRx(Ptr<const Packet> packet, const Address&, const Address&)
{
    ++gApplicationRxPackets;
    gApplicationRxBytes += packet->GetSize();
}

void EnsureDirectory(const std::string& path)
{
    std::error_code ec;
    std::filesystem::create_directories(path, ec);
    if (ec)
    {
        std::cerr << "Failed to create directory: " << path << " (" << ec.message() << ")\n";
    }
}

void RecordMobilityPerNode(Ptr<Node> node, double currentTime, double stopTime, double sampleInterval)
{
    if (currentTime <= stopTime)
    {
        Ptr<MobilityModel> mobility = node->GetObject<MobilityModel>();
        if (mobility)
        {
            Vector pos = mobility->GetPosition();
            Vector vel = mobility->GetVelocity();
            std::ostringstream oss;
            oss << std::fixed << std::setprecision(6)
                << currentTime << "," << node->GetId() << "," << pos.x << "," << pos.y << "," << vel.x << "," << vel.y << "\n";
            gMobilityRows.push_back(oss.str());
        }
        Simulator::Schedule(Seconds(sampleInterval), &RecordMobilityPerNode, node, currentTime + sampleInterval, stopTime, sampleInterval);
    }
}
}

int main(int argc, char* argv[])
{
    uint32_t nodeCount = 150;
    double simulationTime = 100.0;
    double areaSize = 500.0;
    double areaSizeY = 500.0;
    double samplingInterval = 1.0;
    double mobilityPause = 2.0;
    double nodeSpeed = 5.0;
    double txPowerDbm = 16.04;
    double noiseFloorDbm = -95.02;
    std::string trafficRate = "2kbps";
    uint32_t packetSize = 512;
    uint32_t source = 0;
    uint32_t destination = 149;
    uint32_t randomSeed = 1;
    uint32_t randomRun = 1;
    uint32_t runId = 1;
    uint16_t port = 9000;
    std::string mobilityModel = "RandomWalk2dMobilityModel";
    std::string routingProtocol = "DSR";
    std::string scenarioId = "unidentified";
    std::string wifiStandard = "802.11b";
    std::string channelHelper = "YansWifiChannel";
    std::string transportProtocol = "UDP";
    std::string applicationType = "CBR";
    uint32_t flowId = 0;
    bool enableAnimation = true;
    std::string outputDir = "/Users/bistupaul/Movies/DISSERTATION/ns3/results";

    CommandLine cmd(__FILE__);
    cmd.AddValue("nodeCount", "Number of mobile nodes", nodeCount);
    cmd.AddValue("simulationTime", "Simulation duration in seconds", simulationTime);
    cmd.AddValue("areaSize", "Square mobility area side in metres", areaSize);
    cmd.AddValue("areaSizeY", "Mobility area Y dimension in metres", areaSizeY);
    cmd.AddValue("samplingInterval", "Mobility trace sample interval in seconds", samplingInterval);
    cmd.AddValue("mobilityPause", "RandomWaypoint pause in seconds", mobilityPause);
    cmd.AddValue("nodeSpeed", "Maximum mobility speed in m/s", nodeSpeed);
    cmd.AddValue("txPowerDbm", "Transmit power in dBm from the manifest", txPowerDbm);
    cmd.AddValue("noiseFloorDbm", "Noise floor in dBm from the manifest", noiseFloorDbm);
    cmd.AddValue("trafficRate", "UDP application data rate", trafficRate);
    cmd.AddValue("packetSize", "UDP payload size in bytes", packetSize);
    cmd.AddValue("source", "UDP source node index", source);
    cmd.AddValue("destination", "UDP destination node index", destination);
    cmd.AddValue("randomSeed", "ns-3 seed", randomSeed);
    cmd.AddValue("randomRun", "ns-3 run number", randomRun);
    cmd.AddValue("runId", "Manifest scenario run identifier", runId);
    cmd.AddValue("port", "UDP destination port", port);
    cmd.AddValue("mobilityModel", "Mobility model name", mobilityModel);
    cmd.AddValue("routingProtocol", "Routing protocol name", routingProtocol);
    cmd.AddValue("scenarioId", "Manifest scenario identifier", scenarioId);
    cmd.AddValue("wifiStandard", "Wi-Fi standard from the manifest", wifiStandard);
    cmd.AddValue("channelHelper", "Wi-Fi channel helper from the manifest", channelHelper);
    cmd.AddValue("transportProtocol", "Transport protocol from the manifest", transportProtocol);
    cmd.AddValue("applicationType", "Application type from the manifest", applicationType);
    cmd.AddValue("flowId", "Manifest flow identifier", flowId);
    cmd.AddValue("enableAnimation", "Write a NetAnim XML trace", enableAnimation);
    cmd.AddValue("outputDir", "Directory for generated output files", outputDir);
    cmd.Parse(argc, argv);

    NS_ABORT_MSG_IF(channelHelper != "YansWifiChannel", "Unsupported channel helper: " << channelHelper);
    NS_ABORT_MSG_IF(transportProtocol != "UDP", "Unsupported transport protocol: " << transportProtocol);
    NS_ABORT_MSG_IF(applicationType != "CBR", "Unsupported application type: " << applicationType);
    const double thermalNoiseDbmAt20Mhz = -100.97;
    const double noiseFigureDb = noiseFloorDbm - thermalNoiseDbmAt20Mhz;
    NS_ABORT_MSG_IF(noiseFigureDb < 0.0, "noise_floor_dbm is below the 20 MHz thermal noise floor");

    NS_ABORT_MSG_IF(nodeCount < 2, "nodeCount must be at least 2");
    NS_ABORT_MSG_IF(source >= nodeCount || destination >= nodeCount || source == destination,
                    "source and destination must be distinct valid node indices");
    NS_ABORT_MSG_IF(areaSize <= 0.0, "areaSize must be positive");
    NS_ABORT_MSG_IF(areaSizeY <= 0.0, "areaSizeY must be positive");
    NS_ABORT_MSG_IF(samplingInterval <= 0.0, "samplingInterval must be positive");
    NS_ABORT_MSG_IF(nodeSpeed <= 0.0, "nodeSpeed must be positive");

    RngSeedManager::SetSeed(randomSeed);
    RngSeedManager::SetRun(randomRun);

    std::string csvDir = outputDir + "/csv";
    std::string animDir = outputDir + "/animation";
    std::string logDir = outputDir + "/logs";
    std::string plotDir = outputDir + "/plots";
    std::string reportDir = outputDir + "/reports";
    EnsureDirectory(csvDir);
    EnsureDirectory(animDir);
    EnsureDirectory(logDir);
    EnsureDirectory(plotDir);
    EnsureDirectory(reportDir);

    std::string metricsFile = csvDir + "/dsr_metrics_seed_" + std::to_string(randomSeed) + "_run_" + std::to_string(randomRun) + ".csv";
    std::string mobilityFile = csvDir + "/dsr_mobility_seed_" + std::to_string(randomSeed) + "_run_" + std::to_string(randomRun) + ".csv";
    std::string routeFile = csvDir + "/dsr_route_events_seed_" + std::to_string(randomSeed) + "_run_" + std::to_string(randomRun) + ".csv";
    std::string animationFile = animDir + "/dsr_manet_seed_" + std::to_string(randomSeed) + "_run_" + std::to_string(randomRun) + ".xml";
    std::string logFile = logDir + "/simulation_seed_" + std::to_string(randomSeed) + "_run_" + std::to_string(randomRun) + ".log";

    std::ofstream logStream(logFile);
    logStream << "run_id=" << runId << "\n";
    logStream << "scenario_id=" << scenarioId << "\n";
    logStream << "random_seed=" << randomSeed << "\n";
    logStream << "node_count=" << nodeCount << "\n";
    logStream << "simulation_time=" << simulationTime << "\n";
    logStream << "area_size=" << areaSize << "\n";
    logStream << "area_x_m=" << areaSize << "\n";
    logStream << "area_y_m=" << areaSizeY << "\n";
    logStream << "sampling_interval_s=" << samplingInterval << "\n";
    logStream << "mobility_pause_s=" << mobilityPause << "\n";
    logStream << "node_speed=" << nodeSpeed << "\n";
    logStream << "tx_power_dbm=" << txPowerDbm << "\n";
    logStream << "noise_floor_dbm=" << noiseFloorDbm << "\n";
    logStream << "rx_noise_figure_db=" << noiseFigureDb << "\n";
    logStream << "traffic_rate=" << trafficRate << "\n";
    logStream << "packet_size=" << packetSize << "\n";
    logStream << "source=" << source << "\n";
    logStream << "destination=" << destination << "\n";
    logStream << "routing_protocol=" << routingProtocol << "\n";
    logStream << "wifi_standard=" << wifiStandard << "\n";
    logStream << "channel_helper=" << channelHelper << "\n";
    logStream << "transport_protocol=" << transportProtocol << "\n";
    logStream << "application_type=" << applicationType << "\n";
    logStream << "flow_id=" << flowId << "\n";
    logStream << "udp_port=" << port << "\n";
    logStream << "radio_range_m=250\n";
    logStream << "random_run=" << randomRun << "\n";
    logStream << "mobility_model=" << mobilityModel << "\n";
    logStream << "animation_enabled=" << (enableAnimation ? "true" : "false") << "\n";
    logStream.flush();

    NodeContainer nodes;
    nodes.Create(nodeCount);

    WifiHelper wifi;
    if (wifiStandard == "802.11g")
    {
        wifi.SetStandard(WIFI_STANDARD_80211g);
    }
    else if (wifiStandard == "802.11b")
    {
        wifi.SetStandard(WIFI_STANDARD_80211b);
    }
    else
    {
        NS_ABORT_MSG("Unsupported Wi-Fi standard: " << wifiStandard);
    }
    wifi.SetRemoteStationManager("ns3::ConstantRateWifiManager",
                                 "DataMode", StringValue("DsssRate2Mbps"),
                                 "ControlMode", StringValue("DsssRate1Mbps"));

    YansWifiChannelHelper channel;
    channel.SetPropagationDelay("ns3::ConstantSpeedPropagationDelayModel");
    channel.AddPropagationLoss("ns3::RangePropagationLossModel",
                               "MaxRange",
                               DoubleValue(250.0));
    YansWifiPhyHelper phy;
    phy.Set("TxPowerStart", DoubleValue(txPowerDbm));
    phy.Set("TxPowerEnd", DoubleValue(txPowerDbm));
    phy.Set("RxNoiseFigure", DoubleValue(noiseFigureDb));
    phy.SetChannel(channel.Create());

    WifiMacHelper mac;
    mac.SetType("ns3::AdhocWifiMac");

    NetDeviceContainer devices = wifi.Install(phy, mac, nodes);

    MobilityHelper mobHelper;
    mobHelper.SetPositionAllocator("ns3::RandomRectanglePositionAllocator",
                                  "X", StringValue("ns3::UniformRandomVariable[Min=0.0|Max=" + std::to_string(areaSize) + "]"),
                                  "Y", StringValue("ns3::UniformRandomVariable[Min=0.0|Max=" + std::to_string(areaSizeY) + "]"));
    if (mobilityModel == "RandomWaypoint")
    {
        Ptr<RandomRectanglePositionAllocator> waypointAllocator = CreateObject<RandomRectanglePositionAllocator>();
        waypointAllocator->SetAttribute("X", StringValue("ns3::UniformRandomVariable[Min=0.0|Max=" + std::to_string(areaSize) + "]"));
        waypointAllocator->SetAttribute("Y", StringValue("ns3::UniformRandomVariable[Min=0.0|Max=" + std::to_string(areaSizeY) + "]"));
        mobHelper.SetMobilityModel("ns3::RandomWaypointMobilityModel",
                                   "Speed", StringValue("ns3::ConstantRandomVariable[Constant=" + std::to_string(nodeSpeed) + "]"),
                                   "Pause", StringValue("ns3::ConstantRandomVariable[Constant=" + std::to_string(mobilityPause) + "]"),
                                   "PositionAllocator", PointerValue(waypointAllocator));
    }
    else if (mobilityModel == "RandomWalk2dMobilityModel")
    {
        mobHelper.SetMobilityModel("ns3::RandomWalk2dMobilityModel",
                                   "Mode", StringValue("Time"),
                                   "Time", TimeValue(Seconds(1.0)),
                                   "Speed", StringValue("ns3::ConstantRandomVariable[Constant=" + std::to_string(nodeSpeed) + "]"),
                                   "Bounds", RectangleValue(Rectangle(0.0, areaSize, 0.0, areaSizeY)));
    }
    else
    {
        NS_ABORT_MSG("Unsupported mobility model: " << mobilityModel);
    }
    mobHelper.Install(nodes);

    InternetStackHelper internet;
    internet.Install(nodes);

    DsrHelper dsr;
    DsrMainHelper dsrMain;
    dsrMain.Install(dsr, nodes);

    Ipv4AddressHelper address;
    address.SetBase("10.1.1.0", "255.255.255.0");
    Ipv4InterfaceContainer interfaces = address.Assign(devices);

    uint16_t flowPort = port;
    OnOffHelper onOff("ns3::UdpSocketFactory",
                      Address(InetSocketAddress(interfaces.GetAddress(destination), flowPort)));
    onOff.SetAttribute("DataRate", DataRateValue(DataRate(trafficRate)));
    onOff.SetAttribute("PacketSize", UintegerValue(packetSize));
    onOff.SetAttribute("OnTime", StringValue("ns3::ConstantRandomVariable[Constant=1.0]"));
    onOff.SetAttribute("OffTime", StringValue("ns3::ConstantRandomVariable[Constant=0.0]"));
    ApplicationContainer sender = onOff.Install(nodes.Get(source));
    sender.Get(0)->TraceConnectWithoutContext("Tx", MakeCallback(&RecordApplicationTx));
    sender.Start(Seconds(1.0));
    sender.Stop(Seconds(simulationTime - 1.0));

    PacketSinkHelper sink("ns3::UdpSocketFactory",
                          Address(InetSocketAddress(Ipv4Address::GetAny(), flowPort)));
    ApplicationContainer receiver = sink.Install(nodes.Get(destination));
    receiver.Get(0)->TraceConnectWithoutContext("RxWithAddresses", MakeCallback(&RecordApplicationRx));
    receiver.Start(Seconds(0.0));
    receiver.Stop(Seconds(simulationTime));

    FlowMonitorHelper flowMonitorHelper;
    Ptr<FlowMonitor> flowMonitor = flowMonitorHelper.InstallAll();

    std::unique_ptr<AnimationInterface> animation;
    if (enableAnimation)
    {
        animation = std::make_unique<AnimationInterface>(animationFile);
        animation->SetMobilityPollInterval(Seconds(1.0));
        animation->EnablePacketMetadata(true);
        animation->SetMaxPktsPerTraceFile(100000);
        animation->SetConstantPosition(nodes.Get(source), 0.0, 0.0);
        animation->SetConstantPosition(nodes.Get(destination), areaSize, areaSizeY);

        for (uint32_t i = 0; i < nodeCount; ++i)
        {
            if (i != source && i != destination)
            {
                animation->SetConstantPosition(nodes.Get(i), 0.0, 0.0);
            }
        }
    }

    double stopTime = simulationTime;
    for (uint32_t i = 0; i < nodeCount; ++i)
    {
        Simulator::Schedule(Seconds(0.0), &RecordMobilityPerNode, nodes.Get(i), 0.0, stopTime, samplingInterval);
    }

    Simulator::Stop(Seconds(simulationTime + 1.0));
    Simulator::Run();

    auto classifier = DynamicCast<Ipv4FlowClassifier>(flowMonitorHelper.GetClassifier());
    auto stats = flowMonitor->GetFlowStats();

    std::ofstream metricsCsv(metricsFile);
    metricsCsv << "run_id,random_seed,random_run,timestamp_s,node_count,source,destination,tx_packets,rx_packets,tx_bytes,rx_bytes,packet_loss,pdr,throughput_bps,delay_ms,packet_size,traffic_rate,area_size,node_speed,mobility_model,routing_protocol,measurement_layer\n";

    double flowDurationSeconds = std::max(1.0, simulationTime - 2.0);
    for (const auto& entry : stats)
    {
        Ipv4FlowClassifier::FiveTuple tuple = classifier->FindFlow(entry.first);
        const FlowMonitor::FlowStats& flow = entry.second;

        uint64_t txPackets = flow.txPackets;
        uint64_t rxPackets = flow.rxPackets;
        uint64_t txBytes = flow.txBytes;
        uint64_t rxBytes = flow.rxBytes;
        double packetLoss = txPackets > 0 ? static_cast<double>(txPackets - rxPackets) : 0.0;
        double pdr = txPackets > 0 ? static_cast<double>(rxPackets) / static_cast<double>(txPackets) : 0.0;
        double throughputBps = flow.rxPackets > 0 ? (static_cast<double>(rxBytes) * 8.0) / std::max(1e-9, flow.timeLastRxPacket.GetSeconds() - flow.timeFirstTxPacket.GetSeconds()) : 0.0;
        double delayMs = flow.rxPackets > 0 ? (flow.delaySum.GetSeconds() / static_cast<double>(flow.rxPackets)) * 1000.0 : 0.0;

        metricsCsv << runId << "," << randomSeed << "," << randomRun << "," << simulationTime << "," << nodeCount << "," << tuple.sourceAddress << "," << tuple.destinationAddress << ","
                   << txPackets << "," << rxPackets << "," << txBytes << "," << rxBytes << "," << std::fixed << std::setprecision(6) << packetLoss << "," << pdr << "," << throughputBps << "," << delayMs << ","
                   << packetSize << "," << trafficRate << "," << areaSize << "," << nodeSpeed << "," << mobilityModel << "," << routingProtocol << ",ipv4_flow_monitor\n";

        if (flow.txPackets > 0 || flow.rxPackets > 0)
        {
            std::ostringstream oss;
            oss << "time=" << simulationTime << ",source=" << tuple.sourceAddress << ",destination=" << tuple.destinationAddress
                << ",tx_packets=" << txPackets << ",rx_packets=" << rxPackets << ",pdr=" << pdr
                << ",throughput_bps=" << throughputBps << ",delay_ms=" << delayMs << "\n";
            gRouteEvents.push_back(oss.str());
        }
    }
    if (stats.empty())
    {
        uint64_t packetLoss = gApplicationTxPackets > gApplicationRxPackets
                                  ? gApplicationTxPackets - gApplicationRxPackets
                                  : 0;
        double pdr = gApplicationTxPackets > 0
                         ? static_cast<double>(gApplicationRxPackets) / gApplicationTxPackets
                         : 0.0;
        double throughputBps = (static_cast<double>(gApplicationRxBytes) * 8.0) / flowDurationSeconds;

        metricsCsv << runId << "," << randomSeed << "," << randomRun << "," << simulationTime << "," << nodeCount << ","
                   << interfaces.GetAddress(source) << "," << interfaces.GetAddress(destination) << ","
                   << gApplicationTxPackets << "," << gApplicationRxPackets << "," << gApplicationTxBytes << ","
                   << gApplicationRxBytes << "," << packetLoss << "," << std::fixed << std::setprecision(6)
                   << pdr << "," << throughputBps << ",," << packetSize << "," << trafficRate << "," << areaSize << ","
                   << nodeSpeed << "," << mobilityModel << "," << routingProtocol << ",application_trace\n";
    }
    metricsCsv.close();

    std::ofstream mobilityCsv(mobilityFile);
    mobilityCsv << "run_id,random_seed,random_run,time,node_id,x_m,y_m,velocity_x_mps,velocity_y_mps\n";
    for (const auto& row : gMobilityRows)
    {
        mobilityCsv << runId << "," << randomSeed << "," << randomRun << "," << row;
    }
    mobilityCsv.close();

    std::ofstream routeCsv(routeFile);
    routeCsv << "run_id,random_seed,random_run,time,source,destination,event_type,route_information\n";
    if (gRouteEvents.empty())
    {
        routeCsv << runId << "," << randomSeed << "," << randomRun << "," << simulationTime << "," << source << "," << destination << "," << "not_available" << ","
                 << "No public DSR route trace API was exposed by the ns-3.48 installation for this baseline simulation; route path data was unavailable and no synthetic route path was invented.\n";
    }
    else
    {
        for (const auto& event : gRouteEvents)
        {
            routeCsv << runId << "," << randomSeed << "," << randomRun << "," << simulationTime << "," << source << "," << destination << "," << "flow_summary" << "," << event << "\n";
        }
    }
    routeCsv.close();

    flowMonitor->SerializeToXmlFile(metricsFile + ".flowmon.xml", true, true);

    logStream << "metrics_file=" << metricsFile << "\n";
    logStream << "mobility_file=" << mobilityFile << "\n";
    logStream << "route_file=" << routeFile << "\n";
    logStream << "animation_file=" << animationFile << "\n";
    logStream << "application_tx_packets=" << gApplicationTxPackets << "\n";
    logStream << "application_rx_packets=" << gApplicationRxPackets << "\n";
    logStream << "application_tx_bytes=" << gApplicationTxBytes << "\n";
    logStream << "application_rx_bytes=" << gApplicationRxBytes << "\n";
    logStream << "status=baseline_dsr_run_complete\n";
    logStream.close();

    Simulator::Destroy();
    return 0;
}

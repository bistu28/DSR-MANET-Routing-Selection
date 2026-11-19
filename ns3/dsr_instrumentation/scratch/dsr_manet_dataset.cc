#include "ns3/applications-module.h"
#include "ns3/core-module.h"
#include "ns3/dsr-module.h"
#include "ns3/flow-monitor-module.h"
#include "ns3/internet-module.h"
#include "ns3/ipv4-l3-protocol.h"
#include "ns3/mobility-module.h"
#include "ns3/netanim-module.h"
#include "ns3/network-module.h"
#include "ns3/pcap-file-wrapper.h"
#include "ns3/propagation-module.h"
#include "ns3/wifi-module.h"
#include "../src/dsr/model/stage2-dsr-event-sink.h"
#include <algorithm>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <condition_variable>
#include <mutex>
#include <queue>
#include <sstream>
#include <string>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

using namespace ns3;

namespace
{
std::vector<std::string> gMobilityRows;
std::vector<std::string> gRouteEvents;
std::ofstream gLiveTrace;
std::mutex gLiveQueueMutex;
std::condition_variable gLiveQueueReady;
std::queue<std::string> gLiveQueue;
bool gLiveWriterStopping = false;
bool gLiveStreamingEnabled = false;
uint64_t gApplicationTxPackets = 0;
uint64_t gApplicationTxBytes = 0;
uint64_t gApplicationRxPackets = 0;
uint64_t gApplicationRxBytes = 0;
uint64_t gApplicationDelayNsSum = 0;
uint64_t gApplicationDelayPackets = 0;
std::unordered_map<uint64_t, uint64_t> gApplicationTxTimesNs;
std::ofstream gApplicationPacketTrace;
Ptr<PcapFileWrapper> gDsrControlPcap;
Ptr<RangePropagationLossModel> gRangeModel;
std::ofstream gDsrPcapIndex;
std::ofstream gExperimentControl;
uint64_t gDsrPcapRecordIndex = 0;
uint32_t gSourceNode = 0;
uint32_t gDestinationNode = 0;
double gRadioRangeMeters = 250.0;

void QueueLiveTrace(std::string record)
{
    {
        std::lock_guard<std::mutex> lock(gLiveQueueMutex);
        gLiveQueue.push(std::move(record));
    }
    gLiveQueueReady.notify_one();
}

void WriteLiveTrace()
{
    while (true)
    {
        std::string record;
        {
            std::unique_lock<std::mutex> lock(gLiveQueueMutex);
            gLiveQueueReady.wait(lock, [] { return gLiveWriterStopping || !gLiveQueue.empty(); });
            if (gLiveQueue.empty() && gLiveWriterStopping)
            {
                return;
            }
            record = std::move(gLiveQueue.front());
            gLiveQueue.pop();
        }
        gLiveTrace << record << '\n';
        gLiveTrace.flush();
    }
}

void RecordApplicationTx(Ptr<const Packet> packet)
{
    ++gApplicationTxPackets;
    gApplicationTxBytes += packet->GetSize();
    const uint64_t packetUid = packet->GetUid();
    const uint64_t now = Simulator::Now().GetNanoSeconds();
    const auto inserted = gApplicationTxTimesNs.emplace(packetUid, now);
    NS_ABORT_MSG_IF(!inserted.second, "Duplicate application packet UID at transmit: " << packetUid);
    if (gApplicationPacketTrace.is_open())
    {
        gApplicationPacketTrace << "ns3uid:" << packetUid << ",tx," << now << "," << gSourceNode << ","
                                << packet->GetSize() << ",\n";
    }
}

void RecordApplicationRx(Ptr<const Packet> packet, const Address&, const Address&)
{
    ++gApplicationRxPackets;
    gApplicationRxBytes += packet->GetSize();
    const uint64_t packetUid = packet->GetUid();
    const uint64_t now = Simulator::Now().GetNanoSeconds();
    int64_t delayNs = -1;
    auto transmit = gApplicationTxTimesNs.find(packetUid);
    if (transmit != gApplicationTxTimesNs.end())
    {
        NS_ABORT_MSG_IF(now < transmit->second, "Application receive timestamp precedes transmit");
        delayNs = static_cast<int64_t>(now - transmit->second);
        gApplicationDelayNsSum += static_cast<uint64_t>(delayNs);
        ++gApplicationDelayPackets;
        gApplicationTxTimesNs.erase(transmit);
    }
    if (gApplicationPacketTrace.is_open())
    {
        gApplicationPacketTrace << "ns3uid:" << packetUid << ",rx," << now << "," << gDestinationNode << ","
                                << packet->GetSize() << ",";
        if (delayNs >= 0) { gApplicationPacketTrace << delayNs; }
        gApplicationPacketTrace << "\n";
    }
}

void ApplyRangeIntervention(double rangeMeters)
{
    NS_ABORT_MSG_IF(!gRangeModel, "Range propagation model was not initialized");
    gRangeModel->SetAttribute("MaxRange", DoubleValue(rangeMeters));
    if (gExperimentControl.is_open())
    {
        gExperimentControl << "{\"schema_version\":\"range_intervention_v1\",\"simulation_time_ns\":"
                           << Simulator::Now().GetNanoSeconds() << ",\"max_range_m\":" << rangeMeters << "}\n";
        gExperimentControl.flush();
    }
}

void RecordDsrControlPacket(uint32_t nodeId,
                            uint8_t direction,
                            Ptr<const Packet> packet,
                            Ptr<Ipv4> ipv4,
                            uint32_t interface)
{
    (void)ipv4;
    if (!gDsrControlPcap || !packet || packet->GetSize() < 28) { return; }
    Ptr<Packet> ipPayload = packet->Copy();
    Ipv4Header ipHeader;
    if (ipPayload->RemoveHeader(ipHeader) == 0 || ipHeader.GetProtocol() != 48 || ipPayload->GetSize() < 8) { return; }
    dsr::DsrRoutingHeader dsrHeader;
    if (ipPayload->RemoveHeader(dsrHeader) == 0 || dsrHeader.GetMessageType() != 1) { return; }
    Buffer options = dsrHeader.GetDsrOptionBuffer();
    Buffer::Iterator it = options.Begin();
    std::vector<uint8_t> optionTypes;
    while (it.GetRemainingSize() >= 2)
    {
        uint8_t type = it.ReadU8();
        uint8_t length = it.ReadU8();
        if (length > it.GetRemainingSize()) { break; }
        if (type == 1 || type == 2 || type == 3) { optionTypes.push_back(type); }
        it.Next(length);
    }
    if (optionTypes.empty()) { return; }

    const uint64_t recordIndex = gDsrPcapRecordIndex++;
    gDsrControlPcap->Write(Simulator::Now(), packet);
    const std::string directionName = direction == 0 ? "rx" : "tx";
    gDsrPcapIndex << "{\"schema_version\":\"dsr_packet_v1\",\"pcap_record_index\":" << recordIndex
                  << ",\"timestamp_ns\":" << Simulator::Now().GetNanoSeconds()
                  << ",\"node_id\":" << nodeId << ",\"direction\":\"" << directionName
                  << "\",\"interface_id\":" << interface << ",\"ipv4_protocol\":48"
                  << ",\"ipv4_source\":\"" << ipHeader.GetSource() << "\",\"ipv4_destination\":\"" << ipHeader.GetDestination()
                  << "\",\"dsr_message_type\":" << static_cast<uint32_t>(dsrHeader.GetMessageType())
                  << ",\"dsr_source_node\":" << dsrHeader.GetSourceId() << ",\"dsr_destination_node\":" << dsrHeader.GetDestId()
                  << ",\"dsr_option_types\":[";
    for (size_t i = 0; i < optionTypes.size(); ++i) { if (i) gDsrPcapIndex << ','; gDsrPcapIndex << static_cast<uint32_t>(optionTypes[i]); }
    gDsrPcapIndex << "],\"packet_id\":\"ns3uid:" << packet->GetUid() << "\"}\n";
    if (direction == 0)
    {
        dsr::stage2::EventSink::Emit("packet_rx", nodeId, dsrHeader.GetSourceId(), dsrHeader.GetDestId() == 255 ? -1 : dsrHeader.GetDestId(), "Ipv4L3Protocol::Rx", "src/internet/model/ipv4-l3-protocol.cc", {}, -1, {}, packet->GetUid(), recordIndex);
    }
    else
    {
        dsr::stage2::EventSink::Emit("packet_tx", nodeId, dsrHeader.GetSourceId(), dsrHeader.GetDestId() == 255 ? -1 : dsrHeader.GetDestId(), "Ipv4L3Protocol::Tx", "src/internet/model/ipv4-l3-protocol.cc", {}, -1, {}, packet->GetUid(), recordIndex);
    }
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

void RecordLiveSnapshot(NodeContainer nodes, double currentTime, double stopTime, double sampleInterval)
{
    if (currentTime > stopTime)
    {
        return;
    }
    if (gLiveStreamingEnabled)
    {
        std::ostringstream record;
        const double elapsed = std::max(1.0, std::min(currentTime - 1.0, stopTime - 2.0));
        const double pdr = gApplicationTxPackets > 0
                               ? static_cast<double>(gApplicationRxPackets) / gApplicationTxPackets
                               : 0.0;
        const double throughput = static_cast<double>(gApplicationRxBytes) * 8.0 / elapsed;
        record << "{\"type\":\"snapshot\",\"time_s\":" << currentTime
                   << ",\"source\":" << gSourceNode << ",\"destination\":" << gDestinationNode
                   << ",\"radio_range_m\":" << gRadioRangeMeters
                   << ",\"metrics\":{\"tx_packets\":" << gApplicationTxPackets
                   << ",\"rx_packets\":" << gApplicationRxPackets
                   << ",\"packet_loss\":" << (gApplicationTxPackets > gApplicationRxPackets
                                                        ? gApplicationTxPackets - gApplicationRxPackets
                                                        : 0)
                   << ",\"pdr\":" << std::fixed << std::setprecision(6) << pdr
                   << ",\"throughput_bps\":" << throughput
                   << ",\"delay_ms\":null,\"delay_status\":\"unavailable\"},\"nodes\":[";
        for (uint32_t i = 0; i < nodes.GetN(); ++i)
        {
            Ptr<MobilityModel> mobility = nodes.Get(i)->GetObject<MobilityModel>();
            Vector pos = mobility ? mobility->GetPosition() : Vector(0.0, 0.0, 0.0);
            if (i != 0)
            {
                record << ",";
            }
            record << "{\"id\":" << i << ",\"x\":" << std::fixed << std::setprecision(3) << pos.x
                       << ",\"y\":" << pos.y << ",\"source\":" << (i == gSourceNode ? "true" : "false")
                       << ",\"destination\":" << (i == gDestinationNode ? "true" : "false") << "}";
        }
        record << "],\"routing_events_status\":\"unavailable: no DSR RREQ/RREP/RERR trace source is connected\"}";
        QueueLiveTrace(record.str());
    }
    Simulator::Schedule(Seconds(sampleInterval), &RecordLiveSnapshot, nodes, currentTime + sampleInterval,
                       stopTime, sampleInterval);
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
    std::string liveTraceFile;
    std::string dsrEventFile;
    std::string dsrPcapFile;
    std::string applicationTraceFile;
    std::string failureControlFile;
    double failureOutageStartS = 0.0;
    double failureOutageDurationS = 0.0;
    double failureOutageRangeM = 0.0;

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
    cmd.AddValue("liveTraceFile", "Optional JSONL stream of real simulation snapshots", liveTraceFile);
    cmd.AddValue("dsrEventFile", "Optional raw JSONL stream of instrumented DSR events", dsrEventFile);
    cmd.AddValue("dsrPcapFile", "Optional DLT_RAW pcap containing IPv4 DSR control packets", dsrPcapFile);
    cmd.AddValue("applicationTraceFile", "Optional per-packet application Tx/Rx timestamp CSV", applicationTraceFile);
    cmd.AddValue("failureControlFile", "Optional JSONL log for explicit propagation range interventions", failureControlFile);
    cmd.AddValue("failureOutageStartS", "Start time for a separate controlled range-outage experiment; zero disables", failureOutageStartS);
    cmd.AddValue("failureOutageDurationS", "Duration of the separate controlled range outage", failureOutageDurationS);
    cmd.AddValue("failureOutageRangeM", "Temporary RangePropagationLossModel MaxRange during outage", failureOutageRangeM);
    cmd.Parse(argc, argv);

    NS_ABORT_MSG_IF(channelHelper != "YansWifiChannel", "Unsupported channel helper: " << channelHelper);
    NS_ABORT_MSG_IF(transportProtocol != "UDP", "Unsupported transport protocol: " << transportProtocol);
    NS_ABORT_MSG_IF(applicationType != "CBR", "Unsupported application type: " << applicationType);
    NS_ABORT_MSG_IF(failureOutageStartS < 0.0 || failureOutageDurationS < 0.0 || failureOutageRangeM < 0.0,
                    "Failure experiment timing and range must be non-negative");
    const bool failureExperiment = failureOutageStartS > 0.0 || failureOutageDurationS > 0.0 || failureOutageRangeM > 0.0;
    NS_ABORT_MSG_IF(failureExperiment && (failureOutageStartS <= 0.0 || failureOutageDurationS <= 0.0 ||
                    failureOutageStartS + failureOutageDurationS >= simulationTime || failureControlFile.empty()),
                    "A failure experiment requires start, positive duration, and failureControlFile within simulation duration");
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
    gSourceNode = source;
    gDestinationNode = destination;

    RngSeedManager::SetSeed(randomSeed);
    RngSeedManager::SetRun(randomRun);
    if (!dsrEventFile.empty())
    {
        EnsureDirectory(std::filesystem::path(dsrEventFile).parent_path().string());
        dsr::stage2::EventSink::Configure(dsrEventFile, scenarioId, runId, randomSeed, randomRun);
    }

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
    if (!applicationTraceFile.empty())
    {
        const auto parent = std::filesystem::path(applicationTraceFile).parent_path();
        if (!parent.empty()) { EnsureDirectory(parent.string()); }
        gApplicationPacketTrace.open(applicationTraceFile, std::ios::out | std::ios::trunc);
        NS_ABORT_MSG_IF(!gApplicationPacketTrace.is_open(),
                        "Could not open application packet trace: " << applicationTraceFile);
        gApplicationPacketTrace << "packet_id,direction,simulation_time_ns,node_id,packet_bytes,delay_ns\n";
    }
    if (!dsrPcapFile.empty())
    {
        EnsureDirectory(std::filesystem::path(dsrPcapFile).parent_path().string());
        gDsrControlPcap = CreateObject<PcapFileWrapper>();
        gDsrControlPcap->Open(dsrPcapFile, std::ios::out | std::ios::trunc);
        gDsrControlPcap->Init(101, 65535); // LINKTYPE_RAW: full IPv4 datagrams.
        gDsrPcapIndex.open(dsrPcapFile + ".index.jsonl", std::ios::out | std::ios::trunc);
        NS_ABORT_MSG_IF(!gDsrPcapIndex.is_open(), "Could not open DSR pcap index: " << dsrPcapFile << ".index.jsonl");
    }

    std::string metricsFile = csvDir + "/dsr_metrics_seed_" + std::to_string(randomSeed) + "_run_" + std::to_string(randomRun) + ".csv";
    std::string mobilityFile = csvDir + "/dsr_mobility_seed_" + std::to_string(randomSeed) + "_run_" + std::to_string(randomRun) + ".csv";
    std::string routeFile = csvDir + "/dsr_route_events_seed_" + std::to_string(randomSeed) + "_run_" + std::to_string(randomRun) + ".csv";
    std::string animationFile = animDir + "/dsr_manet_seed_" + std::to_string(randomSeed) + "_run_" + std::to_string(randomRun) + ".xml";
    std::string logFile = logDir + "/simulation_seed_" + std::to_string(randomSeed) + "_run_" + std::to_string(randomRun) + ".log";

    std::ofstream logStream(logFile);
    std::thread liveTraceWriter;
    if (!liveTraceFile.empty())
    {
        EnsureDirectory(std::filesystem::path(liveTraceFile).parent_path().string());
        gLiveTrace.open(liveTraceFile, std::ios::out | std::ios::trunc);
        NS_ABORT_MSG_IF(!gLiveTrace.is_open(), "Could not open live trace file: " << liveTraceFile);
        gLiveStreamingEnabled = true;
        liveTraceWriter = std::thread(&WriteLiveTrace);
    }
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
    logStream << "dsr_event_file=" << dsrEventFile << "\n";
    logStream << "dsr_pcap_file=" << dsrPcapFile << "\n";
    logStream << "failure_outage_start_s=" << failureOutageStartS << "\n";
    logStream << "failure_outage_duration_s=" << failureOutageDurationS << "\n";
    logStream << "failure_outage_range_m=" << failureOutageRangeM << "\n";
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
    Ptr<YansWifiChannel> wifiChannel = channel.Create();
    gRangeModel = CreateObject<RangePropagationLossModel>();
    gRangeModel->SetAttribute("MaxRange", DoubleValue(gRadioRangeMeters));
    wifiChannel->SetPropagationLossModel(gRangeModel);
    phy.SetChannel(wifiChannel);

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
    // A /16 keeps the configured address pool valid for the dashboard's
    // supported 2–500 node scenarios (the previous /24 ran out above 254).
    address.SetBase("10.1.0.0", "255.255.0.0");
    Ipv4InterfaceContainer interfaces = address.Assign(devices);
    if (gDsrControlPcap)
    {
        for (uint32_t i = 0; i < nodes.GetN(); ++i)
        {
            Ptr<Ipv4L3Protocol> ipv4L3 = nodes.Get(i)->GetObject<Ipv4L3Protocol>();
            NS_ABORT_MSG_IF(!ipv4L3, "IPv4 L3 object missing on node " << i);
            bool rxConnected = ipv4L3->TraceConnectWithoutContext("Rx", MakeBoundCallback(&RecordDsrControlPacket, i, static_cast<uint8_t>(0)));
            bool txConnected = ipv4L3->TraceConnectWithoutContext("Tx", MakeBoundCallback(&RecordDsrControlPacket, i, static_cast<uint8_t>(1)));
            NS_ABORT_MSG_IF(!rxConnected || !txConnected, "Could not connect IPv4 Tx/Rx pcap capture on node " << i);
        }
    }

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

    if (failureExperiment)
    {
        EnsureDirectory(std::filesystem::path(failureControlFile).parent_path().string());
        gExperimentControl.open(failureControlFile, std::ios::out | std::ios::trunc);
        NS_ABORT_MSG_IF(!gExperimentControl.is_open(), "Could not open experiment control log: " << failureControlFile);
        gExperimentControl << "{\"schema_version\":\"range_intervention_v1\",\"status\":\"scheduled\",\"start_s\":" << failureOutageStartS
                           << ",\"duration_s\":" << failureOutageDurationS << ",\"outage_range_m\":" << failureOutageRangeM
                           << ",\"restored_range_m\":" << gRadioRangeMeters << "}\n";
        gExperimentControl.flush();
        NS_ABORT_MSG_IF(!gExperimentControl.good(), "Could not persist scheduled range intervention to " << failureControlFile);
        Simulator::Schedule(Seconds(failureOutageStartS), &ApplyRangeIntervention, failureOutageRangeM);
        Simulator::Schedule(Seconds(failureOutageStartS + failureOutageDurationS), &ApplyRangeIntervention, gRadioRangeMeters);
    }

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
    if (gLiveTrace.is_open())
    {
        NodeContainer liveNodes = nodes;
        Simulator::Schedule(Seconds(0.0), &RecordLiveSnapshot, liveNodes, 0.0, stopTime, samplingInterval);
    }

    Simulator::Stop(Seconds(simulationTime + 1.0));
    Simulator::Run();
    if (gApplicationPacketTrace.is_open())
    {
        gApplicationPacketTrace.flush();
        NS_ABORT_MSG_IF(!gApplicationPacketTrace.good(), "Could not flush application packet trace");
        gApplicationPacketTrace.close();
        NS_ABORT_MSG_IF(gApplicationPacketTrace.fail(), "Could not close application packet trace");
    }
    if (gLiveTrace.is_open())
    {
        {
            std::lock_guard<std::mutex> lock(gLiveQueueMutex);
            gLiveWriterStopping = true;
        }
        gLiveQueueReady.notify_one();
        liveTraceWriter.join();
        gLiveTrace.close();
    }

    auto classifier = DynamicCast<Ipv4FlowClassifier>(flowMonitorHelper.GetClassifier());
    auto stats = flowMonitor->GetFlowStats();

    std::ofstream metricsCsv(metricsFile);
    metricsCsv << "run_id,random_seed,random_run,timestamp_s,node_count,source,destination,tx_packets,rx_packets,tx_bytes,rx_bytes,packet_loss,pdr,throughput_bps,delay_ms,delay_sample_count,packet_size,traffic_rate,area_size,node_speed,mobility_model,routing_protocol,measurement_layer\n";

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
                   << txPackets << "," << rxPackets << "," << txBytes << "," << rxBytes << "," << std::fixed << std::setprecision(6) << packetLoss << "," << pdr << "," << throughputBps << "," << delayMs << "," << flow.rxPackets << ","
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
        const double delayMs = gApplicationDelayPackets > 0
                                   ? static_cast<double>(gApplicationDelayNsSum) /
                                         static_cast<double>(gApplicationDelayPackets) / 1e6
                                   : 0.0;

        metricsCsv << runId << "," << randomSeed << "," << randomRun << "," << simulationTime << "," << nodeCount << ","
                   << interfaces.GetAddress(source) << "," << interfaces.GetAddress(destination) << ","
                   << gApplicationTxPackets << "," << gApplicationRxPackets << "," << gApplicationTxBytes << ","
                   << gApplicationRxBytes << "," << packetLoss << "," << std::fixed << std::setprecision(6)
                   << pdr << "," << throughputBps << "," << delayMs << "," << gApplicationDelayPackets << ","
                   << packetSize << "," << trafficRate << "," << areaSize << ","
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
    logStream << "application_trace_file=" << applicationTraceFile << "\n";
    logStream << "application_delay_samples=" << gApplicationDelayPackets << "\n";
    logStream << "application_mean_delay_ms="
              << (gApplicationDelayPackets > 0
                      ? static_cast<double>(gApplicationDelayNsSum) /
                            static_cast<double>(gApplicationDelayPackets) / 1e6
                      : 0.0)
              << "\n";
    logStream << "status=baseline_dsr_run_complete\n";
    logStream.close();

    Simulator::Destroy();
    dsr::stage2::EventSink::Close();
    if (gDsrControlPcap) { gDsrControlPcap->Close(); }
    if (gDsrPcapIndex.is_open()) { gDsrPcapIndex.flush(); gDsrPcapIndex.close(); }
    if (gExperimentControl.is_open()) { gExperimentControl.flush(); gExperimentControl.close(); }
    return 0;
}

#ifndef STAGE2_DSR_EVENT_SINK_H
#define STAGE2_DSR_EVENT_SINK_H

#include "ns3/simulator.h"
#include "ns3/ipv4.h"
#include "ns3/node-list.h"
#include "ns3/node.h"
#include "ns3/abort.h"

#include <cstdint>
#include <fstream>
#include <iomanip>
#include <string>
#include <vector>

namespace ns3::dsr::stage2
{
struct EventSink
{
    static void Configure(const std::string& path,
                          const std::string& scenario,
                          uint32_t run,
                          uint32_t seed,
                          uint32_t repeat)
    {
        auto& s = State();
        s.file.open(path, std::ios::out | std::ios::trunc);
        NS_ABORT_MSG_IF(!s.file.is_open(), "Could not open DSR event JSONL file: " << path);
        s.scenario = scenario;
        s.run = run;
        s.seed = seed;
        s.repeat = repeat;
        s.seq = 0;
    }

    static void Close()
    {
        auto& s = State();
        if (s.file.is_open())
        {
            s.file.flush();
            NS_ABORT_MSG_IF(!s.file.good(), "Could not flush DSR event JSONL file");
            s.file.close();
            NS_ABORT_MSG_IF(s.file.fail(), "Could not close DSR event JSONL file");
        }
    }

    static void Emit(const std::string& type,
                     uint32_t node,
                     int64_t source,
                     int64_t destination,
                     const std::string& hook,
                     const std::string& sourceFile,
                     const std::vector<uint32_t>& route = {},
                     int64_t neighbor = -1,
                     const std::string& failure = {},
                     int64_t packetId = -1,
                     int64_t pcapRecordIndex = -1,
                     int64_t recoveryDurationNs = -1)
    {
        auto& s = State();
        if (!s.file.is_open()) { return; }
        const uint64_t now = Simulator::Now().GetNanoSeconds();
        const uint64_t seq = s.seq++;
        s.file << "{\"schema_version\":\"dsr_event_v2\",\"scenario_id\":\""
               << Escape(s.scenario) << "\",\"run_id\":" << s.run
               << ",\"random_seed\":" << s.seed << ",\"random_run\":" << s.repeat
               << ",\"simulation_time_ns\":" << now << ",\"simulation_time_s\":"
               << std::setprecision(17) << static_cast<double>(now) / 1e9
               << ",\"event_id\":\"" << Escape(s.scenario) << ':' << s.run << ':' << s.seed
               << ':' << s.repeat << ':' << seq << "\",\"event_seq\":" << seq
               << ",\"event_type\":\"" << Escape(type) << "\",\"node_id\":" << node
               << ",\"source_node\":";
        WriteOptional(s.file, source);
        s.file << ",\"destination_node\":";
        WriteOptional(s.file, destination);
        s.file << ",\"neighbor_id\":";
        WriteOptional(s.file, neighbor);
        s.file << ",\"route_nodes\":";
        if (route.empty()) { s.file << "null"; }
        else
        {
            s.file << '[';
            for (size_t i = 0; i < route.size(); ++i) { if (i) s.file << ','; s.file << route[i]; }
            s.file << ']';
        }
        s.file << ",\"hop_count\":";
        if (route.empty()) { s.file << "null"; } else { s.file << route.size() - 1; }
        s.file << ",\"route_id\":";
        if (route.empty()) { s.file << "null"; }
        else
        {
            uint64_t hash = 1469598103934665603ULL;
            for (uint32_t id : route) { for (unsigned b = 0; b < 4; ++b) { hash ^= (id >> (8*b)) & 0xff; hash *= 1099511628211ULL; } }
            s.file << "\"" << s.run << ":" << std::hex << hash << std::dec << "\"";
        }
        s.file << ",\"packet_id\":";
        if (packetId < 0) { s.file << "null"; } else { s.file << "\"ns3uid:" << packetId << "\""; }
        s.file << ",\"pcap_record_index\":";
        if (pcapRecordIndex < 0) { s.file << "null"; } else { s.file << pcapRecordIndex; }
        s.file << ",\"recovery_duration_ns\":";
        if (recoveryDurationNs < 0) { s.file << "null"; } else { s.file << recoveryDurationNs; }
        s.file << ",\"evidence_class\":\"direct_observation\",\"evidence_source\":\"ns-3.48 DSR source hook\",\"instrumentation_hook\":\""
               << Escape(hook) << "\",\"source_file\":\"" << Escape(sourceFile) << '"';
        if (!failure.empty()) { s.file << ",\"failure_reason\":\"" << Escape(failure) << '"'; }
        s.file << "}\n";
        if ((seq & 63U) == 63U) { s.file.flush(); }
    }

    static int64_t NodeIdForAddress(Ipv4Address address)
    {
        for (uint32_t n = 0; n < NodeList::GetNNodes(); ++n)
        {
            Ptr<Node> node = NodeList::GetNode(n);
            Ptr<Ipv4> ipv4 = node->GetObject<Ipv4>();
            if (!ipv4) { continue; }
            for (uint32_t interface = 0; interface < ipv4->GetNInterfaces(); ++interface)
            {
                for (uint32_t a = 0; a < ipv4->GetNAddresses(interface); ++a)
                {
                    if (ipv4->GetAddress(interface, a).GetLocal() == address) { return node->GetId(); }
                }
            }
        }
        return -1;
    }

    static std::vector<uint32_t> NodeIdsForRoute(const std::vector<Ipv4Address>& route)
    {
        std::vector<uint32_t> ids;
        for (const auto& address : route)
        {
            const int64_t id = NodeIdForAddress(address);
            if (id < 0) { return {}; }
            ids.push_back(static_cast<uint32_t>(id));
        }
        return ids;
    }

  private:
    struct StateData { std::ofstream file; std::string scenario; uint32_t run=0, seed=0, repeat=1; uint64_t seq=0; };
    static StateData& State() { static StateData state; return state; }
    static std::string Escape(const std::string& in)
    {
        std::string out;
        for (char c : in) { if (c == '\n') { out += "\\n"; } else { if (c == '"' || c == '\\') out += '\\'; out += c; } }
        return out;
    }
    static void WriteOptional(std::ofstream& out, int64_t value) { if (value < 0) out << "null"; else out << value; }
};
}
#endif

#include "sch/netcheck.hpp"

#include "utils/sexpr.hpp"

#include <algorithm>
#include <cstdio>
#include <map>
#include <set>
#include <stdexcept>

namespace kigit {

namespace {

using PinSet = std::set<std::string>; // "REF.PIN"

std::string join(const PinSet& s, size_t limit = 8) {
    std::string out;
    size_t i = 0;
    for (const auto& x : s) {
        if (i++ == limit) {
            out += " ...";
            break;
        }
        out += (out.empty() ? "" : " ") + x;
    }
    return out;
}

// Labels and power symbols attached to the net called `name`, with their
// sheet, to show why things were joined.
std::string describe_names(const Schematic& sch, const std::string& name) {
    int index = -1;
    for (size_t i = 0; i < sch.nets.size(); ++i)
        if (sch.nets[i].name == name) index = static_cast<int>(i);
    std::set<std::string> parts;
    auto sheet = [&](int s) { return sch.sheets[s].file; };
    for (const auto& l : sch.labels) {
        if (l.net != index) continue;
        const char* kind = l.kind == LabelKind::Global ? "global" : l.kind == LabelKind::Local ? "label"
                           : l.kind == LabelKind::Hierarchical ? "hier" : "sheet-pin";
        parts.insert(std::string(kind) + " " + l.text + " @" + sheet(l.sheet));
    }
    for (const auto& s : sch.symbols) {
        for (const auto& p : s.pins) {
            if (p.net != index) continue;
            if (p.type != "power_in") continue;
            if (s.power) parts.insert("power " + s.value + " (" + s.ref + ") @" + sheet(s.sheet));
            else if (p.hidden) parts.insert("hidden pin " + s.ref + "." + p.name);
        }
    }
    std::string out;
    for (const auto& p : parts) out += (out.empty() ? "" : ", ") + p;
    return out.empty() ? "(nothing)" : out;
}

} // namespace

bool check_netlist(const Schematic& sch, const std::string& netlist_text, bool strict_names) {
    // KiCad's nets: name -> pins.
    sexpr::Node doc = sexpr::parse(netlist_text);
    const sexpr::Node* exp = nullptr;
    for (const auto& c : doc.children)
        if (c.is_list && c.name() == "export") exp = &c;
    if (!exp || !exp->child("nets")) throw std::runtime_error("not a KiCad netlist (expected (export (nets ...)))");

    std::map<std::string, PinSet> theirs;
    std::map<std::string, std::string> their_net_of; // pin -> net
    exp->child("nets")->each("net", [&](const sexpr::Node& n) {
        std::string name = sexpr::unescape(n.child("name") ? n.child("name")->arg(0) : "");
        PinSet& pins = theirs[name];
        n.each("node", [&](const sexpr::Node& node) {
            std::string key = sexpr::unescape(node.child("ref")->arg(0)) + "." +
                              sexpr::unescape(node.child("pin")->arg(0));
            pins.insert(key);
            their_net_of[key] = name;
        });
    });

    // Ours, same shape. Nets without real pins (bare wires) aren't in KiCad's list.
    std::map<std::string, PinSet> ours;
    std::map<std::string, std::string> our_net_of;
    for (const auto& n : sch.nets) {
        if (n.nodes.empty()) continue;
        PinSet& pins = ours[n.name];
        for (const auto& node : n.nodes) {
            const auto& s = sch.symbols[node.symbol];
            std::string key = s.ref + "." + s.pins[node.pin].number;
            pins.insert(key);
            our_net_of[key] = n.name;
        }
    }

    int same = 0, renamed = 0, differ = 0;
    std::set<std::string> reported;
    for (const auto& [name, pins] : theirs) {
        // Which of our nets hold this net's pins?
        std::set<std::string> where;
        PinSet missing;
        for (const auto& p : pins) {
            auto f = our_net_of.find(p);
            if (f == our_net_of.end()) missing.insert(p);
            else where.insert(f->second);
        }
        if (missing.empty() && where.size() == 1 && ours[*where.begin()] == pins) {
            const std::string& our_name = *where.begin();
            if (our_name == name) {
                ++same;
            } else {
                ++renamed;
                std::printf("  name   KiCad %-40s kigit %s\n", name.c_str(), our_name.c_str());
            }
            continue;
        }
        ++differ;
        std::printf("  DIFF   KiCad net %s: %s\n", name.c_str(), join(pins).c_str());
        for (const auto& w : where) {
            if (!reported.insert(w).second) continue;
            std::printf("           kigit net %s: %s\n", w.c_str(), join(ours[w]).c_str());
            std::printf("             named by: %s\n", describe_names(sch, w).c_str());
        }
        if (!missing.empty()) std::printf("           pins kigit doesn't have: %s\n", join(missing).c_str());
    }
    PinSet extra;
    for (const auto& [pin, net] : our_net_of)
        if (!their_net_of.count(pin)) extra.insert(pin);
    if (!extra.empty()) std::printf("  EXTRA  pins only kigit has: %s\n", join(extra, 20).c_str());

    std::printf("\n  %zu KiCad nets: %d identical, %d same pins but different name, %d different\n",
                theirs.size(), same, renamed, differ);
    for (const auto& w : sch.warnings) std::printf("  note: %s\n", w.c_str());
    return differ == 0 && extra.empty() && (!strict_names || renamed == 0);
}

} // namespace kigit

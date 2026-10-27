#include "sch_diff.hpp"

#include <algorithm>
#include <cmath>
#include <map>
#include <set>
#include <tuple>
#include <unordered_map>

namespace kigit {

std::string PinRef::text() const {
    bool named = !name.empty() && name != "~" && name != number;
    return ref + "." + number + (named ? " (" + name + ")" : "");
}

bool SymbolDiff::electrical() const {
    if (status == SchStatus::Added || status == SchStatus::Removed || !pins.empty()) return true;
    for (const auto& f : fields)
        if (f.field == "Value" || f.field == "Footprint" || f.field == "Symbol") return true;
    return false;
}

bool SymbolDiff::fields_only() const {
    return status == SchStatus::Changed && !electrical() && (!fields.empty() || ref_before != ref_after);
}

namespace {

std::string grid_key(Point p) {
    return std::to_string(std::llround(p.x * 1e4)) + "," + std::to_string(std::llround(p.y * 1e4));
}

// KiCad's generated names change whenever the pin they're named after changes,
// so they don't identify a net across revisions the way a label does.
bool is_auto_name(const std::string& n) {
    return n.empty() || n.starts_with("Net-(") || n.starts_with("unconnected-(");
}

PinRef pin_ref(const SchSymbol& s, const SchPin& p) { return {s.ref, p.number, p.name}; }

// Matches parts by their KiCad ID within the same sheet instance, then
// unmatched ones by reference + unit (e.g. a part deleted and re-added).
// Returns old index -> new index (-1 if unmatched).
std::vector<int> match_symbols(const Schematic& a, const Schematic& b) {
    auto uuid_key = [](const Schematic& s, const SchSymbol& sym) {
        return s.sheets[sym.sheet].uuid_path + "/" + sym.uuid;
    };
    std::unordered_map<std::string, int> new_by_uuid;
    for (size_t i = 0; i < b.symbols.size(); ++i)
        if (!b.symbols[i].power) new_by_uuid[uuid_key(b, b.symbols[i])] = static_cast<int>(i);

    std::vector<int> map(a.symbols.size(), -1);
    std::vector<bool> taken(b.symbols.size(), false);
    for (size_t i = 0; i < a.symbols.size(); ++i) {
        if (a.symbols[i].power) continue;
        auto f = new_by_uuid.find(uuid_key(a, a.symbols[i]));
        if (f != new_by_uuid.end() && !taken[f->second]) {
            map[i] = f->second;
            taken[f->second] = true;
        }
    }

    std::map<std::pair<std::string, int>, int> new_by_ref;
    for (size_t i = 0; i < b.symbols.size(); ++i) {
        const auto& s = b.symbols[i];
        if (!s.power && !taken[i] && !s.ref.ends_with("?")) new_by_ref[{s.ref, s.unit}] = static_cast<int>(i);
    }
    for (size_t i = 0; i < a.symbols.size(); ++i) {
        const auto& s = a.symbols[i];
        if (s.power || map[i] >= 0 || s.ref.ends_with("?")) continue;
        auto f = new_by_ref.find({s.ref, s.unit});
        if (f != new_by_ref.end() && !taken[f->second]) {
            map[i] = f->second;
            taken[f->second] = true;
        }
    }
    return map;
}

} // namespace

SchDiff diff_schematics(const Schematic& a, const Schematic& b) {
    SchDiff d;

    // ---- parts: a shared id per matched pair, so pins can be compared.
    std::vector<int> sym_map = match_symbols(a, b);
    std::vector<int> new_to_old(b.symbols.size(), -1);
    for (size_t i = 0; i < sym_map.size(); ++i)
        if (sym_map[i] >= 0) new_to_old[sym_map[i]] = static_cast<int>(i);

    auto id_old = [&](int i) { return sym_map[i] >= 0 ? sym_map[i] : static_cast<int>(b.symbols.size()) + i; };
    auto pin_key = [](int id, const std::string& number) { return std::to_string(id) + "." + number; };

    std::unordered_map<std::string, int> old_net_of, new_net_of; // pin key -> net
    for (size_t n = 0; n < a.nets.size(); ++n)
        for (const auto& node : a.nets[n].nodes)
            old_net_of[pin_key(id_old(node.symbol), a.symbols[node.symbol].pins[node.pin].number)] = static_cast<int>(n);
    for (size_t n = 0; n < b.nets.size(); ++n)
        for (const auto& node : b.nets[n].nodes)
            new_net_of[pin_key(node.symbol, b.symbols[node.symbol].pins[node.pin].number)] = static_cast<int>(n);

    // ---- nets: pair them up. A label name that survives is the strongest
    // signal; otherwise the old net sharing the most pins.
    auto relevant = [](const SchNet& n) { return !n.nodes.empty() || !is_auto_name(n.name); };
    std::vector<std::tuple<long, int, int>> candidates; // (score, new, old)
    std::unordered_map<std::string, int> old_by_name;
    for (size_t n = 0; n < a.nets.size(); ++n)
        if (relevant(a.nets[n]) && !is_auto_name(a.nets[n].name)) old_by_name[a.nets[n].name] = static_cast<int>(n);
    for (size_t n = 0; n < b.nets.size(); ++n) {
        const SchNet& net = b.nets[n];
        if (!relevant(net)) continue;
        std::map<int, int> overlap; // old net -> shared pins
        for (const auto& node : net.nodes) {
            auto f = old_net_of.find(pin_key(static_cast<int>(node.symbol), b.symbols[node.symbol].pins[node.pin].number));
            if (f != old_net_of.end()) ++overlap[f->second];
        }
        if (!is_auto_name(net.name)) {
            auto f = old_by_name.find(net.name);
            if (f != old_by_name.end()) overlap.try_emplace(f->second, 0);
        }
        for (const auto& [o, count] : overlap) {
            bool same_label = !is_auto_name(net.name) && a.nets[o].name == net.name;
            long score = (same_label ? 1'000'000L : 0) + count * 10L + (a.nets[o].name == net.name ? 1 : 0);
            candidates.emplace_back(score, static_cast<int>(n), o);
        }
    }
    std::sort(candidates.begin(), candidates.end(), [](const auto& x, const auto& y) { return std::get<0>(x) > std::get<0>(y); });
    std::vector<int> net_new_to_old(b.nets.size(), -1), net_old_to_new(a.nets.size(), -1);
    for (const auto& [score, n, o] : candidates) {
        if (net_new_to_old[n] >= 0 || net_old_to_new[o] >= 0) continue;
        net_new_to_old[n] = o;
        net_old_to_new[o] = n;
    }

    std::vector<int> netdiff_of_new(b.nets.size(), -1), netdiff_of_old(a.nets.size(), -1);
    for (size_t n = 0; n < b.nets.size(); ++n) {
        if (!relevant(b.nets[n])) continue;
        NetDiff nd;
        nd.new_index = static_cast<int>(n);
        nd.old_index = net_new_to_old[n];
        nd.name_after = b.nets[n].name;
        if (nd.old_index >= 0) nd.name_before = a.nets[nd.old_index].name;
        for (const auto& node : b.nets[n].nodes) {
            const auto& s = b.symbols[node.symbol];
            auto f = old_net_of.find(pin_key(node.symbol, s.pins[node.pin].number));
            if (f == old_net_of.end() || f->second != nd.old_index) nd.joined.push_back(pin_ref(s, s.pins[node.pin]));
        }
        if (nd.old_index >= 0) {
            for (const auto& node : a.nets[nd.old_index].nodes) {
                const auto& s = a.symbols[node.symbol];
                auto f = new_net_of.find(pin_key(id_old(node.symbol), s.pins[node.pin].number));
                if (f == new_net_of.end() || f->second != static_cast<int>(n)) nd.left.push_back(pin_ref(s, s.pins[node.pin]));
            }
        }
        bool renamed = nd.old_index >= 0 && nd.name_before != nd.name_after;
        nd.status = nd.old_index < 0 ? SchStatus::Added
                    : (renamed || !nd.joined.empty() || !nd.left.empty()) ? SchStatus::Changed
                                                                           : SchStatus::Same;
        netdiff_of_new[n] = static_cast<int>(d.nets.size());
        if (nd.old_index >= 0) netdiff_of_old[nd.old_index] = static_cast<int>(d.nets.size());
        d.nets.push_back(std::move(nd));
    }
    for (size_t o = 0; o < a.nets.size(); ++o) {
        if (!relevant(a.nets[o]) || net_old_to_new[o] >= 0) continue;
        NetDiff nd;
        nd.old_index = static_cast<int>(o);
        nd.name_before = a.nets[o].name;
        nd.status = SchStatus::Removed;
        std::set<int> went_to;
        for (const auto& node : a.nets[o].nodes) {
            const auto& s = a.symbols[node.symbol];
            nd.left.push_back(pin_ref(s, s.pins[node.pin]));
            auto f = new_net_of.find(pin_key(id_old(node.symbol), s.pins[node.pin].number));
            went_to.insert(f == new_net_of.end() ? -1 : f->second);
        }
        if (went_to.size() == 1 && *went_to.begin() >= 0) nd.merged_into = b.nets[*went_to.begin()].name;
        netdiff_of_old[o] = static_cast<int>(d.nets.size());
        d.nets.push_back(std::move(nd));
    }

    // ---- wires and labels: matched by position on the same sheet instance.
    auto count_into = [&](int net, bool old_side, int NetDiff::*field) {
        if (net < 0) return;
        int idx = old_side ? netdiff_of_old[net] : netdiff_of_new[net];
        if (idx >= 0) ++(d.nets[idx].*field);
    };
    {
        auto key = [](const Schematic& s, const SchWire& w) {
            std::string p = grid_key(w.a), q = grid_key(w.b);
            if (q < p) std::swap(p, q); // direction doesn't matter
            return s.sheets[w.sheet].uuid_path + "|" + p + "|" + q;
        };
        std::unordered_map<std::string, int> pending;
        for (const auto& w : a.wires) ++pending[key(a, w)];
        d.wires_new.assign(b.wires.size(), SchStatus::Added);
        for (size_t i = 0; i < b.wires.size(); ++i) {
            auto f = pending.find(key(b, b.wires[i]));
            if (f != pending.end() && f->second > 0) {
                --f->second;
                d.wires_new[i] = SchStatus::Same;
            } else {
                count_into(b.wires[i].net, false, &NetDiff::wires_added);
            }
        }
        std::unordered_map<std::string, int> in_new;
        for (const auto& w : b.wires) ++in_new[key(b, w)];
        d.wires_old.assign(a.wires.size(), SchStatus::Removed);
        for (size_t i = 0; i < a.wires.size(); ++i) {
            auto f = in_new.find(key(a, a.wires[i]));
            if (f != in_new.end() && f->second > 0) {
                --f->second;
                d.wires_old[i] = SchStatus::Same;
            } else {
                count_into(a.wires[i].net, true, &NetDiff::wires_removed);
            }
        }
    }
    {
        auto key = [](const Schematic& s, const SchLabel& l) {
            return s.sheets[l.sheet].uuid_path + "|" + std::to_string(static_cast<int>(l.kind)) + "|" + l.text + "|" +
                   grid_key(l.at);
        };
        std::unordered_map<std::string, int> in_old, in_new;
        for (const auto& l : a.labels) ++in_old[key(a, l)];
        for (const auto& l : b.labels) ++in_new[key(b, l)];
        d.labels_new.assign(b.labels.size(), SchStatus::Same);
        for (size_t i = 0; i < b.labels.size(); ++i) {
            auto f = in_old.find(key(b, b.labels[i]));
            if (f != in_old.end() && f->second > 0) {
                --f->second;
            } else {
                d.labels_new[i] = SchStatus::Added;
                count_into(b.labels[i].net, false, &NetDiff::labels_added);
            }
        }
        d.labels_old.assign(a.labels.size(), SchStatus::Same);
        for (size_t i = 0; i < a.labels.size(); ++i) {
            auto f = in_new.find(key(a, a.labels[i]));
            if (f != in_new.end() && f->second > 0) {
                --f->second;
            } else {
                d.labels_old[i] = SchStatus::Removed;
                count_into(a.labels[i].net, true, &NetDiff::labels_removed);
            }
        }
    }

    // ---- per part: what changed about it.
    auto net_name = [](const Schematic& s, int net) { return net >= 0 ? s.nets[net].name : std::string(); };
    for (size_t i = 0; i < b.symbols.size(); ++i) {
        const SchSymbol& ns = b.symbols[i];
        if (ns.power) continue;
        SymbolDiff sd;
        sd.new_index = static_cast<int>(i);
        sd.old_index = new_to_old[i];
        sd.ref_after = ns.ref;
        if (sd.old_index < 0) {
            sd.status = SchStatus::Added;
            d.symbols.push_back(std::move(sd));
            continue;
        }
        const SchSymbol& os = a.symbols[sd.old_index];
        sd.ref_before = os.ref;
        auto field = [&](const std::string& name, const std::string& before, const std::string& after) {
            if (before != after) sd.fields.push_back({name, before, after});
        };
        field("Value", os.value, ns.value);
        field("Footprint", os.footprint, ns.footprint);
        field("Symbol", os.lib_id, ns.lib_id);
        std::set<std::string> keys;
        for (const auto& [k, v] : os.fields) keys.insert(k);
        for (const auto& [k, v] : ns.fields) keys.insert(k);
        for (const auto& k : keys) {
            auto fo = os.fields.find(k), fn = ns.fields.find(k);
            field(k, fo == os.fields.end() ? "" : fo->second, fn == ns.fields.end() ? "" : fn->second);
        }
        sd.moved = os.at.x != ns.at.x || os.at.y != ns.at.y || os.angle != ns.angle || os.mirror_x != ns.mirror_x ||
                   os.mirror_y != ns.mirror_y || a.sheets[os.sheet].uuid_path != b.sheets[ns.sheet].uuid_path;

        // Pins whose net isn't the counterpart of their old net.
        std::map<std::string, int> old_pin_net;
        for (const auto& p : os.pins) old_pin_net[p.number] = p.net;
        std::set<std::string> seen;
        for (const auto& p : ns.pins) {
            seen.insert(p.number);
            auto f = old_pin_net.find(p.number);
            int before = f == old_pin_net.end() ? -1 : f->second;
            bool same = before >= 0 && p.net >= 0 && net_old_to_new[before] == p.net;
            bool both_unconnected = before >= 0 && p.net >= 0 && a.nets[before].nodes.size() == 1 && b.nets[p.net].nodes.size() == 1;
            if (!same && !both_unconnected) sd.pins.push_back({pin_ref(ns, p), net_name(a, before), net_name(b, p.net)});
        }
        for (const auto& p : os.pins)
            if (!seen.count(p.number)) sd.pins.push_back({pin_ref(os, p), net_name(a, p.net), ""});

        bool changed = sd.ref_before != sd.ref_after || !sd.fields.empty() || !sd.pins.empty() || sd.moved;
        sd.status = changed ? SchStatus::Changed : SchStatus::Same;
        d.symbols.push_back(std::move(sd));
    }
    for (size_t i = 0; i < a.symbols.size(); ++i) {
        if (a.symbols[i].power || sym_map[i] >= 0) continue;
        SymbolDiff sd;
        sd.old_index = static_cast<int>(i);
        sd.ref_before = a.symbols[i].ref;
        sd.status = SchStatus::Removed;
        d.symbols.push_back(std::move(sd));
    }
    return d;
}

} // namespace kigit

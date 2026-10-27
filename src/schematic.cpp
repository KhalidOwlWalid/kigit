#include "schematic.hpp"

#include "sexpr.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <cmath>
#include <map>
#include <numeric>
#include <stdexcept>
#include <unordered_map>

namespace kigit {

using sexpr::Node;

namespace {

// ---------------------------------------------------------------- parsing

struct LibPin {
    std::string number, name, type;
    Point at;       // library coordinates (y points up)
    bool hidden = false;
    int unit = 0;   // 0 = shared by all units
    int style = 0;  // body style (De Morgan), 0 = shared
};

struct LibSymbol {
    bool power = false;
    bool local_power = false; // (power local): net is local to the sheet
    std::string extends;
    std::vector<LibPin> pins;
};

using LibMap = std::unordered_map<std::string, LibSymbol>;

Point xy(const Node* n) { return n ? Point{n->num(0), n->num(1)} : Point{}; }

// True if `n` has a flag either as a bare atom, (pin ... hide ...), or as a
// child list, (hide yes).
bool has_flag(const Node& n, std::string_view flag) {
    for (size_t i = 1; i < n.children.size(); ++i) {
        const Node& c = n.children[i];
        if (!c.is_list && !c.quoted && c.atom == flag) return true;
        if (c.is_list && c.name() == flag) return c.arg_count() == 0 || c.arg(0) == "yes";
    }
    return false;
}

std::string property(const Node& n, std::string_view key) {
    std::string out;
    n.each("property", [&](const Node& p) {
        if (p.arg(0) == key) out = sexpr::unescape(p.arg(1));
    });
    return out;
}

// "C_1_1" -> unit 1, style 1. The base name may itself contain underscores.
void unit_and_style(const std::string& name, int& unit, int& style) {
    unit = 0;
    style = 0;
    size_t s = name.rfind('_');
    if (s == std::string::npos || s == 0) return;
    size_t u = name.rfind('_', s - 1);
    if (u == std::string::npos) return;
    try {
        unit = std::stoi(name.substr(u + 1, s - u - 1));
        style = std::stoi(name.substr(s + 1));
    } catch (...) {
        unit = style = 0;
    }
}

LibMap read_lib_symbols(const Node& sheet) {
    LibMap lib;
    const Node* libs = sheet.child("lib_symbols");
    if (!libs) return lib;
    libs->each("symbol", [&](const Node& s) {
        LibSymbol ls;
        if (const Node* p = s.child("power")) {
            ls.power = true;
            ls.local_power = p->arg(0) == "local";
        }
        if (const Node* e = s.child("extends")) ls.extends = sexpr::unescape(e->arg(0));
        s.each("symbol", [&](const Node& u) {
            int unit, style;
            unit_and_style(sexpr::unescape(u.arg(0)), unit, style);
            u.each("pin", [&](const Node& p) {
                LibPin lp;
                lp.type = std::string(p.arg(0));
                lp.at = xy(p.child("at"));
                lp.hidden = has_flag(p, "hide");
                if (const Node* n = p.child("name")) lp.name = sexpr::unescape(n->arg(0));
                if (const Node* n = p.child("number")) lp.number = sexpr::unescape(n->arg(0));
                lp.unit = unit;
                lp.style = style;
                ls.pins.push_back(std::move(lp));
            });
        });
        lib[sexpr::unescape(s.arg(0))] = std::move(ls);
    });
    // Derived symbols take their pins from the parent.
    for (auto& [name, sym] : lib) {
        if (sym.extends.empty() || !sym.pins.empty()) continue;
        auto parent = lib.find(sym.extends);
        if (parent == lib.end()) {
            auto colon = name.find(':');
            if (colon != std::string::npos) parent = lib.find(name.substr(0, colon + 1) + sym.extends);
        }
        if (parent != lib.end()) sym.pins = parent->second.pins;
    }
    return lib;
}

// Library pin position -> sheet position. Library y points up, sheet y points
// down; then the symbol's rotation (counter-clockwise) and mirroring apply.
Point place_pin(Point lib, const SchSymbol& s) {
    double x = lib.x, y = -lib.y;
    int quarter = static_cast<int>(std::lround(s.angle / 90.0)) & 3;
    static const int cs[4][2] = {{1, 0}, {0, 1}, {-1, 0}, {0, -1}}; // cos, sin
    double c = cs[quarter][0], sn = cs[quarter][1];
    double rx = x * c + y * sn, ry = -x * sn + y * c;
    if (s.mirror_y) rx = -rx;
    if (s.mirror_x) ry = -ry;
    return {s.at.x + rx, s.at.y + ry};
}

class Loader {
public:
    Loader(const FileReader& read, Schematic& sch) : read_(read), sch_(sch) {}

    bool multiple_roots = false;

    // Loads one top-level sheet and everything below it. `name` is its name
    // in the project ("" = use the file name).
    void load_root(const std::string& file, const std::string& name) {
        std::optional<std::string> text = read_(file);
        if (!text) throw std::runtime_error("cannot read schematic " + file);
        SheetInstance root;
        root.file = file;
        root.name = name;
        int index = static_cast<int>(sch_.sheets.size());
        sch_.sheets.push_back(root);
        load_sheet(index, *text, 0);
    }

private:
    void load_sheet(int index, const std::string& text, int depth) {
        Node doc = sexpr::parse(text);
        const Node* top = nullptr;
        for (const Node& c : doc.children)
            if (c.is_list && c.name() == "kicad_sch") top = &c;
        if (!top) throw std::runtime_error(sch_.sheets[index].file + " is not a KiCad schematic");

        if (sch_.sheets[index].parent < 0) {
            // A top-level sheet. With several of them (KiCad 10), net names
            // say which one: "/owl_v1/GPIOs/X". With just one, plain "/".
            SheetInstance& root = sch_.sheets[index];
            if (root.name.empty()) {
                root.name = root.file;
                if (auto slash = root.name.rfind('/'); slash != std::string::npos) root.name = root.name.substr(slash + 1);
                if (auto dot = root.name.rfind(".kicad_sch"); dot != std::string::npos) root.name = root.name.substr(0, dot);
            }
            root.path = multiple_roots ? "/" + root.name + "/" : "/";
            if (const Node* u = top->child("uuid")) root.uuid_path = "/" + sexpr::unescape(u->arg(0));
        }

        const SheetInstance sheet = sch_.sheets[index]; // copy: the vector grows below
        LibMap lib = read_lib_symbols(*top);
        std::vector<std::pair<int, std::string>> children; // (instance, file)

        for (const Node& n : top->children) {
            if (!n.is_list) continue;
            std::string_view kind = n.name();
            if (kind == "symbol") {
                read_symbol(n, index, sheet, lib);
            } else if (kind == "wire") {
                const Node* pts = n.child("pts");
                if (!pts) continue;
                std::vector<Point> p;
                pts->each("xy", [&](const Node& q) { p.push_back(xy(&q)); });
                if (p.size() == 2) sch_.wires.push_back({index, p[0], p[1], -1});
            } else if (kind == "junction") {
                sch_.junctions.emplace_back(index, xy(n.child("at")));
            } else if (kind == "label" || kind == "global_label" || kind == "hierarchical_label") {
                SchLabel l;
                l.sheet = index;
                l.kind = kind == "label"          ? LabelKind::Local
                         : kind == "global_label" ? LabelKind::Global
                                                  : LabelKind::Hierarchical;
                l.text = sexpr::unescape(n.arg(0));
                l.at = xy(n.child("at"));
                sch_.labels.push_back(std::move(l));
            } else if (kind == "sheet") {
                SheetInstance child;
                child.name = property(n, "Sheetname");
                child.file = property(n, "Sheetfile");
                child.parent = index;
                child.path = sheet.path + child.name + "/";
                std::string uuid;
                if (const Node* u = n.child("uuid")) uuid = sexpr::unescape(u->arg(0));
                child.uuid_path = sheet.uuid_path + "/" + uuid;
                int child_index = static_cast<int>(sch_.sheets.size());
                sch_.sheets.push_back(child);
                n.each("pin", [&](const Node& p) {
                    SchLabel l;
                    l.sheet = index;
                    l.kind = LabelKind::SheetPin;
                    l.text = sexpr::unescape(p.arg(0));
                    l.at = xy(p.child("at"));
                    l.child = child_index;
                    sch_.labels.push_back(std::move(l));
                });
                children.emplace_back(child_index, child.file);
            } else if ((kind == "bus" || kind == "bus_entry") && !warned_bus_) {
                sch_.warnings.push_back("buses aren't supported yet; nets carried only by buses may be split");
                warned_bus_ = true;
            }
        }

        for (const auto& [child_index, file] : children) {
            if (depth > 32) {
                sch_.warnings.push_back("sheet nesting deeper than 32 levels, stopped at " + file);
                continue;
            }
            std::optional<std::string> child_text = read_(file);
            if (!child_text) {
                sch_.warnings.push_back("sheet file " + file + " not found");
                continue;
            }
            load_sheet(child_index, *child_text, depth + 1);
        }
    }

    void read_symbol(const Node& n, int index, const SheetInstance& sheet, const LibMap& lib) {
        SchSymbol s;
        s.sheet = index;
        if (const Node* id = n.child("lib_id")) s.lib_id = sexpr::unescape(id->arg(0));
        std::string lib_key = s.lib_id;
        if (const Node* ln = n.child("lib_name")) lib_key = sexpr::unescape(ln->arg(0));
        if (const Node* u = n.child("uuid")) s.uuid = sexpr::unescape(u->arg(0));
        if (const Node* at = n.child("at")) {
            s.at = xy(at);
            s.angle = at->num(2);
        }
        if (const Node* m = n.child("mirror")) {
            s.mirror_x = m->arg(0) == "x";
            s.mirror_y = m->arg(0) == "y";
        }
        if (const Node* u = n.child("unit")) s.unit = static_cast<int>(u->num(0, 1));
        int style = 1;
        if (const Node* b = n.child("body_style")) style = static_cast<int>(b->num(0, 1));
        else if (const Node* b2 = n.child("convert")) style = static_cast<int>(b2->num(0, 1));
        s.ref = property(n, "Reference");
        s.value = property(n, "Value");
        s.footprint = property(n, "Footprint");

        // The reference and unit for this sheet instance live in (instances).
        if (const Node* inst = n.child("instances")) {
            inst->each("project", [&](const Node& proj) {
                proj.each("path", [&](const Node& p) {
                    if (sexpr::unescape(p.arg(0)) != sheet.uuid_path) return;
                    if (const Node* r = p.child("reference")) s.ref = sexpr::unescape(r->arg(0));
                    if (const Node* u = p.child("unit")) s.unit = static_cast<int>(u->num(0, s.unit));
                });
            });
        }

        auto found = lib.find(lib_key);
        if (found == lib.end()) {
            sch_.warnings.push_back("symbol " + s.ref + " (" + lib_key + ") has no library definition");
        } else {
            s.power = found->second.power;
            local_power_[sch_.symbols.size()] = found->second.local_power;
            for (const LibPin& lp : found->second.pins) {
                if (lp.unit != 0 && lp.unit != s.unit) continue;
                if (lp.style != 0 && lp.style != style) continue;
                SchPin pin;
                pin.number = lp.number;
                pin.name = lp.name;
                pin.type = lp.type;
                pin.hidden = lp.hidden;
                pin.pos = place_pin(lp.at, s);
                s.pins.push_back(std::move(pin));
            }
        }
        sch_.symbols.push_back(std::move(s));
    }

public:
    std::unordered_map<size_t, bool> local_power_; // symbol index -> (power local)

private:
    const FileReader& read_;
    Schematic& sch_;
    bool warned_bus_ = false;
};

// ---------------------------------------------------------- connectivity

struct DisjointSet {
    std::vector<int> parent;
    int add() {
        parent.push_back(static_cast<int>(parent.size()));
        return parent.back();
    }
    int find(int x) {
        while (parent[x] != x) x = parent[x] = parent[parent[x]];
        return x;
    }
    void join(int a, int b) { parent[find(a)] = find(b); }
};

struct PointKey {
    int sheet;
    long long x, y;
    bool operator==(const PointKey&) const = default;
};
struct PointKeyHash {
    size_t operator()(const PointKey& k) const {
        return std::hash<long long>()(k.x * 1000003LL ^ k.y) ^ (static_cast<size_t>(k.sheet) << 1);
    }
};

long long grid(double v) { return std::llround(v * 1e4); } // 0.1 µm

// True if p lies on segment a-b, endpoints excluded.
bool on_segment_interior(long long px, long long py, long long ax, long long ay, long long bx, long long by) {
    if ((px == ax && py == ay) || (px == bx && py == by)) return false;
    long long cross = (bx - ax) * (py - ay) - (by - ay) * (px - ax); // fits: coords < 1e8
    if (cross != 0) return false;
    return px >= std::min(ax, bx) && px <= std::max(ax, bx) && py >= std::min(ay, by) && py <= std::max(ay, by);
}

// Name candidates, highest priority wins (mirrors KiCad's driver priority).
enum Priority { kPin = 1, kSheetPin = 2, kHierLabel = 3, kLocalLabel = 4, kLocalPower = 5, kGlobalPower = 6, kGlobal = 7 };

struct Candidate {
    int priority = 0;
    int depth = 0;
    std::string name;
    int rank = 0; // pins: 0 = has a pin name, 1 = only a number (KiCad prefers named pins)
    bool better_than(const Candidate& o) const {
        if (priority != o.priority) return priority > o.priority;
        if (rank != o.rank) return rank < o.rank;
        if (depth != o.depth) return depth < o.depth; // prefer higher in the hierarchy
        return name < o.name;
    }
};

// KiCad's rule: a power-input pin that is hidden, or belongs to a power
// symbol, joins a net by name. (PWR_FLAG is a power symbol too, but its pin
// is a power output, so it names nothing.)
bool is_power_pin(const SchSymbol& s, const SchPin& p) {
    return p.type == "power_in" && (s.power || p.hidden);
}

// Power symbols name their net after their value (GND, +3.3V); hidden power
// pins on ordinary parts after the pin name.
std::string power_net(const SchSymbol& s, const SchPin& p) { return s.power ? s.value : p.name; }

// A pin name that says something: not empty, not "~", not just the number again.
bool has_real_name(const SchPin& p) { return !p.name.empty() && p.name != "~" && p.name != p.number; }

std::string pin_label(const SchSymbol& s, const SchPin& p) {
    if (!has_real_name(p)) return "Pad" + p.number;
    // A name shared by several pins doesn't identify one; add the number.
    int same = 0;
    for (const SchPin& q : s.pins) same += q.name == p.name;
    return same > 1 ? p.name + "-Pad" + p.number : p.name;
}

void connect(Schematic& sch, const std::unordered_map<size_t, bool>& local_power) {
    DisjointSet ds;
    std::unordered_map<PointKey, int, PointKeyHash> points;
    std::unordered_map<std::string, int> named;

    auto point = [&](int sheet, Point p) {
        PointKey k{sheet, grid(p.x), grid(p.y)};
        auto [it, inserted] = points.try_emplace(k, 0);
        if (inserted) it->second = ds.add();
        return it->second;
    };
    auto name_node = [&](const std::string& key) {
        auto [it, inserted] = named.try_emplace(key, 0);
        if (inserted) it->second = ds.add();
        return it->second;
    };

    // Register every connection point.
    for (auto& w : sch.wires) {
        ds.join(point(w.sheet, w.a), point(w.sheet, w.b));
    }
    for (auto& [sheet, at] : sch.junctions) point(sheet, at);
    for (auto& s : sch.symbols)
        for (auto& p : s.pins) point(s.sheet, p.pos);
    for (auto& l : sch.labels) point(l.sheet, l.at);

    // A point touching a wire anywhere along it connects to that wire.
    // (Two wires merely crossing don't: the crossing isn't a point unless a
    // junction or an endpoint sits there.)
    std::vector<std::vector<std::pair<PointKey, int>>> by_sheet(sch.sheets.size());
    for (const auto& [k, id] : points) by_sheet[k.sheet].emplace_back(k, id);
    for (const auto& w : sch.wires) {
        long long ax = grid(w.a.x), ay = grid(w.a.y), bx = grid(w.b.x), by = grid(w.b.y);
        int wire_id = point(w.sheet, w.a);
        for (const auto& [k, id] : by_sheet[w.sheet])
            if (on_segment_interior(k.x, k.y, ax, ay, bx, by)) ds.join(id, wire_id);
    }

    // Labels, power symbols and sheet pins join points by name.
    for (const auto& l : sch.labels) {
        int id = point(l.sheet, l.at);
        switch (l.kind) {
        case LabelKind::Global: ds.join(id, name_node("G:" + l.text)); break;
        case LabelKind::Local: ds.join(id, name_node("L:" + std::to_string(l.sheet) + ":" + l.text)); break;
        case LabelKind::Hierarchical: ds.join(id, name_node("H:" + std::to_string(l.sheet) + ":" + l.text)); break;
        case LabelKind::SheetPin: ds.join(id, name_node("H:" + std::to_string(l.child) + ":" + l.text)); break;
        }
    }
    for (size_t i = 0; i < sch.symbols.size(); ++i) {
        const SchSymbol& s = sch.symbols[i];
        for (const SchPin& p : s.pins) {
            if (!is_power_pin(s, p) || power_net(s, p).empty()) continue;
            auto lp = local_power.find(i);
            bool local = s.power && lp != local_power.end() && lp->second;
            std::string key = local ? "P:" + std::to_string(s.sheet) + ":" + power_net(s, p) : "G:" + power_net(s, p);
            ds.join(point(s.sheet, p.pos), name_node(key));
        }
    }

    // Every group that contains a pin, label or wire becomes a net.
    std::unordered_map<int, int> net_of_root;
    std::vector<Candidate> best;
    std::vector<int> pin_count;
    auto net_for = [&](int id) {
        int root = ds.find(id);
        auto [it, inserted] = net_of_root.try_emplace(root, static_cast<int>(sch.nets.size()));
        if (inserted) {
            sch.nets.emplace_back();
            best.emplace_back();
            pin_count.push_back(0);
        }
        return it->second;
    };
    auto offer = [&](int net, Candidate c) {
        if (best[net].priority == 0 || c.better_than(best[net])) best[net] = std::move(c);
    };
    auto depth_of = [&](int sheet) {
        int d = 0;
        for (int s = sheet; sch.sheets[s].parent >= 0; s = sch.sheets[s].parent) ++d;
        return d;
    };

    for (auto& w : sch.wires) w.net = net_for(point(w.sheet, w.a));
    for (auto& l : sch.labels) {
        l.net = net_for(point(l.sheet, l.at));
        int d = depth_of(l.sheet);
        const std::string& path = sch.sheets[l.sheet].path;
        switch (l.kind) {
        case LabelKind::Global: offer(l.net, {kGlobal, d, l.text}); break;
        case LabelKind::Local: offer(l.net, {kLocalLabel, d, path + l.text}); break;
        case LabelKind::Hierarchical: offer(l.net, {kHierLabel, d, path + l.text}); break;
        case LabelKind::SheetPin: offer(l.net, {kSheetPin, d, path + l.text}); break;
        }
    }
    for (size_t i = 0; i < sch.symbols.size(); ++i) {
        SchSymbol& s = sch.symbols[i];
        int d = depth_of(s.sheet);
        for (size_t j = 0; j < s.pins.size(); ++j) {
            SchPin& p = s.pins[j];
            p.net = net_for(point(s.sheet, p.pos));
            if (is_power_pin(s, p) && !power_net(s, p).empty()) {
                auto lp = local_power.find(i);
                bool local = s.power && lp != local_power.end() && lp->second;
                offer(p.net, {local ? kLocalPower : kGlobalPower, d,
                              local ? sch.sheets[s.sheet].path + power_net(s, p) : power_net(s, p)});
            }
            if (s.power) continue; // power symbols and flags aren't parts
            sch.nets[p.net].nodes.push_back({static_cast<int>(i), static_cast<int>(j)});
            ++pin_count[p.net];
        }
    }

    // Nets named only by their pins: "Net-(R1-Pad1)", or "unconnected-(...)"
    // for a pin with nothing else attached.
    for (size_t n = 0; n < sch.nets.size(); ++n) {
        SchNet& net = sch.nets[n];
        if (best[n].priority == 0) {
            bool lonely = pin_count[n] == 1;
            for (const SchNode& node : net.nodes) {
                const SchSymbol& s = sch.symbols[node.symbol];
                const SchPin& p = s.pins[node.pin];
                std::string name;
                if (lonely) {
                    name = "unconnected-(" + s.ref + "-" + (has_real_name(p) ? p.name + "-" : "") + "Pad" + p.number + ")";
                } else {
                    name = "Net-(" + s.ref + "-" + pin_label(s, p) + ")";
                }
                offer(static_cast<int>(n), {kPin, 0, name, has_real_name(p) ? 0 : 1});
            }
        }
        net.name = best[n].name;
    }
}

} // namespace

Schematic load_schematic(const std::string& root_file, const FileReader& read) {
    Schematic sch;
    Loader loader(read, sch);

    // KiCad 10 projects can have several top-level sheets, listed in the
    // .kicad_pro file. Older projects have just the root schematic.
    std::vector<std::pair<std::string, std::string>> roots; // (file, name)
    std::string pro = root_file.substr(0, root_file.rfind('.')) + ".kicad_pro";
    if (std::optional<std::string> text = read(pro)) {
        try {
            nlohmann::json j = nlohmann::json::parse(*text);
            for (const auto& t : j.at("schematic").at("top_level_sheets"))
                roots.emplace_back(t.value("filename", ""), t.value("name", ""));
        } catch (const std::exception&) {
            roots.clear(); // no list (older KiCad) or unreadable: use the root file
        }
    }
    if (roots.empty()) roots.emplace_back(root_file, "");
    loader.multiple_roots = roots.size() > 1;
    for (const auto& [file, name] : roots) {
        if (file.empty()) continue;
        loader.load_root(file, name);
    }
    connect(sch, loader.local_power_);
    return sch;
}

} // namespace kigit

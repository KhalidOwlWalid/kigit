#include "html.hpp"

#include "viewer_template.hpp"
#include "sch_diff.hpp"
#include "schematic.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <unordered_map>
#include <unordered_set>

namespace kigit {

using nlohmann::json;

namespace {

double r4(double v) { return std::round(v * 1e4) / 1e4; }

json rev_json(const git::Revision& r) {
    return {{"spec", r.spec}, {"short", r.short_hash}, {"subject", r.subject}, {"date", r.date},
            {"local", r.local}, {"path", r.board_rel.empty() ? r.path : r.board_rel}};
}

} // namespace

nlohmann::json report_data(const Board& old_board, const Board& new_board, const Diff& diff,
                           const ReportInfo& info) {
    // Copper layers: the new board's stackup, plus any only the old one had.
    std::vector<Layer> layers = new_board.layers;
    for (const Layer& l : old_board.layers) {
        bool known = std::any_of(layers.begin(), layers.end(),
                                 [&](const Layer& x) { return x.name == l.name; });
        if (!known) layers.push_back(l);
    }
    std::unordered_map<std::string, int> layer_index;
    json jlayers = json::array();
    for (const Layer& l : layers) {
        layer_index[l.name] = static_cast<int>(jlayers.size());
        jlayers.push_back({{"name", l.name}, {"display", l.display}});
    }

    std::unordered_map<std::string, int> net_index;
    json jnets = json::array();
    for (const auto& [name, s] : diff.nets) {
        net_index[name] = static_cast<int>(jnets.size());
        jnets.push_back({{"name", name},
                         {"add", s.added},
                         {"rem", s.removed},
                         {"same", s.same},
                         {"vAdd", s.vias_added},
                         {"vRem", s.vias_removed},
                         {"pAdd", s.pads_added},
                         {"pRem", s.pads_removed},
                         {"moved", s.moved},
                         {"changed", s.changed},
                         {"lenOld", r4(s.length_old)},
                         {"lenNew", r4(s.length_new)}});
    }

    auto layer_ids = [&](const Item& it) {
        json ids = json::array();
        for (const auto& l : it.layers) {
            auto f = layer_index.find(l);
            if (f != layer_index.end()) ids.push_back(f->second);
        }
        return ids;
    };

    // Footprint changes, and which one each pad belongs to (for highlighting).
    std::unordered_map<std::string, int> fp_index; // footprint ID (or ref) -> index in jfootprints
    json jfootprints = json::array();
    for (const FootprintDiff& fd : diff.footprints) {
        const Footprint* f = fd.new_fp ? fd.new_fp : fd.old_fp;
        int idx = static_cast<int>(jfootprints.size());
        for (const Footprint* side : {fd.old_fp, fd.new_fp})
            if (side) fp_index[side->id.empty() ? "ref:" + side->ref : side->id] = idx;
        json fields = json::array();
        for (const auto& [k, b, a] : fd.fields) fields.push_back({k, b, a});
        jfootprints.push_back({{"ref", fd.ref()},
                               {"lib", f->lib},
                               {"st", static_cast<int>(fd.status)},
                               {"moved", fd.moved},
                               {"pads", fd.pads_changed},
                               {"gAdd", fd.graphics_added},
                               {"gRem", fd.graphics_removed},
                               {"fields", fields}});
    }
    json jzone_changes = json::array();
    for (const ZoneDiff& zd : diff.zone_changes) {
        const ZoneInfo* z = zd.new_zone ? zd.new_zone : zd.old_zone;
        static const char* kinds[] = {"added", "removed", "outline", "refilled"};
        jzone_changes.push_back({{"net", z->net}, {"name", z->name}, {"layers", z->layers}, {"kind", kinds[zd.kind]}});
    }

    json jitems = json::array();
    for (const DiffItem& di : diff.items) {
        const Item& it = *di.item;
        json j = {{"s", static_cast<int>(di.status)}, {"n", net_index[it.net]}, {"l", layer_ids(it)}};
        switch (it.kind) {
        case ItemKind::Track:
            j["k"] = "t";
            j["d"] = "M" + svg_num(it.a.x) + " " + svg_num(it.a.y) + "L" + svg_num(it.b.x) + " " +
                     svg_num(it.b.y);
            j["w"] = r4(it.width);
            j["len"] = r4(it.length());
            break;
        case ItemKind::Arc:
            j["k"] = "a";
            j["d"] = svg_arc_path(it.a, it.mid, it.b);
            j["w"] = r4(it.width);
            j["len"] = r4(it.length());
            break;
        case ItemKind::Via:
            j["k"] = "v";
            j["x"] = r4(it.a.x);
            j["y"] = r4(it.a.y);
            j["w"] = r4(it.width);
            j["dr"] = r4(it.drill);
            break;
        case ItemKind::Pad:
            j["k"] = "p";
            j["x"] = r4(it.a.x);
            j["y"] = r4(it.a.y);
            j["sw"] = r4(it.size.x);
            j["sh"] = r4(it.size.y);
            j["a"] = r4(it.angle);
            j["shape"] = it.shape;
            j["rr"] = r4(it.rratio);
            j["dr"] = r4(it.drill);
            j["ref"] = it.ref;
            j["pin"] = it.pad_number;
            if (auto f = fp_index.find(it.fp_id.empty() ? "ref:" + it.ref : it.fp_id); f != fp_index.end())
                j["fp"] = f->second;
            break;
        case ItemKind::Zone:
            continue;
        }
        jitems.push_back(std::move(j));
    }

    json jzones = json::array();
    for (const Item* z : diff.zones) {
        std::string d;
        for (const auto& poly : z->polygons) {
            for (size_t i = 0; i < poly.size(); ++i)
                d += (i ? "L" : "M") + svg_num(poly[i].x) + " " + svg_num(poly[i].y);
            d += "Z";
        }
        jzones.push_back({{"n", net_index[z->net]}, {"l", layer_ids(*z)}, {"d", d}});
    }

    const Board& outline_src = new_board.outline.empty() ? old_board : new_board;
    json data = {
        {"meta",
         {{"tool", "kigit"},
          {"version", KIGIT_VERSION},
          {"board", info.board_name},
          {"old", rev_json(info.old_rev)},
          {"new", rev_json(info.new_rev)},
          {"warnings", info.warnings}}},
        {"layers", jlayers},
        {"nets", jnets},
        {"outline", outline_src.outline},
        {"items", jitems},
        {"zones", jzones},
        {"footprints", jfootprints},
        {"zone_changes", jzone_changes},
    };

    return data;
}

nlohmann::json schematic_json(const Schematic& sch) {
    json sheets = json::array();
    for (const auto& sh : sch.sheets)
        sheets.push_back({{"name", sh.name}, {"file", sh.file}, {"path", sh.path}, {"parent", sh.parent}});
    json symbols = json::array();
    for (const auto& s : sch.symbols) {
        if (s.power) continue;
        symbols.push_back({{"ref", s.ref},
                           {"value", s.value},
                           {"footprint", s.footprint},
                           {"lib_id", s.lib_id},
                           {"unit", s.unit},
                           {"uuid", s.uuid},
                           {"sheet", s.sheet}});
    }
    json nets = json::array();
    for (const auto& n : sch.nets) {
        if (n.nodes.empty()) continue;
        json nodes = json::array();
        for (const auto& node : n.nodes) {
            const auto& s = sch.symbols[node.symbol];
            const auto& p = s.pins[node.pin];
            nodes.push_back({{"ref", s.ref}, {"pin", p.number}, {"name", p.name}, {"type", p.type}});
        }
        nets.push_back({{"name", n.name}, {"nodes", nodes}});
    }
    int wires = static_cast<int>(sch.wires.size());
    return {{"sheets", sheets},
            {"symbols", symbols},
            {"nets", nets},
            {"wire_count", wires},
            {"warnings", sch.warnings}};
}

nlohmann::json schematic_diff_json(const SchDiff& d) {
    auto status = [](SchStatus s) {
        switch (s) {
        case SchStatus::Same: return "same";
        case SchStatus::Added: return "added";
        case SchStatus::Removed: return "removed";
        case SchStatus::Changed: return "changed";
        }
        return "same";
    };
    auto pin = [](const PinRef& p) { return json{{"ref", p.ref}, {"pin", p.number}, {"name", p.name}}; };

    json symbols = json::array();
    for (const auto& s : d.symbols) {
        if (s.status == SchStatus::Same) continue;
        json fields = json::array(), pins = json::array();
        for (const auto& f : s.fields) fields.push_back({{"field", f.field}, {"before", f.before}, {"after", f.after}});
        for (const auto& p : s.pins) pins.push_back({{"pin", pin(p.pin)}, {"before", p.net_before}, {"after", p.net_after}});
        symbols.push_back({{"status", status(s.status)},
                           {"old", s.old_index},
                           {"new", s.new_index},
                           {"ref_before", s.ref_before},
                           {"ref_after", s.ref_after},
                           {"electrical", s.electrical()},
                           {"fields_only", s.fields_only()},
                           {"moved", s.moved},
                           {"fields", fields},
                           {"pins", pins}});
    }
    json nets = json::array();
    for (const auto& n : d.nets) {
        if (n.status == SchStatus::Same && !n.cosmetic_only()) continue;
        json joined = json::array(), left = json::array();
        for (const auto& p : n.joined) joined.push_back(pin(p));
        for (const auto& p : n.left) left.push_back(pin(p));
        nets.push_back({{"status", status(n.status)},
                        {"old", n.old_index},
                        {"new", n.new_index},
                        {"name_before", n.name_before},
                        {"name_after", n.name_after},
                        {"joined", joined},
                        {"left", left},
                        {"wires_added", n.wires_added},
                        {"wires_removed", n.wires_removed},
                        {"labels_added", n.labels_added},
                        {"labels_removed", n.labels_removed},
                        {"merged_into", n.merged_into},
                        {"electrical", n.electrical()},
                        {"cosmetic_only", n.cosmetic_only()}});
    }
    json wires_new = json::array(), wires_old = json::array();
    for (auto s : d.wires_new) wires_new.push_back(status(s));
    for (auto s : d.wires_old) wires_old.push_back(status(s));
    return {{"symbols", symbols}, {"nets", nets}, {"wires_new", wires_new}, {"wires_old", wires_old}};
}

namespace {

// Status codes shared with the viewer (sch.js).
enum ViewStatus { kSame = 0, kAdded = 1, kRemoved = 2, kChanged = 3, kFieldsOnly = 4, kMovedOnly = 5, kGhost = 6 };

double r4s(double v) { return std::round(v * 1e4) / 1e4; }

json text_json(const SchText& t) {
    return json::array({t.text, r4s(t.at.x), r4s(t.at.y), t.angle, r4s(t.size), t.h, t.v});
}

json def_json(const SymbolDef& d) {
    json g = json::array(), p = json::array();
    for (const auto& x : d.graphics) g.push_back(json::array({x.d, x.fill, r4s(x.width)}));
    for (const auto& x : d.pins)
        p.push_back(json::array({r4s(x.at.x), r4s(x.at.y), x.angle, r4s(x.length), x.number, x.name,
                                 r4s(x.number_size), r4s(x.name_size), x.hidden ? 1 : 0}));
    return {{"g", g}, {"p", p}, {"off", r4s(d.name_offset)}, {"hn", d.hide_names}, {"hu", d.hide_numbers}};
}

std::string pos_key(const Schematic& s, int sheet, Point p) {
    return s.sheets[sheet].uuid_path + "|" + std::to_string(std::llround(p.x * 1e4)) + "," +
           std::to_string(std::llround(p.y * 1e4));
}

} // namespace

nlohmann::json schematic_view_json(const Schematic& a, const Schematic& b, const SchDiff& d) {
    // Old sheet instance -> new one (same KiCad instance path).
    std::unordered_map<std::string, int> new_sheet_by_path;
    for (size_t i = 0; i < b.sheets.size(); ++i) new_sheet_by_path[b.sheets[i].uuid_path] = static_cast<int>(i);
    std::vector<int> old_sheet(a.sheets.size(), -1);
    for (size_t i = 0; i < a.sheets.size(); ++i) {
        auto f = new_sheet_by_path.find(a.sheets[i].uuid_path);
        if (f != new_sheet_by_path.end()) old_sheet[i] = f->second;
    }

    // Net and part diff indexes, as the viewer's highlight keys.
    std::vector<int> net_new(b.nets.size(), -1), net_old(a.nets.size(), -1);
    for (size_t i = 0; i < d.nets.size(); ++i) {
        if (d.nets[i].new_index >= 0) net_new[d.nets[i].new_index] = static_cast<int>(i);
        if (d.nets[i].old_index >= 0) net_old[d.nets[i].old_index] = static_cast<int>(i);
    }
    std::vector<int> part_new(b.symbols.size(), -1), part_old(a.symbols.size(), -1);
    for (size_t i = 0; i < d.symbols.size(); ++i) {
        if (d.symbols[i].new_index >= 0) part_new[d.symbols[i].new_index] = static_cast<int>(i);
        if (d.symbols[i].old_index >= 0) part_old[d.symbols[i].old_index] = static_cast<int>(i);
    }

    struct SheetOut {
        json wires = json::array(), junctions = json::array(), nc = json::array(), labels = json::array(),
             symbols = json::array(), boxes = json::array(), texts = json::array(), drawings = json::array();
        int changes = 0;
    };
    std::vector<SheetOut> out(b.sheets.size());
    auto note = [&](int sheet, int st) {
        if (st != kSame && st != kMovedOnly && st != kGhost) ++out[sheet].changes;
    };

    // Symbol drawings, shared by both revisions unless the library symbol changed.
    json defs = json::object();
    for (const auto& [key, def] : b.defs) defs[key] = def_json(def);
    auto old_def_key = [&](const std::string& key) {
        auto f = a.defs.find(key);
        if (f == a.defs.end()) return key;
        json j = def_json(f->second);
        if (defs.contains(key) && defs[key] == j) return key;
        defs["old:" + key] = j;
        return "old:" + key;
    };

    // Wires.
    for (size_t i = 0; i < b.wires.size(); ++i) {
        const auto& w = b.wires[i];
        int st = d.wires_new[i] == SchStatus::Added ? kAdded : kSame;
        out[w.sheet].wires.push_back({r4s(w.a.x), r4s(w.a.y), r4s(w.b.x), r4s(w.b.y), st, w.net >= 0 ? net_new[w.net] : -1});
        note(w.sheet, st);
    }
    for (size_t i = 0; i < a.wires.size(); ++i) {
        const auto& w = a.wires[i];
        if (d.wires_old[i] != SchStatus::Removed || old_sheet[w.sheet] < 0) continue;
        int sh = old_sheet[w.sheet];
        out[sh].wires.push_back({r4s(w.a.x), r4s(w.a.y), r4s(w.b.x), r4s(w.b.y), kRemoved, w.net >= 0 ? net_old[w.net] : -1});
        note(sh, kRemoved);
    }

    // Junctions and no-connect flags, matched by position.
    {
        std::unordered_map<std::string, int> in_old, in_new;
        for (const auto& [sh, p] : a.junctions) ++in_old[pos_key(a, sh, p)];
        for (const auto& [sh, p] : b.junctions) ++in_new[pos_key(b, sh, p)];
        for (const auto& [sh, p] : b.junctions) {
            auto f = in_old.find(pos_key(b, sh, p));
            int st = (f != in_old.end() && f->second-- > 0) ? kSame : kAdded;
            out[sh].junctions.push_back({r4s(p.x), r4s(p.y), st});
        }
        for (const auto& [sh, p] : a.junctions) {
            auto f = in_new.find(pos_key(a, sh, p));
            if (f != in_new.end() && f->second-- > 0) continue;
            if (old_sheet[sh] >= 0) out[old_sheet[sh]].junctions.push_back({r4s(p.x), r4s(p.y), kRemoved});
        }
        for (const auto& [sh, p] : b.no_connects) out[sh].nc.push_back({r4s(p.x), r4s(p.y)});
    }

    // Labels and sheet pins.
    auto label_json = [&](const SchLabel& l, int st, int net) {
        return json::array({static_cast<int>(l.kind), l.text, r4s(l.at.x), r4s(l.at.y), l.angle, r4s(l.size), l.shape, st, net});
    };
    for (size_t i = 0; i < b.labels.size(); ++i) {
        const auto& l = b.labels[i];
        int st = d.labels_new[i] == SchStatus::Added ? kAdded : kSame;
        out[l.sheet].labels.push_back(label_json(l, st, l.net >= 0 ? net_new[l.net] : -1));
        note(l.sheet, st);
    }
    for (size_t i = 0; i < a.labels.size(); ++i) {
        const auto& l = a.labels[i];
        if (d.labels_old[i] != SchStatus::Removed || old_sheet[l.sheet] < 0) continue;
        out[old_sheet[l.sheet]].labels.push_back(label_json(l, kRemoved, l.net >= 0 ? net_old[l.net] : -1));
        note(old_sheet[l.sheet], kRemoved);
    }

    // Parts. Power symbols aren't in the part diff; match them by position.
    auto symbol_json = [&](const Schematic& s, const SchSymbol& sym, const std::string& def, int st, int part,
                           const std::vector<int>& net_map) {
        json fields = json::array(), pins = json::array();
        for (const auto& f : sym.visible_fields) fields.push_back(text_json(f));
        for (const auto& p : sym.pins) pins.push_back(p.net >= 0 ? net_map[p.net] : -1);
        (void)s;
        return json{{"d", def},          {"x", r4s(sym.at.x)}, {"y", r4s(sym.at.y)}, {"a", sym.angle},
                    {"mx", sym.mirror_x}, {"my", sym.mirror_y}, {"st", st},          {"i", part},
                    {"f", fields},       {"pn", pins},         {"pw", sym.power}};
    };
    auto power_key = [](const Schematic& s, const SchSymbol& sym) {
        return pos_key(s, sym.sheet, sym.at) + "|" + sym.lib_id + "|" + sym.value + "|" + std::to_string(sym.angle) +
               (sym.mirror_x ? "x" : "") + (sym.mirror_y ? "y" : "");
    };
    std::unordered_map<std::string, int> power_old, power_new;
    for (const auto& sym : a.symbols)
        if (sym.power) ++power_old[power_key(a, sym)];
    for (const auto& sym : b.symbols)
        if (sym.power) ++power_new[power_key(b, sym)];

    for (size_t i = 0; i < b.symbols.size(); ++i) {
        const auto& sym = b.symbols[i];
        if (sym.def.empty()) continue;
        int st = kSame, part = part_new[i];
        if (sym.power) {
            auto f = power_old.find(power_key(b, sym));
            st = (f != power_old.end() && f->second-- > 0) ? kSame : kAdded;
        } else if (part >= 0) {
            const SymbolDiff& sd = d.symbols[part];
            st = sd.status == SchStatus::Added   ? kAdded
                 : sd.status == SchStatus::Same  ? kSame
                 : sd.electrical()               ? kChanged
                 : sd.fields_only()              ? kFieldsOnly
                                                 : kMovedOnly;
            // Ghost of a moved part at its old place (hidden unless asked for).
            if (sd.moved && sd.old_index >= 0) {
                const SchSymbol& os = a.symbols[sd.old_index];
                if (old_sheet[os.sheet] >= 0 && !os.def.empty())
                    out[old_sheet[os.sheet]].symbols.push_back(symbol_json(a, os, old_def_key(os.def), kGhost, part, net_old));
            }
        }
        out[sym.sheet].symbols.push_back(symbol_json(b, sym, sym.def, st, part, net_new));
        note(sym.sheet, st);
    }
    for (size_t i = 0; i < a.symbols.size(); ++i) {
        const auto& sym = a.symbols[i];
        if (sym.def.empty() || old_sheet[sym.sheet] < 0) continue;
        bool removed = false;
        if (sym.power) {
            auto f = power_new.find(power_key(a, sym));
            removed = !(f != power_new.end() && f->second-- > 0);
        } else {
            removed = part_old[i] >= 0 && d.symbols[part_old[i]].status == SchStatus::Removed;
        }
        if (!removed) continue;
        out[old_sheet[sym.sheet]].symbols.push_back(symbol_json(a, sym, old_def_key(sym.def), kRemoved, part_old[i], net_old));
        note(old_sheet[sym.sheet], kRemoved);
    }

    // Sheet boxes, notes and drawings (new revision).
    std::unordered_set<std::string> old_paths;
    for (const auto& sh : a.sheets) old_paths.insert(sh.uuid_path);
    for (const auto& box : b.sheet_boxes) {
        int st = old_paths.count(b.sheets[box.child].uuid_path) ? kSame : kAdded;
        out[box.sheet].boxes.push_back({{"x", r4s(box.at.x)}, {"y", r4s(box.at.y)}, {"w", r4s(box.size.x)},
                                        {"h", r4s(box.size.y)}, {"c", box.child}, {"st", st},
                                        {"name", text_json(box.name)}, {"file", text_json(box.file)}});
        note(box.sheet, st);
    }
    for (const auto& [sh, t] : b.texts)
        if (!t.hidden) out[sh].texts.push_back(text_json(t));
    for (const auto& [sh, dpath] : b.drawings) out[sh].drawings.push_back(dpath);

    json sheets = json::array();
    for (size_t i = 0; i < b.sheets.size(); ++i) {
        const auto& sh = b.sheets[i];
        SheetOut& o = out[i];
        sheets.push_back({{"name", sh.name},       {"file", sh.file},           {"path", sh.path},
                          {"parent", sh.parent},   {"w", sh.paper.x},           {"h", sh.paper.y},
                          {"changes", o.changes},  {"wires", o.wires},          {"junctions", o.junctions},
                          {"nc", o.nc},            {"labels", o.labels},        {"symbols", o.symbols},
                          {"boxes", o.boxes},      {"texts", o.texts},          {"drawings", o.drawings}});
    }

    // Nets and parts, for tooltips.
    auto pins_json = [](const std::vector<PinRef>& v) {
        json j = json::array();
        for (const auto& p : v) j.push_back(p.text());
        return j;
    };
    json nets = json::array();
    for (const auto& n : d.nets) {
        int st = n.status == SchStatus::Added ? kAdded : n.status == SchStatus::Removed ? kRemoved
                 : n.status == SchStatus::Changed ? kChanged : kSame;
        nets.push_back({{"name", n.status == SchStatus::Removed ? n.name_before : n.name_after},
                        {"before", n.name_before},
                        {"st", st},
                        {"el", n.electrical()},
                        {"joined", pins_json(n.joined)},
                        {"left", pins_json(n.left)},
                        {"wa", n.wires_added},
                        {"wr", n.wires_removed},
                        {"la", n.labels_added},
                        {"lr", n.labels_removed},
                        {"merged", n.merged_into}});
    }
    json parts = json::array();
    for (const auto& p : d.symbols) {
        const SchSymbol* sym = p.new_index >= 0 ? &b.symbols[p.new_index] : &a.symbols[p.old_index];
        json fields = json::array(), pins = json::array();
        for (const auto& f : p.fields) fields.push_back({f.field, f.before, f.after});
        for (const auto& m : p.pins) pins.push_back({m.pin.text(), m.net_before, m.net_after});
        int st = p.status == SchStatus::Added ? kAdded : p.status == SchStatus::Removed ? kRemoved
                 : p.status == SchStatus::Same ? kSame : p.electrical() ? kChanged : p.fields_only() ? kFieldsOnly : kMovedOnly;
        parts.push_back({{"ref", p.new_index >= 0 ? p.ref_after : p.ref_before},
                         {"before", p.ref_before},
                         {"value", sym->value},
                         {"lib", sym->lib_id},
                         {"fp", sym->footprint},
                         {"st", st},
                         {"fields", fields},
                         {"pins", pins},
                         {"moved", p.moved}});
    }
    return {{"sheets", sheets}, {"defs", defs}, {"nets", nets}, {"parts", parts}};
}

std::string render_html(const nlohmann::json& data) {
    // Keep the JSON from closing the <script> tag early.
    std::string payload = data.dump();
    std::string safe;
    safe.reserve(payload.size());
    for (size_t i = 0; i < payload.size(); ++i) {
        if (payload[i] == '<' && i + 1 < payload.size() && payload[i + 1] == '/') safe += "<\\";
        else safe += payload[i];
    }

    std::string page(viewer_template());
    const std::string marker = "/*KIGIT_DATA*/null";
    size_t at = page.find(marker);
    if (at == std::string::npos) throw std::runtime_error("viewer template has no data marker");
    page.replace(at, marker.size(), safe);
    return page;
}

} // namespace kigit

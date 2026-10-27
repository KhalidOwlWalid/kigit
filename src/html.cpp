#include "html.hpp"

#include "viewer_template.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <unordered_map>

namespace kigit {

using nlohmann::json;

namespace {

double r4(double v) { return std::round(v * 1e4) / 1e4; }

json rev_json(const git::Revision& r) {
    return {{"spec", r.spec}, {"short", r.short_hash}, {"subject", r.subject}, {"date", r.date},
            {"local", r.local}, {"path", r.board_rel.empty() ? r.path : r.board_rel}};
}

} // namespace

std::string render_html(const Board& old_board, const Board& new_board, const Diff& diff,
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
    };

    // Keep the JSON from closing the <script> tag early.
    std::string payload = data.dump();
    std::string safe;
    safe.reserve(payload.size());
    for (size_t i = 0; i < payload.size(); ++i) {
        if (payload[i] == '<' && i + 1 < payload.size() && payload[i + 1] == '/') safe += "<\\";
        else safe += payload[i];
    }

    std::string page = kViewerTemplate;
    const std::string marker = "/*KIGIT_DATA*/null";
    size_t at = page.find(marker);
    if (at == std::string::npos) throw std::runtime_error("viewer template has no data marker");
    page.replace(at, marker.size(), safe);
    return page;
}

} // namespace kigit

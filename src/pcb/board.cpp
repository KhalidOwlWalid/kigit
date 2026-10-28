#include "pcb/board.hpp"

#include "utils/sexpr.hpp"

#include <algorithm>
#include <charconv>
#include <cmath>
#include <cstdio>
#include <stdexcept>
#include <unordered_map>

namespace kigit {

using sexpr::Node;

namespace {

constexpr double kPi = 3.14159265358979323846;

std::string fnum(double v) {
    char buf[32];
    int n = std::snprintf(buf, sizeof buf, "%.4f", v);
    std::string s(buf, n);
    while (!s.empty() && s.back() == '0') s.pop_back();
    if (!s.empty() && s.back() == '.') s.pop_back();
    if (s == "-0") s = "0";
    return s;
}

std::string pt(Point p) { return fnum(p.x) + " " + fnum(p.y); }

Point read_xy(const Node* n) {
    return n ? Point{n->num(0), n->num(1)} : Point{};
}

bool is_integer(std::string_view s) {
    int v;
    auto [p, ec] = std::from_chars(s.data(), s.data() + s.size(), v);
    return ec == std::errc{} && p == s.data() + s.size();
}

// Rotates a footprint-local point by the footprint angle (KiCad: degrees,
// counter-clockwise on screen with y pointing down).
Point rotate(Point p, double deg) {
    if (deg == 0) return p;
    double r = deg * kPi / 180.0, c = std::cos(r), s = std::sin(r);
    return {p.x * c + p.y * s, -p.x * s + p.y * c};
}

// SVG path for an arc through three points.
std::string arc_path(Point a, Point m, Point b, double* length = nullptr) {
    Point c;
    if (!circle_center(a, m, b, c)) {
        if (length) *length = std::hypot(b.x - a.x, b.y - a.y);
        return "M" + pt(a) + "L" + pt(b);
    }
    double r = std::hypot(a.x - c.x, a.y - c.y);
    double cross = (m.x - a.x) * (b.y - m.y) - (m.y - a.y) * (b.x - m.x);
    bool sweep = cross > 0; // clockwise on screen
    double ta = std::atan2(a.y - c.y, a.x - c.x), tb = std::atan2(b.y - c.y, b.x - c.x);
    double span = sweep ? tb - ta : ta - tb;
    while (span < 0) span += 2 * kPi;
    while (span >= 2 * kPi) span -= 2 * kPi;
    if (length) *length = r * span;
    return "M" + pt(a) + "A" + fnum(r) + " " + fnum(r) + " 0 " + (span > kPi ? "1" : "0") +
           " " + (sweep ? "1" : "0") + " " + pt(b);
}

struct Ctx {
    std::vector<std::string> net_table; // old format: net number -> name
    std::vector<std::string> copper;    // copper layer names in order
};

// KiCad's ID for an item: (uuid ...) in KiCad 8+, (tstamp ...) before.
std::string id_of(const Node& n) {
    if (const Node* u = n.child("uuid")) return sexpr::unescape(u->arg(0));
    if (const Node* t = n.child("tstamp")) return sexpr::unescape(t->arg(0));
    return {};
}

std::string net_of(const Node& item, const Ctx& ctx) {
    if (const Node* nn = item.child("net_name")) return sexpr::unescape(nn->arg(0)); // old zones
    const Node* n = item.child("net");
    if (!n || n->arg_count() == 0) return {};
    if (n->arg_count() >= 2) return sexpr::unescape(n->arg(1)); // (net 3 "GND")
    const Node* a = n->arg_node(0);
    if (!a->quoted && is_integer(a->atom) && !ctx.net_table.empty()) {
        size_t id = std::stoul(std::string(a->atom));
        return id < ctx.net_table.size() ? ctx.net_table[id] : std::string{};
    }
    return sexpr::unescape(a->atom);
}

// Expands a layer list such as ("*.Cu" "F.Mask") to copper layer names.
std::vector<std::string> copper_layers(const Node* layers, const Ctx& ctx) {
    std::vector<std::string> out;
    if (!layers) return out;
    auto add = [&](const std::string& l) {
        if (std::find(ctx.copper.begin(), ctx.copper.end(), l) != ctx.copper.end() &&
            std::find(out.begin(), out.end(), l) == out.end())
            out.push_back(l);
    };
    for (size_t i = 0; i < layers->arg_count(); ++i) {
        std::string l(layers->arg(i));
        if (l == "*.Cu") {
            for (const auto& c : ctx.copper) add(c);
        } else if (l == "F&B.Cu") {
            add("F.Cu");
            add("B.Cu");
        } else {
            add(l);
        }
    }
    return out;
}

// A via lists its two end layers; it exists on every copper layer between.
std::vector<std::string> via_span(const Node* layers, const Ctx& ctx) {
    std::vector<std::string> ends = copper_layers(layers, ctx);
    if (ends.size() < 2) return ends;
    auto ia = std::find(ctx.copper.begin(), ctx.copper.end(), ends.front()) - ctx.copper.begin();
    auto ib = std::find(ctx.copper.begin(), ctx.copper.end(), ends.back()) - ctx.copper.begin();
    if (ia > ib) std::swap(ia, ib);
    return {ctx.copper.begin() + ia, ctx.copper.begin() + ib + 1};
}

void read_outline(const Node& n, std::vector<std::string>& out) {
    const Node* layer = n.child("layer");
    if (!layer || layer->arg(0) != "Edge.Cuts") return;
    std::string_view kind = n.name();
    if (kind == "gr_line") {
        out.push_back("M" + pt(read_xy(n.child("start"))) + "L" + pt(read_xy(n.child("end"))));
    } else if (kind == "gr_rect") {
        Point a = read_xy(n.child("start")), b = read_xy(n.child("end"));
        out.push_back("M" + pt(a) + "L" + pt({b.x, a.y}) + "L" + pt(b) + "L" + pt({a.x, b.y}) + "Z");
    } else if (kind == "gr_arc") {
        if (n.child("mid")) {
            out.push_back(arc_path(read_xy(n.child("start")), read_xy(n.child("mid")), read_xy(n.child("end"))));
        } else if (const Node* angle = n.child("angle")) {
            // KiCad 5: (start) is the centre, (end) the arc's first point, and
            // (angle) how far it sweeps.
            Point c = read_xy(n.child("start")), p0 = read_xy(n.child("end"));
            double a = angle->num(0);
            auto around = [&](double deg) {
                Point r = rotate({p0.x - c.x, p0.y - c.y}, -deg);
                return Point{c.x + r.x, c.y + r.y};
            };
            out.push_back(arc_path(p0, around(a / 2), around(a)));
        }
    } else if (kind == "gr_circle") {
        Point c = read_xy(n.child("center")), e = read_xy(n.child("end"));
        double r = std::hypot(e.x - c.x, e.y - c.y);
        std::string rs = fnum(r) + " " + fnum(r) + " 0 1 1 ";
        out.push_back("M" + pt({c.x - r, c.y}) + "A" + rs + pt({c.x + r, c.y}) + "A" + rs +
                      pt({c.x - r, c.y}) + "Z");
    } else if (kind == "gr_poly") {
        std::string d;
        if (const Node* pts = n.child("pts"))
            pts->each("xy", [&](const Node& xy) { d += (d.empty() ? "M" : "L") + pt(read_xy(&xy)); });
        if (!d.empty()) out.push_back(d + "Z");
    }
}

bool is_fp_graphic(std::string_view k) {
    return k == "fp_line" || k == "fp_arc" || k == "fp_circle" || k == "fp_rect" || k == "fp_poly" ||
           k == "fp_curve" || k == "fp_text" || k == "fp_text_box";
}

bool is_silk_layer(std::string_view l) { return l == "F.SilkS" || l == "B.SilkS"; }

// Text effects: size, thickness, justification, mirroring, visibility.
void read_text_effects(const Node& n, SilkItem& t, bool& hidden) {
    hidden = false;
    for (size_t i = 1; i < n.children.size(); ++i) {
        const Node& c = n.children[i];
        if (!c.is_list && !c.quoted && c.atom == "hide") hidden = true;
        if (c.is_list && c.name() == "hide" && (c.arg_count() == 0 || c.arg(0) == "yes")) hidden = true;
    }
    const Node* e = n.child("effects");
    if (!e) return;
    if (const Node* f = e->child("font")) {
        if (const Node* sz = f->child("size")) t.size = sz->num(0, 1);
        if (const Node* th = f->child("thickness")) t.thickness = th->num(0, 0.15);
    }
    if (const Node* j = e->child("justify"))
        for (size_t i = 0; i < j->arg_count(); ++i) {
            std::string_view a = j->arg(i);
            if (a == "left") t.h = -1;
            else if (a == "right") t.h = 1;
            else if (a == "top") t.v = -1;
            else if (a == "bottom") t.v = 1;
            else if (a == "mirror") t.mirror = true;
        }
    for (size_t i = 1; i < e->children.size(); ++i) {
        const Node& c = e->children[i];
        if ((!c.is_list && c.atom == "hide") || (c.is_list && c.name() == "hide" && c.arg(0) != "no")) hidden = true;
    }
}

// A silkscreen shape as SVG path data, with `to_board` mapping its points
// (identity for board items, the footprint's placement for footprint items).
template <typename F>
std::string silk_path(const Node& g, F to_board, bool& fill) {
    auto P = [&](const Node* n) { return to_board(read_xy(n)); };
    std::string_view k = g.name();
    if (const Node* f = g.child("fill")) {
        std::string_view t = f->child("type") ? f->child("type")->arg(0) : f->arg(0);
        fill = t == "solid" || t == "yes" || t == "outline";
    }
    if (k.ends_with("_line")) return "M" + pt(P(g.child("start"))) + "L" + pt(P(g.child("end")));
    if (k.ends_with("_arc")) {
        if (g.child("mid")) return arc_path(P(g.child("start")), P(g.child("mid")), P(g.child("end")));
        return {};
    }
    if (k.ends_with("_rect")) {
        Point a = read_xy(g.child("start")), b = read_xy(g.child("end"));
        return "M" + pt(to_board(a)) + "L" + pt(to_board({b.x, a.y})) + "L" + pt(to_board(b)) + "L" +
               pt(to_board({a.x, b.y})) + "Z";
    }
    if (k.ends_with("_circle")) {
        Point c = read_xy(g.child("center")), e = read_xy(g.child("end"));
        double r = std::hypot(e.x - c.x, e.y - c.y);
        Point cc = to_board(c);
        std::string rs = fnum(r) + " " + fnum(r) + " 0 1 1 ";
        return "M" + pt({cc.x - r, cc.y}) + "A" + rs + pt({cc.x + r, cc.y}) + "A" + rs + pt({cc.x - r, cc.y}) + "Z";
    }
    if (k.ends_with("_poly")) {
        std::string d;
        if (const Node* pts = g.child("pts"))
            for (const Node& p : pts->children) {
                if (!p.is_list) continue;
                if (p.name() == "xy") d += (d.empty() ? "M" : "L") + pt(P(&p));
                else if (p.name() == "arc") d += (d.empty() ? "M" : "L") + pt(P(p.child("end")));
            }
        return d.empty() ? d : d + "Z";
    }
    return {};
}

double stroke_width(const Node& g) {
    if (const Node* st = g.child("stroke"))
        if (const Node* w = st->child("width")) return w->num(0);
    if (const Node* w = g.child("width")) return w->num(0);
    return 0.12;
}

void read_footprint(const Node& fp, const Ctx& ctx, std::vector<Item>& items, std::vector<Footprint>& footprints,
                    std::vector<SilkItem>* silk) {
    const Node* at = fp.child("at");
    Point origin = read_xy(at);
    double fp_angle = at ? at->num(2) : 0;

    std::string ref;
    std::string fp_id = id_of(fp);
    fp.each("property", [&](const Node& p) {
        if (p.arg(0) == "Reference") ref = sexpr::unescape(p.arg(1));
    });
    if (ref.empty())
        fp.each("fp_text", [&](const Node& t) {
            if (t.arg(0) == "reference") ref = sexpr::unescape(t.arg(1));
        });

    // The footprint as a whole.
    Footprint info;
    info.id = fp_id;
    info.ref = ref;
    info.lib = sexpr::unescape(fp.arg(0));
    info.at = origin;
    info.angle = fp_angle;
    if (const Node* l = fp.child("layer")) info.side = sexpr::unescape(l->arg(0));
    // Pads' and texts' (at x y angle): x, y are in the footprint's frame but the
    // angle includes the footprint's rotation. Make it relative, so rotating a
    // footprint doesn't look like editing it.
    auto with_local_at = [&](const Node& c, std::vector<std::string_view> skip) {
        skip.push_back("at");
        std::string out = sexpr::canonical(c, skip);
        if (const Node* a = c.child("at")) {
            double rel = std::fmod(std::fmod(a->num(2) - fp_angle, 360.0) + 360.0, 360.0);
            char buf[96];
            std::snprintf(buf, sizeof buf, " (at %.6g %.6g %.6g)", a->num(0), a->num(1), std::round(rel * 1e4) / 1e4);
            out += buf;
        }
        return out;
    };
    for (const Node& c : fp.children) {
        if (!c.is_list) continue;
        std::string_view k = c.name();
        if (k == "property") {
            // The value is a field; where and how it's shown is graphics.
            std::string key = sexpr::unescape(c.arg(0));
            if (key != "Reference") info.fields[key] = sexpr::unescape(c.arg(1));
            Node look = c;
            if (look.children.size() > 2) look.children.erase(look.children.begin() + 2);
            info.graphics.push_back(with_local_at(look, {"uuid", "tstamp"}));
        } else if (k == "model") {
            info.fields["3D model"] = sexpr::unescape(c.arg(0));
        } else if (is_fp_graphic(k)) {
            info.graphics.push_back(with_local_at(c, {"uuid", "tstamp"}));
        } else if (k == "pad") {
            // Shape and place in the footprint's frame; the net is electrical,
            // compared elsewhere.
            info.pads.push_back(with_local_at(c, {"uuid", "tstamp", "net", "pinfunction", "pintype"}));
        }
    }
    // Silkscreen (only if asked for), mapped to the board.
    if (silk) {
        auto to_board = [&](Point local) {
            Point r = rotate(local, fp_angle);
            return Point{origin.x + r.x, origin.y + r.y};
        };
        for (const Node& c : fp.children) {
            if (!c.is_list) continue;
            std::string_view k = c.name();
            const Node* layer = c.child("layer");
            if (!layer || !is_silk_layer(layer->arg(0))) continue;
            SilkItem it;
            it.front = layer->arg(0) == "F.SilkS";
            it.owner = fp_id.empty() ? "ref:" + ref : fp_id;
            if (is_fp_graphic(k) && k != "fp_text" && k != "fp_text_box") {
                it.d = silk_path(c, to_board, it.fill);
                if (it.d.empty()) continue;
                it.width = stroke_width(c);
            } else if (k == "fp_text" || k == "property") {
                bool hidden = false;
                read_text_effects(c, it, hidden);
                if (hidden) continue;
                std::string text = sexpr::unescape(c.arg(1));
                if (k == "property" && c.arg(0) == "Reference") text = ref;
                if (text == "${REFERENCE}") text = ref;
                if (text.empty()) continue;
                it.text = text;
                const Node* a = c.child("at");
                it.at = to_board(read_xy(a));
                it.angle = a ? a->num(2) : 0;
            } else {
                continue;
            }
            it.key = it.owner + "|" + with_local_at(c, {"uuid", "tstamp"});
            silk->push_back(std::move(it));
        }
    }

    std::sort(info.graphics.begin(), info.graphics.end());
    std::sort(info.pads.begin(), info.pads.end());
    footprints.push_back(std::move(info));

    fp.each("pad", [&](const Node& pad) {
        Item it;
        it.kind = ItemKind::Pad;
        it.pad_number = sexpr::unescape(pad.arg(0));
        it.fp_id = fp_id;
        if (!fp_id.empty()) it.id = fp_id + "/" + it.pad_number;
        it.shape = std::string(pad.arg(2));
        it.ref = ref;
        it.net = net_of(pad, ctx);
        it.layers = copper_layers(pad.child("layers"), ctx);
        if (it.layers.empty()) return; // paste/mask-only pad

        const Node* pat = pad.child("at");
        Point local = read_xy(pat);
        Point r = rotate(local, fp_angle);
        it.a = {origin.x + r.x, origin.y + r.y};
        it.angle = pat ? pat->num(2) : 0; // stored as absolute orientation
        it.local = local;
        it.local_angle = std::fmod(std::fmod(it.angle - fp_angle, 360.0) + 360.0, 360.0);
        it.size = read_xy(pad.child("size"));
        if (const Node* rr = pad.child("roundrect_rratio")) it.rratio = rr->num(0);
        if (const Node* d = pad.child("drill")) {
            // (drill 0.8) or (drill oval 1.0 2.0)
            it.drill = d->num(0, d->num(1));
        }
        items.push_back(std::move(it));
    });
}

void read_zone(const Node& z, const Ctx& ctx, std::vector<Item>& items, std::vector<ZoneInfo>& zones) {
    std::string net = net_of(z, ctx);

    ZoneInfo info;
    info.id = id_of(z);
    info.net = net;
    if (const Node* nm = z.child("name")) info.name = sexpr::unescape(nm->arg(0));
    if (const Node* l = z.child("layer")) info.layers = {sexpr::unescape(l->arg(0))};
    if (const Node* ls = z.child("layers"))
        for (size_t i = 0; i < ls->arg_count(); ++i) info.layers.push_back(sexpr::unescape(ls->arg(i)));
    std::string outline, fill;
    z.each("polygon", [&](const Node& p) { outline += sexpr::canonical(p); });
    z.each("filled_polygon", [&](const Node& p) { fill += sexpr::canonical(p); });
    info.outline = std::hash<std::string>{}(outline);
    info.fill = std::hash<std::string>{}(fill);
    zones.push_back(std::move(info));

    // KiCad 5 zones are single-layer and give the layer on the zone itself.
    const Node* zone_layer = z.child("layer");
    std::unordered_map<std::string, size_t> by_layer; // layer -> item index
    z.each("filled_polygon", [&](const Node& fpoly) {
        const Node* layer = fpoly.child("layer");
        if (!layer) layer = zone_layer;
        if (!layer) return;
        std::string lname = sexpr::unescape(layer->arg(0));
        auto [iter, inserted] = by_layer.try_emplace(lname, items.size());
        if (inserted) {
            Item it;
            it.kind = ItemKind::Zone;
            it.net = net;
            it.layers = {lname};
            items.push_back(std::move(it));
        }
        std::vector<Point> poly;
        if (const Node* pts = fpoly.child("pts")) {
            for (const Node& p : pts->children) {
                if (!p.is_list) continue;
                if (p.name() == "xy") {
                    poly.push_back(read_xy(&p));
                } else if (p.name() == "arc") {
                    poly.push_back(read_xy(p.child("start")));
                    poly.push_back(read_xy(p.child("mid")));
                    poly.push_back(read_xy(p.child("end")));
                }
            }
        }
        if (poly.size() >= 3) items[iter->second].polygons.push_back(std::move(poly));
    });
}

} // namespace

bool circle_center(Point a, Point m, Point b, Point& c) {
    double d = 2 * (a.x * (m.y - b.y) + m.x * (b.y - a.y) + b.x * (a.y - m.y));
    if (std::abs(d) < 1e-12) return false;
    double a2 = a.x * a.x + a.y * a.y, m2 = m.x * m.x + m.y * m.y, b2 = b.x * b.x + b.y * b.y;
    c.x = (a2 * (m.y - b.y) + m2 * (b.y - a.y) + b2 * (a.y - m.y)) / d;
    c.y = (a2 * (b.x - m.x) + m2 * (a.x - b.x) + b2 * (m.x - a.x)) / d;
    return true;
}

double Item::length() const {
    if (kind == ItemKind::Track) return std::hypot(b.x - a.x, b.y - a.y);
    if (kind == ItemKind::Arc) {
        double len = 0;
        arc_path(a, mid, b, &len);
        return len;
    }
    return 0;
}

std::string Item::key() const {
    auto q = [](double v) { return std::to_string(std::llround(v * 1e6)); };
    auto qp = [&](Point p) { return q(p.x) + "," + q(p.y); };
    auto before = [](Point p1, Point p2) {
        return std::llround(p1.x * 1e6) < std::llround(p2.x * 1e6) ||
               (std::llround(p1.x * 1e6) == std::llround(p2.x * 1e6) &&
                std::llround(p1.y * 1e6) < std::llround(p2.y * 1e6));
    };
    std::string layer_list;
    for (const auto& l : layers) layer_list += l + ";";

    switch (kind) {
    case ItemKind::Track: {
        Point p1 = a, p2 = b;
        if (before(p2, p1)) std::swap(p1, p2); // direction doesn't matter
        return "T|" + net + "|" + layer_list + "|" + q(width) + "|" + qp(p1) + "|" + qp(p2);
    }
    case ItemKind::Arc: {
        Point p1 = a, p2 = b;
        if (before(p2, p1)) std::swap(p1, p2);
        return "A|" + net + "|" + layer_list + "|" + q(width) + "|" + qp(p1) + "|" + qp(mid) + "|" + qp(p2);
    }
    case ItemKind::Via:
        return "V|" + net + "|" + layer_list + "|" + q(width) + "|" + q(drill) + "|" + qp(a);
    case ItemKind::Pad: {
        double ang = std::fmod(angle, 360.0);
        if (ang < 0) ang += 360.0;
        return "P|" + net + "|" + layer_list + "|" + shape + "|" + qp(a) + "|" + qp(size) + "|" +
               std::to_string(std::llround(ang * 100)) + "|" + q(rratio) + "|" + q(drill);
    }
    case ItemKind::Zone:
        return "Z|" + net + "|" + layer_list + "|" + std::to_string(polygons.size()) + "|" +
               (polygons.empty() ? "" : qp(polygons[0][0]));
    }
    return {};
}

Board load_board(std::string_view text, bool silkscreen) {
    Node root = sexpr::parse(text);
    const Node* pcb = nullptr;
    for (const Node& c : root.children)
        if (c.is_list && c.name() == "kicad_pcb") pcb = &c;
    if (!pcb) throw std::runtime_error("not a KiCad board file (no kicad_pcb)");

    Board board;
    Ctx ctx;
    if (const Node* v = pcb->child("version")) board.version = static_cast<int>(v->num(0));

    if (const Node* layers = pcb->child("layers")) {
        for (const Node& l : layers->children) {
            if (!l.is_list) continue;
            // (0 "F.Cu" signal ["User Name"])
            Layer layer;
            layer.name = sexpr::unescape(l.arg(0));
            std::string_view type = l.arg(1);
            layer.display = l.arg_count() >= 3 ? sexpr::unescape(l.arg(2)) : layer.name;
            layer.copper = type == "signal" || type == "power" || type == "mixed" || type == "jumper" ||
                           layer.name.ends_with(".Cu");
            if (layer.copper) {
                ctx.copper.push_back(layer.name);
                board.layers.push_back(std::move(layer));
            }
        }
    }

    // Old formats keep a net table: (net 1 "GND").
    pcb->each("net", [&](const Node& n) {
        if (n.arg_count() < 2) return;
        size_t id = static_cast<size_t>(n.num(0, -1));
        if (id >= ctx.net_table.size()) ctx.net_table.resize(id + 1);
        ctx.net_table[id] = sexpr::unescape(n.arg(1));
    });

    for (const Node& n : pcb->children) {
        if (!n.is_list) continue;
        std::string_view kind = n.name();
        if (kind == "segment" || kind == "arc") {
            Item it;
            it.kind = kind == "segment" ? ItemKind::Track : ItemKind::Arc;
            it.net = net_of(n, ctx);
            if (const Node* l = n.child("layer")) it.layers = {sexpr::unescape(l->arg(0))};
            it.a = read_xy(n.child("start"));
            it.b = read_xy(n.child("end"));
            it.mid = read_xy(n.child("mid"));
            if (const Node* w = n.child("width")) it.width = w->num(0);
            it.id = id_of(n);
            board.items.push_back(std::move(it));
        } else if (kind == "via") {
            Item it;
            it.kind = ItemKind::Via;
            it.net = net_of(n, ctx);
            it.a = read_xy(n.child("at"));
            if (const Node* s = n.child("size")) it.width = s->num(0);
            if (const Node* d = n.child("drill")) it.drill = d->num(0);
            it.layers = via_span(n.child("layers"), ctx);
            it.id = id_of(n);
            board.items.push_back(std::move(it));
        } else if (kind == "footprint" || kind == "module") {
            read_footprint(n, ctx, board.items, board.footprints, silkscreen ? &board.silk : nullptr);
        } else if (kind == "zone") {
            read_zone(n, ctx, board.items, board.zones);
        } else if (kind.starts_with("gr_")) {
            read_outline(n, board.outline);
            const Node* layer = n.child("layer");
            if (silkscreen && layer && is_silk_layer(layer->arg(0))) {
                SilkItem it;
                it.front = layer->arg(0) == "F.SilkS";
                if (kind == "gr_text") {
                    bool hidden = false;
                    read_text_effects(n, it, hidden);
                    it.text = sexpr::unescape(n.arg(0));
                    while (!it.text.empty() && it.text.back() == '\n') it.text.pop_back();
                    const Node* a = n.child("at");
                    it.at = read_xy(a);
                    it.angle = a ? a->num(2) : 0;
                    if (hidden || it.text.empty()) continue;
                } else {
                    it.d = silk_path(n, [](Point p) { return p; }, it.fill);
                    it.width = stroke_width(n);
                    if (it.d.empty()) continue;
                }
                it.key = "board|" + sexpr::canonical(n);
                board.silk.push_back(std::move(it));
            }
        }
    }
    return board;
}

std::string svg_arc_path(Point a, Point m, Point b) { return arc_path(a, m, b); }
std::string svg_num(double v) { return fnum(v); }

} // namespace kigit

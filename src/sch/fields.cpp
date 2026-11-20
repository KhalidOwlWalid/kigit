#include "sch/fields.hpp"

#include "utils/sexpr.hpp"

#include <algorithm>
#include <cctype>
#include <functional>
#include <map>
#include <set>
#include <stdexcept>
#include <tuple>

namespace kigit {

namespace {

using sexpr::Node;

// KiCad escapes \ and " in strings, and writes newlines as \n.
std::string escape(const std::string& s) {
    std::string out;
    for (char c : s) {
        if (c == '\\' || c == '"') out += '\\', out += c;
        else if (c == '\n') out += "\\n";
        else out += c;
    }
    return out;
}

// An atom's place in the text: the atoms are views into it. Quoted atoms
// include their quotes.
std::pair<size_t, size_t> where(const Node& atom, std::string_view text) {
    size_t at = static_cast<size_t>(atom.atom.data() - text.data()), len = atom.atom.size();
    if (atom.quoted) at -= 1, len += 2;
    return {at, len};
}

// Hidden: (hide yes) / (hide) in KiCad 8+, a bare "hide" in (effects ...) before.
bool hidden(const Node& prop) {
    bool yes = false;
    std::function<void(const Node&)> walk = [&](const Node& n) {
        for (const Node& c : n.children) {
            if (!c.is_list) continue;
            if (c.name() == "hide") yes = yes || c.arg(0) != "no";
            if (c.name() == "effects")
                for (const Node& a : c.children)
                    if (!a.is_list && !a.quoted && a.atom == "hide") yes = true;
            walk(c);
        }
    };
    walk(prop);
    return yes;
}

struct Change {
    size_t at, len;
    std::string with;
};

} // namespace

std::string field_refused(const std::string& name) {
    static const std::set<std::string> kicad = {"Reference", "Value", "Footprint", "Datasheet", "Description",
                                                "Sheetname", "Sheetfile", "Sheet name", "Sheet file",
                                                "Intersheetrefs", "Intersheet References"};
    if (name.empty()) return "a field needs a name";
    if (name.size() > 100) return "the field name is too long";
    for (char c : name)
        if (static_cast<unsigned char>(c) < 0x20) return "the field name can't have line breaks or control characters";
    std::string lower;
    for (char c : name) lower += static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    for (const auto& k : kicad) {
        std::string kl;
        for (char c : k) kl += static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
        if (lower == kl) return "\"" + name + "\" is one of KiCad's own fields: kigit only writes part information";
    }
    if (lower.starts_with("ki_") || lower.starts_with("sim.") || lower.starts_with("sim_"))
        return "\"" + name + "\" is one of KiCad's own fields: kigit only writes part information";
    return "";
}

FieldsResult set_fields(const std::string& text, const std::vector<FieldEdit>& edits) {
    FieldsResult result;
    Node doc = sexpr::parse(text);
    const Node* top = nullptr;
    for (const Node& c : doc.children)
        if (c.is_list && c.name() == "kicad_sch") top = &c;
    if (!top) throw std::runtime_error("not a KiCad schematic");
    const bool crlf = text.find("\r\n") != std::string::npos;

    // The placed symbols (not the library's, which are inside lib_symbols).
    std::map<std::string, const Node*> by_uuid;
    for (const Node& n : top->children)
        if (n.is_list && n.name() == "symbol" && n.child("lib_id"))
            if (const Node* u = n.child("uuid")) by_uuid[sexpr::unescape(u->arg(0))] = &n;

    std::map<const Node*, std::vector<const FieldEdit*>> per_symbol;
    for (const auto& e : edits) {
        if (auto why = field_refused(e.name); !why.empty()) {
            result.problems.push_back(why);
            continue;
        }
        if (!e.rename.empty()) {
            if (auto why = field_refused(e.rename); !why.empty()) {
                result.problems.push_back(why);
                continue;
            }
        } else if (e.value.find_first_of("\r\n") != std::string::npos || e.value.size() > 500) {
            result.problems.push_back(e.name + ": a value must be one line, at most 500 characters");
            continue;
        }
        auto s = by_uuid.find(e.uuid);
        if (s == by_uuid.end()) {
            result.problems.push_back("no symbol " + e.uuid + " in this file");
            continue;
        }
        per_symbol[s->second].push_back(&e);
    }

    std::vector<Change> changes;
    for (const auto& [sym, list] : per_symbol) {
        std::vector<const Node*> props;
        sym->each("property", [&](const Node& p) { props.push_back(&p); });
        if (props.empty()) {
            result.problems.push_back("a symbol without fields: left as it is");
            continue;
        }
        // A hidden field to copy for new ones: Footprint, Datasheet, then any.
        const Node* model = nullptr;
        for (const char* want : {"Footprint", "Datasheet", "Description"})
            for (const Node* p : props)
                if (!model && sexpr::unescape(p->arg(0)) == want && hidden(*p)) model = p;
        for (const Node* p : props)
            if (!model && hidden(*p)) model = p;
        int next_id = -1; // KiCad 6 numbers its fields: (id N)
        for (const Node* p : props)
            if (const Node* id = p->child("id")) next_id = std::max(next_id, static_cast<int>(id->num(0)) + 1);

        // Renaming to a name that's also being set on this part would make two fields of one name.
        std::set<std::string> targets, set_names;
        for (const FieldEdit* e : list) (e->rename.empty() ? set_names : targets).insert(e->rename.empty() ? e->name : e->rename);
        bool clash = false;
        for (const auto& t : targets)
            if (set_names.count(t)) {
                result.problems.push_back("can't rename a field to " + t + " and set " + t + " at once: left as it is");
                clash = true;
            }
        if (clash) continue;

        std::string added;
        std::set<std::string> done; // the same field twice in one go: the last wins
        for (auto it = list.rbegin(); it != list.rend(); ++it) {
            const FieldEdit& e = **it;
            if (!done.insert(e.name).second) continue;
            const Node* existing = nullptr;
            for (const Node* p : props)
                if (sexpr::unescape(p->arg(0)) == e.name) existing = p;
            if (!e.rename.empty()) {
                if (!existing || e.rename == e.name) continue; // nothing to rename on this part
                bool taken = false;
                for (const Node* p : props) taken = taken || sexpr::unescape(p->arg(0)) == e.rename;
                if (taken) {
                    result.problems.push_back("a part already has both " + e.name + " and " + e.rename + ": left as it is");
                    continue;
                }
                auto [at, len] = where(*existing->arg_node(0), text);
                changes.push_back({at, len, "\"" + escape(e.rename) + "\""});
                ++result.changed;
                continue;
            }
            if (existing) {
                if (sexpr::unescape(existing->arg(1)) == e.value) continue;
                const Node* v = existing->arg_node(1);
                if (!v) {
                    result.problems.push_back(e.name + ": a field without a value: left as it is");
                    continue;
                }
                auto [at, len] = where(*v, text);
                changes.push_back({at, len, "\"" + escape(e.value) + "\""});
                ++result.changed;
                continue;
            }
            if (e.value.empty()) continue; // nothing to add
            if (!model) {
                result.problems.push_back(e.name + ": the symbol has no hidden field to copy, so it wasn't added "
                                                   "(add it once in KiCad)");
                continue;
            }
            // The model's text with its name and value swapped (and a fresh id in KiCad 6).
            std::vector<Change> inner;
            auto [nat, nlen] = where(*model->arg_node(0), text);
            inner.push_back({nat, nlen, "\"" + escape(e.name) + "\""});
            if (const Node* v = model->arg_node(1)) {
                auto [vat, vlen] = where(*v, text);
                inner.push_back({vat, vlen, "\"" + escape(e.value) + "\""});
            }
            if (const Node* id = model->child("id"); id && id->arg_node(0)) {
                auto [iat, ilen] = where(*id->arg_node(0), text);
                inner.push_back({iat, ilen, std::to_string(next_id++)});
            }
            std::sort(inner.begin(), inner.end(), [](const Change& a, const Change& b) { return a.at > b.at; });
            std::string copy = text.substr(model->span.begin, model->span.end - model->span.begin);
            for (const auto& c : inner) copy.replace(c.at - model->span.begin, c.len, c.with);
            // Indented like the last property, on its own line after it.
            const Node* last = props.back();
            size_t line = text.rfind('\n', last->span.begin);
            line = line == std::string::npos ? 0 : line + 1;
            std::string indent = text.substr(line, last->span.begin - line);
            if (indent.find_first_not_of(" \t") != std::string::npos) indent = "\t\t";
            added = std::string(crlf ? "\r\n" : "\n") + indent + copy + added;
            ++result.changed;
        }
        if (!added.empty()) changes.push_back({props.back()->span.end, 0, added});
    }
    std::sort(changes.begin(), changes.end(), [](const Change& a, const Change& b) { return a.at > b.at; });
    result.text = text;
    for (const auto& c : changes) result.text.replace(c.at, c.len, c.with);
    return result;
}

std::string same_design(const Schematic& a, const Schematic& b, const std::set<std::string>& edited) {
    if (a.sheets.size() != b.sheets.size()) return "the sheets differ";
    for (size_t i = 0; i < a.sheets.size(); ++i)
        if (a.sheets[i].file != b.sheets[i].file || a.sheets[i].path != b.sheets[i].path) return "the sheets differ";
    if (a.symbols.size() != b.symbols.size()) return "the number of symbols differs";
    for (size_t i = 0; i < a.symbols.size(); ++i) {
        const SchSymbol &x = a.symbols[i], &y = b.symbols[i];
        if (std::tie(x.uuid, x.sheet, x.ref, x.value, x.footprint, x.lib_id, x.unit, x.in_bom, x.on_board, x.dnp, x.power) !=
            std::tie(y.uuid, y.sheet, y.ref, y.value, y.footprint, y.lib_id, y.unit, y.in_bom, y.on_board, y.dnp, y.power))
            return "symbol " + x.ref + " changed";
        auto others = [&](const SchSymbol& s) {
            std::map<std::string, std::string> f;
            for (const auto& [k, v] : s.fields)
                if (!edited.count(k)) f[k] = v;
            return f;
        };
        if (others(x) != others(y)) return "a field of " + x.ref + " that wasn't edited changed";
    }
    auto nets = [](const Schematic& s) {
        std::map<std::string, std::set<std::string>> out;
        for (const auto& n : s.nets) {
            auto& pins = out[n.name];
            for (const auto& node : n.nodes)
                pins.insert(s.symbols[node.symbol].ref + "." + s.symbols[node.symbol].pins[node.pin].number);
        }
        return out;
    };
    if (nets(a) != nets(b)) return "the nets differ";
    // The drawing too: every wire, label, junction and no-connect where it was.
    auto pt = [](const Point& p) { return std::pair(p.x, p.y); };
    if (a.wires.size() != b.wires.size()) return "the wiring differs";
    for (size_t i = 0; i < a.wires.size(); ++i)
        if (a.wires[i].sheet != b.wires[i].sheet || pt(a.wires[i].a) != pt(b.wires[i].a) || pt(a.wires[i].b) != pt(b.wires[i].b))
            return "the wiring differs";
    if (a.labels.size() != b.labels.size()) return "the labels differ";
    for (size_t i = 0; i < a.labels.size(); ++i) {
        const SchLabel &x = a.labels[i], &y = b.labels[i];
        if (x.sheet != y.sheet || x.kind != y.kind || x.text != y.text || pt(x.at) != pt(y.at)) return "the labels differ";
    }
    auto points = [&](const std::vector<std::pair<int, Point>>& v) {
        std::vector<std::tuple<int, double, double>> out;
        for (const auto& [sheet, p] : v) out.emplace_back(sheet, p.x, p.y);
        return out;
    };
    if (points(a.junctions) != points(b.junctions) || points(a.no_connects) != points(b.no_connects))
        return "junctions or no-connects differ";
    for (size_t i = 0; i < a.symbols.size(); ++i) {
        const SchSymbol &x = a.symbols[i], &y = b.symbols[i];
        if (pt(x.at) != pt(y.at) || x.angle != y.angle || x.mirror_x != y.mirror_x || x.mirror_y != y.mirror_y)
            return "symbol " + x.ref + " moved";
    }
    return "";
}

} // namespace kigit

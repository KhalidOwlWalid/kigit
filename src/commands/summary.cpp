#include "commands/summary.hpp"

#include <algorithm>
#include <cstdio>
#include <set>
#include <string>
#include <vector>

namespace kigit::cmd {

namespace {

std::string pad_right(std::string s, size_t n) {
    if (s.size() < n) s.append(n - s.size(), ' ');
    return s;
}

std::string signed_counts(int add, int rem) {
    std::string s;
    if (add) s += "+" + std::to_string(add);
    if (rem) s += (s.empty() ? "-" : " -") + std::to_string(rem);
    return s.empty() ? "." : s;
}

std::string join_list(const std::vector<std::string>& v, size_t limit = 6) {
    std::string out;
    for (size_t i = 0; i < v.size() && i < limit; ++i) out += (i ? ", " : "") + v[i];
    if (v.size() > limit) out += ", +" + std::to_string(v.size() - limit) + " more";
    return out;
}

} // namespace

void print_sch_summary(const SchDiff& d, const Schematic& a, const Schematic& b, bool all) {
    int added = 0, removed = 0, electrical = 0, fields = 0, cosmetic_parts = 0, nets_changed = 0, nets_renamed = 0,
        nets_cosmetic = 0;
    for (const auto& s : d.symbols) {
        if (s.status == SchStatus::Added) ++added;
        else if (s.status == SchStatus::Removed) ++removed;
        else if (s.status == SchStatus::Changed && s.electrical()) ++electrical;
        else if (s.fields_only()) ++fields;
        else if (s.status == SchStatus::Changed) ++cosmetic_parts;
    }
    for (const auto& n : d.nets) {
        if (n.status == SchStatus::Changed && !n.electrical()) ++nets_renamed;
        else if (n.status != SchStatus::Same) ++nets_changed;
        else if (n.cosmetic_only()) ++nets_cosmetic;
    }
    std::printf("\n  schematic: parts +%d -%d, %d changed electrically, %d fields only, %d only moved;"
                " %d nets changed, %d renamed, %d only redrawn\n",
                added, removed, electrical, fields, cosmetic_parts, nets_changed, nets_renamed, nets_cosmetic);

    auto part_line = [&](const SymbolDiff& s) {
        if (s.status == SchStatus::Added || s.status == SchStatus::Removed) {
            const Schematic& sch = s.status == SchStatus::Added ? b : a;
            const SchSymbol& sym = sch.symbols[s.status == SchStatus::Added ? s.new_index : s.old_index];
            std::set<std::string> nets;
            for (const auto& p : sym.pins)
                if (p.net >= 0 && sch.nets[p.net].nodes.size() > 1) nets.insert(sch.nets[p.net].name);
            std::string on = join_list({nets.begin(), nets.end()});
            std::printf("    %s %-6s %-10s %s%s%s\n", s.status == SchStatus::Added ? "+" : "-", sym.ref.c_str(),
                        sym.value.c_str(), sch.sheets[sym.sheet].name.empty() ? "" : ("[" + sch.sheets[sym.sheet].name + "] ").c_str(),
                        on.empty() ? "(not connected)" : "on ", on.c_str());
            return;
        }
        std::vector<std::string> what;
        if (s.ref_before != s.ref_after) what.push_back("renamed from " + s.ref_before);
        for (const auto& f : s.fields)
            what.push_back(f.field + " " + (f.before.empty() ? "(none)" : f.before) + " -> " + (f.after.empty() ? "(none)" : f.after));
        for (const auto& p : s.pins)
            what.push_back(p.pin.text() + ": " + (p.net_before.empty() ? "(none)" : p.net_before) + " -> " +
                           (p.net_after.empty() ? "(none)" : p.net_after));
        if (s.moved) what.push_back("moved");
        std::printf("    ~ %-6s %s\n", s.ref_after.c_str(), join_list(what, 4).c_str());
    };
    // Electrical changes first, then field edits, then (with --stats) moves.
    std::vector<const SymbolDiff*> parts;
    for (const auto& s : d.symbols)
        if (s.status != SchStatus::Same && (all || s.electrical() || s.fields_only())) parts.push_back(&s);
    std::stable_sort(parts.begin(), parts.end(), [](const SymbolDiff* x, const SymbolDiff* y) {
        auto rank = [](const SymbolDiff* s) { return s->electrical() ? 0 : s->fields_only() ? 1 : 2; };
        return rank(x) < rank(y);
    });
    int shown = 0;
    for (const SymbolDiff* sp : parts) {
        const SymbolDiff& s = *sp;
        if (!all && ++shown > 20) {
            std::printf("    ... more parts (use --stats)\n");
            break;
        }
        part_line(s);
    }

    shown = 0;
    for (const auto& n : d.nets) {
        if (n.status == SchStatus::Same && !(all && n.cosmetic_only())) continue;
        if (!all && ++shown > 20) {
            std::printf("    ... more nets (use --stats)\n");
            break;
        }
        std::vector<std::string> joined, left;
        for (const auto& p : n.joined) joined.push_back(p.text());
        for (const auto& p : n.left) left.push_back(p.text());
        std::string name = n.status == SchStatus::Removed ? n.name_before : n.name_after;
        if (n.status == SchStatus::Same) {
            std::printf("    = net %-24s wiring redrawn, connections unchanged (wires +%d -%d)\n", name.c_str(),
                        n.wires_added, n.wires_removed);
            continue;
        }
        const char* mark = n.status == SchStatus::Added ? "+" : n.status == SchStatus::Removed ? "-" : "~";
        std::string line;
        if (n.status == SchStatus::Changed && n.name_before != n.name_after) line += "renamed from " + n.name_before + "  ";
        if (!n.merged_into.empty()) {
            std::printf("    - net %-24s merged into %s\n", name.c_str(), n.merged_into.c_str());
            continue;
        }
        if (!joined.empty()) line += "joined: " + join_list(joined) + "  ";
        if (!left.empty()) line += "left: " + join_list(left);
        std::printf("    %s net %-24s %s\n", mark, name.c_str(), line.c_str());
    }
}

void print_summary(const Diff& d, bool all) {
    std::vector<std::pair<std::string, NetStats>> changed;
    int add = 0, rem = 0, vadd = 0, vrem = 0;
    for (const auto& [name, s] : d.nets) {
        add += s.added;
        rem += s.removed;
        vadd += s.vias_added;
        vrem += s.vias_removed;
        if (s.changed_any()) changed.emplace_back(name, s);
    }
    std::sort(changed.begin(), changed.end(), [](const auto& x, const auto& y) {
        auto weight = [](const NetStats& s) { return s.added + s.removed + s.changed; };
        return weight(x.second) > weight(y.second);
    });

    std::printf("  %zu of %zu nets changed  (tracks +%d -%d, vias +%d -%d)", changed.size(), d.nets.size(), add,
                rem, vadd, vrem);
    if (d.changed) std::printf("; %d items changed in place", d.changed);
    if (d.moved) std::printf("; %d items only moved", d.moved);
    std::printf("\n");

    if (!changed.empty()) {
        size_t limit = all ? changed.size() : std::min<size_t>(changed.size(), 15);
        std::printf("\n  %-28s %-12s %-8s %-8s %-8s %s\n", "NET", "TRACKS", "VIAS", "PADS", "EDITED", "LENGTH mm");
        for (size_t i = 0; i < limit; ++i) {
            const auto& [name, s] = changed[i];
            char len[64];
            std::snprintf(len, sizeof len, "%.2f -> %.2f", s.length_old, s.length_new);
            std::printf("  %s %-12s %-8s %-8s %-8s %s\n", pad_right(name.empty() ? "(no net)" : name, 28).c_str(),
                        signed_counts(s.added, s.removed).c_str(),
                        signed_counts(s.vias_added, s.vias_removed).c_str(),
                        signed_counts(s.pads_added, s.pads_removed).c_str(),
                        s.changed ? std::to_string(s.changed).c_str() : ".", len);
        }
        if (limit < changed.size())
            std::printf("  ... %zu more (use --stats to list all)\n", changed.size() - limit);
    }

    // Footprints: what changed about each, copper or not.
    if (!d.footprints.empty()) {
        int added = 0, removed = 0, pads = 0, graphics = 0, fields = 0, moved = 0;
        for (const auto& f : d.footprints) {
            added += f.status == Status::Added;
            removed += f.status == Status::Removed;
            pads += f.pads_changed;
            graphics += f.graphics_changed();
            fields += !f.fields.empty();
            moved += f.moved;
        }
        std::printf("\n  footprints: +%d -%d; pads changed %d, graphics changed %d, fields changed %d, moved %d\n",
                    added, removed, pads, graphics, fields, moved);
        int shown = 0;
        for (const auto& f : d.footprints) {
            // Footprints that only moved are listed with --stats.
            bool only_moved = f.status == Status::Changed && !f.pads_changed && !f.graphics_changed() && f.fields.empty();
            if (only_moved && !all) continue;
            if (!all && ++shown > 15) {
                std::printf("    ... more (use --stats)\n");
                break;
            }
            std::vector<std::string> what;
            if (f.status == Status::Added) what.push_back("added (" + f.new_fp->lib + ")");
            if (f.status == Status::Removed) what.push_back("removed (" + f.old_fp->lib + ")");
            if (f.pads_changed) what.push_back("pads changed");
            if (f.graphics_changed())
                what.push_back("graphics +" + std::to_string(f.graphics_added) + " -" + std::to_string(f.graphics_removed));
            for (const auto& [k, b, a] : f.fields)
                what.push_back(k + " " + (b.empty() ? "(none)" : b) + " -> " + (a.empty() ? "(none)" : a));
            if (f.moved) what.push_back("moved");
            std::printf("    %s %-8s %s\n", f.status == Status::Added ? "+" : f.status == Status::Removed ? "-" : "~",
                        f.ref().c_str(), join_list(what, 4).c_str());
        }
    }

    // Pours: a changed outline is an edit; a refill alone is routine.
    if (!d.zone_changes.empty()) {
        int counts[4] = {0, 0, 0, 0};
        for (const auto& z : d.zone_changes) ++counts[z.kind];
        std::printf("\n  zones: +%d -%d, outline changed %d, refilled only %d\n", counts[ZoneDiff::Added],
                    counts[ZoneDiff::Removed], counts[ZoneDiff::OutlineChanged], counts[ZoneDiff::Refilled]);
    }
}


} // namespace kigit::cmd

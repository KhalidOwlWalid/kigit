#include "pcb/diff.hpp"

#include <algorithm>
#include <cmath>
#include <iterator>
#include <set>
#include <unordered_map>
#include <unordered_set>

namespace kigit {

namespace {

void count(NetStats& s, const Item& it, Status st) {
    if (st == Status::Moved || st == Status::Changed) {
        ++(st == Status::Moved ? s.moved : s.changed);
        if (it.kind == ItemKind::Track || it.kind == ItemKind::Arc) ++s.same;
        return;
    }
    switch (it.kind) {
    case ItemKind::Track:
    case ItemKind::Arc:
        if (st == Status::Added) ++s.added;
        else if (st == Status::Removed) ++s.removed;
        else ++s.same;
        break;
    case ItemKind::Via:
        if (st == Status::Added) ++s.vias_added;
        else if (st == Status::Removed) ++s.vias_removed;
        break;
    case ItemKind::Pad:
        if (st == Status::Added) ++s.pads_added;
        else if (st == Status::Removed) ++s.pads_removed;
        break;
    case ItemKind::Zone:
        break;
    }
}

bool near(double a, double b) { return std::abs(a - b) < 1e-4; }

bool same_angle(double a, double b) {
    double d = std::fmod(std::abs(a - b), 360.0);
    return d < 1e-3 || d > 360.0 - 1e-3;
}

// The same item, only shifted or rotated as a whole: everything that makes it
// the copper it is (net, layers, width, size, length) is unchanged. A pad
// must also sit in the same place within its footprint; a pad that moved
// within its footprint means the footprint itself changed.
bool only_moved(const Item& a, const Item& b) {
    if (a.kind != b.kind || a.net != b.net || a.layers != b.layers) return false;
    switch (a.kind) {
    case ItemKind::Track:
    case ItemKind::Arc:
        return near(a.width, b.width) && near(a.length(), b.length());
    case ItemKind::Via:
        return near(a.width, b.width) && near(a.drill, b.drill);
    case ItemKind::Pad:
        return a.shape == b.shape && near(a.size.x, b.size.x) && near(a.size.y, b.size.y) &&
               near(a.rratio, b.rratio) && near(a.drill, b.drill) && near(a.local.x, b.local.x) &&
               near(a.local.y, b.local.y) && same_angle(a.local_angle, b.local_angle);
    case ItemKind::Zone:
        return false;
    }
    return false;
}

// How many entries of sorted `a` aren't in sorted `b` (multiset difference).
int missing_from(const std::vector<std::string>& a, const std::vector<std::string>& b) {
    std::vector<std::string> out;
    std::set_difference(a.begin(), a.end(), b.begin(), b.end(), std::back_inserter(out));
    return static_cast<int>(out.size());
}

void diff_footprints(const Board& a, const Board& b, Diff& d) {
    // By ID, then by reference for footprints KiCad re-created.
    std::unordered_map<std::string, const Footprint*> old_by_id, old_by_ref;
    for (const auto& f : a.footprints) {
        if (!f.id.empty()) old_by_id.emplace(f.id, &f);
        if (!f.ref.empty()) old_by_ref.emplace(f.ref, &f);
    }
    std::unordered_set<const Footprint*> matched;
    for (const auto& nf : b.footprints) {
        const Footprint* of = nullptr;
        if (auto i = old_by_id.find(nf.id); !nf.id.empty() && i != old_by_id.end() && !matched.count(i->second))
            of = i->second;
        else if (auto r = old_by_ref.find(nf.ref); !nf.ref.empty() && r != old_by_ref.end() && !matched.count(r->second))
            of = r->second;
        FootprintDiff fd;
        fd.new_fp = &nf;
        if (!of) {
            fd.status = Status::Added;
            d.footprints.push_back(std::move(fd));
            continue;
        }
        matched.insert(of);
        fd.old_fp = of;
        fd.moved = !near(of->at.x, nf.at.x) || !near(of->at.y, nf.at.y) || !same_angle(of->angle, nf.angle) ||
                   of->side != nf.side;
        fd.pads_changed = of->pads != nf.pads;
        fd.graphics_added = missing_from(nf.graphics, of->graphics);
        fd.graphics_removed = missing_from(of->graphics, nf.graphics);
        if (of->lib != nf.lib) fd.fields.push_back({"Footprint", of->lib, nf.lib});
        std::set<std::string> keys;
        for (const auto& [k, v] : of->fields) keys.insert(k);
        for (const auto& [k, v] : nf.fields) keys.insert(k);
        for (const auto& k : keys) {
            auto o = of->fields.find(k), n = nf.fields.find(k);
            std::string before = o == of->fields.end() ? "" : o->second, after = n == nf.fields.end() ? "" : n->second;
            if (before != after) fd.fields.push_back({k, before, after});
        }
        if (fd.moved || fd.pads_changed || fd.graphics_changed() || !fd.fields.empty()) {
            fd.status = Status::Changed;
            d.footprints.push_back(std::move(fd));
        }
    }
    for (const auto& of : a.footprints) {
        if (matched.count(&of)) continue;
        FootprintDiff fd;
        fd.old_fp = &of;
        fd.status = Status::Removed;
        d.footprints.push_back(std::move(fd));
    }
}

void diff_zones(const Board& a, const Board& b, Diff& d) {
    auto key = [](const ZoneInfo& z) {
        if (!z.id.empty()) return z.id;
        std::string k = z.net + "|" + z.name;
        for (const auto& l : z.layers) k += "|" + l;
        return k;
    };
    std::unordered_map<std::string, const ZoneInfo*> old_zones;
    for (const auto& z : a.zones) old_zones.emplace(key(z), &z);
    std::unordered_set<const ZoneInfo*> matched;
    for (const auto& nz : b.zones) {
        auto f = old_zones.find(key(nz));
        if (f == old_zones.end() || matched.count(f->second)) {
            d.zone_changes.push_back({nullptr, &nz, ZoneDiff::Added});
            continue;
        }
        const ZoneInfo& oz = *f->second;
        matched.insert(&oz);
        if (oz.outline != nz.outline || oz.net != nz.net || oz.layers != nz.layers)
            d.zone_changes.push_back({&oz, &nz, ZoneDiff::OutlineChanged});
        else if (oz.fill != nz.fill)
            d.zone_changes.push_back({&oz, &nz, ZoneDiff::Refilled});
    }
    for (const auto& oz : a.zones)
        if (!matched.count(&oz)) d.zone_changes.push_back({&oz, nullptr, ZoneDiff::Removed});
}

// Silkscreen: the same item if it's the same shape in its footprint's frame
// (or on the board) for the same footprint. Moved with its footprint if its
// board position changed; otherwise unchanged. The rest is added/removed.
void diff_silk(const Board& a, const Board& b, Diff& d) {
    std::unordered_map<std::string, std::vector<const SilkItem*>> old_by_key;
    for (const auto& it : a.silk) old_by_key[it.key].push_back(&it);
    for (const auto& it : b.silk) {
        auto f = old_by_key.find(it.key);
        if (f == old_by_key.end() || f->second.empty()) {
            d.silk.push_back({&it, Status::Added});
            continue;
        }
        const SilkItem* old = f->second.back();
        f->second.pop_back();
        bool same_place = old->d == it.d && near(old->at.x, it.at.x) && near(old->at.y, it.at.y) && old->angle == it.angle;
        d.silk.push_back({&it, same_place ? Status::Same : Status::Moved});
    }
    for (const auto& [key, left] : old_by_key)
        for (const SilkItem* it : left) d.silk.push_back({it, Status::Removed});
}

} // namespace

Diff diff_boards(const Board& old_board, const Board& new_board) {
    Diff d;

    for (const Item& it : old_board.items)
        if (it.kind != ItemKind::Zone) d.nets[it.net].length_old += it.length();

    auto add = [&](const Item& it, Status st, const Item* other = nullptr) {
        d.items.push_back({&it, st, other});
        if (st != Status::OldPosition) count(d.nets[it.net], it, st);
    };

    // 1. By KiCad ID. Items with the same ID are the same item: unchanged,
    //    moved, or changed in place (drawn with a ghost of the old copper).
    std::unordered_map<std::string, const Item*> old_by_id;
    for (const Item& it : old_board.items)
        if (it.kind != ItemKind::Zone && !it.id.empty()) old_by_id.emplace(it.id, &it);

    std::unordered_set<const Item*> done; // old items already accounted for
    std::vector<const Item*> unmatched_new;
    for (const Item& it : new_board.items) {
        if (it.kind == ItemKind::Zone) {
            d.zones.push_back(&it);
            d.nets[it.net]; // make sure plane nets are listed
            continue;
        }
        d.nets[it.net].length_new += it.length();
        auto f = it.id.empty() ? old_by_id.end() : old_by_id.find(it.id);
        if (f == old_by_id.end() || done.count(f->second) || f->second->kind != it.kind) {
            unmatched_new.push_back(&it);
            continue;
        }
        const Item& old = *f->second;
        done.insert(&old);
        if (old.key() == it.key() && (it.kind != ItemKind::Pad || only_moved(old, it))) {
            add(it, Status::Same);
        } else if (only_moved(old, it)) {
            add(it, Status::Moved, &old);
            add(old, Status::OldPosition, &it);
            ++d.moved;
        } else if (old.net != it.net && old.key() != it.key()) {
            // Moved to another net: that's an electrical change, not an edit.
            add(it, Status::Added);
            add(old, Status::Removed);
        } else {
            add(it, Status::Changed, &old);
            add(old, Status::OldPosition, &it);
            ++d.changed;
        }
    }

    // 2. The rest by geometry: items without IDs (older files), or whose ID
    //    changed (re-routed, copy-pasted). Same copper in the same place counts
    //    as unchanged.
    std::unordered_map<std::string, std::vector<const Item*>> pending;
    for (const Item& it : old_board.items)
        if (it.kind != ItemKind::Zone && !done.count(&it)) pending[it.key()].push_back(&it);
    for (const Item* it : unmatched_new) {
        auto f = pending.find(it->key());
        if (f != pending.end() && !f->second.empty()) {
            done.insert(f->second.back());
            f->second.pop_back();
            add(*it, Status::Same);
        } else {
            add(*it, Status::Added);
        }
    }

    // 3. Whatever is left on the old side no longer exists.
    for (const Item& it : old_board.items)
        if (it.kind != ItemKind::Zone && !done.count(&it)) add(it, Status::Removed);

    diff_footprints(old_board, new_board, d);
    diff_zones(old_board, new_board, d);
    diff_silk(old_board, new_board, d);
    return d;
}

} // namespace kigit

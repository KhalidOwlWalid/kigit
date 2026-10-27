#include "diff.hpp"

#include <cmath>
#include <unordered_map>
#include <unordered_set>

namespace kigit {

namespace {

void count(NetStats& s, const Item& it, Status st) {
    if (st == Status::Moved) {
        ++s.moved;
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

// The same item, only shifted or rotated: everything that makes it the copper
// it is (net, layers, width, size, length) is unchanged. A dragged track end
// or a new width is an edit, not a move.
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
               near(a.rratio, b.rratio) && near(a.drill, b.drill);
    case ItemKind::Zone:
        return false;
    }
    return false;
}

} // namespace

Diff diff_boards(const Board& old_board, const Board& new_board) {
    Diff d;

    for (const Item& it : old_board.items)
        if (it.kind != ItemKind::Zone) d.nets[it.net].length_old += it.length();

    auto add = [&](const Item& it, Status st) {
        d.items.push_back({&it, st});
        if (st != Status::OldPosition) count(d.nets[it.net], it, st);
    };

    // 1. By KiCad ID. Items with the same ID are the same item: unchanged,
    //    moved, or edited (then the old one is removed and the new one added).
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
        if (old.key() == it.key()) {
            add(it, Status::Same);
        } else if (only_moved(old, it)) {
            add(it, Status::Moved);
            add(old, Status::OldPosition);
            ++d.moved;
        } else {
            add(it, Status::Added);
            add(old, Status::Removed);
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
    return d;
}

} // namespace kigit

#include "diff.hpp"

#include <unordered_map>

namespace kigit {

namespace {

void count(NetStats& s, const Item& it, Status st) {
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

} // namespace

Diff diff_boards(const Board& old_board, const Board& new_board) {
    Diff d;

    // Old items by key; a list per key so duplicate geometry still pairs up 1:1.
    std::unordered_map<std::string, std::vector<const Item*>> pending;
    for (const Item& it : old_board.items) {
        if (it.kind == ItemKind::Zone) continue;
        pending[it.key()].push_back(&it);
        d.nets[it.net].length_old += it.length();
    }

    for (const Item& it : new_board.items) {
        if (it.kind == ItemKind::Zone) {
            d.zones.push_back(&it);
            d.nets[it.net]; // make sure plane nets are listed
            continue;
        }
        NetStats& s = d.nets[it.net];
        s.length_new += it.length();
        auto found = pending.find(it.key());
        Status st = Status::Added;
        if (found != pending.end() && !found->second.empty()) {
            found->second.pop_back();
            st = Status::Same;
        }
        d.items.push_back({&it, st});
        count(s, it, st);
    }

    // Whatever is left on the old side no longer exists.
    for (const Item& it : old_board.items) {
        if (it.kind == ItemKind::Zone) continue;
        auto found = pending.find(it.key());
        if (found == pending.end() || found->second.empty()) continue;
        // Report each leftover exactly once.
        auto& left = found->second;
        for (auto p = left.begin(); p != left.end(); ++p) {
            if (*p == &it) {
                left.erase(p);
                d.items.push_back({&it, Status::Removed});
                count(d.nets[it.net], it, Status::Removed);
                break;
            }
        }
    }
    return d;
}

} // namespace kigit

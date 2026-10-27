// Per-net comparison of two boards.
#pragma once

#include "board.hpp"

#include <map>
#include <string>
#include <vector>

namespace kigit {

enum class Status { Same, Added, Removed };

struct DiffItem {
    const Item* item;
    Status status;
};

struct NetStats {
    int added = 0, removed = 0, same = 0;     // tracks + arcs
    int vias_added = 0, vias_removed = 0;
    int pads_added = 0, pads_removed = 0;
    double length_old = 0, length_new = 0;    // mm of track copper

    bool changed() const {
        return added || removed || vias_added || vias_removed || pads_added || pads_removed;
    }
};

struct Diff {
    std::vector<DiffItem> items;          // tracks, arcs, vias, pads of both sides
    std::vector<const Item*> zones;       // zones of the new board (not diffed)
    std::map<std::string, NetStats> nets; // every net seen on either side
};

// Matches items of `old_board` and `new_board` by geometry, per net.
Diff diff_boards(const Board& old_board, const Board& new_board);

} // namespace kigit

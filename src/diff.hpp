// Per-net comparison of two boards.
#pragma once

#include "board.hpp"

#include <map>
#include <string>
#include <vector>

namespace kigit {

// Same:    in both revisions, unchanged.
// Added / Removed: only in the new / old revision.
// Moved:   the same item (KiCad ID), same shape, at a new position or angle.
// OldPosition: where a moved item used to be (for drawing a ghost).
// The numbers are shared with the viewer (pcb.js).
enum class Status { Same = 0, Added = 1, Removed = 2, Moved = 3, OldPosition = 4 };

struct DiffItem {
    const Item* item;
    Status status;
};

struct NetStats {
    int added = 0, removed = 0, same = 0;     // tracks + arcs
    int vias_added = 0, vias_removed = 0;
    int pads_added = 0, pads_removed = 0;
    int moved = 0;                            // tracks, arcs, vias and pads that only moved
    double length_old = 0, length_new = 0;    // mm of track copper

    // Copper added or removed. Moving things around doesn't count.
    bool changed() const {
        return added || removed || vias_added || vias_removed || pads_added || pads_removed;
    }
};

struct Diff {
    std::vector<DiffItem> items;          // tracks, arcs, vias, pads of both sides (+ old positions)
    std::vector<const Item*> zones;       // zones of the new board (not diffed)
    std::map<std::string, NetStats> nets; // every net seen on either side
    int moved = 0;                        // items that only moved, all nets
};

// Matches items of `old_board` and `new_board`: first by KiCad ID (so moved
// items are recognised), then by geometry for the rest.
Diff diff_boards(const Board& old_board, const Board& new_board);

} // namespace kigit

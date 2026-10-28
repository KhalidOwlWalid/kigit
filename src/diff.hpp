// Comparison of two boards: copper per net, footprints and pours.
#pragma once

#include "board.hpp"

#include <array>
#include <map>
#include <string>
#include <vector>

namespace kigit {

// Same:        in both revisions, unchanged.
// Added / Removed: only in the new / old revision.
// Moved:       the same item (KiCad ID), same copper, moved as a whole (a pad
//              counts as moved only if its footprint moved it).
// OldPosition: where a moved or changed item used to be (drawn as a ghost).
// Changed:     the same item (KiCad ID) with different copper: a dragged track
//              end, a new width, a pad moved within its footprint, ...
// The numbers are shared with the viewer (pcb.js).
enum class Status { Same = 0, Added = 1, Removed = 2, Moved = 3, OldPosition = 4, Changed = 5 };

struct DiffItem {
    const Item* item;
    Status status;
};

struct NetStats {
    int added = 0, removed = 0, same = 0;     // tracks + arcs
    int vias_added = 0, vias_removed = 0;
    int pads_added = 0, pads_removed = 0;
    int moved = 0;                            // tracks, arcs, vias and pads that only moved
    int changed = 0;                          // tracks, arcs, vias and pads edited in place
    double length_old = 0, length_new = 0;    // mm of track copper

    // Copper added, removed or edited. Moving things around doesn't count.
    bool changed_any() const {
        return added || removed || vias_added || vias_removed || pads_added || pads_removed || changed;
    }
};

// What happened to one footprint.
struct FootprintDiff {
    const Footprint* old_fp = nullptr;
    const Footprint* new_fp = nullptr;
    Status status = Status::Same;            // Same, Added, Removed or Changed
    bool moved = false;                      // position, rotation or side
    bool pads_changed = false;               // pad shapes/places within the footprint
    int graphics_added = 0, graphics_removed = 0; // fab/courtyard/silkscreen lines and texts
    std::vector<std::array<std::string, 3>> fields; // {field, before, after}, incl. library footprint
    std::string ref() const { return new_fp ? new_fp->ref : old_fp->ref; }
    bool graphics_changed() const { return graphics_added || graphics_removed; }
};

// What happened to one copper pour.
struct ZoneDiff {
    const ZoneInfo* old_zone = nullptr;
    const ZoneInfo* new_zone = nullptr;
    enum Kind { Added, Removed, OutlineChanged, Refilled } kind;
};

struct Diff {
    std::vector<DiffItem> items;          // tracks, arcs, vias, pads of both sides (+ old positions)
    std::vector<const Item*> zones;       // zone fills of the new board (drawn, not diffed)
    std::map<std::string, NetStats> nets; // every net seen on either side
    int moved = 0;                        // items that only moved, all nets
    int changed = 0;                      // items edited in place, all nets
    std::vector<FootprintDiff> footprints; // only the ones that differ
    std::vector<ZoneDiff> zone_changes;    // only the ones that differ
};

// Matches items of `old_board` and `new_board`: first by KiCad ID (so moved
// and edited items are recognised), then by geometry for the rest.
Diff diff_boards(const Board& old_board, const Board& new_board);

} // namespace kigit

// Comparing two revisions of a schematic: parts, nets, wires and labels.
//
// Changes are split into electrical ones (a part added, a pin joining or
// leaving a net, a new value or footprint) and cosmetic ones (a part moved,
// wires redrawn with the same connections), so tidying a sheet doesn't drown
// out real changes.
#pragma once

#include "schematic.hpp"

#include <string>
#include <vector>

namespace kigit {

enum class SchStatus { Same, Added, Removed, Changed };

// A pin, named the way people read it: "U1.40 (PB4)".
struct PinRef {
    std::string ref, number, name;
    std::string text() const;
};

struct FieldChange {
    std::string field; // "Value", "Footprint", "MPN", ...
    std::string before, after;
};

struct PinMove {
    PinRef pin;
    std::string net_before, net_after; // "" = not connected / didn't exist
};

struct SymbolDiff {
    int old_index = -1, new_index = -1;    // into each schematic's symbols
    SchStatus status = SchStatus::Same;
    std::string ref_before, ref_after;     // differ if re-annotated
    std::vector<FieldChange> fields;       // value, footprint, lib symbol, other fields
    std::vector<PinMove> pins;             // pins now on a different net
    bool moved = false;                    // position, rotation, mirror or sheet changed
    bool electrical() const;               // added/removed, value/footprint/lib, or pins rewired
    bool fields_only() const;              // only BOM fields / reference changed (not electrical, not just moved)
};

struct NetDiff {
    int old_index = -1, new_index = -1;    // into each schematic's nets
    SchStatus status = SchStatus::Same;
    std::string name_before, name_after;   // differ if renamed
    std::vector<PinRef> joined, left;      // pins that joined / left this net
    int wires_added = 0, wires_removed = 0;
    int labels_added = 0, labels_removed = 0;
    std::string merged_into;               // removed net whose pins all went to one net
    bool electrical() const { return status == SchStatus::Added || status == SchStatus::Removed || !joined.empty() || !left.empty(); }
    bool cosmetic_only() const { return !electrical() && (wires_added || wires_removed || labels_added || labels_removed); }
};

struct SchDiff {
    std::vector<SymbolDiff> symbols;   // every non-power part, both sides
    std::vector<NetDiff> nets;         // every net with pins or wires, both sides
    std::vector<SchStatus> wires_new;  // per new wire: Same or Added
    std::vector<SchStatus> wires_old;  // per old wire: Same or Removed
    std::vector<SchStatus> labels_new, labels_old;
};

SchDiff diff_schematics(const Schematic& old_sch, const Schematic& new_sch);

} // namespace kigit

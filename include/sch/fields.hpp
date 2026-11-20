#pragma once
// Writing part information fields (MPN, Manufacturer, DigiKey, ...) into a
// schematic file, for the BOM. Nothing else: kigit is not a schematic
// editor. KiCad's own fields (Reference, Value, Footprint, Datasheet,
// Description, ki_*, Sim.*, sheet fields) are refused, and same_design()
// checks that an edited schematic is the same circuit with the same parts.
//
// Edits are the smallest change to the text: a property's value is
// replaced in place; a new property is a copy of one of the symbol's own
// hidden fields (so it's in that file's KiCad format and stays hidden),
// put after its last property. A rename replaces only the property's name.
// The rest of the file is left byte for byte.
#include "sch/schematic.hpp"

#include <set>
#include <string>
#include <vector>

namespace kigit {

struct FieldEdit {
    std::string uuid;  // the placed symbol's uuid (each unit of a part is its own symbol)
    std::string name;  // the field, e.g. "MPN"
    std::string value; // "" empties an existing field (a missing one stays missing)
    std::string rename; // if set: the field gets this name instead (its value stays); value is unused
};

struct FieldsResult {
    std::string text;               // the file after the edits
    int changed = 0;                // fields set or added (unchanged ones don't count)
    std::vector<std::string> problems; // edits that couldn't be made (unknown symbol, ...)
};

// Why a field can't be written by kigit ("" if it can).
std::string field_refused(const std::string& name);

// Applies the edits to one schematic file's text.
FieldsResult set_fields(const std::string& text, const std::vector<FieldEdit>& edits);

// "" if `b` is the same design as `a`: the same sheets, parts (reference,
// value, footprint, library symbol, unit, BOM/board/DNP flags) and nets, and
// every field the same except those named in `edited`. Otherwise what differs.
std::string same_design(const Schematic& a, const Schematic& b, const std::set<std::string>& edited);

} // namespace kigit

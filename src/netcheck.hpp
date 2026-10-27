// Compares kigit's computed schematic nets with a netlist exported by KiCad
// (kicad-cli sch export netlist), to verify the connectivity rules.
#pragma once

#include "schematic.hpp"

#include <string>

namespace kigit {

// Prints the differences and returns true if the nets match exactly (same
// pins grouped together; names are reported but don't count as failures
// unless `strict_names`).
bool check_netlist(const Schematic& sch, const std::string& netlist_text, bool strict_names);

} // namespace kigit

#pragma once
// The terminal summary printed after a diff.
#include "pcb/diff.hpp"
#include "sch/sch_diff.hpp"
#include "sch/schematic.hpp"

namespace kigit::cmd {

// PCB: changed nets, footprints, zones. `all` = everything (--stats), not the top few.
void print_summary(const Diff& d, bool all);
// Schematic: parts and nets. Cosmetic changes (moves, redrawn wires) only with `all`.
void print_sch_summary(const SchDiff& d, const Schematic& a, const Schematic& b, bool all);

} // namespace kigit::cmd

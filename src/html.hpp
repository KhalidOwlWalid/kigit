// Writes the self-contained HTML viewer.
#pragma once

#include "board.hpp"
#include "diff.hpp"
#include "git.hpp"

#include <nlohmann/json_fwd.hpp>

#include <string>
#include <vector>

namespace kigit {

struct ReportInfo {
    std::string board_name;
    git::Revision old_rev, new_rev;
    std::vector<std::string> warnings; // shown in the viewer, e.g. board moved
};

struct Schematic;
struct SchDiff;

// Everything the viewer needs about the PCB diff, as JSON.
nlohmann::json report_data(const Board& old_board, const Board& new_board, const Diff& diff,
                           const ReportInfo& info);

// One revision's schematic: sheets, parts and computed nets.
nlohmann::json schematic_json(const Schematic& sch);

// What changed between two schematics (only the changed parts and nets).
nlohmann::json schematic_diff_json(const SchDiff& d);

// Everything the schematic view draws: per sheet, wires/labels/parts with
// their change status and net, plus symbol drawings, nets and parts.
nlohmann::json schematic_view_json(const Schematic& old_sch, const Schematic& new_sch, const SchDiff& d);

// The full HTML page with `data` embedded.
std::string render_html(const nlohmann::json& data);

} // namespace kigit

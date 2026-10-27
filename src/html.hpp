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

// Everything the viewer needs about the PCB diff, as JSON.
nlohmann::json report_data(const Board& old_board, const Board& new_board, const Diff& diff,
                           const ReportInfo& info);

// One revision's schematic: sheets, parts and computed nets.
nlohmann::json schematic_json(const Schematic& sch);

// The full HTML page with `data` embedded.
std::string render_html(const nlohmann::json& data);

} // namespace kigit

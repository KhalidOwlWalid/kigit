// Writes the self-contained HTML viewer.
#pragma once

#include "board.hpp"
#include "diff.hpp"
#include "git.hpp"

#include <string>

namespace kigit {

struct ReportInfo {
    std::string board_name;
    git::Revision old_rev, new_rev;
};

// Returns the full HTML page for the diff.
std::string render_html(const Board& old_board, const Board& new_board, const Diff& diff,
                        const ReportInfo& info);

} // namespace kigit

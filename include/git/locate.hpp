// Finding the board file in a revision, even if it was moved or renamed.
#pragma once

#include "pcb/board.hpp"
#include "git/git.hpp"

#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace kigit {

// A real board file name (not a KiCad lock/autosave file).
bool is_board_name(std::string_view filename);

// Folders never searched: hidden ones (.git, .kiri, .kigit), KiCad backups,
// build output.
bool is_skipped_dir(std::string_view dirname);

// The board text of one revision and where it came from.
struct BoardSource {
    std::string rel;        // path from the repo root
    std::string text;
    bool relocated = false; // not at the expected path; found by similarity
    double score = 0;       // similarity to the reference board (0..1)
    int refs_common = 0, refs_total = 0;
    int nets_common = 0, nets_total = 0;
};

// Contents of `rel` at `rev` (the working tree if rev.local), or nullopt.
std::optional<std::string> read_board_at(const std::string& root, const std::string& rel,
                                         const git::Revision& rev);

// Every board file path (from the repo root) in `rev`.
std::vector<std::string> list_boards(const std::string& root, const git::Revision& rev);

// Searches `rev` for the board most similar to `reference` (same footprints
// and nets). Throws with the list of candidates if none is a convincing match.
BoardSource find_similar_board(const std::string& root, const std::string& expected_rel,
                               const git::Revision& rev, const Board& reference);

} // namespace kigit

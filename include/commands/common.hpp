#pragma once
// Helpers shared by the commands: paths from arguments, finding the board,
// warnings, where pages are written.
#include "git/git.hpp"

#include <filesystem>
#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace kigit::cmd {

namespace fs = std::filesystem;
struct Options;

bool is_board_arg(const std::string& a);
std::string expand_home(std::string p);
// Board path from a user argument: ~ expanded, relative to `base`,
// and a .kicad_pro swapped for its .kicad_pcb.
fs::path board_from_arg(const std::string& arg, const fs::path& base);
// Short names for two board files shown in the viewer.
std::pair<std::string, std::string> file_labels(const fs::path& a, const fs::path& b);
// A warning on stderr (yellow when it's a terminal) and in the log.
void warn(const std::string& msg);
std::optional<std::string> read_disk(const fs::path& p);
// The only .kicad_pcb in `dir` (or below it); throws if there's none or several.
fs::path find_board(const fs::path& dir);
// <board folder>/.kigit/<board>-<old>-<new>.html
fs::path default_output(const fs::path& board_dir, const std::string& board, const git::Revision& a,
                        const git::Revision& b);

// The project folder: the current directory, or --kicad-repo. Pointing
// --kicad-repo at a board file adds it to o.board_args.
fs::path project_dir(Options& o);

// The board in its git repository.
struct GitBoard {
    fs::path path;    // the board file (may not exist on disk)
    std::string root; // repository top level
    std::string rel;  // board path relative to root, with /
};
GitBoard git_board(const fs::path& project, const std::vector<std::string>& board_args);

} // namespace kigit::cmd

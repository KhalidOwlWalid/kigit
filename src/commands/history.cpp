#include "commands/commands.hpp"
#include "commands/common.hpp"
#include "git/git.hpp"
#include "git/locate.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <cstdio>
#include <set>

namespace kigit::cmd {

// `kigit --log`: HEAD's history as JSON, newest first, each commit flagged
// with whether it changed this project's board / schematic. The project may
// have lived in other folders before (renamed or moved), so those count too.
// With `kicad_only`, only such commits are listed, searched through the whole
// history. "local" describes the uncommitted changes in the project folder.
namespace {

void print_log(const std::string& root, const std::string& board_rel, git::LogQuery q, bool kicad_only) {
    std::vector<std::string> boards = git::past_paths(root, board_rel);
    if (std::find(boards.begin(), boards.end(), board_rel) == boards.end()) boards.insert(boards.begin(), board_rel);
    std::set<std::string> dirs; // every folder the project has been in
    for (const auto& b : boards) {
        std::string d = fs::path(b).parent_path().generic_string();
        dirs.insert(d.empty() ? "" : d + "/");
    }
    // In one of the project's folders (or below), but not in tool/backup folders.
    auto in_project = [&](const std::string& f) {
        for (const auto& d : dirs) {
            if (!f.starts_with(d)) continue;
            bool skipped = false;
            for (const auto& part : fs::path(f.substr(d.size())).parent_path())
                if (is_skipped_dir(part.string())) skipped = true;
            if (!skipped) return true;
        }
        return false;
    };
    auto kind = [&](const std::string& f, bool& pcb, bool& sch) {
        if (!in_project(f)) return;
        if (f.ends_with(".kicad_pcb")) pcb = true;
        if (f.ends_with(".kicad_sch")) sch = true;
    };

    if (kicad_only)
        for (const auto& d : dirs) {
            q.paths.push_back(":(glob)" + d + "**/*.kicad_pcb");
            q.paths.push_back(":(glob)" + d + "**/*.kicad_sch");
        }
    int total = git::count(root, q);

    nlohmann::json commits = nlohmann::json::array();
    for (const auto& c : git::log(root, q)) {
        bool pcb = false, sch = false;
        for (const auto& f : c.files) kind(f, pcb, sch);
        commits.push_back({{"hash", c.hash}, {"short", c.short_hash}, {"date", c.date}, {"author", c.author},
                           {"subject", c.subject}, {"body", c.body}, {"pcb", pcb}, {"sch", sch}});
    }

    // Uncommitted changes, ignoring tool folders like KiCad's .history backups.
    std::string here = fs::path(board_rel).parent_path().generic_string();
    bool pcb = false, sch = false;
    std::vector<std::string> changed;
    for (const auto& f : git::changed_files(root, here.empty() ? "." : here)) {
        bool skipped = false;
        for (const auto& part : fs::path(f).parent_path())
            if (is_skipped_dir(part.string())) skipped = true;
        if (skipped) continue;
        changed.push_back(f);
        kind(f, pcb, sch);
    }
    nlohmann::json past = nlohmann::json::array();
    for (const auto& d : dirs) past.push_back(d.empty() ? "." : d.substr(0, d.size() - 1));
    nlohmann::json out = {
        {"repo", root},
        {"board", board_rel},
        {"folders", past},
        {"total", total},
        {"commits", commits},
        {"local", nlohmann::json{{"dirty", !changed.empty()}, {"pcb", pcb}, {"sch", sch}, {"files", changed}}}};
    std::printf("%s\n", out.dump().c_str());
}

} // namespace

int run_history(const Options& o, const fs::path& project) {
    GitBoard g = git_board(project, o.board_args);
    print_log(g.root, g.rel, o.log_query, o.log_kicad_only);
    return 0;
}

} // namespace kigit::cmd

#include "commands/commands.hpp"
#include "commands/common.hpp"
#include "git/git.hpp"
#include "git/locate.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <cstdio>
#include <map>
#include <tuple>

namespace kigit::cmd {

// `kigit --projects`: KiCad projects in `dir` and up to `depth` levels below
// it, as JSON. A project is a .kicad_pro / .kicad_pcb / .kicad_sch sharing a
// folder and name; kigit needs its .kicad_pcb.
int run_projects(const fs::path& dir, int depth) {
    struct Found {
        bool pro = false, pcb = false, sch = false;
        int level = 0;
    };
    std::map<std::pair<std::string, std::string>, Found> found; // (folder, name)
    auto note = [&](const fs::path& p, int level) {
        std::string name = p.filename().string();
        if (name.starts_with("~") || name.starts_with("_autosave")) return;
        std::string ext = p.extension().string();
        if (ext != ".kicad_pro" && ext != ".kicad_pcb" && ext != ".kicad_sch") return;
        Found& f = found[{p.parent_path().string(), p.stem().string()}];
        f.level = level;
        if (ext == ".kicad_pro") f.pro = true;
        else if (ext == ".kicad_pcb") f.pcb = true;
        else f.sch = true;
    };
    std::error_code ec;
    auto it = fs::recursive_directory_iterator(dir, fs::directory_options::skip_permission_denied, ec);
    for (; !ec && it != fs::recursive_directory_iterator(); it.increment(ec)) {
        const auto& e = *it;
        if (e.is_directory(ec)) {
            if (is_skipped_dir(e.path().filename().string()) || it.depth() >= depth) it.disable_recursion_pending();
            continue;
        }
        if (e.is_regular_file(ec)) note(e.path(), it.depth());
    }

    // Sub-sheets (a .kicad_sch with no project of its own) aren't projects.
    nlohmann::json projects = nlohmann::json::array();
    for (const auto& [key, f] : found) {
        if (!f.pro && !f.pcb) continue;
        const auto& [folder, name] = key;
        bool in_git = git::is_repo(folder);
        projects.push_back({{"name", name},
                            {"dir", folder},
                            {"level", f.level},
                            {"pro", f.pro},
                            {"pcb", f.pcb},
                            {"sch", f.sch},
                            {"board", f.pcb ? (fs::path(folder) / (name + ".kicad_pcb")).string() : ""},
                            {"git", in_git},
                            {"repo", in_git ? git::toplevel(folder) : ""}});
    }
    std::sort(projects.begin(), projects.end(), [](const auto& a, const auto& b) {
        return std::tie(a["level"], a["dir"], a["name"]) < std::tie(b["level"], b["dir"], b["name"]);
    });
    nlohmann::json out = {{"dir", fs::absolute(dir).lexically_normal().string()}, {"depth", depth}, {"projects", projects}};
    std::printf("%s\n", out.dump().c_str());
    return 0;
}

} // namespace kigit::cmd

#include "commands/common.hpp"

#include "commands/options.hpp"
#include "git/locate.hpp"
#include "utils/platform.hpp"

#include <spdlog/spdlog.h>

#include <cctype>
#include <cstdio>
#include <fstream>
#include <sstream>
#include <stdexcept>

namespace kigit::cmd {

bool is_board_arg(const std::string& a) {
    return a.ends_with(".kicad_pcb") || a.ends_with(".kicad_pro");
}

std::string expand_home(std::string p) {
    if (p == "~" || p.starts_with("~/") || p.starts_with("~\\"))
        p = platform::home_dir().string() + p.substr(1);
    return p;
}

// Board path from a user argument: ~ expanded, relative to `base`,
// and a .kicad_pro swapped for its .kicad_pcb.
fs::path board_from_arg(const std::string& arg, const fs::path& base) {
    fs::path p = expand_home(arg);
    if (p.is_relative()) p = base / p;
    if (p.extension() == ".kicad_pro") p.replace_extension(".kicad_pcb");
    return p.lexically_normal();
}

// Short names for two board files shown in the viewer: file names if they
// differ, else their folder names, else "old"/"new".
std::pair<std::string, std::string> file_labels(const fs::path& a, const fs::path& b) {
    if (a.stem() != b.stem()) return {a.stem().string(), b.stem().string()};
    std::string pa = a.parent_path().filename().string(), pb = b.parent_path().filename().string();
    if (!pa.empty() && !pb.empty() && pa != pb) return {pa, pb};
    return {"old", "new"};
}

namespace {

std::string safe_filename(std::string s) {
    for (char& c : s)
        if (!std::isalnum(static_cast<unsigned char>(c)) && c != '-' && c != '_' && c != '.') c = '_';
    return s;
}

bool is_board_file(const fs::directory_entry& e) {
    return e.is_regular_file() && is_board_name(e.path().filename().string());
}

} // namespace

void warn(const std::string& msg) {
    bool color = platform::stderr_supports_color();
    std::fprintf(stderr, "%swarning:%s %s\n", color ? "\033[1;33m" : "", color ? "\033[0m" : "", msg.c_str());
    spdlog::warn("{}", msg);
}

std::optional<std::string> read_disk(const fs::path& p) {
    std::ifstream f(p, std::ios::binary);
    if (!f) return std::nullopt;
    std::ostringstream ss;
    ss << f.rdbuf();
    return ss.str();
}

// Finds the board in `dir`: the only .kicad_pcb at the top level, or else the
// only one anywhere below it.
fs::path find_board(const fs::path& dir) {
    std::vector<fs::path> found;
    for (const auto& e : fs::directory_iterator(dir))
        if (is_board_file(e)) found.push_back(e.path());

    if (found.empty()) {
        auto it = fs::recursive_directory_iterator(dir, fs::directory_options::skip_permission_denied);
        for (; it != fs::recursive_directory_iterator(); ++it) {
            if (it->is_directory() && is_skipped_dir(it->path().filename().string())) {
                it.disable_recursion_pending();
                continue;
            }
            if (is_board_file(*it)) found.push_back(it->path());
        }
    }

    if (found.size() == 1) return found[0];
    if (found.empty()) throw std::runtime_error("no .kicad_pcb found in " + dir.string() + "; pass one");
    std::string list;
    for (size_t i = 0; i < found.size() && i < 10; ++i) list += "\n    " + fs::relative(found[i], dir).string();
    if (found.size() > 10) list += "\n    ... and " + std::to_string(found.size() - 10) + " more";
    throw std::runtime_error("several boards in " + dir.string() + ", pick one:" + list);
}

// Pages go in <board folder>/.kigit/. Not ~/.cache: snap browsers (Ubuntu's
// Firefox/Chromium) can't read hidden folders at the top of $HOME.
fs::path default_output(const fs::path& board_dir, const std::string& board, const git::Revision& a,
                        const git::Revision& b) {
    fs::path dir = board_dir / ".kigit";
    fs::create_directories(dir);
    // Ignore the folder's contents without touching the project's .gitignore.
    fs::path ignore = dir / ".gitignore";
    if (!fs::exists(ignore)) std::ofstream(ignore) << "*\n";
    return dir / safe_filename(board + "-" + a.short_hash + "-" + b.short_hash + ".html");
}

fs::path project_dir(Options& o) {
    fs::path project = fs::current_path();
    if (o.project_arg.empty()) return project;
    project = fs::absolute(expand_home(o.project_arg));
    // Pointing straight at a .kicad_pcb / .kicad_pro also works.
    if (fs::is_regular_file(project)) {
        if (o.board_args.empty() && is_board_arg(project.string())) o.board_args.push_back(project.string());
        project = project.parent_path();
    }
    if (!fs::is_directory(project)) throw std::runtime_error("--kicad-repo: no such folder " + project.string());
    return project;
}

GitBoard git_board(const fs::path& project, const std::vector<std::string>& board_args) {
    GitBoard g;
    g.path = board_args.empty() ? find_board(project) : board_from_arg(board_args[0], project);
    // The board's folder may not exist (moved, or a path from an old commit).
    fs::path existing = fs::is_directory(g.path.parent_path()) ? g.path.parent_path() : project;
    if (!git::is_repo(existing.string()))
        throw std::runtime_error(existing.string() + " is not in a git repository.\n"
                                 "       To compare two board files without git:\n"
                                 "       kigit --files OLD.kicad_pcb NEW.kicad_pcb");
    g.root = git::toplevel(existing.string());
    g.rel = fs::weakly_canonical(g.path).lexically_relative(fs::weakly_canonical(g.root)).generic_string();
    if (g.rel.empty() || g.rel.starts_with(".."))
        throw std::runtime_error(g.path.string() + " is outside the git repository " + g.root);
    return g;
}

} // namespace kigit::cmd

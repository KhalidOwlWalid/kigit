// `kigit --3d [REV]`: the board at one revision as a 3D model (binary glTF),
// made by KiCad's own kicad-cli. kigit only gets the files out of git.
#include "commands/commands.hpp"
#include "commands/common.hpp"
#include "git/git.hpp"
#include "git/locate.hpp"
#include "pcb/board.hpp"
#include "utils/platform.hpp"

#include <spdlog/spdlog.h>

#include <algorithm>
#include <cctype>
#include <cstdio>
#include <fstream>
#include <sstream>
#include <stdexcept>

namespace kigit::cmd {

namespace {

// 3D model files a footprint can point at.
bool is_model_file(const std::string& path) {
    std::string ext = fs::path(path).extension().string();
    std::transform(ext.begin(), ext.end(), ext.begin(), [](unsigned char c) { return std::tolower(c); });
    for (const char* e : {".step", ".stp", ".stpz", ".wrl", ".wrz", ".igs", ".iges"})
        if (ext == e) return true;
    return false;
}

void write_file(const fs::path& p, const std::string& data) {
    fs::create_directories(p.parent_path());
    std::ofstream f(p, std::ios::binary);
    f << data;
    if (!f) throw std::runtime_error("cannot write " + p.string());
}

// The last few lines of a program's output, for an error message.
std::string tail(const std::string& text, size_t lines = 6) {
    std::vector<std::string> all;
    std::istringstream in(text);
    for (std::string l; std::getline(in, l);)
        if (!l.empty() && l != "\r") all.push_back(l);
    std::string out;
    for (size_t i = all.size() > lines ? all.size() - lines : 0; i < all.size(); ++i) out += "\n  " + all[i];
    return out;
}

// KiCad's major version (10 for "10.0.7"), or 0 if unknown.
int kicad_major(const fs::path& cli) {
    platform::RunResult r = platform::run({cli.string(), "version"}, true);
    return r.ok ? std::atoi(r.out.c_str()) : 0;
}

// The revision's files kicad-cli needs, in a temporary copy of the repo
// layout (so ${KIPRJMOD} model paths work): the board, its project file and
// every 3D model file. Returns the board's path in the copy.
fs::path checkout(const GitBoard& g, git::Revision& rev, const fs::path& dir, int major) {
    std::string rel = g.rel;
    std::optional<std::string> text = read_board_at(g.root, rel, rev);
    if (!text) {
        // Moved or renamed in this revision: the board most like the current one.
        std::optional<std::string> latest = read_disk(g.path);
        if (!latest) throw std::runtime_error(g.rel + " doesn't exist on disk or at " + rev.short_hash);
        BoardSource src = find_similar_board(g.root, rel, rev, load_board(*latest));
        warn(g.rel + " doesn't exist in " + rev.short_hash + ", using " + src.rel + " instead");
        rel = src.rel;
        text = std::move(src.text);
    }
    int moved = 0;
    write_file(dir / rel, modernize_model_paths(*text, major, &moved));
    if (moved) spdlog::info("3d: {} library model path(s) updated for KiCad {}", moved, major);
    // A file at this revision: from git, or from disk for the working tree.
    auto read = [&](const std::string& f) {
        return rev.local ? read_disk(fs::path(g.root) / f) : git::show(g.root, f, rev);
    };
    std::string pro = fs::path(rel).replace_extension(".kicad_pro").generic_string();
    if (auto p = read(pro)) write_file(dir / pro, *p);
    int models = 0;
    git::Revision listed = rev;
    if (rev.local) listed = git::resolve(g.root, "HEAD"); // the working tree has HEAD's files (and edits)
    for (const auto& f : git::list_files(g.root, listed)) {
        if (!is_model_file(f)) continue;
        if (auto m = read(f)) {
            write_file(dir / f, *m);
            ++models;
        }
    }
    spdlog::info("3d: {} at {} with {} model file(s) from the repo", rel, rev.short_hash, models);
    return dir / rel;
}

} // namespace

int run_board3d(const Options& o, const fs::path& project) {
    std::optional<fs::path> cli = platform::find_kicad_cli();
    if (!cli)
        throw std::runtime_error("the 3D view needs KiCad's kicad-cli (KiCad 8 or newer), which wasn't found.\n"
                                 "Install KiCad, or set KIGIT_KICAD_CLI to the path of kicad-cli.");
    if (o.output == "-") throw std::runtime_error("--3d writes a .glb file: give it a file name with -o");

    GitBoard g = git_board(project, o.board_args);
    git::Revision rev = git::resolve(g.root, o.revs[0]);
    fs::path out = o.output.empty() ? g.path.parent_path() / ".kigit" /
                                          (g.path.stem().string() + "-" + rev.short_hash + ".glb")
                                    : fs::path(expand_home(o.output));

    // Always a copy (also of the working tree), so model paths can be fixed
    // without touching the project.
    if (rev.local && !fs::exists(g.path)) throw std::runtime_error(g.path.string() + " doesn't exist");
    fs::path tmp = fs::temp_directory_path() /
                   ("kigit-3d-" + std::to_string(platform::process_id()) + "-" + rev.short_hash);
    fs::remove_all(tmp);
    fs::path input = checkout(g, rev, tmp, kicad_major(*cli));

    if (out.has_parent_path()) fs::create_directories(out.parent_path());
    std::vector<std::string> args{cli->string(), "pcb", "export", "glb", "--include-tracks", "--include-pads",
                                  "--include-zones", "--include-silkscreen", "--include-soldermask", "--force",
                                  "--output", out.string(), input.string()};
    spdlog::info("3d: running {}", cli->string());
    std::error_code ec;
    fs::remove(out, ec);
    // kicad-cli writes a scratch file ("$tempfile$.bin.tmp") next to its
    // output, so it writes into our own temp folder and the result is moved
    // into place: exports running at the same time (the GUI's side-by-side
    // view, all into one cache folder) would otherwise share that file.
    fs::path made = tmp / "board.glb";
    args[args.size() - 2] = made.string();
    platform::RunResult r = platform::run(args, true);
    // Parts whose 3D model KiCad couldn't find: "Could not add 3D model for
    // U405." then "File not found: <path>". Listed on stderr, one per line
    // ("missing 3D model: REF<tab>PATH"), for the GUI's notifications.
    std::vector<std::pair<std::string, std::string>> missing;
    for (const auto& text : {r.out, r.err}) {
        std::istringstream in(text);
        for (std::string l; std::getline(in, l);) {
            while (!l.empty() && (l.back() == '\r' || l.back() == ' ')) l.pop_back();
            if (l.empty()) continue;
            spdlog::info("kicad-cli: {}", l);
            static const std::string part = "Could not add 3D model for ", file = "File not found: ";
            if (l.rfind(part, 0) == 0) {
                std::string ref = l.substr(part.size());
                if (!ref.empty() && ref.back() == '.') ref.pop_back();
                missing.emplace_back(ref, "");
            } else if (l.rfind(file, 0) == 0 && !missing.empty() && missing.back().second.empty()) {
                missing.back().second = l.substr(file.size());
            }
        }
    }
    int no_model = static_cast<int>(missing.size());
    if (r.ok && fs::exists(made)) {
        fs::rename(made, out, ec);
        if (ec) { // another drive: copy instead
            ec.clear();
            fs::copy_file(made, out, fs::copy_options::overwrite_existing, ec);
        }
    }
    fs::remove_all(tmp, ec);
    if (!r.ok || !fs::exists(out))
        throw std::runtime_error("kicad-cli couldn't make the 3D board" + tail(r.err + "\n" + r.out));
    if (no_model) {
        warn(std::to_string(no_model) + (no_model == 1 ? " part has" : " parts have") +
             " no 3D model: KiCad couldn't find the file (the log lists them)");
        for (const auto& [ref, path] : missing) std::fprintf(stderr, "missing 3D model: %s\t%s\n", ref.c_str(), path.c_str());
    }
    if (!o.quiet) std::fprintf(stderr, "3D board of %s written\n", rev.short_hash.c_str());
    std::printf("%s\n", out.string().c_str());
    return 0;
}

int run_render(const Options& o, const fs::path& project) {
    // A picture of the board as it is on disk, for the GUI's recent
    // projects: KiCad's own 3D render, from the top, square (KiCad fits the
    // board to the width; square fits wide and tall boards alike).
    std::optional<fs::path> cli = platform::find_kicad_cli();
    if (!cli)
        throw std::runtime_error("a board picture needs KiCad's kicad-cli (KiCad 8 or newer), which wasn't found.\n"
                                 "Install KiCad, or set KIGIT_KICAD_CLI to the path of kicad-cli.");
    if (o.output.empty() || o.output == "-") throw std::runtime_error("--render writes a .png file: name it with -o");
    fs::path board = o.board_args.empty() ? find_board(project) : board_from_arg(o.board_args[0], project);
    if (!fs::exists(board)) throw std::runtime_error(board.string() + " doesn't exist");
    fs::path out = fs::absolute(expand_home(o.output));
    if (out.has_parent_path()) fs::create_directories(out.parent_path());
    // Rendered into our own temp folder and moved, like --3d: never half a
    // picture where the GUI reads it.
    fs::path tmp = fs::temp_directory_path() / ("kigit-render-" + std::to_string(platform::process_id()));
    fs::remove_all(tmp);
    fs::create_directories(tmp);
    fs::path made = tmp / "board.png";
    platform::RunResult r = platform::run({cli->string(), "pcb", "render", "--side", "top", "--width", "480",
                                           "--height", "480", "--background", "transparent", "--quality", "basic",
                                           "--zoom", "0.95", "--output", made.string(), fs::absolute(board).string()},
                                          true);
    for (const auto& text : {r.out, r.err}) {
        std::istringstream in(text);
        for (std::string l; std::getline(in, l);)
            if (!l.empty()) spdlog::debug("kicad-cli: {}", l);
    }
    std::error_code ec;
    if (r.ok && fs::exists(made)) {
        fs::rename(made, out, ec);
        if (ec) { ec.clear(); fs::copy_file(made, out, fs::copy_options::overwrite_existing, ec); }
    }
    fs::remove_all(tmp, ec);
    if (!r.ok || !fs::exists(out))
        throw std::runtime_error("kicad-cli couldn't render the board" + tail(r.err + "\n" + r.out));
    std::printf("%s\n", out.string().c_str());
    return 0;
}

} // namespace kigit::cmd

// `kigit example [DIR]`: makes the example project's git repository, to try
// kigit on. The project is shipped as one copy per commit
// (examples/blinky/steps/<n>/, made by tools/make_example.py) plus
// history.json, which says which copy is which commit; this commits them in
// order with fixed authors and dates (UTC), so every user gets the same
// commit hashes. Text in reviews (.md) can name commits as {{commit:N}} or
// {{short:N}}: filled in once that commit exists. The last copy is left
// uncommitted, to show the working tree.
#include "commands/commands.hpp"
#include "utils/platform.hpp"

#include <nlohmann/json.hpp>
#include <spdlog/spdlog.h>

#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>

namespace fs = std::filesystem;

namespace kigit::cmd {

namespace {

std::string read_all(const fs::path& p) {
    std::ifstream f(p, std::ios::binary);
    std::ostringstream s;
    s << f.rdbuf();
    return s.str();
}

// The shipped examples: $KIGIT_EXAMPLES_DIR, <prefix>/share/kigit/examples
// (installed), or <repo>/examples (build folder, or build/Release on Windows).
fs::path find_examples(const char* argv0) {
    fs::path exe = platform::executable_path(argv0).parent_path();
    std::vector<fs::path> candidates;
    if (const char* env = std::getenv("KIGIT_EXAMPLES_DIR"); env && *env) candidates.emplace_back(env);
    candidates.push_back(exe.parent_path() / "share" / "kigit" / "examples");
    candidates.push_back(exe.parent_path() / "examples");
    candidates.push_back(exe.parent_path().parent_path() / "examples");
    for (const auto& c : candidates)
        if (fs::exists(c / "blinky" / "history.json")) return c / "blinky";
    std::string where;
    for (const auto& c : candidates) where += " " + c.string();
    throw std::runtime_error("can't find the example project (looked in" + where +
                             "). Set KIGIT_EXAMPLES_DIR to kigit's examples folder.");
}

std::string fill(std::string text, const std::vector<std::string>& commits) {
    for (size_t i = 0; i < commits.size(); ++i)
        for (const auto& [key, value] :
             {std::pair{"{{commit:" + std::to_string(i + 1) + "}}", commits[i]},
              std::pair{"{{short:" + std::to_string(i + 1) + "}}", commits[i].substr(0, 7)}}) {
            for (size_t at; (at = text.find(key)) != std::string::npos;) text.replace(at, key.size(), value);
        }
    return text;
}

// The repository's files become this step's copy of the project.
void put_step(const fs::path& src, const fs::path& dest, const fs::path& folder,
              const std::vector<std::string>& commits) {
    for (const auto& e : fs::directory_iterator(dest))
        if (e.path().filename() != ".git") fs::remove_all(e.path());
    for (const auto& e : fs::recursive_directory_iterator(src)) {
        if (!e.is_regular_file()) continue;
        fs::path to = dest / folder / fs::relative(e.path(), src);
        fs::create_directories(to.parent_path());
        std::string data = read_all(e.path());
        if (e.path().extension() == ".md") data = fill(data, commits);
        std::ofstream(to, std::ios::binary) << data;
    }
}

std::string git(const fs::path& repo, std::vector<std::string> args) {
    // Same bytes on every OS: no line-ending conversion, no signing.
    args.insert(args.begin(), {"git", "-C", repo.string(), "-c", "core.autocrlf=false", "-c", "commit.gpgsign=false"});
    platform::RunResult r = platform::run(args, true);
    if (!r.ok) throw std::runtime_error("git " + args[7] + " failed: " + r.err);
    std::string out = r.out;
    while (!out.empty() && (out.back() == '\n' || out.back() == '\r')) out.pop_back();
    return out;
}

} // namespace

int run_example(const char* argv0, int argc, char** argv) {
    fs::path dest = "kigit-example";
    for (int i = 0; i < argc; ++i) {
        std::string a = argv[i];
        if (a == "-h" || a == "--help") {
            std::cout << "kigit example [DIR]   make the example project (a git repository) in DIR\n"
                         "                      (default: ./kigit-example), to try kigit on:\n"
                         "                      kigit gui DIR\n";
            return 0;
        }
        if (a == "--log-file" || a == "--log-dir") { // from the GUI: logging isn't needed here
            ++i;
            continue;
        }
        if (a == "--log-stderr" || a == "--no-log" || a == "-q" || a == "--quiet") continue;
        if (a.starts_with("-")) {
            std::cerr << "kigit: unknown option " << a << " (see kigit example --help)\n";
            return 2;
        }
        dest = a;
    }
    try {
        fs::path src = find_examples(argv0);
        nlohmann::json h = nlohmann::json::parse(read_all(src / "history.json"));
        dest = fs::absolute(dest);
        if (fs::exists(dest) && !fs::is_empty(dest))
            throw std::runtime_error(dest.string() + " already exists and isn't empty: pick another folder, or "
                                     "delete it to make the example again");
        fs::create_directories(dest);
        git(dest, {"init", "-q"});
        git(dest, {"symbolic-ref", "HEAD", "refs/heads/main"});
        const std::string name = h["author"]["name"], email = h["author"]["email"];
        for (const char* who : {"AUTHOR", "COMMITTER"}) {
            platform::set_env(std::string("GIT_") + who + "_NAME", name);
            platform::set_env(std::string("GIT_") + who + "_EMAIL", email);
        }
        std::vector<std::string> commits;
        fs::path folder;
        for (const auto& c : h["commits"]) {
            folder = c["folder"].get<std::string>();
            put_step(src / "steps" / std::to_string(c["step"].get<int>()), dest, folder, commits);
            platform::set_env("GIT_AUTHOR_DATE", c["date"]);
            platform::set_env("GIT_COMMITTER_DATE", c["date"]);
            git(dest, {"add", "-A"});
            git(dest, {"commit", "-q", "-m", c["message"].get<std::string>()});
            commits.push_back(git(dest, {"rev-parse", "HEAD"}));
            spdlog::info("example: {} {}", commits.back().substr(0, 7), c["message"].get<std::string>());
        }
        if (h.contains("uncommitted")) {
            folder = h["uncommitted"]["folder"].get<std::string>();
            put_step(src / "steps" / std::to_string(h["uncommitted"]["step"].get<int>()), dest, folder, commits);
        }
        std::fprintf(stderr, "The example project, %zu commits plus an uncommitted change: try `kigit gui %s`\n",
                     commits.size(), dest.string().c_str());
        std::printf("%s\n", (dest / folder).string().c_str());
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "kigit: " << e.what() << "\n";
        spdlog::error("{}", e.what());
        return 1;
    }
}

} // namespace kigit::cmd

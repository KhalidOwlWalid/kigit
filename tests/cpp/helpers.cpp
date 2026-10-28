#include "helpers.hpp"

#include "utils/platform.hpp"

#include <doctest/doctest.h>

#include <fstream>
#include <random>
#include <sstream>

namespace kigit::test {

fs::path fixture(const std::string& rel) { return fs::path(KIGIT_FIXTURES) / rel; }

std::string read_text(const fs::path& p) {
    std::ifstream f(p, std::ios::binary);
    REQUIRE_MESSAGE(f.good(), "cannot read " << p.string());
    std::ostringstream ss;
    ss << f.rdbuf();
    return ss.str();
}

void write_text(const fs::path& p, const std::string& text) {
    fs::create_directories(p.parent_path());
    std::ofstream f(p, std::ios::binary);
    REQUIRE_MESSAGE(f.good(), "cannot write " << p.string());
    f << text;
}

TempDir::TempDir() {
    std::random_device rd;
    for (int i = 0; i < 100; ++i) {
        fs::path p = fs::temp_directory_path() / ("kigit-test-" + std::to_string(rd()));
        if (fs::create_directory(p)) {
            path_ = p;
            return;
        }
    }
    FAIL("could not create a temporary folder");
}

TempDir::~TempDir() {
    std::error_code ec;
    fs::remove_all(path_, ec);
}

std::string quote(const std::string& s) { return platform::quote(s); }

RunResult run(const std::string& command) {
    // stderr into a file, which works the same in sh and cmd.exe.
    TempDir tmp;
    fs::path err_file = tmp / "stderr";
    platform::CommandResult c = platform::run_shell(command + " 2>" + quote(err_file.string()), true);
    RunResult r;
    r.code = c.code;
    r.out = c.out;
    std::error_code ec;
    if (fs::exists(err_file, ec)) r.err = read_text(err_file);
    return r;
}

RunResult run_kigit(const std::string& args) { return run(quote(KIGIT_BIN) + " " + args); }

void make_fixture_repo(const fs::path& dest) {
    // The demo project's history (fixed dates, so date filters are testable):
    //   2025-01-10  v1: first board        hw/demo.kicad_{pro,pcb,sch} (v1)
    //   2025-02-01  docs only              README.md
    //   2025-03-01  v2: board changes      hw/ -> v2 files
    //   2025-04-01  move project folder    hw/ -> board/
    // gui/tests/fixture_repo.py builds the same history for the GUI tests.
    auto git = [&](std::vector<std::string> args) {
        args.insert(args.begin(), {"git", "-C", dest.string()});
        platform::RunResult r = platform::run(args, true);
        REQUIRE_MESSAGE(r.ok, "git " << args[3] << " failed: " << r.err);
    };
    auto commit = [&](const std::string& date, const std::string& message) {
        platform::set_env("GIT_AUTHOR_DATE", date + "T12:00:00");
        platform::set_env("GIT_COMMITTER_DATE", date + "T12:00:00");
        git({"commit", "-q", "-m", message});
    };
    auto copy = [&](const std::string& from, const std::string& to) {
        fs::create_directories((dest / to).parent_path());
        fs::copy_file(fixture(from), dest / to, fs::copy_options::overwrite_existing);
    };

    fs::remove_all(dest);
    fs::create_directories(dest);
    git({"init", "-q"});
    git({"checkout", "-q", "-b", "main"});
    git({"config", "user.email", "tests@kigit.invalid"});
    git({"config", "user.name", "kigit tests"});
    git({"config", "commit.gpgsign", "false"});
    git({"config", "core.autocrlf", "false"}); // keep the files byte-identical on Windows

    copy("demo.kicad_pro", "hw/demo.kicad_pro");
    copy("v1/demo.kicad_pcb", "hw/demo.kicad_pcb");
    copy("v1/demo.kicad_sch", "hw/demo.kicad_sch");
    git({"add", "-A"});
    commit("2025-01-10", "v1: first board");

    write_text(dest / "README.md", "Demo project for the kigit tests.\n");
    git({"add", "-A"});
    commit("2025-02-01", "docs only");

    copy("v2/demo.kicad_pcb", "hw/demo.kicad_pcb");
    copy("v2/demo.kicad_sch", "hw/demo.kicad_sch");
    git({"add", "-A"});
    commit("2025-03-01", "v2: add C1, move R2, widen a track");

    git({"mv", "hw", "board"});
    commit("2025-04-01", "move project folder");
}

FileReader folder_reader(const fs::path& dir) {
    return [dir](const std::string& rel) -> std::optional<std::string> {
        std::ifstream f(dir / rel, std::ios::binary);
        if (!f) return std::nullopt;
        std::ostringstream ss;
        ss << f.rdbuf();
        return ss.str();
    };
}

} // namespace kigit::test

// Shared helpers for the kigit tests.
#pragma once

#include "schematic.hpp"

#include <filesystem>
#include <string>

namespace kigit::test {

namespace fs = std::filesystem;

// Path inside tests/fixtures.
fs::path fixture(const std::string& rel);

// Whole file as a string. Fails the test if it can't be read.
std::string read_text(const fs::path& p);
void write_text(const fs::path& p, const std::string& text);

// A fresh temporary folder, deleted when it goes out of scope.
class TempDir {
public:
    TempDir();
    ~TempDir();
    TempDir(const TempDir&) = delete;
    TempDir& operator=(const TempDir&) = delete;
    const fs::path& path() const { return path_; }
    fs::path operator/(const std::string& rel) const { return path_ / rel; }

private:
    fs::path path_;
};

// Builds the demo git repo (tests/make_fixture_repo.sh) in `dest`.
// Layout afterwards: dest/board/demo.kicad_{pro,pcb,sch}; see the script
// for the commit history.
void make_fixture_repo(const fs::path& dest);

struct RunResult {
    int code = -1;
    std::string out, err;
};

// Runs a shell command, capturing stdout, stderr and the exit code.
RunResult run(const std::string& command);

// Runs the kigit binary under test with the given (already quoted) arguments.
RunResult run_kigit(const std::string& args);

// Single-quotes a string for the shell.
std::string quote(const std::string& s);

// A schematic reader over a folder on disk (like kigit's own readers).
FileReader folder_reader(const fs::path& dir);

} // namespace kigit::test

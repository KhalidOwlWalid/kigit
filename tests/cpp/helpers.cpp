#include "helpers.hpp"

#include <doctest/doctest.h>

#include <array>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <random>
#include <sstream>
#include <sys/wait.h>

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

std::string quote(const std::string& s) {
    std::string out = "'";
    for (char c : s) out += c == '\'' ? std::string("'\\''") : std::string(1, c);
    return out + "'";
}

RunResult run(const std::string& command) {
    TempDir tmp;
    fs::path err_file = tmp / "stderr";
    RunResult r;
    FILE* p = popen((command + " 2>" + quote(err_file.string())).c_str(), "r");
    REQUIRE(p != nullptr);
    std::array<char, 1 << 16> buf;
    size_t n;
    while ((n = std::fread(buf.data(), 1, buf.size(), p)) > 0) r.out.append(buf.data(), n);
    int status = pclose(p);
    r.code = WIFEXITED(status) ? WEXITSTATUS(status) : -1;
    std::error_code ec;
    if (fs::exists(err_file, ec)) r.err = read_text(err_file);
    return r;
}

RunResult run_kigit(const std::string& args) { return run(quote(KIGIT_BIN) + " " + args); }

void make_fixture_repo(const fs::path& dest) {
    RunResult r = run("sh " + quote(KIGIT_MAKE_REPO) + " " + quote(dest.string()));
    REQUIRE_MESSAGE(r.code == 0, "make_fixture_repo.sh failed: " << r.err);
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

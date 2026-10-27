#include "git.hpp"

#include <array>
#include <cstdio>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <sys/wait.h>

namespace kigit::git {

namespace {

std::string quote(const std::string& s) {
    std::string out = "'";
    for (char c : s) {
        if (c == '\'') out += "'\\''";
        else out += c;
    }
    return out + "'";
}

// Runs a shell command and returns stdout. `ok` receives success.
std::string run(const std::string& cmd, bool& ok) {
    std::string out;
    FILE* p = popen((cmd + " 2>/dev/null").c_str(), "r");
    if (!p) {
        ok = false;
        return out;
    }
    std::array<char, 1 << 16> buf;
    size_t n;
    while ((n = std::fread(buf.data(), 1, buf.size(), p)) > 0) out.append(buf.data(), n);
    int status = pclose(p);
    ok = status != -1 && WIFEXITED(status) && WEXITSTATUS(status) == 0;
    return out;
}

std::string git(const std::string& dir, const std::string& args, bool& ok) {
    return run("git -C " + quote(dir) + " " + args, ok);
}

} // namespace

Revision resolve(const std::string& dir, const std::string& spec) {
    Revision r;
    r.spec = spec;
    if (spec == "LOCAL" || spec == "local" || spec == "WORKTREE") {
        r.local = true;
        r.short_hash = "LOCAL";
        r.subject = "Working tree (uncommitted)";
        return r;
    }
    bool ok;
    std::string info = git(dir, "log -1 --format=%H%n%h%n%ci%n%s " + quote(spec + "^{commit}") + " --", ok);
    if (!ok || info.empty()) throw std::runtime_error("unknown revision '" + spec + "'");
    std::istringstream in(info);
    std::getline(in, r.hash);
    std::getline(in, r.short_hash);
    std::getline(in, r.date);
    std::getline(in, r.subject);
    return r;
}

std::string read_file(const std::string& dir, const std::string& file, const Revision& rev) {
    if (rev.local) {
        std::ifstream f(dir + "/" + file, std::ios::binary);
        if (!f) throw std::runtime_error("cannot read " + dir + "/" + file);
        std::ostringstream ss;
        ss << f.rdbuf();
        return ss.str();
    }
    bool ok;
    std::string text = git(dir, "show " + quote(rev.hash + ":./" + file), ok);
    if (!ok) throw std::runtime_error(file + " does not exist at " + rev.short_hash);
    return text;
}

bool is_ancestor(const std::string& dir, const Revision& ancestor, const Revision& descendant) {
    if (ancestor.local || descendant.local) return descendant.local && !ancestor.local;
    bool ok;
    git(dir, "merge-base --is-ancestor " + quote(ancestor.hash) + " " + quote(descendant.hash), ok);
    return ok;
}

} // namespace kigit::git

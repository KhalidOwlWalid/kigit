#include "git.hpp"

#include <algorithm>
#include <array>
#include <cstdlib>
#include <optional>
#include <sstream>
#include <vector>
#include <cstdio>
#include <ctime>
#include <sys/stat.h>
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

Revision from_file(const std::string& path, const std::string& label) {
    Revision r;
    r.spec = path;
    r.local = true;
    r.path = path;
    r.short_hash = label;
    r.subject = path;
    struct stat st {};
    if (::stat(path.c_str(), &st) == 0) {
        char buf[32];
        std::strftime(buf, sizeof buf, "%Y-%m-%d %H:%M:%S", std::localtime(&st.st_mtime));
        r.date = std::string("modified ") + buf;
    }
    return r;
}

bool is_repo(const std::string& dir) {
    bool ok;
    std::string out = git(dir, "rev-parse --is-inside-work-tree", ok);
    return ok && out.starts_with("true");
}

std::string read_file(const std::string& dir, const std::string& file, const Revision& rev) {
    if (rev.local) {
        std::string p = rev.path.empty() ? dir + "/" + file : rev.path;
        std::ifstream f(p, std::ios::binary);
        if (!f) throw std::runtime_error("cannot read " + p);
        std::ostringstream ss;
        ss << f.rdbuf();
        return ss.str();
    }
    bool ok;
    std::string text = git(dir, "show " + quote(rev.hash + ":./" + file), ok);
    if (!ok) throw std::runtime_error(file + " does not exist at " + rev.short_hash);
    return text;
}

std::string toplevel(const std::string& dir) {
    bool ok;
    std::string out = git(dir, "rev-parse --show-toplevel", ok);
    while (!out.empty() && (out.back() == '\n' || out.back() == '\r')) out.pop_back();
    if (!ok || out.empty()) throw std::runtime_error(dir + " is not in a git repository");
    return out;
}

std::optional<std::string> show(const std::string& root, const std::string& rel, const Revision& rev) {
    bool ok;
    std::string text = git(root, "show " + quote(rev.hash + ":" + rel), ok);
    if (!ok) return std::nullopt;
    return text;
}

std::vector<std::string> list_files(const std::string& root, const Revision& rev) {
    bool ok;
    std::string out = git(root, "ls-tree -r -z --name-only --full-tree " + quote(rev.hash), ok);
    std::vector<std::string> files;
    if (!ok) return files;
    size_t start = 0;
    for (size_t i = 0; i < out.size(); ++i) {
        if (out[i] == '\0') {
            if (i > start) files.push_back(out.substr(start, i - start));
            start = i + 1;
        }
    }
    return files;
}

namespace {

std::string query_args(const LogQuery& q) {
    std::string a;
    if (q.max_count > 0) a += " -n " + std::to_string(q.max_count);
    if (!q.since.empty()) a += " --since=" + quote(q.since);
    if (!q.until.empty()) a += " --until=" + quote(q.until);
    return a;
}

std::string path_args(const LogQuery& q) {
    if (q.paths.empty()) return {};
    std::string a = " --";
    for (const auto& p : q.paths) a += " " + quote(p);
    return a;
}

} // namespace

int count(const std::string& root, const LogQuery& q) {
    LogQuery all = q;
    all.max_count = 0;
    bool ok;
    std::string out = git(root, "rev-list --count HEAD" + query_args(all) + path_args(all), ok);
    return ok ? std::atoi(out.c_str()) : 0;
}

std::vector<std::string> past_paths(const std::string& root, const std::string& file) {
    bool ok;
    std::string out = git(root, "log --follow --format= --name-only -- " + quote(file), ok);
    std::vector<std::string> paths;
    std::istringstream in(out);
    std::string line;
    while (std::getline(in, line))
        if (!line.empty() && std::find(paths.begin(), paths.end(), line) == paths.end()) paths.push_back(line);
    return paths;
}

std::vector<Commit> log(const std::string& root, const LogQuery& q) {
    // One record per commit: \x1e starts it, header fields are separated by
    // \x1f, \x1d ends the message, then the changed files one per line.
    bool ok;
    std::string out = git(root, "log" + query_args(q) +
                                    " --format=%x1e%H%x1f%h%x1f%ci%x1f%an%x1f%s%x1f%b%x1d --name-only --diff-merges=first-parent" +
                                    path_args(q),
                          ok);
    std::vector<Commit> commits;
    if (!ok) return commits;
    size_t pos = 0;
    while ((pos = out.find('\x1e', pos)) != std::string::npos) {
        size_t end = out.find('\x1e', pos + 1);
        std::string rec = out.substr(pos + 1, end == std::string::npos ? std::string::npos : end - pos - 1);
        pos = end == std::string::npos ? out.size() : end;
        size_t msg_end = rec.find('\x1d');
        std::string header = rec.substr(0, msg_end);
        Commit c;
        std::vector<std::string*> fields{&c.hash, &c.short_hash, &c.date, &c.author, &c.subject, &c.body};
        size_t start = 0;
        for (size_t i = 0; i < fields.size(); ++i) {
            size_t sep = i + 1 < fields.size() ? header.find('\x1f', start) : std::string::npos;
            *fields[i] = header.substr(start, sep == std::string::npos ? std::string::npos : sep - start);
            if (sep == std::string::npos) break;
            start = sep + 1;
        }
        while (!c.body.empty() && (c.body.back() == '\n' || c.body.back() == ' ')) c.body.pop_back();
        if (msg_end != std::string::npos) {
            std::istringstream in(rec.substr(msg_end + 1));
            std::string line;
            while (std::getline(in, line))
                if (!line.empty()) c.files.push_back(line);
        }
        commits.push_back(std::move(c));
    }
    return commits;
}

std::vector<std::string> changed_files(const std::string& root, const std::string& pathspec) {
    bool ok;
    std::string out = git(root, "status --porcelain -z -- " + quote(pathspec), ok);
    std::vector<std::string> files;
    if (!ok) return files;
    // Entries are "XY path\0"; renames add "\0old path".
    size_t i = 0;
    while (i + 3 < out.size()) {
        size_t end = out.find('\0', i);
        if (end == std::string::npos) break;
        char x = out[i];
        files.push_back(out.substr(i + 3, end - i - 3));
        i = end + 1;
        if (x == 'R' || x == 'C') i = out.find('\0', i) + 1;
    }
    return files;
}

bool is_ancestor(const std::string& dir, const Revision& ancestor, const Revision& descendant) {
    if (ancestor.local || descendant.local) return descendant.local && !ancestor.local;
    bool ok;
    git(dir, "merge-base --is-ancestor " + quote(ancestor.hash) + " " + quote(descendant.hash), ok);
    return ok;
}

} // namespace kigit::git

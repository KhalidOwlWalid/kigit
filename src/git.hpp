// Thin wrapper around the git command line.
#pragma once

#include <optional>
#include <string>
#include <vector>

namespace kigit::git {

// A revision to compare. "LOCAL" means the file on disk (working tree).
struct Revision {
    std::string spec;       // what the user typed, e.g. "HEAD~1"
    bool local = false;
    std::string hash;       // full hash ("" for LOCAL)
    std::string short_hash; // "LOCAL" for the working tree
    std::string subject;    // commit message first line
    std::string date;       // commit date, ISO-ish
    std::string path;       // set in --files mode: read this file, no git involved
    std::string board_rel;  // where the board was found, from the repo root
};

// A revision that is just a file on disk (no git). `label` is shown in the viewer.
Revision from_file(const std::string& path, const std::string& label);

// True if `dir` is inside a git work tree.
bool is_repo(const std::string& dir);

// Resolves `spec` in the repository containing `dir`. Throws on failure.
Revision resolve(const std::string& dir, const std::string& spec);

// Contents of `file` (relative to `dir`) at `rev`. Throws on failure.
std::string read_file(const std::string& dir, const std::string& file, const Revision& rev);

// Absolute path of the repository root containing `dir`. Throws if none.
std::string toplevel(const std::string& dir);

// Contents of `rel` (path from the repo root) at commit `rev`, or nullopt if
// the file doesn't exist in that commit.
std::optional<std::string> show(const std::string& root, const std::string& rel, const Revision& rev);

// Every file path (from the repo root) in commit `rev`.
std::vector<std::string> list_files(const std::string& root, const Revision& rev);

// A commit that touched the project, newest first.
struct Commit {
    std::string hash, short_hash, date, author, subject;
    std::string body;               // rest of the commit message after the subject
    std::vector<std::string> files; // changed paths (from the repo root)
};

// Which commits log() returns.
struct LogQuery {
    std::vector<std::string> paths; // only commits touching these (git pathspecs); empty = all
    int max_count = 0;              // 0 = no limit
    std::string since, until;       // dates git understands ("2025-01-31", "2 weeks ago"); "" = open
};

// Commits in HEAD's history, newest first.
std::vector<Commit> log(const std::string& root, const LogQuery& q);

// How many commits log() would return without max_count.
int count(const std::string& root, const LogQuery& q);

// Every path `file` has had in HEAD's history, following renames (newest first).
std::vector<std::string> past_paths(const std::string& root, const std::string& file);

// Uncommitted changed/untracked paths under `pathspec`.
std::vector<std::string> changed_files(const std::string& root, const std::string& pathspec);

// True if commit `ancestor` is an ancestor of `descendant`.
bool is_ancestor(const std::string& dir, const Revision& ancestor, const Revision& descendant);

} // namespace kigit::git

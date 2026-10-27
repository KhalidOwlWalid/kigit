// Thin wrapper around the git command line.
#pragma once

#include <string>

namespace kigit::git {

// A revision to compare. "LOCAL" means the file on disk (working tree).
struct Revision {
    std::string spec;       // what the user typed, e.g. "HEAD~1"
    bool local = false;
    std::string hash;       // full hash ("" for LOCAL)
    std::string short_hash; // "LOCAL" for the working tree
    std::string subject;    // commit message first line
    std::string date;       // commit date, ISO-ish
};

// Resolves `spec` in the repository containing `dir`. Throws on failure.
Revision resolve(const std::string& dir, const std::string& spec);

// Contents of `file` (relative to `dir`) at `rev`. Throws on failure.
std::string read_file(const std::string& dir, const std::string& file, const Revision& rev);

// True if commit `ancestor` is an ancestor of `descendant`.
bool is_ancestor(const std::string& dir, const Revision& ancestor, const Revision& descendant);

} // namespace kigit::git

// Minimal S-expression parser for KiCad files.
//
// KiCad stores boards as nested lists: (name arg arg (child ...) ...).
// Atoms are views into the source text, so the text must outlive the tree.
#pragma once

#include <string>
#include <string_view>
#include <vector>

namespace kigit::sexpr {

struct Node {
    std::string_view atom;      // atom text (quotes stripped), empty for lists
    std::vector<Node> children; // list items
    bool is_list = false;
    bool quoted = false;        // atom was written as "..."

    // Name of a list: its first atom, e.g. "segment" for (segment ...).
    std::string_view name() const;

    // First child list with the given name, or nullptr.
    const Node* child(std::string_view name) const;

    // All child lists with the given name.
    template <typename F>
    void each(std::string_view name, F&& fn) const {
        for (const Node& c : children)
            if (c.is_list && c.name() == name) fn(c);
    }

    // i-th argument after the name: (name arg0 arg1 ...). Empty if missing.
    std::string_view arg(size_t i) const;
    const Node* arg_node(size_t i) const;
    size_t arg_count() const { return children.empty() ? 0 : children.size() - 1; }

    // Numeric argument, or `fallback` if missing or not a number.
    double num(size_t i, double fallback = 0.0) const;
};

// Parses the whole text. Returns a list node whose children are the
// top-level expressions. Throws std::runtime_error on malformed input.
Node parse(std::string_view text);

// Resolves backslash escapes in a quoted atom (\" \\ \n).
std::string unescape(std::string_view atom);

// A node written out in a normal form, for comparing two versions of
// something: child lists named in `skip` (e.g. "uuid") are left out, and
// numbers are normalised (1.0 and 1 are the same), so only real differences
// show. Strings are always quoted.
std::string canonical(const Node& n, const std::vector<std::string_view>& skip = {"uuid", "tstamp"});

} // namespace kigit::sexpr

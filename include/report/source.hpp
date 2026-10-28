// Source text of changed items, for the viewer's side-by-side source panel
// (--source): each item's text in the old and the new file, with line numbers.
#pragma once

#include "utils/sexpr.hpp" // Span

#include <nlohmann/json.hpp>

#include <map>
#include <string>
#include <string_view>
#include <tuple>
#include <vector>

namespace kigit {

// One file's text, with its line starts for turning offsets into line numbers.
class SourceFile {
public:
    SourceFile(std::string name, std::string_view text);

    const std::string& name() const { return name_; }

    // 1-based line of byte offset `at`.
    int line_of(size_t at) const;

    // The whole lines covering `span` (indentation included, no trailing
    // newline), as [file name, first line, text]. Null if the span is empty.
    nlohmann::json snippet(Span span) const;

private:
    std::string name_;
    std::string_view text_;
    std::vector<size_t> line_starts_;
};

// The snippets of one view, as a list the viewer looks up by index. Each
// entry is one item's old and new text:
//   {"k": "track · GND", "o": [file, line, text] | null, "n": [...] | null}
// plus "cut": 1 when the text stops early (a zone's fill isn't included).
class SourceTable {
public:
    // Adds (or finds) the entry for this old/new pair. Either side may be
    // missing (added or removed items). Returns its index, or -1 if both are.
    int add(const std::string& label, const SourceFile* old_file, Span old_span, const SourceFile* new_file,
            Span new_span, bool cut = false);

    const nlohmann::json& entries() const { return entries_; }
    bool empty() const { return entries_.empty(); }

private:
    nlohmann::json entries_ = nlohmann::json::array();
    std::map<std::tuple<const SourceFile*, size_t, const SourceFile*, size_t>, int> index_;
};

} // namespace kigit

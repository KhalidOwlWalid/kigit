#include "report/source.hpp"

#include <algorithm>

namespace kigit {

SourceFile::SourceFile(std::string name, std::string_view text) : name_(std::move(name)), text_(text) {
    line_starts_.push_back(0);
    for (size_t i = 0; i < text_.size(); ++i)
        if (text_[i] == '\n') line_starts_.push_back(i + 1);
}

int SourceFile::line_of(size_t at) const {
    auto it = std::upper_bound(line_starts_.begin(), line_starts_.end(), at);
    return static_cast<int>(it - line_starts_.begin());
}

nlohmann::json SourceFile::snippet(Span span) const {
    if (span.empty() || span.begin >= text_.size()) return nullptr;
    size_t end = std::min(span.end, text_.size());
    int first = line_of(span.begin);
    size_t from = line_starts_[first - 1];
    // To the end of the line holding the last non-blank character (a span cut
    // just before the next item, like a zone before its fill, ends in blanks).
    size_t last = end - 1;
    auto blank = [](char c) { return c == ' ' || c == '\t' || c == '\n' || c == '\r'; };
    while (last > from && blank(text_[last])) --last;
    size_t to = text_.find('\n', last);
    if (to == std::string_view::npos) to = text_.size();
    std::string text(text_.substr(from, to - from));
    // Windows line endings: keep the lines, drop the \r.
    text.erase(std::remove(text.begin(), text.end(), '\r'), text.end());
    return nlohmann::json::array({name_, first, text});
}

int SourceTable::add(const std::string& label, const SourceFile* old_file, Span old_span, const SourceFile* new_file,
                     Span new_span, bool cut) {
    if (!old_file || old_span.empty()) old_file = nullptr;
    if (!new_file || new_span.empty()) new_file = nullptr;
    if (!old_file && !new_file) return -1;
    auto key = std::make_tuple(old_file, old_file ? old_span.begin : 0, new_file, new_file ? new_span.begin : 0);
    if (auto f = index_.find(key); f != index_.end()) return f->second;
    nlohmann::json e = {{"k", label},
                        {"o", old_file ? old_file->snippet(old_span) : nlohmann::json(nullptr)},
                        {"n", new_file ? new_file->snippet(new_span) : nlohmann::json(nullptr)}};
    if (cut) e["cut"] = 1;
    int index = static_cast<int>(entries_.size());
    entries_.push_back(std::move(e));
    index_.emplace(key, index);
    return index;
}

} // namespace kigit

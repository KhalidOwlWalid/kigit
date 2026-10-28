#include "sexpr.hpp"

#include <algorithm>
#include <charconv>
#include <cstdio>
#include <locale>
#include <sstream>
#include <stdexcept>

namespace kigit::sexpr {

namespace {

// A whole atom as a number. std::from_chars where the standard library has
// it for floating point (GCC, MSVC); a locale-independent stream otherwise
// (Apple's libc++ only gained it recently).
bool parse_number(std::string_view s, double& v) {
    if (s.empty()) return false;
#if defined(__cpp_lib_to_chars) && __cpp_lib_to_chars >= 201611L
    auto [ptr, ec] = std::from_chars(s.data(), s.data() + s.size(), v);
    return ec == std::errc{} && ptr == s.data() + s.size();
#else
    std::istringstream in{std::string(s)};
    in.imbue(std::locale::classic());
    in >> v;
    return !in.fail() && in.peek() == std::char_traits<char>::eof();
#endif
}

} // namespace

std::string_view Node::name() const {
    if (!is_list || children.empty() || children[0].is_list) return {};
    return children[0].atom;
}

const Node* Node::child(std::string_view n) const {
    for (const Node& c : children)
        if (c.is_list && c.name() == n) return &c;
    return nullptr;
}

const Node* Node::arg_node(size_t i) const {
    return i + 1 < children.size() ? &children[i + 1] : nullptr;
}

std::string_view Node::arg(size_t i) const {
    const Node* n = arg_node(i);
    return (n && !n->is_list) ? n->atom : std::string_view{};
}

double Node::num(size_t i, double fallback) const {
    std::string_view s = arg(i);
    if (s.empty()) return fallback;
    double v = fallback;
    return parse_number(s, v) ? v : fallback;
}

namespace {

class Parser {
public:
    explicit Parser(std::string_view t) : text_(t) {}

    Node parse_all() {
        Node root;
        root.is_list = true;
        // Explicit stack instead of recursion, so deep nesting can't overflow.
        std::vector<Node*> stack{&root};
        while (true) {
            skip_space();
            if (pos_ >= text_.size()) break;
            char c = text_[pos_];
            if (c == '(') {
                ++pos_;
                Node& n = stack.back()->children.emplace_back();
                n.is_list = true;
                stack.push_back(&n);
            } else if (c == ')') {
                ++pos_;
                if (stack.size() == 1) fail("unexpected ')'");
                stack.pop_back();
            } else {
                stack.back()->children.push_back(read_atom());
            }
        }
        if (stack.size() != 1) fail("unclosed '('");
        return root;
    }

private:
    void skip_space() {
        while (pos_ < text_.size()) {
            char c = text_[pos_];
            if (c == ' ' || c == '\t' || c == '\n' || c == '\r') {
                ++pos_;
            } else {
                break;
            }
        }
    }

    Node read_atom() {
        Node n;
        if (text_[pos_] == '"') {
            size_t start = ++pos_;
            while (pos_ < text_.size() && text_[pos_] != '"') {
                if (text_[pos_] == '\\') ++pos_; // skip escaped char
                ++pos_;
            }
            if (pos_ >= text_.size()) fail("unterminated string");
            n.atom = text_.substr(start, pos_ - start);
            n.quoted = true;
            ++pos_; // closing quote
        } else {
            size_t start = pos_;
            while (pos_ < text_.size()) {
                char c = text_[pos_];
                if (c == '(' || c == ')' || c == ' ' || c == '\t' || c == '\n' || c == '\r') break;
                ++pos_;
            }
            n.atom = text_.substr(start, pos_ - start);
        }
        return n;
    }

    [[noreturn]] void fail(const char* what) const {
        size_t line = 1;
        for (size_t i = 0; i < pos_ && i < text_.size(); ++i)
            if (text_[i] == '\n') ++line;
        throw std::runtime_error(std::string("s-expression parse error: ") + what +
                                 " at line " + std::to_string(line));
    }

    std::string_view text_;
    size_t pos_ = 0;
};

} // namespace

Node parse(std::string_view text) { return Parser(text).parse_all(); }

std::string unescape(std::string_view atom) {
    std::string out;
    out.reserve(atom.size());
    for (size_t i = 0; i < atom.size(); ++i) {
        if (atom[i] == '\\' && i + 1 < atom.size()) {
            char e = atom[++i];
            out += (e == 'n') ? '\n' : e;
        } else {
            out += atom[i];
        }
    }
    return out;
}

namespace {

void write_canonical(const Node& n, const std::vector<std::string_view>& skip, std::string& out) {
    if (!n.is_list) {
        double v;
        if (!n.quoted && parse_number(n.atom, v)) {
            char buf[32];
            int len = std::snprintf(buf, sizeof buf, "%.6f", v);
            std::string num(buf, len);
            while (!num.empty() && num.back() == '0') num.pop_back();
            if (!num.empty() && num.back() == '.') num.pop_back();
            if (num == "-0") num = "0";
            out += num;
        } else {
            out += '"';
            out += unescape(n.atom);
            out += '"';
        }
        return;
    }
    out += '(';
    bool first = true;
    for (const Node& c : n.children) {
        if (c.is_list && std::find(skip.begin(), skip.end(), c.name()) != skip.end()) continue;
        if (!first) out += ' ';
        first = false;
        write_canonical(c, skip, out);
    }
    out += ')';
}

} // namespace

std::string canonical(const Node& n, const std::vector<std::string_view>& skip) {
    std::string out;
    write_canonical(n, skip, out);
    return out;
}

} // namespace kigit::sexpr

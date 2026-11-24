#include "net/http.hpp"

#include "utils/platform.hpp"

#include <spdlog/spdlog.h>

#include <cctype>
#include <cstdlib>
#include <optional>

namespace kigit::net {

namespace {

// A quoted string in curl's config syntax.
std::string quoted(const std::string& s) {
    std::string out = "\"";
    for (char c : s) {
        switch (c) {
        case '"': out += "\\\""; break;
        case '\\': out += "\\\\"; break;
        case '\n': out += "\\n"; break;
        case '\r': out += "\\r"; break;
        case '\t': out += "\\t"; break;
        default: out += c;
        }
    }
    return out + "\"";
}

std::string trim(std::string s) {
    while (!s.empty() && (s.back() == '\n' || s.back() == '\r' || s.back() == ' ')) s.pop_back();
    return s;
}

} // namespace

std::string url_encode(const std::string& s) {
    static const char* hex = "0123456789ABCDEF";
    std::string out;
    for (unsigned char c : s) {
        if (std::isalnum(c) || c == '-' || c == '_' || c == '.' || c == '~') {
            out += static_cast<char>(c);
        } else {
            out += '%';
            out += hex[c >> 4];
            out += hex[c & 15];
        }
    }
    return out;
}

std::string redact(std::string text, const std::vector<std::string>& secrets) {
    for (const auto& s : secrets) {
        if (s.empty()) continue;
        for (size_t at = text.find(s); at != std::string::npos; at = text.find(s, at + 3)) text.replace(at, s.size(), "***");
    }
    return text;
}

std::string curl_config(const HttpRequest& rq) {
    std::string c;
    c += "url = " + quoted(rq.url) + "\n";
    c += "request = " + quoted(rq.method) + "\n";
    c += "silent\nshow-error\n";
    c += "max-time = " + std::to_string(rq.timeout) + "\n";
    for (const auto& h : rq.headers) c += "header = " + quoted(h) + "\n";
    if (!rq.body.empty()) c += "data-binary = " + quoted(rq.body) + "\n";
    c += "write-out = \"\\n%{http_code}\"\n"; // the status, on a line after the body
    return c;
}

HttpResponse curl_http(const HttpRequest& rq) {
    HttpResponse r;
    std::optional<std::filesystem::path> curl;
    if (const char* e = std::getenv("KIGIT_CURL"); e && *e) curl = std::filesystem::path(e);
    else curl = platform::find_program("curl");
    if (!curl) {
        r.error = "curl isn't installed (kigit uses it to talk to the parts sites)";
        return r;
    }
    platform::RunResult run = platform::run_input({curl->string(), "-K", "-"}, curl_config(rq), true);
    size_t nl = run.out.rfind('\n');
    std::string code = nl == std::string::npos ? run.out : run.out.substr(nl + 1);
    r.body = nl == std::string::npos ? "" : run.out.substr(0, nl);
    try {
        r.status = std::stoi(code);
    } catch (const std::exception&) {
        r.status = 0;
    }
    if (!run.ok || r.status == 0) {
        std::string why = trim(run.err);
        if (why.empty()) why = run.code < 0 ? "could not run " + curl->string() : "curl failed (exit " + std::to_string(run.code) + ")";
        r.error = redact(why, rq.secrets);
        r.status = 0;
    }
    // The address without its query: keys can be in it (Mouser's is).
    std::string where = rq.url.substr(0, rq.url.find('?'));
    if (r.error.empty()) spdlog::debug("http: {} {} -> {} ({} bytes)", rq.method, where, r.status, r.body.size());
    else spdlog::debug("http: {} {} -> no answer: {}", rq.method, where, r.error);
    return r;
}

} // namespace kigit::net

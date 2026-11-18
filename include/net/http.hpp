#pragma once
// HTTPS requests, made by the curl program (on PATH on Windows 10+ and Linux).
// Everything about a request, the address included, goes to curl on its
// standard input, so keys never show on a command line.
#include <functional>
#include <string>
#include <vector>

namespace kigit::net {

struct HttpRequest {
    std::string method = "GET";
    std::string url;
    std::vector<std::string> headers; // "Name: value"
    std::string body;
    int timeout = 30;                  // seconds
    std::vector<std::string> secrets;  // taken out of error messages
};

struct HttpResponse {
    int status = 0;    // HTTP status; 0 if there was no answer
    std::string body;
    std::string error; // why there was no answer (curl's message), else ""
};

// Something that makes requests: curl_http, or a stand-in in tests.
using Http = std::function<HttpResponse(const HttpRequest&)>;

// Makes the request with curl: $KIGIT_CURL, else curl on PATH.
HttpResponse curl_http(const HttpRequest& request);

// The config curl reads for a request (`curl -K -`).
std::string curl_config(const HttpRequest& request);

// Percent-encodes everything but letters, digits and -_.~
std::string url_encode(const std::string& s);

// `text` with each secret replaced by "***".
std::string redact(std::string text, const std::vector<std::string>& secrets);

} // namespace kigit::net

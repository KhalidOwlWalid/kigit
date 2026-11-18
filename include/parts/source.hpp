#pragma once
// A parts site kigit can ask: Mouser, Digi-Key. Each turns its own API into
// Offers; lookup() does the rest the same way for all of them.
#include "net/http.hpp"
#include "parts/offer.hpp"

#include <chrono>
#include <string>
#include <vector>

namespace kigit::parts {

struct Search {
    std::vector<Offer> offers;
    std::string error;  // "" if the search worked (it may still find nothing)
    bool fatal = false; // a bad key, the daily limit, no network: don't ask again this run
};

class Source {
public:
    Source(net::Http http, int pace_ms) : http_(std::move(http)), pace_(pace_ms) {}
    virtual ~Source() = default;
    virtual std::string site() const = 0;
    // By the site's own number or a manufacturer's part number.
    virtual Search part_number(const std::string& pn) = 0;
    // By words: "10k 0603 resistor".
    virtual Search keyword(const std::string& words) = 0;
    // Parts the site suggests instead of this one (none if it has no such thing).
    virtual Search substitutes(const Offer&) { return {}; }
    virtual bool has_substitutes() const { return false; }
    int calls() const { return calls_; }

protected:
    // Sends a request, waiting first so calls are at least pace apart.
    net::HttpResponse send(const net::HttpRequest& rq);
    net::Http http_;
    std::chrono::milliseconds pace_;
    std::chrono::steady_clock::time_point last_{};
    int calls_ = 0;
};

} // namespace kigit::parts

#pragma once
// Mouser's Search API (v1): https://api.mouser.com/api/docs/ui/index
// A free key from a Mouser account ("APIs" in My Account). Limits: 30 calls
// a minute, 1000 a day, so calls are spaced out.
#include "net/http.hpp"
#include "parts/offer.hpp"

#include <chrono>
#include <string>
#include <vector>

namespace kigit::parts {

struct Search {
    std::vector<Offer> offers;
    std::string error;  // "" if the search worked (it may still find nothing)
    bool fatal = false; // a bad key or the daily limit: don't ask again this run
};

// The parts in a search reply. Errors in the reply go to `error`.
std::vector<Offer> parse_mouser(const nlohmann::json& reply, std::string& error);

class Mouser {
public:
    // pace_ms: the least time between two calls.
    Mouser(std::string key, net::Http http, int pace_ms = 2100);
    // By Mouser's own number or a manufacturer's part number, exact.
    Search part_number(const std::string& pn);
    // By words: "10k 0603 resistor".
    Search keyword(const std::string& words, int records = 10);
    int calls() const { return calls_; }

private:
    Search post(const std::string& path, const nlohmann::json& body);
    std::string key_;
    net::Http http_;
    std::chrono::milliseconds pace_;
    std::chrono::steady_clock::time_point last_{};
    int calls_ = 0;
};

} // namespace kigit::parts

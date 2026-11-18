#pragma once
// Digi-Key's Product Information API (v4): https://developer.digikey.com/
// A free app on Digi-Key's developer site (Production, Product Information
// v4) gives a client ID and secret; kigit swaps them for a token (OAuth
// client credentials, no browser sign-in). Limits: about 120 calls a
// minute and 1000 a day, so calls are spaced out.
#include "parts/source.hpp"

#include <chrono>
#include <string>
#include <vector>

namespace kigit::parts {

struct DigiKeyLogin {
    std::string client_id, client_secret;
    std::string site = "US", language = "en", currency = "USD"; // prices in this site's currency
};

// One offer per packaging (cut tape, reel, ...) of each product in a keyword
// search reply, exact matches first. Digi-Reel is left out: it's cut tape
// on a reel for a fee.
std::vector<Offer> parse_digikey(const nlohmann::json& reply);

// The parts in a substitutions reply.
std::vector<Offer> parse_digikey_substitutes(const nlohmann::json& reply);

class DigiKey : public Source {
public:
    DigiKey(DigiKeyLogin login, net::Http http, int pace_ms = 600);
    std::string site() const override { return "digikey"; }
    Search part_number(const std::string& pn) override;
    Search keyword(const std::string& words) override;
    Search substitutes(const Offer& o) override;
    bool has_substitutes() const override { return true; }

private:
    // A request to the API, with a token (got first, or again if it expired).
    Search call(const std::string& method, const std::string& path, const nlohmann::json& body, nlohmann::json& reply);
    bool login(Search& s);
    DigiKeyLogin login_;
    std::string token_;
    std::chrono::steady_clock::time_point token_until_{};
};

} // namespace kigit::parts

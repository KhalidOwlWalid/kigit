#pragma once
// Mouser's Search API (v1): https://api.mouser.com/api/docs/ui/index
// A free key from a Mouser account ("APIs" in My Account). Limits: 30 calls
// a minute, 1000 a day, so calls are spaced out.
#include "parts/source.hpp"

#include <string>
#include <vector>

namespace kigit::parts {

// The parts in a search reply. Errors in the reply go to `error`.
std::vector<Offer> parse_mouser(const nlohmann::json& reply, std::string& error);

class Mouser : public Source {
public:
    // pace_ms: the least time between two calls.
    Mouser(std::string key, net::Http http, int pace_ms = 2100);
    std::string site() const override { return "mouser"; }
    Search part_number(const std::string& pn) override; // exact
    Search keyword(const std::string& words) override;

private:
    Search post(const std::string& path, const nlohmann::json& body);
    std::string key_;
};

} // namespace kigit::parts

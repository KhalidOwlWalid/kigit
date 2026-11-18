#pragma once
// What part lookups keep in kigit's app folder (<app data>/kigit): the API
// keys (parts-keys.json) and recent answers (parts-cache.json).
#include "parts/digikey.hpp"

#include <nlohmann/json.hpp>

#include <ctime>
#include <filesystem>
#include <optional>
#include <string>

namespace kigit::parts {

// <app data>/kigit, or the folder above $KIGIT_LOG_DIR when that is set.
std::filesystem::path app_dir();

// Mouser's key: $KIGIT_MOUSER_API_KEY, else parts-keys.json's
// {"mouser": "..."}; "" if none.
std::string api_key(const std::string& site);

// Sets (or with "" removes) a site's key in parts-keys.json.
void set_api_key(const std::string& site, const std::string& key);

// Digi-Key's login: $KIGIT_DIGIKEY_CLIENT_ID and _CLIENT_SECRET (and
// _SITE, _CURRENCY), else parts-keys.json's {"digikey": {client_id,
// client_secret, site, currency}}. Empty client_id if none.
DigiKeyLogin digikey_login();
void set_digikey_login(const DigiKeyLogin& login); // empty client_id removes it

// Whether a site has a key, and whether it comes from the environment.
bool has_key(const std::string& site);
bool key_from_env(const std::string& site);

// Answers by key ("mouser|pn|...") with the time they were got.
class Cache {
public:
    explicit Cache(std::filesystem::path file);
    // The answer if it's younger than max_age seconds.
    std::optional<nlohmann::json> get(const std::string& key, long max_age) const;
    void put(const std::string& key, const nlohmann::json& value);
    void save() const; // only if something was put
    static std::filesystem::path default_file();

private:
    std::filesystem::path file_;
    nlohmann::json data_ = nlohmann::json::object();
    bool dirty_ = false;
};

} // namespace kigit::parts

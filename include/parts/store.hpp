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

// Mouser's key: $KIGIT_MOUSER_API_KEY, else the keyring, else
// parts-keys.json's {"mouser": "..."}; "" if none.
std::string api_key(const std::string& site);

// Sets (or with "" removes) a site's key: in the OS keyring when there is
// one (platform::keyring), else in parts-keys.json (owner only). Returns
// where it went: "keyring", "file", or "" when removed. A key found in the
// file while a keyring is available is moved into it when next read.
std::string set_api_key(const std::string& site, const std::string& key);

// Digi-Key's login: $KIGIT_DIGIKEY_CLIENT_ID and _CLIENT_SECRET (and
// _SITE, _CURRENCY), else the keyring's {client_id, client_secret} (or
// parts-keys.json's, without one); site and currency are always in
// parts-keys.json (not secret). Empty client_id if none.
DigiKeyLogin digikey_login();
std::string set_digikey_login(const DigiKeyLogin& login); // empty client_id removes it; as set_api_key

// Where a site's key is: "env", "keyring", "file", or "" (none).
std::string key_place(const std::string& site);
std::filesystem::path keys_path(); // parts-keys.json

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

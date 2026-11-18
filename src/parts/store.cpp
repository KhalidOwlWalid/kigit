#include "parts/store.hpp"

#include "utils/platform.hpp"

#include <spdlog/spdlog.h>

#include <cctype>
#include <cstdlib>
#include <fstream>
#include <sstream>

namespace fs = std::filesystem;

namespace kigit::parts {

namespace {

nlohmann::json read_json(const fs::path& p) {
    std::ifstream f(p, std::ios::binary);
    if (!f) return nlohmann::json::object();
    std::stringstream ss;
    ss << f.rdbuf();
    nlohmann::json j = nlohmann::json::parse(ss.str(), nullptr, false);
    if (!j.is_object()) {
        spdlog::warn("parts: ignoring {} (not a JSON object)", p.string());
        return nlohmann::json::object();
    }
    return j;
}

// Written whole to a temp file, then renamed over the old one.
void write_json(const fs::path& p, const nlohmann::json& j, bool private_file) {
    fs::create_directories(p.parent_path());
    fs::path tmp = p;
    tmp += ".tmp";
    {
        std::ofstream f(tmp, std::ios::binary);
        if (!(f << j.dump(1) << "\n")) throw std::runtime_error("cannot write " + tmp.string());
    }
    if (private_file) fs::permissions(tmp, fs::perms::owner_read | fs::perms::owner_write);
    fs::rename(tmp, p);
}

fs::path keys_file() { return app_dir() / "parts-keys.json"; }

} // namespace

fs::path app_dir() {
    // As the GUI does: with the logs moved, the rest goes in the folder above them.
    if (const char* e = std::getenv("KIGIT_LOG_DIR"); e && *e) return fs::absolute(fs::path(e)).parent_path();
    return platform::state_dir() / "kigit";
}

std::string api_key(const std::string& site) {
    std::string var = "KIGIT_";
    for (char c : site) var += static_cast<char>(std::toupper(static_cast<unsigned char>(c)));
    var += "_API_KEY";
    if (const char* e = std::getenv(var.c_str()); e && *e) return e;
    nlohmann::json keys = read_json(keys_file());
    auto k = keys.find(site);
    return k != keys.end() && k->is_string() ? k->get<std::string>() : "";
}

void set_api_key(const std::string& site, const std::string& key) {
    nlohmann::json keys = read_json(keys_file());
    if (key.empty()) keys.erase(site);
    else keys[site] = key;
    write_json(keys_file(), keys, true);
}

namespace {

std::string env(const char* name) {
    const char* e = std::getenv(name);
    return e ? e : "";
}

} // namespace

DigiKeyLogin digikey_login() {
    DigiKeyLogin l;
    if (!env("KIGIT_DIGIKEY_CLIENT_ID").empty()) {
        l.client_id = env("KIGIT_DIGIKEY_CLIENT_ID");
        l.client_secret = env("KIGIT_DIGIKEY_CLIENT_SECRET");
    } else {
        nlohmann::json keys = read_json(keys_file());
        auto d = keys.find("digikey");
        if (d != keys.end() && d->is_object()) {
            l.client_id = d->value("client_id", "");
            l.client_secret = d->value("client_secret", "");
            l.site = d->value("site", l.site);
            l.currency = d->value("currency", l.currency);
        }
    }
    if (!env("KIGIT_DIGIKEY_SITE").empty()) l.site = env("KIGIT_DIGIKEY_SITE");
    if (!env("KIGIT_DIGIKEY_CURRENCY").empty()) l.currency = env("KIGIT_DIGIKEY_CURRENCY");
    return l;
}

void set_digikey_login(const DigiKeyLogin& l) {
    nlohmann::json keys = read_json(keys_file());
    if (l.client_id.empty()) keys.erase("digikey");
    else keys["digikey"] = {{"client_id", l.client_id}, {"client_secret", l.client_secret}, {"site", l.site}, {"currency", l.currency}};
    write_json(keys_file(), keys, true);
}

bool has_key(const std::string& site) {
    if (site == "digikey") {
        DigiKeyLogin l = digikey_login();
        return !l.client_id.empty() && !l.client_secret.empty();
    }
    return !api_key(site).empty();
}

bool key_from_env(const std::string& site) {
    if (site == "digikey") return !env("KIGIT_DIGIKEY_CLIENT_ID").empty();
    std::string var = "KIGIT_";
    for (char c : site) var += static_cast<char>(std::toupper(static_cast<unsigned char>(c)));
    return !env((var + "_API_KEY").c_str()).empty();
}

Cache::Cache(fs::path file) : file_(std::move(file)) {
    data_ = read_json(file_);
}

fs::path Cache::default_file() { return app_dir() / "parts-cache.json"; }

std::optional<nlohmann::json> Cache::get(const std::string& key, long max_age) const {
    auto e = data_.find(key);
    if (e == data_.end() || !e->is_object()) return std::nullopt;
    long age = static_cast<long>(std::time(nullptr)) - e->value("time", 0L);
    if (age < 0 || age > max_age || !e->contains("value")) return std::nullopt;
    return (*e)["value"];
}

void Cache::put(const std::string& key, const nlohmann::json& value) {
    data_[key] = {{"time", static_cast<long>(std::time(nullptr))}, {"value", value}};
    dirty_ = true;
}

void Cache::save() const {
    if (!dirty_) return;
    // Old answers are dropped (older than a week).
    nlohmann::json keep = nlohmann::json::object();
    long now = static_cast<long>(std::time(nullptr));
    for (const auto& [k, v] : data_.items())
        if (v.is_object() && now - v.value("time", 0L) < 7 * 24 * 3600) keep[k] = v;
    write_json(file_, keep, false);
}

} // namespace kigit::parts
